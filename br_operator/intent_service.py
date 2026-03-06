"""Intent Service for Stage 3 multi-step governance.

Manages intent lifecycle: creation, step execution, rollback, and audit.

@amundson 0.1.0
@governor alice.governor.v1
@operator alexa.operator.v1
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from br_operator.models.intent import (
    Intent,
    IntentCreate,
    IntentEvent,
    IntentEventType,
    IntentList,
    IntentQuery,
    IntentResponse,
    IntentState,
    IntentStep,
    IntentTemplate,
    StepDefinition,
    StepExecuteRequest,
    StepExecuteResponse,
    StepStatus,
)
from br_operator.models.policy import (
    PolicyContext,
    PolicyEvaluateRequest,
    RequestMetadata,
    Resource,
    Subject,
)

logger = logging.getLogger(__name__)


# ============================================
# IN-MEMORY STORAGE (Dev/Test)
# ============================================

_intent_templates: Dict[str, IntentTemplate] = {}
_intents: Dict[UUID, Intent] = {}
_intent_steps: Dict[UUID, List[IntentStep]] = {}
_intent_events: Dict[UUID, List[IntentEvent]] = {}


# ============================================
# DEFAULT TEMPLATES
# ============================================

DEFAULT_TEMPLATES = [
    IntentTemplate(
        id=uuid4(),
        name="deployment",
        version="1.0.0",
        description="Deploy a service to production",
        template_type="deployment",
        steps=[
            StepDefinition(sequence=1, action="deployment:request", name="Request Deployment"),
            StepDefinition(sequence=2, action="deployment:approve", name="Approve Deployment", requires_role="operator"),
            StepDefinition(sequence=3, action="deployment:pre-check", name="Pre-flight Checks"),
            StepDefinition(sequence=4, action="deployment:execute", name="Execute Deployment"),
            StepDefinition(sequence=5, action="deployment:validate", name="Validate Deployment"),
        ],
        policy_scope="intents.deployment.*",
        required_role="operator",
        rollback_on_failure=["deployment:execute", "deployment:validate"],
    ),
    IntentTemplate(
        id=uuid4(),
        name="db-migration",
        version="1.0.0",
        description="Run database migration",
        template_type="db_migration",
        steps=[
            StepDefinition(sequence=1, action="migration:request", name="Request Migration"),
            StepDefinition(sequence=2, action="migration:backup", name="Backup Database"),
            StepDefinition(sequence=3, action="migration:approve", name="Approve Migration", requires_role="operator"),
            StepDefinition(sequence=4, action="migration:execute", name="Execute Migration"),
            StepDefinition(sequence=5, action="migration:validate", name="Validate Schema"),
        ],
        policy_scope="intents.migration.*",
        required_role="operator",
        rollback_on_failure=["migration:execute"],
    ),
    IntentTemplate(
        id=uuid4(),
        name="agent-register",
        version="1.0.0",
        description="Register a new agent in the mesh",
        template_type="agent_register",
        steps=[
            StepDefinition(sequence=1, action="agent:request-registration", name="Request Registration"),
            StepDefinition(sequence=2, action="agent:verify-capabilities", name="Verify Capabilities"),
            StepDefinition(sequence=3, action="agent:approve-registration", name="Approve Registration", requires_role="operator"),
            StepDefinition(sequence=4, action="agent:activate", name="Activate Agent"),
        ],
        policy_scope="intents.agent.*",
        required_role="operator",
        rollback_on_failure=["agent:activate"],
    ),
    IntentTemplate(
        id=uuid4(),
        name="secret-rotation",
        version="1.0.0",
        description="Rotate a secret or credential",
        template_type="secret_rotate",
        steps=[
            StepDefinition(sequence=1, action="secret:request-rotation", name="Request Rotation"),
            StepDefinition(sequence=2, action="secret:backup-current", name="Backup Current Secret"),
            StepDefinition(sequence=3, action="secret:generate-new", name="Generate New Secret"),
            StepDefinition(sequence=4, action="secret:validate-new", name="Validate New Secret"),
            StepDefinition(sequence=5, action="secret:activate", name="Activate New Secret", requires_role="operator"),
            StepDefinition(sequence=6, action="secret:cleanup-old", name="Cleanup Old Secret", required=False),
        ],
        policy_scope="intents.secret.*",
        required_role="operator",
        rollback_on_failure=["secret:activate"],
    ),
    IntentTemplate(
        id=uuid4(),
        name="infra-scale",
        version="1.0.0",
        description="Scale infrastructure component",
        template_type="infra_scale",
        steps=[
            StepDefinition(sequence=1, action="infra:request-scale", name="Request Scale"),
            StepDefinition(sequence=2, action="infra:approve-scale", name="Approve Scale", requires_role="operator"),
            StepDefinition(sequence=3, action="infra:pre-check", name="Pre-Scale Check"),
            StepDefinition(sequence=4, action="infra:execute-scale", name="Execute Scale"),
            StepDefinition(sequence=5, action="infra:verify-scale", name="Verify Scale"),
        ],
        policy_scope="intents.infra.*",
        required_role="operator",
        rollback_on_failure=["infra:execute-scale"],
    ),
]


# ============================================
# SERVICE CLASS
# ============================================

class IntentService:
    """Service for managing intent lifecycle."""

    def __init__(self, policy_engine=None, ledger_service=None):
        self.policy_engine = policy_engine
        self.ledger_service = ledger_service
        self._load_default_templates()

    def _load_default_templates(self):
        """Load default intent templates."""
        for template in DEFAULT_TEMPLATES:
            _intent_templates[template.name] = template
        logger.info(f"Loaded {len(_intent_templates)} intent templates")

    # ============================================
    # TEMPLATE OPERATIONS
    # ============================================

    async def get_template(self, name: str, version: Optional[str] = None) -> Optional[IntentTemplate]:
        """Get an intent template by name."""
        template = _intent_templates.get(name)
        if template and version and template.version != version:
            return None
        return template

    async def list_templates(self) -> List[IntentTemplate]:
        """List all intent templates."""
        return list(_intent_templates.values())

    # ============================================
    # INTENT CRUD
    # ============================================

    async def create_intent(self, request: IntentCreate) -> IntentResponse:
        """Create a new intent from a template."""
        # Get template
        template = await self.get_template(request.template_name, request.template_version)
        if not template:
            raise ValueError(f"Template not found: {request.template_name}")

        # Check role requirements
        if template.required_role and request.role != template.required_role and request.role != "operator":
            raise PermissionError(f"Role {request.role} cannot create {request.template_name} intents")

        # Create intent
        intent_id = uuid4()
        correlation_id = uuid4()
        now = datetime.now(timezone.utc)

        intent = Intent(
            id=intent_id,
            template_id=template.id,
            template_name=template.name,
            template_version=template.version,
            state=IntentState.PENDING,
            current_step=0,
            created_by_user_id=request.user_id,
            created_by_agent_id=request.agent_id,
            created_by_role=request.role,
            correlation_id=correlation_id,
            parent_intent_id=request.parent_intent_id,
            context=request.context,
            policy_scope=template.policy_scope,
            created_at=now,
            metadata=request.metadata,
        )

        # Create steps from template
        steps = []
        for step_def in template.steps:
            step = IntentStep(
                id=uuid4(),
                intent_id=intent_id,
                sequence_num=step_def.sequence,
                action=step_def.action,
                name=step_def.name,
                status=StepStatus.PENDING,
                created_at=now,
                max_attempts=3,
            )
            steps.append(step)

        # Store
        _intents[intent_id] = intent
        _intent_steps[intent_id] = steps
        _intent_events[intent_id] = []

        # Record creation event
        await self._record_event(
            intent_id=intent_id,
            event_type=IntentEventType.CREATED,
            actor_user_id=request.user_id,
            actor_agent_id=request.agent_id,
            actor_role=request.role,
            new_state=IntentState.PENDING,
            correlation_id=correlation_id,
        )

        logger.info(f"Created intent {intent_id} from template {template.name}")

        return IntentResponse(
            id=intent_id,
            template_name=template.name,
            state=IntentState.PENDING,
            current_step=0,
            total_steps=len(steps),
            correlation_id=correlation_id,
            created_by_role=request.role,
            created_at=now,
            policy_scope=template.policy_scope,
            steps=steps,
            next_step={"sequence": 1, "action": steps[0].action, "name": steps[0].name} if steps else None,
        )

    async def get_intent(self, intent_id: UUID) -> Optional[Intent]:
        """Get an intent by ID."""
        intent = _intents.get(intent_id)
        if intent:
            intent.steps = _intent_steps.get(intent_id, [])
        return intent

    async def list_intents(self, query: IntentQuery) -> IntentList:
        """List intents with filters."""
        results = []
        for intent in _intents.values():
            if query.state and intent.state != query.state:
                continue
            if query.template_name and intent.template_name != query.template_name:
                continue
            if query.created_by_user_id and intent.created_by_user_id != query.created_by_user_id:
                continue
            if query.created_by_agent_id and intent.created_by_agent_id != query.created_by_agent_id:
                continue
            if query.correlation_id and intent.correlation_id != query.correlation_id:
                continue
            if query.parent_intent_id and intent.parent_intent_id != query.parent_intent_id:
                continue
            results.append(intent)

        # Sort by created_at descending
        results.sort(key=lambda x: x.created_at or datetime.min, reverse=True)

        # Paginate
        total = len(results)
        results = results[query.offset:query.offset + query.limit]

        return IntentList(
            intents=results,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    # ============================================
    # STEP EXECUTION
    # ============================================

    async def execute_step(
        self,
        intent_id: UUID,
        sequence_num: int,
        request: StepExecuteRequest,
    ) -> StepExecuteResponse:
        """Execute a step in an intent."""
        intent = await self.get_intent(intent_id)
        if not intent:
            raise ValueError(f"Intent not found: {intent_id}")

        # Get the step
        steps = _intent_steps.get(intent_id, [])
        step = next((s for s in steps if s.sequence_num == sequence_num), None)
        if not step:
            raise ValueError(f"Step {sequence_num} not found in intent {intent_id}")

        # Check intent state
        if intent.state not in (IntentState.PENDING, IntentState.IN_PROGRESS):
            raise ValueError(f"Intent is {intent.state}, cannot execute steps")

        # Check step is pending
        if step.status != StepStatus.PENDING:
            raise ValueError(f"Step is {step.status}, cannot execute")

        # Check previous step completed (if not first)
        if sequence_num > 1:
            prev_step = next((s for s in steps if s.sequence_num == sequence_num - 1), None)
            if not prev_step or prev_step.status != StepStatus.COMPLETED:
                raise ValueError("Previous step not completed")

        # Update intent to in_progress if pending
        if intent.state == IntentState.PENDING:
            intent.state = IntentState.IN_PROGRESS
            intent.started_at = datetime.now(timezone.utc)
            await self._record_event(
                intent_id=intent_id,
                event_type=IntentEventType.STARTED,
                actor_user_id=request.user_id,
                actor_agent_id=request.agent_id,
                actor_role=request.role,
                previous_state=IntentState.PENDING,
                new_state=IntentState.IN_PROGRESS,
                correlation_id=intent.correlation_id,
            )

        # Mark step in progress
        step.status = StepStatus.IN_PROGRESS
        step.started_at = datetime.now(timezone.utc)
        step.executed_by_user_id = request.user_id
        step.executed_by_agent_id = request.agent_id
        step.executed_by_role = request.role
        step.input = request.input
        step.attempt_count += 1

        await self._record_event(
            intent_id=intent_id,
            step_id=step.id,
            event_type=IntentEventType.STEP_STARTED,
            actor_user_id=request.user_id,
            actor_agent_id=request.agent_id,
            actor_role=request.role,
            correlation_id=intent.correlation_id,
            payload={"sequence_num": sequence_num, "action": step.action},
        )

        # Evaluate policy (if policy engine available)
        policy_decision = "allow"
        policy_id = None

        if self.policy_engine:
            policy_request = PolicyEvaluateRequest(
                subject=Subject(
                    user_id=request.user_id,
                    role=request.role,
                    attributes={"agent_id": request.agent_id} if request.agent_id else {},
                ),
                action=step.action,
                resource=Resource(type="intent_step", id=str(step.id)),
                context=PolicyContext(
                    claims=[],
                    asserted_facts=["previous_step_completed"] if sequence_num > 1 else [],
                    fact_evidence={},
                    request_metadata=RequestMetadata(
                        host="gov.api.blackroad.io",
                        service="intent-service",
                        correlation_id=str(intent.correlation_id),
                    ),
                ),
            )
            policy_response = self.policy_engine.evaluate(policy_request)
            policy_decision = policy_response.decision.value
            policy_id = policy_response.policy_id

        step.policy_decision = policy_decision
        step.policy_id = policy_id

        # Check policy result
        if policy_decision == "deny":
            step.status = StepStatus.FAILED
            step.completed_at = datetime.now(timezone.utc)
            step.error_message = "Policy denied execution"

            await self._record_event(
                intent_id=intent_id,
                step_id=step.id,
                event_type=IntentEventType.STEP_FAILED,
                actor_user_id=request.user_id,
                actor_agent_id=request.agent_id,
                actor_role=request.role,
                correlation_id=intent.correlation_id,
                payload={"reason": "policy_denied", "policy_id": policy_id},
            )

            # Check if this triggers rollback
            template = await self.get_template(intent.template_name)
            if template and step.action in template.rollback_on_failure:
                await self._trigger_rollback(intent, step, request)

            return StepExecuteResponse(
                step_id=step.id,
                intent_id=intent_id,
                sequence_num=sequence_num,
                action=step.action,
                status=StepStatus.FAILED,
                policy_decision=policy_decision,
                policy_id=policy_id,
                error_message="Policy denied execution",
            )

        # Execute step (simulate success for now)
        step.status = StepStatus.COMPLETED
        step.completed_at = datetime.now(timezone.utc)
        step.output = {"executed_at": step.completed_at.isoformat()}

        # Update intent current step
        intent.current_step = sequence_num

        await self._record_event(
            intent_id=intent_id,
            step_id=step.id,
            event_type=IntentEventType.STEP_COMPLETED,
            actor_user_id=request.user_id,
            actor_agent_id=request.agent_id,
            actor_role=request.role,
            correlation_id=intent.correlation_id,
            payload={"sequence_num": sequence_num, "action": step.action},
        )

        # Check if intent is complete
        all_required_complete = all(
            s.status == StepStatus.COMPLETED
            for s in steps
            if s.sequence_num <= len(steps)  # Simplified check
        )

        if sequence_num == len(steps):
            intent.state = IntentState.COMPLETED
            intent.completed_at = datetime.now(timezone.utc)
            await self._record_event(
                intent_id=intent_id,
                event_type=IntentEventType.COMPLETED,
                actor_user_id=request.user_id,
                actor_agent_id=request.agent_id,
                actor_role=request.role,
                previous_state=IntentState.IN_PROGRESS,
                new_state=IntentState.COMPLETED,
                correlation_id=intent.correlation_id,
            )
            logger.info(f"Intent {intent_id} completed")

        # Get next step
        next_step = None
        if sequence_num < len(steps):
            next_s = steps[sequence_num]
            next_step = {"sequence": next_s.sequence_num, "action": next_s.action, "name": next_s.name}

        return StepExecuteResponse(
            step_id=step.id,
            intent_id=intent_id,
            sequence_num=sequence_num,
            action=step.action,
            status=step.status,
            policy_decision=policy_decision,
            policy_id=policy_id,
            output=step.output,
            next_step=next_step,
        )

    # ============================================
    # ROLLBACK
    # ============================================

    async def rollback_intent(
        self,
        intent_id: UUID,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        role: str = "operator",
    ) -> Intent:
        """Trigger rollback of a failed intent."""
        intent = await self.get_intent(intent_id)
        if not intent:
            raise ValueError(f"Intent not found: {intent_id}")

        if intent.state not in (IntentState.FAILED, IntentState.IN_PROGRESS):
            raise ValueError(f"Cannot rollback intent in state {intent.state}")

        await self._record_event(
            intent_id=intent_id,
            event_type=IntentEventType.ROLLBACK_STARTED,
            actor_user_id=user_id,
            actor_agent_id=agent_id,
            actor_role=role,
            previous_state=intent.state,
            correlation_id=intent.correlation_id,
        )

        # Mark completed steps as rolled back (in reverse order)
        steps = _intent_steps.get(intent_id, [])
        for step in reversed(steps):
            if step.status == StepStatus.COMPLETED:
                step.status = StepStatus.ROLLED_BACK
                logger.info(f"Rolled back step {step.sequence_num}: {step.action}")

        intent.state = IntentState.ROLLED_BACK
        intent.completed_at = datetime.now(timezone.utc)

        await self._record_event(
            intent_id=intent_id,
            event_type=IntentEventType.ROLLBACK_COMPLETED,
            actor_user_id=user_id,
            actor_agent_id=agent_id,
            actor_role=role,
            new_state=IntentState.ROLLED_BACK,
            correlation_id=intent.correlation_id,
        )

        logger.info(f"Intent {intent_id} rolled back")
        return intent

    async def _trigger_rollback(self, intent: Intent, failed_step: IntentStep, request: StepExecuteRequest):
        """Internal rollback trigger on step failure."""
        intent.state = IntentState.FAILED
        intent.error_message = f"Step {failed_step.sequence_num} ({failed_step.action}) failed"

        await self._record_event(
            intent_id=intent.id,
            event_type=IntentEventType.FAILED,
            actor_user_id=request.user_id,
            actor_agent_id=request.agent_id,
            actor_role=request.role,
            previous_state=IntentState.IN_PROGRESS,
            new_state=IntentState.FAILED,
            correlation_id=intent.correlation_id,
            payload={"failed_step": failed_step.sequence_num, "action": failed_step.action},
        )

    # ============================================
    # CANCEL
    # ============================================

    async def cancel_intent(
        self,
        intent_id: UUID,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        role: str = "operator",
    ) -> Intent:
        """Cancel an active intent."""
        intent = await self.get_intent(intent_id)
        if not intent:
            raise ValueError(f"Intent not found: {intent_id}")

        if intent.state not in (IntentState.PENDING, IntentState.IN_PROGRESS):
            raise ValueError(f"Cannot cancel intent in state {intent.state}")

        previous_state = intent.state
        intent.state = IntentState.CANCELLED
        intent.completed_at = datetime.now(timezone.utc)

        await self._record_event(
            intent_id=intent_id,
            event_type=IntentEventType.CANCELLED,
            actor_user_id=user_id,
            actor_agent_id=agent_id,
            actor_role=role,
            previous_state=previous_state,
            new_state=IntentState.CANCELLED,
            correlation_id=intent.correlation_id,
        )

        logger.info(f"Intent {intent_id} cancelled")
        return intent

    # ============================================
    # AUDIT
    # ============================================

    async def get_audit_trail(self, intent_id: UUID) -> List[IntentEvent]:
        """Get the audit trail for an intent."""
        return _intent_events.get(intent_id, [])

    async def _record_event(
        self,
        intent_id: UUID,
        event_type: IntentEventType,
        actor_user_id: Optional[str] = None,
        actor_agent_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        step_id: Optional[UUID] = None,
        previous_state: Optional[IntentState] = None,
        new_state: Optional[IntentState] = None,
        correlation_id: Optional[UUID] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        """Record an intent event."""
        event = IntentEvent(
            id=uuid4(),
            intent_id=intent_id,
            step_id=step_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_agent_id=actor_agent_id,
            actor_role=actor_role,
            previous_state=previous_state,
            new_state=new_state,
            payload=payload or {},
            occurred_at=datetime.now(timezone.utc),
            correlation_id=correlation_id,
        )

        if intent_id not in _intent_events:
            _intent_events[intent_id] = []
        _intent_events[intent_id].append(event)

    # ============================================
    # STATS
    # ============================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get intent statistics."""
        by_state = {}
        by_template = {}

        for intent in _intents.values():
            state = intent.state.value
            by_state[state] = by_state.get(state, 0) + 1

            template = intent.template_name
            by_template[template] = by_template.get(template, 0) + 1

        return {
            "total_intents": len(_intents),
            "by_state": by_state,
            "by_template": by_template,
            "templates_loaded": len(_intent_templates),
        }


# ============================================
# SINGLETON
# ============================================

_intent_service: Optional[IntentService] = None


async def get_intent_service(policy_engine=None, ledger_service=None) -> IntentService:
    """Get or create the intent service singleton."""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentService(policy_engine, ledger_service)
    return _intent_service
