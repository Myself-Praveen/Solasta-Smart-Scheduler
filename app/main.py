"""
Solasta Smart Study Scheduler — Application Entry Point

FastAPI server with CORS, lifecycle hooks, and route registration.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import asi_router, router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging

# Import tools to trigger self-registration
import app.tools.study_tools  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    setup_logging()
    logger = get_logger("main")
    logger.info(
        "application_starting",
        app=settings.app_name,
        env=settings.app_env.value,
        primary_llm=settings.llm_primary_provider.value,
    )
    yield
    logger.info("application_shutdown")


app = FastAPI(
    title="Solasta Smart Study Scheduler",
    description=(
        "An autonomous AI agent that decomposes study goals into "
        "multi-step execution plans, executes them with verification, "
        "and adapts in real-time on failure."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────

app.include_router(router)
app.include_router(asi_router)


# ── Root ─────────────────────────────────────────────────────


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "agent": "Smart Study Schedule Agent",
        "architecture": "Plan-Execute-Verify-Replan State Machine",
    }


# ── Health Check ─────────────────────────────────────────────


@app.get("/health")
async def health():
    from app.tools.registry import get_all_tools
    tools = get_all_tools()
    return {
        "status": "healthy",
        "env": settings.app_env.value,
        "agent_name": "Solasta Smart Study Agent",
        "architecture": "Plan → Execute → Evaluate → Replan (Autonomous Loop)",
        "agents": ["PlannerAgent", "ExecutorAgent", "EvaluatorAgent", "ReplannerAgent"],
        "llm_provider": settings.llm_primary_provider.value,
        "llm_model": getattr(settings, f"{settings.llm_primary_provider.value}_model", "unknown"),
        "registered_tools": list(tools.keys()) if tools else [],
        "tool_count": len(tools) if tools else 0,
        "features": [
            "Natural language goal decomposition",
            "Multi-step DAG execution with dependency resolution",
            "Real-time SSE streaming",
            "Confidence-scored evaluation",
            "Adaptive replanning on failure",
            "Experience-aware planning (memory recall)",
            "ASI:One Chat Protocol support",
            "Dynamic exam syllabus generation (any exam worldwide)",
        ],
    }


# ── Global Exception Handler ────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    logger = get_logger("exception_handler")
    logger.error("unhandled_exception", error=str(exc), path=str(request.url))
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "component": "FastAPI_Global_Handler",
            "trace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            "agent_recovery_action": "Trigger Replanner or Escalate to Human",
        },
    )
