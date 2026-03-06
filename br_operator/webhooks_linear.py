"""
Linear Webhooks Handler
Receives Linear webhook events and routes to AI workflow engine
"""

import logging

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from .ai_workflow_engine import (
    get_ai_workflow_engine,
    WorkflowTrigger
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ============================================
# WEBHOOK ENDPOINTS
# ============================================

@router.post("/linear")
async def linear_webhook(
    request: Request,
    x_linear_signature: str = Header(None)
):
    """
    Linear webhook endpoint

    Handles:
    - Issue created
    - Issue updated
    - Issue state changed
    - Comment created
    - Label added
    """
    try:
        # Get webhook payload
        payload = await request.json()

        # Verify webhook signature (if configured)
        if x_linear_signature:
            # TODO: Verify signature using Linear webhook secret
            pass

        # Get event type
        action = payload.get('action')
        event_type = payload.get('type')

        logger.info(f"Received Linear webhook: {event_type} - {action}")

        # Map Linear events to workflow triggers
        trigger = _map_linear_event_to_trigger(action, event_type)

        if trigger is None:
            logger.info(f"Ignoring event: {event_type} - {action}")
            return JSONResponse(
                status_code=200,
                content={"message": "Event ignored"}
            )

        # Get AI workflow engine
        engine = await get_ai_workflow_engine()

        # Process workflow
        result = await engine.process_webhook(trigger, payload)

        # Log result
        if result.success:
            logger.info(
                f"Workflow success for {result.issue_id}: "
                f"{', '.join(result.actions_taken)}"
            )
        else:
            logger.error(
                f"Workflow failed for {result.issue_id}: {result.error}"
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": result.success,
                "issue_id": result.issue_id,
                "actions_taken": result.actions_taken,
                "classifications": result.classifications,
                "notion_page_id": result.notion_page_id,
                "error": result.error
            }
        )

    except Exception as e:
        logger.error(f"Linear webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/linear-notion-sync")
async def linear_notion_sync_webhook(request: Request):
    """
    Dedicated endpoint for Linear -> Notion sync

    Triggered when Linear issues are marked as Done
    """
    try:
        payload = await request.json()

        # Check if this is a state change to "Done"
        data = payload.get('data', {})
        state = data.get('state', {}).get('name', '')

        if state != "Done":
            return JSONResponse(
                status_code=200,
                content={"message": "Not a Done state, ignoring"}
            )

        # Get AI workflow engine
        engine = await get_ai_workflow_engine()

        # Parse issue
        issue = engine._parse_linear_issue(payload)

        # Generate Notion doc
        result = await engine.generate_notion_doc(issue)

        return JSONResponse(
            status_code=200,
            content={
                "success": result.success,
                "notion_page_id": result.notion_page_id,
                "actions_taken": result.actions_taken
            }
        )

    except Exception as e:
        logger.error(f"Linear-Notion sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# NOTION WEBHOOKS
# ============================================

@router.post("/notion")
async def notion_webhook(request: Request):
    """
    Notion webhook endpoint (for bidirectional sync)

    Note: Notion doesn't have native webhooks, but this can be used
    with third-party services like Zapier or Make.com
    """
    try:
        payload = await request.json()

        logger.info(f"Received Notion webhook: {payload}")

        # TODO: Implement Notion -> Linear sync
        # This would:
        # 1. Parse Notion page updates
        # 2. Find linked Linear issue
        # 3. Update Linear issue via GraphQL API

        return JSONResponse(
            status_code=200,
            content={"message": "Notion webhook received"}
        )

    except Exception as e:
        logger.error(f"Notion webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# HEALTH & STATUS
# ============================================

@router.get("/linear/health")
async def linear_health():
    """Check Linear webhook health"""
    try:
        engine = await get_ai_workflow_engine()

        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "integrations": {
                    "linear": "configured",
                    "notion": "configured",
                    "huggingface": "configured"
                },
                "workflows": {
                    "auto_triage": engine.linear_config['ai_workflows']['auto_triage']['enabled'],
                    "notion_sync": engine.linear_config['ai_workflows']['notion_sync']['enabled'],
                    "moderation": engine.linear_config['ai_workflows']['moderation']['enabled']
                }
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "unhealthy", "error": str(e)}
        )


# ============================================
# UTILITIES
# ============================================

def _map_linear_event_to_trigger(
    action: str,
    event_type: str
) -> WorkflowTrigger | None:
    """Map Linear webhook event to WorkflowTrigger"""

    # Issue events
    if event_type == "Issue":
        if action == "create":
            return WorkflowTrigger.ISSUE_CREATED
        elif action == "update":
            return WorkflowTrigger.ISSUE_UPDATED
        elif action == "state_change":
            return WorkflowTrigger.ISSUE_STATE_CHANGED

    # Comment events
    elif event_type == "Comment":
        if action == "create":
            return WorkflowTrigger.COMMENT_CREATED

    # Label events
    elif event_type == "IssueLabel":
        if action == "create":
            return WorkflowTrigger.LABEL_ADDED

    return None


# ============================================
# MANUAL TRIGGERS (for testing)
# ============================================

@router.post("/linear/manual-triage/{issue_id}")
async def manual_triage(issue_id: str):
    """Manually trigger AI triage for a specific issue"""
    try:
        engine = await get_ai_workflow_engine()

        # In production, fetch issue from Linear API
        # For now, return example

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Manual triage triggered for issue {issue_id}",
                "note": "Would fetch from Linear API and process"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/linear/manual-notion-sync/{issue_id}")
async def manual_notion_sync(issue_id: str):
    """Manually trigger Notion doc generation for a specific issue"""
    try:
        engine = await get_ai_workflow_engine()

        # In production, fetch issue from Linear API
        # For now, return example

        return JSONResponse(
            status_code=200,
            content={
                "message": f"Manual Notion sync triggered for issue {issue_id}",
                "note": "Would fetch from Linear API and generate doc"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
