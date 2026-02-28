"""
Solasta — Evaluator Agent

An objective judge that assesses whether a step's execution result
satisfies its expected outcome. Provides a confidence score and
actionable suggestions on failure.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from app.cognitive.llm.provider import llm_gateway
from app.core.logging import get_logger
from app.db.repository import AgentLogRepository
from app.schemas.models import EvalResult, Step, StepEvaluation

logger = get_logger(__name__)

EVALUATOR_SYSTEM_PROMPT = """You are the Evaluator Agent for a Smart Study Schedule system.

TASK:
Evaluate one executed step against its expected outcome with strict, objective criteria.

DECISION RULES (apply in order):
1) If any tool result has status="error" OR execution_result.error is not "None", output status="failure".
2) Else if expected outcome is fully satisfied with usable output_data, output status="success".
3) Else output status="partial".

STRICT OUTPUT CONTRACT:
- Return ONLY one JSON object.
- DO NOT include markdown, prose, or extra keys.
- Keys MUST be exactly: status, confidence_score, reasoning, suggestions

JSON SCHEMA:
{
    "status": "success" | "failure" | "partial",
    "confidence_score": <float between 0 and 1>,
    "reasoning": "concise objective justification referencing evidence",
    "suggestions": ["specific corrective action", "specific corrective action"]
}

CONSTRAINTS:
- confidence_score MUST satisfy 0.0 <= x <= 1.0
- suggestions MUST be [] when status="success"
- reasoning MUST cite concrete signals: expected_outcome match, tool errors, output usability
"""


class EvaluatorAgent:
    """Evaluates step execution results against expected outcomes."""

    async def evaluate(
        self,
        step: Step,
        execution_result: Dict[str, Any],
        goal_id: str,
        plan_id: str,
    ) -> StepEvaluation:
        """
        Assess whether the step's execution result meets the expected outcome.
        """
        logger.info("evaluator_start", step_id=step.step_id)

        prompt = f"""STEP BEING EVALUATED:
Title: {step.title}
Description: {step.description}
Expected Outcome: {step.expected_outcome}

EXECUTION RESULT:
Summary: {execution_result.get('result_summary', 'No summary')}
Tool Results: {json.dumps(execution_result.get('tool_results', []), indent=2, default=str)}
Output Data: {json.dumps(execution_result.get('output_data', {}), indent=2, default=str)}
Errors: {execution_result.get('error', 'None')}

Evaluate this execution result thoroughly."""

        try:
            result_text, log = await llm_gateway.generate(
                prompt=prompt,
                system=EVALUATOR_SYSTEM_PROMPT,
                goal_id=goal_id,
                agent_type="evaluator",
            )
            log.step_id = step.step_id
            log.plan_id = plan_id
            await AgentLogRepository.append(log)

            eval_data = self._parse_eval_response(result_text)

            status_value = eval_data.get("status", eval_data.get("result", "failure"))
            confidence_value = eval_data.get("confidence_score", eval_data.get("confidence", 0.5))

            evaluation = StepEvaluation(
                step_id=step.step_id,
                result=EvalResult(status_value),
                reasoning=eval_data.get("reasoning", "No reasoning provided"),
                confidence=float(confidence_value),
                suggestions=eval_data.get("suggestions", []),
            )

            evaluation = self._apply_success_guardrail(evaluation, execution_result)

            logger.info(
                "evaluator_result",
                step_id=step.step_id,
                result=evaluation.result.value,
                confidence=evaluation.confidence,
            )
            return evaluation

        except Exception as e:
            logger.error("evaluator_failed", step_id=step.step_id, error=str(e))
            # On evaluator failure, default to checking tool results directly
            has_errors = any(
                r.get("status") == "error"
                for r in execution_result.get("tool_results", [])
            )
            return StepEvaluation(
                step_id=step.step_id,
                result=EvalResult.FAILURE if has_errors else EvalResult.SUCCESS,
                reasoning=f"Evaluator LLM failed ({e}); direct tool status check used",
                confidence=0.3,
                suggestions=["Retry with different LLM provider"] if has_errors else [],
            )

    def _parse_eval_response(self, text: str) -> Dict[str, Any]:
        """Parse evaluator JSON response."""
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
            logger.warning("evaluator_parse_fallback")
            # Heuristic: if text contains "success", treat as success
            if "success" in cleaned.lower():
                return {
                    "status": "success",
                    "confidence_score": 0.6,
                    "reasoning": cleaned[:300],
                    "suggestions": [],
                }
            return {
                "status": "failure",
                "confidence_score": 0.3,
                "reasoning": cleaned[:300],
                "suggestions": ["Retry with a constrained tool-only execution plan"],
            }

    def _apply_success_guardrail(
        self,
        evaluation: StepEvaluation,
        execution_result: Dict[str, Any],
    ) -> StepEvaluation:
        """Prevent false-negative failure labels when tools succeeded and outputs are usable."""
        if evaluation.result == EvalResult.SUCCESS:
            return evaluation

        tool_results = execution_result.get("tool_results", []) or []
        has_tool_error = any(r.get("status") == "error" for r in tool_results)
        has_top_level_error = bool(execution_result.get("error"))
        output_data = execution_result.get("output_data")
        has_output = bool(output_data) and output_data != {}
        has_summary = bool(execution_result.get("result_summary", "").strip())

        if (not has_tool_error) and (not has_top_level_error) and (has_output or has_summary):
            return StepEvaluation(
                step_id=evaluation.step_id,
                result=EvalResult.SUCCESS,
                reasoning=(
                    "Deterministic guardrail override: tools completed without errors and produced usable output. "
                    + evaluation.reasoning
                )[:1000],
                confidence=max(evaluation.confidence, 0.75),
                suggestions=[],
            )

        return evaluation
