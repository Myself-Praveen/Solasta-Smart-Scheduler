"""
Solasta — API Routes

Asynchronous REST + SSE endpoints for goal management,
plan inspection, real-time streaming, and agent logs.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.logging import get_logger
from app.db.repository import (
    AgentLogRepository,
    GoalRepository,
    PlanRepository,
)
from app.orchestrator.engine import orchestrator
from app.schemas.models import (
    Goal,
    GoalCreate,
    GoalResponse,
    GoalStatus,
    StreamEvent,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["goals"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /api/goals — Create and process a new goal
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/goals", response_model=GoalResponse, status_code=202)
async def create_goal(request: GoalCreate):
    """
    Accept a natural language goal, create it, and begin async processing.
    Returns immediately with 202 Accepted.
    """
    logger.info("api_create_goal", user_input=request.user_input[:100])

    goal = Goal(
        user_id=request.user_id,
        raw_input=request.user_input,
    )
    goal = await GoalRepository.create(goal)

    # Fire-and-forget: start orchestrator in background
    await orchestrator.start_goal_async(goal)

    return GoalResponse(
        goal_id=goal.id,
        status=goal.status,
        message="Goal received. Processing started. Use /api/goals/{id}/stream for real-time updates.",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/goals/{id} — Get goal status and plan
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/goals/{goal_id}")
async def get_goal(goal_id: str):
    """Fetch current state of a goal and its active plan."""
    result = await orchestrator.get_goal_status(goal_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/goals/{id}/plan — Get the execution plan
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/goals/{goal_id}/plan")
async def get_plan(goal_id: str):
    """Fetch the active plan for a goal."""
    plan = await PlanRepository.get_active_for_goal(goal_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No active plan found")
    return plan.model_dump(mode="json")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/goals/{id}/plan/history — Get all plan versions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/goals/{goal_id}/plan/history")
async def get_plan_history(goal_id: str):
    """Fetch all plan versions (immutable audit trail)."""
    versions = await PlanRepository.get_versions_for_goal(goal_id)
    return [v.model_dump(mode="json") for v in versions]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/goals/{id}/stream — SSE real-time event stream
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/goals/{goal_id}/stream")
async def stream_goal_events(goal_id: str, request: Request):
    """Server-Sent Events stream for real-time goal execution updates."""
    event_queue: asyncio.Queue = asyncio.Queue()

    async def listener(event: StreamEvent):
        if event.goal_id == goal_id:
            await event_queue.put(event)

    orchestrator.add_event_listener(listener)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("sse_client_disconnected", goal_id=goal_id)
                    break

                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                    yield f"event: {event.event_type}\ndata: {json.dumps(event.data, default=str)}\n\n"

                    if event.event_type in ("goal_completed", "goal_failed", "error"):
                        break
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"
        except asyncio.CancelledError:
            logger.info("sse_stream_cancelled", goal_id=goal_id)
            raise
        finally:
            orchestrator.remove_event_listener(listener)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/goals/{id}/logs — Agent execution logs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/goals/{goal_id}/logs")
async def get_goal_logs(goal_id: str):
    """Get all agent execution logs for a goal."""
    logs = await AgentLogRepository.get_for_goal(goal_id)
    return [l.model_dump(mode="json") for l in logs]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/goals — List all goals
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/goals")
async def list_goals(user_id: Optional[str] = Query(None)):
    """List all goals, optionally filtered by user_id."""
    goals = await GoalRepository.list_all(user_id)
    return [g.model_dump(mode="json") for g in goals]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /asi/chat — ASI:One Chat Protocol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ASIChatRequest(BaseModel):
    message: str
    sender: str = ""
    session_id: str = ""


class ASIChatResponse(BaseModel):
    response: str
    status: str
    goal_id: Optional[str] = None
    plan_summary: Optional[Dict[str, Any]] = None


asi_router = APIRouter(prefix="/asi", tags=["asi-protocol"])


@asi_router.post("/chat", response_model=ASIChatResponse)
async def asi_chat(request: ASIChatRequest):
    """
    ASI:One Chat Protocol endpoint.
    Accepts a message, creates a goal, and returns initial status.
    """
    logger.info("asi_chat_received", sender=request.sender)

    goal = Goal(
        user_id=request.sender or "asi_user",
        raw_input=request.message,
    )
    goal = await GoalRepository.create(goal)
    await orchestrator.start_goal_async(goal)

    return ASIChatResponse(
        response=f"I've received your goal and started processing. Track progress at /api/goals/{goal.id}/stream",
        status="processing",
        goal_id=goal.id,
    )
