"""
Solasta — Replanner Agent

Triggered when the Evaluator reports a FAILURE. Modifies the plan
by inserting mitigation steps, adjusting parameters, or flagging
for human intervention. Creates a new plan version (immutable history).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from uuid import uuid4

from app.cognitive.llm.provider import llm_gateway
from app.core.logging import get_logger
from app.db.repository import AgentLogRepository
from app.schemas.models import Plan, Step, StepEvaluation, StepPriority, StepStatus

logger = get_logger(__name__)

REPLANNER_SYSTEM_PROMPT = """You are the Replanner Agent for a Smart Study Schedule system.

TASK:
Given a failed step, return a strictly valid recovery plan edit.

ALLOWED STRATEGIES:
- retry: retry failed step with no inserted nodes
- insert: insert one or more new recovery nodes that must run before failed step retry
- skip: mark failed step as skipped when non-critical
- escalate: mark failed step as failed with human intervention required

STRICT CONSTRAINTS:
1) Output ONLY a JSON object (no markdown).
2) Top-level keys MUST be exactly: strategy, reasoning, modified_steps
3) strategy MUST be one of: retry, insert, skip, escalate
4) For strategy="insert":
     - modified_steps MUST include at least 1 object with is_new=true
     - each new step must have non-empty expected_outcome and required_tools
     - each new step must be acyclic and actionable
5) For strategy="retry", "skip", or "escalate": modified_steps SHOULD be [] unless editing existing nodes is essential
6) Do not alter completed steps.
7) Preserve goal intent and downstream executability.

JSON SCHEMA:
{
    "strategy": "retry|insert|skip|escalate",
    "reasoning": "short evidence-based justification",
    "modified_steps": [
        {
            "step_id": "existing_or_new_id",
            "title": "string",
            "description": "string",
            "expected_outcome": "string",
            "thought_process": "string",
            "priority": "high|medium|low",
            "depends_on": ["step_id"],
            "required_tools": ["tool_name"],
            "is_new": true|false
        }
    ]
}
"""


class ReplannerAgent:
    """Adapts the plan when step execution fails."""

    async def replan(
        self,
        plan: Plan,
        failed_step: Step,
        evaluation: StepEvaluation,
        execution_result: Dict[str, Any],
        goal_id: str,
    ) -> Plan:
        """
        Create a new plan version with modifications to address the failure.
        """
        logger.info(
            "replanner_start",
            step_id=failed_step.step_id,
            failure_reason=evaluation.reasoning,
        )

        # Build context about the current plan state
        plan_state = self._describe_plan_state(plan)

        prompt = f"""PLAN STATE:
{plan_state}

FAILED STEP:
Title: {failed_step.title}
Description: {failed_step.description}
Expected Outcome: {failed_step.expected_outcome}
Thought Process: {failed_step.thought_process}
Retry Count: {failed_step.retry_count}/{failed_step.max_retries}

FAILURE EVALUATION:
Result: {evaluation.result.value}
Reasoning: {evaluation.reasoning}
Confidence: {evaluation.confidence}
Suggestions: {json.dumps(evaluation.suggestions)}

EXECUTION RESULT:
{json.dumps(execution_result, indent=2, default=str)[:1000]}

Modify the plan to recover from this failure."""

        try:
            result_text, log = await llm_gateway.generate(
                prompt=prompt,
                system=REPLANNER_SYSTEM_PROMPT,
                goal_id=goal_id,
                agent_type="replanner",
            )
            log.plan_id = plan.id
            log.step_id = failed_step.step_id
            await AgentLogRepository.append(log)

            replan_data = self._parse_replan_response(result_text)
            new_plan = self._apply_modifications(plan, failed_step, replan_data)

            logger.info(
                "replanner_success",
                strategy=replan_data.get("strategy", "unknown"),
                new_version=new_plan.version,
                num_steps=len(new_plan.steps),
            )
            return new_plan

        except Exception as e:
            logger.error("replanner_failed", error=str(e))
            # Fallback: simple retry strategy
            return self._simple_retry(plan, failed_step)

    def _describe_plan_state(self, plan: Plan) -> str:
        """Generate a textual summary of the current plan state."""
        lines = [f"Plan Version: {plan.version}", "Steps:"]
        for s in plan.steps:
            dep_str = f" (depends on: {', '.join(s.depends_on)})" if s.depends_on else ""
            lines.append(f"  [{s.status.value}] {s.step_id}: {s.title}{dep_str}")
        return "\n".join(lines)

    def _parse_replan_response(self, text: str) -> Dict[str, Any]:
        """Parse replanner JSON response."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("replanner_parse_fallback")
            return {"strategy": "retry", "reasoning": "Parse failed, defaulting to retry", "modified_steps": []}

    def _apply_modifications(
        self,
        old_plan: Plan,
        failed_step: Step,
        replan_data: Dict[str, Any],
    ) -> Plan:
        """Create a new Plan version applying the replanner's modifications."""
        strategy = replan_data.get("strategy", "retry")
        modified_steps = replan_data.get("modified_steps", [])

        modified_by_id = {
            ms.get("step_id"): ms
            for ms in modified_steps
            if ms.get("step_id") and not ms.get("is_new", False)
        }

        # Copy existing steps
        new_steps = []
        for s in old_plan.steps:
            step_copy = s.model_copy()
            if step_copy.step_id in modified_by_id and step_copy.status != StepStatus.COMPLETED:
                ms = modified_by_id[step_copy.step_id]
                step_copy.title = ms.get("title", step_copy.title)
                step_copy.description = ms.get("description", step_copy.description)
                step_copy.expected_outcome = ms.get("expected_outcome", step_copy.expected_outcome)
                step_copy.thought_process = ms.get("thought_process", step_copy.thought_process)
                step_copy.priority = StepPriority(ms.get("priority", step_copy.priority.value))
                step_copy.depends_on = ms.get("depends_on", step_copy.depends_on)
                step_copy.required_tools = ms.get("required_tools", step_copy.required_tools)

            if s.step_id == failed_step.step_id:
                if strategy == "retry":
                    step_copy.status = StepStatus.PENDING
                    step_copy.retry_count = 0
                    step_copy.error_message = None
                    step_copy.result_payload = None
                elif strategy == "skip":
                    step_copy.status = StepStatus.SKIPPED
                elif strategy == "escalate":
                    step_copy.status = StepStatus.FAILED
                    step_copy.error_message = "Escalated for human intervention"
            new_steps.append(step_copy)

        # Insert new steps if strategy is "insert"
        if strategy == "insert":
            inserted_ids = []
            for ms in modified_steps:
                if ms.get("is_new", False):
                    new_step_id = ms.get("step_id", f"replan_{str(uuid4())[:6]}")
                    depends_on = ms.get("depends_on", []) or list(failed_step.depends_on)
                    new_step = Step(
                        step_id=new_step_id,
                        title=ms.get("title", "Recovery Step"),
                        description=ms.get("description", ""),
                        expected_outcome=ms.get("expected_outcome", ""),
                        thought_process=ms.get("thought_process", f"Inserted by replanner (strategy: {strategy})"),
                        priority=StepPriority(ms.get("priority", "high")),
                        depends_on=depends_on,
                        required_tools=ms.get("required_tools", []),
                    )
                    new_steps.append(new_step)
                    inserted_ids.append(new_step.step_id)

            # Reset the failed step to pending so it can be retried after new steps
            for s in new_steps:
                if s.step_id == failed_step.step_id:
                    s.status = StepStatus.PENDING
                    s.retry_count = 0
                    s.depends_on = list(dict.fromkeys([*s.depends_on, *inserted_ids]))
                    s.error_message = None
                    s.result_payload = None

        return Plan(
            goal_id=old_plan.goal_id,
            version=old_plan.version + 1,
            is_active=True,
            steps=new_steps,
        )

    def _simple_retry(self, plan: Plan, failed_step: Step) -> Plan:
        """
        Minimal fallback: retry the failed step with a HARD CAP.
        If already at max retries, transition to FAILED to break infinite loops.
        """
        new_steps = []
        for s in plan.steps:
            step_copy = s.model_copy()
            if s.step_id == failed_step.step_id:
                # HARD CAP: If already exhausted retries in this plan version, mark as FAILED
                if s.retry_count >= s.max_retries:
                    logger.warning(
                        "replanner_hard_cap_reached",
                        step_id=s.step_id,
                        retry_count=s.retry_count,
                        max_retries=s.max_retries,
                    )
                    step_copy.status = StepStatus.FAILED
                    step_copy.error_message = f"Hard cap reached: {s.retry_count} retries exhausted. Terminating loop."
                else:
                    step_copy.status = StepStatus.PENDING
                    step_copy.retry_count = s.retry_count + 1
                    step_copy.error_message = None
                    step_copy.result_payload = None
            new_steps.append(step_copy)

        return Plan(
            goal_id=plan.goal_id,
            version=plan.version + 1,
            is_active=True,
            steps=new_steps,
        )
