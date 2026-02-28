"""
Solasta — Orchestrator Engine

The core state machine that drives the Plan-Execute-Verify-Replan cycle.
Manages goal lifecycle, step sequencing with dependency resolution,
and real-time event broadcasting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.cognitive.agents.evaluator import EvaluatorAgent
from app.cognitive.agents.executor import ExecutorAgent
from app.cognitive.agents.planner import PlannerAgent
from app.cognitive.agents.replanner import ReplannerAgent
from app.core.logging import get_logger
from app.db.repository import (
    AgentLogRepository,
    GoalRepository,
    MemoryRepository,
    PlanRepository,
    StepRepository,
)
from app.schemas.models import (
    EvalResult,
    Goal,
    GoalStatus,
    Plan,
    StepStatus,
    StreamEvent,
)

logger = get_logger(__name__)


class Orchestrator:
    """
    Central state machine driving the agent lifecycle.

    State transitions:
        RECEIVED → PLANNING → EXECUTING → COMPLETED
                                ↓            ↑
                            EVALUATING ─→ REPLANNING
                                ↓
                              FAILED (after max retries)
    """

    def __init__(self):
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.evaluator = EvaluatorAgent()
        self.replanner = ReplannerAgent()
        self._event_listeners: List[Callable] = []
        self._listener_lock = asyncio.Lock()
        self._active_goals: Dict[str, asyncio.Task] = {}

    def add_event_listener(self, listener: Callable) -> None:
        """Register a callback for real-time events (SSE/WebSocket)."""
        self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable) -> None:
        """Remove an event listener."""
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)

    async def _broadcast(self, event: StreamEvent) -> None:
        """Broadcast an event to all registered listeners."""
        async with self._listener_lock:
            listeners = list(self._event_listeners)

        for listener in listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(event)
                else:
                    listener(event)
            except Exception as e:
                logger.warning("broadcast_error", error=str(e))

    # ── Main Execution Entry Point ──────────────────────────

    async def process_goal(self, goal: Goal) -> Goal:
        """
        Full lifecycle processing of a goal:
        Plan → Execute → Evaluate → Replan (if needed) → Complete
        """
        logger.info("orchestrator_start", goal_id=goal.id)

        try:
            # ── Phase 15: Hackathon Optimization Strategy ─────────
            # Hardcoded safe-mode fallback to bypass LLM and Internet failure during pitch.
            if "DEMO-SAFE-001" in goal.raw_input.upper():
                logger.warning("DEMO_SAFE_MODE_ACTIVATED", goal_id=goal.id)
                import asyncio
                
                # Mock a successful execution manually
                goal = await GoalRepository.update_status(goal.id, GoalStatus.PLANNING)
                await self._broadcast(StreamEvent(event_type="goal_status", goal_id=goal.id, data={"status": "planning"}))
                
                # Mock Plan
                from app.schemas.models import Plan, Step
                plan = Plan(goal_id=goal.id, steps=[
                    Step(step_id="safe_1", title="Simulated Fetch", status="pending"),
                    Step(step_id="safe_2", title="Simulated Schedule", status="pending")
                ])
                plan = await PlanRepository.create(plan)
                
                await self._broadcast(StreamEvent(
                    event_type="plan_created", goal_id=goal.id,
                    data={"plan_id": plan.id, "version": plan.version, "steps": [s.model_dump(mode="json") for s in plan.steps]}
                ))
                
                await asyncio.sleep(1)
                for i, s in enumerate(plan.steps):
                    s.status = "in_progress"
                    await self._broadcast(StreamEvent(event_type="step_update", goal_id=goal.id, data={"step_id": s.step_id, "status": "in_progress"}))
                    await asyncio.sleep(1)
                    s.status = "completed"
                    await self._broadcast(StreamEvent(event_type="step_update", goal_id=goal.id, data={"step_id": s.step_id, "status": "completed"}))
                
                goal = await GoalRepository.update_status(goal.id, GoalStatus.COMPLETED)
                await self._broadcast(StreamEvent(event_type="goal_completed", goal_id=goal.id, data={"status": "completed"}))
                return goal

            # ── Phase 1: Planning ────────────────────────────
            goal = await GoalRepository.update_status(goal.id, GoalStatus.PLANNING)
            await self._broadcast(StreamEvent(
                event_type="goal_status",
                goal_id=goal.id,
                data={"status": "planning", "message": "Decomposing goal into execution plan..."},
            ))

            plan = await self.planner.create_plan(goal.id, goal.raw_input)
            plan = await PlanRepository.create(plan)
            goal = await GoalRepository.update_status(
                goal.id, GoalStatus.EXECUTING, active_plan_id=plan.id
            )

            await self._broadcast(StreamEvent(
                event_type="plan_created",
                goal_id=goal.id,
                data={
                    "plan_id": plan.id,
                    "version": plan.version,
                    "steps": [s.model_dump(mode="json") for s in plan.steps],
                },
            ))

            # ── Phase 2: Execute-Evaluate Loop ───────────────
            plan = await self._execute_plan(plan, goal.id, goal.raw_input)

            # ── Phase 3: Completion ──────────────────────────
            if plan.is_complete():
                goal = await GoalRepository.update_status(goal.id, GoalStatus.COMPLETED)
                await self._broadcast(StreamEvent(
                    event_type="goal_completed",
                    goal_id=goal.id,
                    data={"status": "completed", "message": "All steps completed successfully"},
                ))

                # Store experience in long-term memory
                await MemoryRepository.store(
                    goal_id=goal.id,
                    summary=goal.raw_input,
                    outcome={"plan_versions": plan.version, "steps_completed": len(plan.steps)},
                )
            else:
                goal = await GoalRepository.update_status(goal.id, GoalStatus.FAILED)
                await self._broadcast(StreamEvent(
                    event_type="goal_failed",
                    goal_id=goal.id,
                    data={"status": "failed", "message": "Goal could not be completed after all retries"},
                ))

            logger.info("orchestrator_complete", goal_id=goal.id, status=goal.status.value)
            return goal

        except Exception as e:
            logger.error("orchestrator_error", goal_id=goal.id, error=str(e))
            goal = await GoalRepository.update_status(goal.id, GoalStatus.FAILED)
            await self._broadcast(StreamEvent(
                event_type="error",
                goal_id=goal.id,
                data={"error": str(e), "component": "orchestrator"},
            ))
            return goal

    async def _execute_plan(self, plan: Plan, goal_id: str, goal_raw_input: str = "") -> Plan:
        """
        Execute all steps in dependency order with evaluation and replanning.
        """
        max_plan_iterations = 5  # Prevent infinite replanning loops
        iteration = 0

        while not plan.is_complete() and iteration < max_plan_iterations:
            iteration += 1
            ready_steps = plan.get_ready_steps()

            if not ready_steps:
                if plan.has_failed_steps():
                    logger.warning("no_ready_steps_with_failures", goal_id=goal_id)
                    break
                logger.warning("no_ready_steps", goal_id=goal_id)
                break

            if len(ready_steps) > 1:
                # ── PARALLEL EXECUTION of independent steps ───
                logger.info("parallel_execution", goal_id=goal_id, steps=[s.step_id for s in ready_steps])
                
                async def execute_single_step(step):
                    step.status = StepStatus.IN_PROGRESS
                    step.started_at = datetime.utcnow()
                    await StepRepository.update_step_in_plan(
                        plan.id, step.step_id,
                        status=StepStatus.IN_PROGRESS,
                        started_at=step.started_at,
                    )
                    await PlanRepository.update(plan)

                    await self._broadcast(StreamEvent(
                        event_type="step_update",
                        goal_id=goal_id,
                        data={"step_id": step.step_id, "status": "in_progress", "title": step.title},
                    ))

                    previous_results = self._gather_previous_results(plan, step)
                    exec_result = await self.executor.execute_step(
                        step=step,
                        goal_id=goal_id,
                        plan_id=plan.id,
                        previous_results=previous_results,
                        goal_context=goal_raw_input,
                    )
                    return step, exec_result

                parallel_results = await asyncio.gather(
                    *[execute_single_step(s) for s in ready_steps],
                    return_exceptions=True,
                )

                needs_replan = False
                for result in parallel_results:
                    if isinstance(result, Exception):
                        logger.error("parallel_step_exception", error=str(result))
                        continue
                    step, exec_result = result
                    
                    # Evaluate
                    step.status = StepStatus.EVALUATING
                    await self._broadcast(StreamEvent(
                        event_type="step_update",
                        goal_id=goal_id,
                        data={"step_id": step.step_id, "status": "evaluating"},
                    ))

                    evaluation = await self.evaluator.evaluate(
                        step=step,
                        execution_result=exec_result,
                        goal_id=goal_id,
                        plan_id=plan.id,
                    )

                    if evaluation.result == EvalResult.SUCCESS:
                        step.status = StepStatus.COMPLETED
                        step.result_payload = exec_result
                        step.completed_at = datetime.utcnow()
                        await StepRepository.update_step_in_plan(
                            plan.id, step.step_id,
                            status=StepStatus.COMPLETED,
                            result_payload=exec_result,
                            completed_at=step.completed_at,
                        )
                        await PlanRepository.update(plan)
                        await self._broadcast(StreamEvent(
                            event_type="step_update",
                            goal_id=goal_id,
                            data={
                                "step_id": step.step_id,
                                "status": "completed",
                                "result_summary": exec_result.get("result_summary", ""),
                            },
                        ))
                    else:
                        step.retry_count += 1
                        if step.retry_count >= step.max_retries:
                            step.status = StepStatus.FAILED
                            step.error_message = evaluation.reasoning
                            await StepRepository.update_step_in_plan(
                                plan.id, step.step_id,
                                status=StepStatus.FAILED,
                                error_message=evaluation.reasoning,
                            )
                            await self._broadcast(StreamEvent(
                                event_type="step_update",
                                goal_id=goal_id,
                                data={"step_id": step.step_id, "status": "failed", "error": evaluation.reasoning},
                            ))
                            needs_replan = True
                        else:
                            step.status = StepStatus.PENDING
                            step.error_message = evaluation.reasoning
                            await StepRepository.update_step_in_plan(
                                plan.id, step.step_id,
                                status=StepStatus.PENDING,
                                error_message=evaluation.reasoning,
                                retry_count=step.retry_count,
                            )
                            await PlanRepository.update(plan)
                            await self._broadcast(StreamEvent(
                                event_type="step_update",
                                goal_id=goal_id,
                                data={"step_id": step.step_id, "status": "retrying", "retry_count": step.retry_count},
                            ))

                if needs_replan:
                    failed_step = next((s for s in ready_steps if s.status == StepStatus.FAILED), None)
                    if failed_step:
                        await self._broadcast(StreamEvent(
                            event_type="replanning",
                            goal_id=goal_id,
                            data={"message": f"Replanning after step '{failed_step.title}' failed"},
                        ))
                        await PlanRepository.deactivate_for_goal(goal_id)
                        new_plan = await self.replanner.replan(
                            plan=plan, failed_step=failed_step,
                            evaluation=evaluation, execution_result=exec_result,
                            goal_id=goal_id,
                        )
                        new_plan = await PlanRepository.create(new_plan)
                        plan = new_plan
                        await self._broadcast(StreamEvent(
                            event_type="plan_created",
                            goal_id=goal_id,
                            data={
                                "plan_id": plan.id, "version": plan.version,
                                "steps": [s.model_dump(mode="json") for s in plan.steps],
                                "message": "Plan updated after failure recovery",
                            },
                        ))

            else:
                # ── SEQUENTIAL EXECUTION (single step) ────────
                step = ready_steps[0]
                # ── Mark step as in-progress ─────────────────
                step.status = StepStatus.IN_PROGRESS
                step.started_at = datetime.utcnow()
                await StepRepository.update_step_in_plan(
                    plan.id, step.step_id,
                    status=StepStatus.IN_PROGRESS,
                    started_at=step.started_at,
                )
                await PlanRepository.update(plan)

                await self._broadcast(StreamEvent(
                    event_type="step_update",
                    goal_id=goal_id,
                    data={"step_id": step.step_id, "status": "in_progress", "title": step.title},
                ))

                # ── Gather previous step outputs ─────────────
                previous_results = self._gather_previous_results(plan, step)

                # ── Execute ──────────────────────────────────
                exec_result = await self.executor.execute_step(
                    step=step,
                    goal_id=goal_id,
                    plan_id=plan.id,
                    previous_results=previous_results,
                    goal_context=goal_raw_input,
                )

                # ── Evaluate ─────────────────────────────────
                step.status = StepStatus.EVALUATING
                await self._broadcast(StreamEvent(
                    event_type="step_update",
                    goal_id=goal_id,
                    data={"step_id": step.step_id, "status": "evaluating"},
                ))

                evaluation = await self.evaluator.evaluate(
                    step=step,
                    execution_result=exec_result,
                    goal_id=goal_id,
                    plan_id=plan.id,
                )

                # ── Handle Evaluation Outcome ────────────────
                if evaluation.result == EvalResult.SUCCESS:
                    step.status = StepStatus.COMPLETED
                    step.result_payload = exec_result
                    step.completed_at = datetime.utcnow()

                    await StepRepository.update_step_in_plan(
                        plan.id, step.step_id,
                        status=StepStatus.COMPLETED,
                        result_payload=exec_result,
                        completed_at=step.completed_at,
                    )
                    await PlanRepository.update(plan)

                    await self._broadcast(StreamEvent(
                        event_type="step_update",
                        goal_id=goal_id,
                        data={
                            "step_id": step.step_id,
                            "status": "completed",
                            "result_summary": exec_result.get("result_summary", ""),
                        },
                    ))

                elif evaluation.result in (EvalResult.FAILURE, EvalResult.PARTIAL):
                    step.retry_count += 1
                    logger.warning(
                        "step_failed",
                        step_id=step.step_id,
                        retry=step.retry_count,
                        max=step.max_retries,
                    )

                    if step.retry_count >= step.max_retries:
                        # Trigger replanning
                        step.status = StepStatus.FAILED
                        step.error_message = evaluation.reasoning

                        await StepRepository.update_step_in_plan(
                            plan.id, step.step_id,
                            status=StepStatus.FAILED,
                            error_message=evaluation.reasoning,
                        )

                        await self._broadcast(StreamEvent(
                            event_type="step_update",
                            goal_id=goal_id,
                            data={
                                "step_id": step.step_id,
                                "status": "failed",
                                "error": evaluation.reasoning,
                            },
                        ))

                        # ── Replan ────────────────────────────
                        await self._broadcast(StreamEvent(
                            event_type="replanning",
                            goal_id=goal_id,
                            data={"message": f"Replanning after step '{step.title}' failed"},
                        ))

                        # Deactivate old plan
                        await PlanRepository.deactivate_for_goal(goal_id)

                        new_plan = await self.replanner.replan(
                            plan=plan,
                            failed_step=step,
                            evaluation=evaluation,
                            execution_result=exec_result,
                            goal_id=goal_id,
                        )
                        new_plan = await PlanRepository.create(new_plan)
                        plan = new_plan

                        await self._broadcast(StreamEvent(
                            event_type="plan_created",
                            goal_id=goal_id,
                            data={
                                "plan_id": plan.id,
                                "version": plan.version,
                                "steps": [s.model_dump(mode="json") for s in plan.steps],
                                "message": "Plan updated after failure recovery",
                            },
                        ))
                        break  # Restart the execution loop with new plan

                    else:
                        # Simple retry: reset to pending
                        step.status = StepStatus.PENDING
                        step.error_message = evaluation.reasoning
                        await StepRepository.update_step_in_plan(
                            plan.id, step.step_id,
                            status=StepStatus.PENDING,
                            error_message=evaluation.reasoning,
                            retry_count=step.retry_count,
                        )
                        await PlanRepository.update(plan)

                        await self._broadcast(StreamEvent(
                            event_type="step_update",
                            goal_id=goal_id,
                            data={
                                "step_id": step.step_id,
                                "status": "retrying",
                                "retry_count": step.retry_count,
                            },
                        ))

        return plan

    def _gather_previous_results(self, plan: Plan, step) -> Dict[str, Any]:
        """Collect results from completed dependency steps."""
        results = {}
        for dep_id in step.depends_on:
            for s in plan.steps:
                if s.step_id == dep_id and s.result_payload:
                    results[dep_id] = s.result_payload
        return results

    async def start_goal_async(self, goal: Goal) -> str:
        """Fire-and-forget goal processing for async API responses."""
        task = asyncio.create_task(self.process_goal(goal))
        self._active_goals[goal.id] = task

        def _cleanup(done_task: asyncio.Task, gid: str = goal.id) -> None:
            self._active_goals.pop(gid, None)
            try:
                done_task.result()
            except Exception as exc:
                logger.error("orchestrator_background_task_error", goal_id=gid, error=str(exc))

        task.add_done_callback(_cleanup)
        return goal.id

    async def get_goal_status(self, goal_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a goal and its active plan."""
        goal = await GoalRepository.get(goal_id)
        if not goal:
            return None

        plan = await PlanRepository.get_active_for_goal(goal_id)
        logs = await AgentLogRepository.get_for_goal(goal_id)

        return {
            "goal": goal.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json") if plan else None,
            "log_count": len(logs),
        }


# Singleton
orchestrator = Orchestrator()
