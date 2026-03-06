"""
BlackRoad OS - Secrets & Capability Resolver

Pattern: Only the Operator holds real secrets.
Everyone else uses aliases via governed API calls.

KEY CONCEPT: API key = CAPABILITY, PS-SHA∞ fingerprint = IDENTITY
- Credentials grant capability (call OpenAI, deploy to Railway)
- Identity is who's doing it (Cece, agent-001, lucidia-pi cluster)

Usage:
    from br_operator.secrets import resolve_secret, get_secret, SecretNotFoundError

    # Get a secret by alias
    api_key = get_secret("openai.default")

    # Check if available (doesn't throw)
    key = resolve_secret("anthropic.default")  # Returns None if missing

    # Check capability for a specific agent
    if can_use_credential("openai.default", agent_id="cece-primary", intent="chat"):
        key = get_secret("openai.default")

    # List all configured aliases
    aliases = list_aliases()

@owner Alexa Louise Amundson
@system BlackRoad OS
@version credentials-v2
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import lru_cache

import yaml


# =============================================================================
# EXCEPTIONS
# =============================================================================

class SecretNotFoundError(Exception):
    """Raised when a required secret is not found."""

    def __init__(self, alias: str, env_var: str, hint: str = ""):
        self.alias = alias
        self.env_var = env_var
        self.hint = hint
        message = f"Secret '{alias}' not found. Set environment variable: {env_var}"
        if hint:
            message += f"\nHint: {hint}"
        super().__init__(message)


class SecretAliasNotFoundError(Exception):
    """Raised when an alias doesn't exist in the config."""

    def __init__(self, alias: str):
        self.alias = alias
        super().__init__(f"Unknown secret alias: '{alias}'. Check config/secrets.aliases.yaml")


class CapabilityDeniedError(Exception):
    """Raised when an agent doesn't have permission to use a credential."""

    def __init__(self, alias: str, agent_id: str, intent: Optional[str] = None):
        self.alias = alias
        self.agent_id = agent_id
        self.intent = intent
        if intent:
            message = f"Agent '{agent_id}' cannot use '{alias}' for intent '{intent}'"
        else:
            message = f"Agent '{agent_id}' not allowed to use credential '{alias}'"
        super().__init__(message)


# =============================================================================
# CONFIG LOADING
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALIASES_PATH = REPO_ROOT / "config" / "secrets.aliases.yaml"


@lru_cache(maxsize=1)
def load_aliases_config(path: Path = DEFAULT_ALIASES_PATH) -> Dict[str, Any]:
    """Load the secrets aliases configuration."""
    if not path.exists():
        return {"providers": {}}

    with open(path, "r") as f:
        return yaml.safe_load(f) or {"providers": {}}


def _parse_alias(alias: str) -> tuple[str, str]:
    """Parse 'provider.name' into (provider, name)."""
    parts = alias.split(".", 1)
    if len(parts) != 2:
        raise SecretAliasNotFoundError(alias)
    return parts[0], parts[1]


def _get_alias_config(alias: str) -> Optional[Dict[str, Any]]:
    """Get the configuration for an alias."""
    config = load_aliases_config()
    provider, name = _parse_alias(alias)

    providers = config.get("providers", {})
    if provider not in providers:
        return None

    provider_config = providers[provider]
    if name not in provider_config:
        return None

    return provider_config[name]


# =============================================================================
# PUBLIC API
# =============================================================================

def resolve_secret(alias: str) -> Optional[str]:
    """
    Resolve a secret alias to its value.

    Returns None if the secret is not set (doesn't throw).
    Use this when the secret is optional.

    Args:
        alias: Secret alias like "openai.default" or "stripe.secret"

    Returns:
        The secret value, or None if not found
    """
    alias_config = _get_alias_config(alias)
    if alias_config is None:
        return None

    env_var = alias_config.get("env_var")
    if not env_var:
        return None

    # Check environment variable
    value = os.environ.get(env_var)
    if value:
        return value

    # Check for default value
    default = alias_config.get("default")
    if default:
        return default

    return None


def get_secret(alias: str) -> str:
    """
    Get a secret by alias. Throws if not found.

    Use this when the secret is required.

    Args:
        alias: Secret alias like "openai.default"

    Returns:
        The secret value

    Raises:
        SecretNotFoundError: If the secret is not set
        SecretAliasNotFoundError: If the alias doesn't exist
    """
    alias_config = _get_alias_config(alias)
    if alias_config is None:
        raise SecretAliasNotFoundError(alias)

    env_var = alias_config.get("env_var", "UNKNOWN")
    value = resolve_secret(alias)

    if value is None:
        hint = alias_config.get("description", "")
        raise SecretNotFoundError(alias, env_var, hint)

    return value


def has_secret(alias: str) -> bool:
    """Check if a secret is available without retrieving it."""
    return resolve_secret(alias) is not None


def list_aliases() -> List[str]:
    """List all configured secret aliases."""
    config = load_aliases_config()
    aliases = []

    for provider, provider_config in config.get("providers", {}).items():
        if isinstance(provider_config, dict):
            for name in provider_config.keys():
                aliases.append(f"{provider}.{name}")

    return sorted(aliases)


def get_alias_info(alias: str) -> Optional[Dict[str, Any]]:
    """Get metadata about an alias (without the actual secret)."""
    alias_config = _get_alias_config(alias)
    if alias_config is None:
        return None

    env_var = alias_config.get("env_var", "")

    return {
        "alias": alias,
        "env_var": env_var,
        "description": alias_config.get("description", ""),
        "required": alias_config.get("required", False),
        "sensitive": alias_config.get("sensitive", True),
        "is_set": has_secret(alias),
        "used_by": alias_config.get("used_by", []),
        # New fields from credentials-v2
        "owner": alias_config.get("owner", "Unknown"),
        "scope": alias_config.get("scope", "external"),
        "allowed_agents": alias_config.get("allowed_agents", ["*"]),
        "allowed_intents": alias_config.get("allowed_intents", []),
    }


# =============================================================================
# CAPABILITY CHECKING (credentials-v2)
# =============================================================================

def get_credential_owner(alias: str) -> Optional[str]:
    """Get the owner of a credential."""
    alias_config = _get_alias_config(alias)
    if alias_config is None:
        return None
    return alias_config.get("owner")


def get_credential_scope(alias: str) -> str:
    """Get the scope of a credential (core, external, research, tenant, deprecated)."""
    alias_config = _get_alias_config(alias)
    if alias_config is None:
        return "external"  # Default to external
    return alias_config.get("scope", "external")


def can_use_credential(
    alias: str,
    agent_id: str,
    intent: Optional[str] = None,
) -> bool:
    """
    Check if an agent has permission to use a credential.

    This is the core capability check. API keys are not identity - they're
    ephemeral limbs that agents can be granted/denied access to.

    Args:
        alias: Credential alias like "openai.default"
        agent_id: Agent PS-SHA∞ ID or name (e.g., "cece-primary")
        intent: Optional intent type (e.g., "chat", "deploy")

    Returns:
        True if the agent can use this credential for the given intent
    """
    alias_config = _get_alias_config(alias)
    if alias_config is None:
        return False

    # Check scope - deprecated credentials always warn
    scope = alias_config.get("scope", "external")
    if scope == "deprecated":
        # Log warning but allow for now
        pass

    # Check allowed_agents
    allowed_agents = alias_config.get("allowed_agents", ["*"])
    if allowed_agents:
        if "*" not in allowed_agents and agent_id not in allowed_agents:
            return False

    # Check allowed_intents (if specified and intent provided)
    if intent:
        allowed_intents = alias_config.get("allowed_intents", [])
        if allowed_intents and intent not in allowed_intents:
            return False

    return True


def get_secret_for_agent(
    alias: str,
    agent_id: str,
    intent: Optional[str] = None,
) -> str:
    """
    Get a secret, checking agent capability first.

    Args:
        alias: Credential alias
        agent_id: Agent requesting the credential
        intent: What the agent wants to do with it

    Returns:
        The secret value

    Raises:
        CapabilityDeniedError: If agent doesn't have permission
        SecretNotFoundError: If secret is not set
    """
    if not can_use_credential(alias, agent_id, intent):
        raise CapabilityDeniedError(alias, agent_id, intent)

    return get_secret(alias)


def list_credentials_by_scope(scope: str) -> List[str]:
    """List all credentials with a specific scope."""
    config = load_aliases_config()
    credentials = []

    for provider, provider_config in config.get("providers", {}).items():
        if isinstance(provider_config, dict):
            for name, alias_config in provider_config.items():
                if isinstance(alias_config, dict):
                    if alias_config.get("scope") == scope:
                        credentials.append(f"{provider}.{name}")

    return sorted(credentials)


def list_credentials_for_agent(agent_id: str) -> List[str]:
    """List all credentials an agent can use."""
    config = load_aliases_config()
    credentials = []

    for provider, provider_config in config.get("providers", {}).items():
        if isinstance(provider_config, dict):
            for name, alias_config in provider_config.items():
                if isinstance(alias_config, dict):
                    alias = f"{provider}.{name}"
                    if can_use_credential(alias, agent_id):
                        credentials.append(alias)

    return sorted(credentials)


def check_required_secrets() -> Dict[str, Any]:
    """
    Check all required secrets and return status.

    Useful for health checks and startup validation.
    """
    config = load_aliases_config()
    results = {
        "ok": True,
        "missing": [],
        "available": [],
        "optional_missing": [],
    }

    for provider, provider_config in config.get("providers", {}).items():
        if not isinstance(provider_config, dict):
            continue

        for name, alias_config in provider_config.items():
            if not isinstance(alias_config, dict):
                continue

            alias = f"{provider}.{name}"
            is_required = alias_config.get("required", False)
            is_set = has_secret(alias)

            if is_set:
                results["available"].append(alias)
            elif is_required:
                results["missing"].append(alias)
                results["ok"] = False
            else:
                results["optional_missing"].append(alias)

    return results


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret for safe logging/display."""
    if len(value) <= show_chars * 2:
        return "*" * len(value)
    return value[:show_chars] + "*" * (len(value) - show_chars * 2) + value[-show_chars:]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_openai_key() -> str:
    """Get the OpenAI API key."""
    return get_secret("openai.default")


def get_anthropic_key() -> Optional[str]:
    """Get the Anthropic API key (optional)."""
    return resolve_secret("anthropic.default")


def get_stripe_secret() -> Optional[str]:
    """Get the Stripe secret key (optional)."""
    return resolve_secret("stripe.secret")


def get_database_url() -> Optional[str]:
    """Get the database connection URL."""
    return resolve_secret("postgres.url")


def get_redis_url() -> Optional[str]:
    """Get the Redis connection URL."""
    return resolve_secret("redis.url")


# =============================================================================
# CLI / DEBUG
# =============================================================================

if __name__ == "__main__":

    print("BlackRoad OS - Credentials Registry")
    print("=" * 60)
    print("KEY CONCEPT: API key = CAPABILITY, PS-SHA∞ fingerprint = IDENTITY")
    print("=" * 60)

    status = check_required_secrets()
    print(f"\nStatus: {'OK' if status['ok'] else 'MISSING REQUIRED SECRETS'}")

    # Group by scope
    print("\n--- By Scope ---")
    for scope in ["core", "external", "research", "tenant", "deprecated"]:
        creds = list_credentials_by_scope(scope)
        if creds:
            print(f"\n{scope.upper()} ({len(creds)}):")
            for alias in creds:
                info = get_alias_info(alias)
                status_mark = "✓" if info and info.get("is_set") else "○"
                owner = info.get("owner", "?")[:20] if info else "?"
                print(f"  {status_mark} {alias:<30} owner={owner}")

    # Show what Cece can use
    print("\n--- Cece's Capabilities ---")
    cece_creds = list_credentials_for_agent("cece-primary")
    print(f"Cece can use {len(cece_creds)} credentials:")
    for alias in cece_creds[:10]:
        info = get_alias_info(alias)
        status_mark = "✓" if info and info.get("is_set") else "○"
        print(f"  {status_mark} {alias}")
    if len(cece_creds) > 10:
        print(f"  ... and {len(cece_creds) - 10} more")

    print(f"\nAvailable ({len(status['available'])}):")
    for alias in status["available"]:
        info = get_alias_info(alias)
        print(f"  ✓ {alias}")

    if status["missing"]:
        print(f"\nMissing REQUIRED ({len(status['missing'])}):")
        for alias in status["missing"]:
            info = get_alias_info(alias)
            print(f"  ✗ {alias} -> Set: {info['env_var']}")

    if status["optional_missing"]:
        print(f"\nMissing optional ({len(status['optional_missing'])}):")
        for alias in status["optional_missing"][:10]:  # Show first 10
            info = get_alias_info(alias)
            print(f"  - {alias}")
        if len(status["optional_missing"]) > 10:
            print(f"  ... and {len(status['optional_missing']) - 10} more")

    print("\n" + "=" * 60)
