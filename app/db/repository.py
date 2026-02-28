"""
Solasta — Repository Layer (SQLite Persistent)

Data access layer implementing the Repository pattern.
Uses aiosqlite for async persistent storage.
All data survives server restarts.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

from app.core.logging import get_logger
from app.schemas.models import (
    AgentLog,
    Goal,
    GoalStatus,
    Plan,
    Step,
    StepStatus,
)

logger = get_logger(__name__)

DB_PATH = "solasta.db"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Database Initialization
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_initialized = False


async def _ensure_db():
    """Create tables if they don't exist. Called lazily."""
    global _initialized
    if _initialized:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                json_data TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                json_data TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                json_data TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id TEXT NOT NULL,
                summary TEXT,
                outcome TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    _initialized = True
    logger.info("database_initialized", path=DB_PATH)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GoalRepository
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GoalRepository:
    """CRUD operations for Goals — SQLite backed."""

    @staticmethod
    async def create(goal: Goal) -> Goal:
        await _ensure_db()
        data = goal.model_dump(mode="json")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO goals (id, json_data) VALUES (?, ?)",
                (goal.id, json.dumps(data)),
            )
            await db.commit()
        logger.info("goal_created", goal_id=goal.id)
        return goal

    @staticmethod
    async def get(goal_id: str) -> Optional[Goal]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT json_data FROM goals WHERE id = ?", (goal_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Goal(**json.loads(row[0]))
        return None

    @staticmethod
    async def update_status(goal_id: str, status: GoalStatus, **kwargs) -> Optional[Goal]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT json_data FROM goals WHERE id = ?", (goal_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
            data = json.loads(row[0])
            data["status"] = status.value
            data["updated_at"] = datetime.utcnow().isoformat()
            for k, v in kwargs.items():
                data[k] = v
            await db.execute(
                "UPDATE goals SET json_data = ? WHERE id = ?",
                (json.dumps(data), goal_id),
            )
            await db.commit()
            return Goal(**data)

    @staticmethod
    async def list_all(user_id: Optional[str] = None) -> List[Goal]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT json_data FROM goals ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
        goals = [Goal(**json.loads(r[0])) for r in rows]
        if user_id:
            goals = [g for g in goals if g.user_id == user_id]
        return goals


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PlanRepository
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PlanRepository:
    """CRUD operations for Plans — SQLite backed."""

    @staticmethod
    async def create(plan: Plan) -> Plan:
        await _ensure_db()
        data = plan.model_dump(mode="json")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO plans (id, goal_id, is_active, json_data) VALUES (?, ?, ?, ?)",
                (plan.id, plan.goal_id, 1 if plan.is_active else 0, json.dumps(data)),
            )
            await db.commit()
        logger.info("plan_created", plan_id=plan.id, goal_id=plan.goal_id, version=plan.version)
        return plan

    @staticmethod
    async def get(plan_id: str) -> Optional[Plan]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT json_data FROM plans WHERE id = ?", (plan_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Plan(**json.loads(row[0]))
        return None

    @staticmethod
    async def get_active_for_goal(goal_id: str) -> Optional[Plan]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT json_data FROM plans WHERE goal_id = ? AND is_active = 1 ORDER BY rowid DESC LIMIT 1",
                (goal_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Plan(**json.loads(row[0]))
        return None

    @staticmethod
    async def update(plan: Plan) -> Plan:
        await _ensure_db()
        data = plan.model_dump(mode="json")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE plans SET json_data = ?, is_active = ? WHERE id = ?",
                (json.dumps(data), 1 if plan.is_active else 0, plan.id),
            )
            await db.commit()
        return plan

    @staticmethod
    async def deactivate_for_goal(goal_id: str) -> None:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            # Update the is_active column
            await db.execute(
                "UPDATE plans SET is_active = 0 WHERE goal_id = ?", (goal_id,)
            )
            # Also update inside the json_data
            async with db.execute(
                "SELECT id, json_data FROM plans WHERE goal_id = ?", (goal_id,)
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                data = json.loads(row[1])
                data["is_active"] = False
                await db.execute(
                    "UPDATE plans SET json_data = ? WHERE id = ?",
                    (json.dumps(data), row[0]),
                )
            await db.commit()

    @staticmethod
    async def get_versions_for_goal(goal_id: str) -> List[Plan]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT json_data FROM plans WHERE goal_id = ? ORDER BY rowid ASC",
                (goal_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        versions = [Plan(**json.loads(r[0])) for r in rows]
        return sorted(versions, key=lambda x: x.version)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# StepRepository
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StepRepository:
    """Step-level operations — updates steps inside the plan JSON."""

    @staticmethod
    async def update_step_in_plan(plan_id: str, step_id: str, **updates) -> Optional[Step]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT json_data FROM plans WHERE id = ?", (plan_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
            plan_data = json.loads(row[0])
            for i, s in enumerate(plan_data["steps"]):
                if s["step_id"] == step_id:
                    for k, v in updates.items():
                        if isinstance(v, datetime):
                            plan_data["steps"][i][k] = v.isoformat()
                        elif hasattr(v, "value"):
                            plan_data["steps"][i][k] = v.value
                        else:
                            plan_data["steps"][i][k] = v
                    await db.execute(
                        "UPDATE plans SET json_data = ? WHERE id = ?",
                        (json.dumps(plan_data), plan_id),
                    )
                    await db.commit()
                    return Step(**plan_data["steps"][i])
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AgentLogRepository
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AgentLogRepository:
    """Immutable append-only log of all agent activity — SQLite backed."""

    @staticmethod
    async def append(log: AgentLog) -> None:
        await _ensure_db()
        log_dump = log.model_dump(mode="json")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO agent_logs (id, goal_id, json_data) VALUES (?, ?, ?)",
                (log.id, log.goal_id, json.dumps(log_dump)),
            )
            await db.commit()
        logger.debug("agent_log_appended", agent_type=log.agent_type, goal_id=log.goal_id)
        sys.stdout.write(json.dumps({"type": "agent_log", "data": log_dump}) + "\n")
        sys.stdout.flush()

    @staticmethod
    async def get_for_goal(goal_id: str) -> List[AgentLog]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT json_data FROM agent_logs WHERE goal_id = ? ORDER BY created_at ASC",
                (goal_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [AgentLog(**json.loads(r[0])) for r in rows]

    @staticmethod
    async def get_all() -> List[Dict[str, Any]]:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT json_data FROM agent_logs ORDER BY created_at ASC") as cursor:
                rows = await cursor.fetchall()
        return [json.loads(r[0]) for r in rows]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MemoryRepository
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MemoryRepository:
    """Long-term memory storage for experience recall — SQLite backed."""

    @staticmethod
    async def store(goal_id: str, summary: str, outcome: Dict[str, Any]) -> None:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO memory (goal_id, summary, outcome) VALUES (?, ?, ?)",
                (goal_id, summary, json.dumps(outcome)),
            )
            await db.commit()
        logger.info("memory_stored", goal_id=goal_id)

    @staticmethod
    async def recall_similar(query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Simple keyword-based recall from persistent memory."""
        await _ensure_db()
        query_lower = query.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT goal_id, summary, outcome, created_at FROM memory") as cursor:
                rows = await cursor.fetchall()
        results = []
        for row in rows:
            summary_lower = (row[1] or "").lower()
            score = sum(1 for word in query_lower.split() if word in summary_lower)
            if score > 0:
                results.append((score, {
                    "goal_id": row[0],
                    "summary": row[1],
                    "outcome": json.loads(row[2]) if row[2] else {},
                    "timestamp": row[3],
                }))
        results.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in results[:limit]]
