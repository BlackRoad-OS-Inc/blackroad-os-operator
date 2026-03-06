"""Policy evaluation engine for BlackRoad OS governance.

This is Cece's brain — the core policy matching and decision logic.

Evaluation rules:
1. Policies are sorted by priority (descending)
2. First matching policy determines the decision
3. Effect precedence for overlapping matches: deny > warn > shadow_deny > allow
4. If no policy matches, use scope's default_stance
5. Ledger level is the max of all matching policies

Usage:
    from br_operator.policy_engine import PolicyEngine

    engine = PolicyEngine()
    await engine.load()

    result = engine.evaluate(request)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from br_operator.models.policy import (
    LedgerLevel,
    Policy,
    PolicyCondition,
    PolicyEffect,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    PolicyPack,
    PolicySubjectMatch,
)


# Effect precedence (higher = wins in conflict)
EFFECT_PRECEDENCE: Dict[PolicyEffect, int] = {
    PolicyEffect.DENY: 4,
    PolicyEffect.WARN: 3,
    PolicyEffect.SHADOW_DENY: 2,
    PolicyEffect.ALLOW: 1,
}

# Ledger level precedence (higher = more verbose)
LEDGER_PRECEDENCE: Dict[LedgerLevel, int] = {
    LedgerLevel.FULL: 4,
    LedgerLevel.ACTION: 3,
    LedgerLevel.DECISION: 2,
    LedgerLevel.NONE: 1,
}


class PolicyEngine:
    """Cece's policy evaluation engine."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.policy_packs: Dict[str, PolicyPack] = {}
        self.service_registry: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    async def load(self) -> None:
        """Load all policy packs and service registry."""
        # Load service registry
        registry_path = self.config_dir / "service_registry.yaml"
        if registry_path.exists():
            with registry_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
                self.service_registry = raw.get("services", {})

        # Load policy packs
        for policy_file in self.config_dir.glob("policies.*.yaml"):
            with policy_file.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

            pack = self._parse_policy_pack(raw)
            self.policy_packs[pack.scope] = pack

        self._loaded = True

    def _parse_policy_pack(self, raw: Dict[str, Any]) -> PolicyPack:
        """Parse a raw YAML dict into a PolicyPack."""
        policies = []
        for p in raw.get("policies", []):
            # Parse subject match
            subject_raw = p.get("subject", {})
            subject = PolicySubjectMatch(
                role=subject_raw.get("role"),
                user_id=subject_raw.get("user_id"),
                attributes=subject_raw.get("attributes", {}),
            )

            # Parse condition
            condition_raw = p.get("condition", {})
            condition = PolicyCondition(
                claim_check=condition_raw.get("claim_check"),
                caller_asserts=condition_raw.get("caller_asserts", []),
                custom={k: v for k, v in condition_raw.items()
                        if k not in ("claim_check", "caller_asserts")},
            )

            policy = Policy(
                id=p["id"],
                description=p.get("description", ""),
                effect=PolicyEffect(p.get("effect", "deny")),
                priority=p.get("priority", 0),
                subject=subject,
                action=p.get("action", "*"),
                resource=p.get("resource", "*"),
                condition=condition,
                ledger_level=LedgerLevel(p.get("ledger_level", "decision")),
                policy_version=raw.get("version"),
            )
            policies.append(policy)

        # Sort by priority descending
        policies.sort(key=lambda x: x.priority, reverse=True)

        return PolicyPack(
            version=raw.get("version", "unknown"),
            scope=raw.get("scope", "*"),
            default_stance=PolicyEffect(raw.get("default_stance", "deny")),
            default_ledger_level=LedgerLevel(raw.get("default_ledger_level", "decision")),
            policies=policies,
        )

    def _get_scope_defaults(self, host: Optional[str]) -> tuple[PolicyEffect, LedgerLevel]:
        """Get default stance and ledger level for a host."""
        if host and host in self.service_registry:
            entry = self.service_registry[host]
            stance = PolicyEffect(entry.get("default_stance", "deny"))
            level = LedgerLevel(entry.get("ledger_level", "decision"))
            return stance, level
        return PolicyEffect.DENY, LedgerLevel.DECISION

    def _matches_pattern(self, pattern: str, value: str) -> bool:
        """Check if value matches pattern (supports * and ** wildcards)."""
        if pattern == "*":
            return True
        # Convert glob-style to regex
        regex = pattern.replace(".", r"\.").replace("**", ".*").replace("*", r"[^:]*")
        return bool(re.match(f"^{regex}$", value))

    def _matches_subject(self, policy_subject: PolicySubjectMatch, request_subject: Dict[str, Any]) -> bool:
        """Check if request subject matches policy subject criteria."""
        # Role match
        if policy_subject.role:
            if policy_subject.role == "*":
                pass  # Matches any role
            elif policy_subject.role != request_subject.get("role"):
                return False

        # User ID match (if specified)
        if policy_subject.user_id:
            if policy_subject.user_id != request_subject.get("user_id"):
                return False

        # Attribute match
        for key, expected in policy_subject.attributes.items():
            if request_subject.get("attributes", {}).get(key) != expected:
                return False

        return True

    def _check_condition(
        self,
        condition: PolicyCondition,
        request: PolicyEvaluateRequest,
    ) -> tuple[bool, Optional[str]]:
        """Check if condition is satisfied.

        Returns (satisfied, reason_if_not).
        """
        # Check claim_check
        if condition.claim_check:
            claim_type = condition.claim_check
            claims = request.context.claims
            has_claim = any(
                c.get("type") == claim_type
                for c in claims
            )
            if not has_claim:
                return False, f"Missing required claim: {claim_type}"

        # Check caller_asserts (we trust but verify presence)
        for required_fact in condition.caller_asserts:
            if required_fact not in request.context.asserted_facts:
                return False, f"Caller did not assert required fact: {required_fact}"

        return True, None

    def evaluate(self, request: PolicyEvaluateRequest) -> PolicyEvaluateResponse:
        """Evaluate a policy request.

        This is the core governance decision function.
        """
        if not self._loaded:
            raise RuntimeError("PolicyEngine not loaded. Call await engine.load() first.")

        host = request.context.request_metadata.host
        default_stance, default_ledger_level = self._get_scope_defaults(host)

        matched_policies: List[tuple[Policy, bool, Optional[str]]] = []

        # Check all policy packs
        for pack in self.policy_packs.values():
            for policy in pack.policies:
                # Match action pattern
                if not self._matches_pattern(policy.action, request.action):
                    continue

                # Match resource pattern
                if not self._matches_pattern(policy.resource, request.resource.type):
                    continue

                # Match subject
                subject_dict = {
                    "role": request.subject.role,
                    "user_id": request.subject.user_id,
                    "attributes": request.subject.attributes,
                }
                if not self._matches_subject(policy.subject, subject_dict):
                    continue

                # Check conditions
                condition_met, reason = self._check_condition(policy.condition, request)
                matched_policies.append((policy, condition_met, reason))

        # Find the winning policy (highest priority with conditions met)
        winning_policy: Optional[Policy] = None
        winning_reason: Optional[str] = None
        max_ledger_level = default_ledger_level

        for policy, condition_met, reason in matched_policies:
            # Track max ledger level across all matches
            if LEDGER_PRECEDENCE[policy.ledger_level] > LEDGER_PRECEDENCE[max_ledger_level]:
                max_ledger_level = policy.ledger_level

            # First policy with met conditions wins (already sorted by priority)
            if condition_met and winning_policy is None:
                winning_policy = policy
            elif not condition_met and winning_policy is None:
                # Track why we didn't match (for deny reasons)
                winning_reason = reason

        # Determine final decision
        if winning_policy:
            decision = winning_policy.effect
            policy_id = winning_policy.id
            policy_version = winning_policy.policy_version
            reason = winning_policy.description
        else:
            # No matching policy - use default stance
            decision = default_stance
            policy_id = None
            policy_version = None
            reason = winning_reason or f"No matching policy; default stance is {default_stance.value}"

        return PolicyEvaluateResponse(
            decision=decision,
            policy_id=policy_id,
            policy_version=policy_version,
            reason=reason,
            required_ledger_level=max_ledger_level,
        )

    def get_policies_for_scope(self, scope: str) -> List[Policy]:
        """Get all policies for a given scope."""
        if scope in self.policy_packs:
            return self.policy_packs[scope].policies
        return []

    def get_scope_for_host(self, host: str) -> Optional[str]:
        """Get the policy scope for a host."""
        if host in self.service_registry:
            return self.service_registry[host].get("policy_scope")
        return None


# Singleton instance
_engine: Optional[PolicyEngine] = None


async def get_policy_engine() -> PolicyEngine:
    """Get or create the singleton policy engine."""
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
        await _engine.load()
    return _engine
