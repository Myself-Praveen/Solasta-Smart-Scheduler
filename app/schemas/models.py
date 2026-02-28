"""
Solasta — Domain Schemas

Strict Pydantic models for Goals, Plans, Steps, and all internal data contracts.
These models are used for LLM structured output parsing, API validation,
and database serialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Enums
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GoalStatus(str, Enum):
    RECEIVED = "received"
    PLANNING = "planning"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REPLANNED = "replanned"


class StepPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvalResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Goal
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GoalCreate(BaseModel):
    """Incoming request to create a new goal."""
    user_input: str = Field(..., min_length=5, description="Natural language goal from the user")
    user_id: str = Field(default_factory=lambda: str(uuid4()))


class Goal(BaseModel):
    """Full goal record."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    raw_input: str
    parsed_objective: str = ""
    constraints: List[str] = Field(default_factory=list)
    status: GoalStatus = GoalStatus.RECEIVED
    active_plan_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step (node in the execution DAG)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Step(BaseModel):
    """A single actionable step within a plan."""
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str
    expected_outcome: str
    thought_process: str = ""
    priority: StepPriority = StepPriority.MEDIUM
    depends_on: List[str] = Field(default_factory=list, description="List of step_ids this step depends on")
    required_tools: List[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result_payload: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Plan (versioned DAG of steps)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Plan(BaseModel):
    """A versioned execution plan (DAG of Steps)."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    goal_id: str
    version: int = 1
    is_active: bool = True
    steps: List[Step] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def get_ready_steps(self) -> List[Step]:
        """Return steps whose dependencies are all completed."""
        completed_ids = {
            s.step_id
            for s in self.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        }
        return [
            s for s in self.steps
            if s.status == StepStatus.PENDING
            and all(dep in completed_ids for dep in s.depends_on)
        ]

    def is_complete(self) -> bool:
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    def has_failed_steps(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Evaluation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StepEvaluation(BaseModel):
    """Output from the Evaluator chain."""
    step_id: str
    result: EvalResult
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    suggestions: List[str] = Field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent Log
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AgentLog(BaseModel):
    """Immutable record of every LLM call and tool invocation."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    goal_id: str
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    agent_type: str  # planner | executor | evaluator | replanner
    provider: str  # ollama | gemini | openai
    model: str
    prompt_summary: str
    response_summary: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API Responses
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GoalResponse(BaseModel):
    """Standard API response for goal operations."""
    goal_id: str
    status: GoalStatus
    message: str
    plan: Optional[Plan] = None


class StreamEvent(BaseModel):
    """Real-time event pushed via SSE/WebSocket."""
    event_type: str  # step_update | plan_created | goal_completed | error
    goal_id: str
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    """Standardised error payload."""
    error_code: str
    component: str
    message: str
    trace: Optional[str] = None
    recovery_action: Optional[str] = None
