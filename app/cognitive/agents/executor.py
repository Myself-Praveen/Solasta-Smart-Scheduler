"""
Solasta — Executor Agent

Given a single Step from the plan, selects and invokes the appropriate tools,
then returns a structured execution result. The Executor is sandboxed
to only the tools the step requires.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.cognitive.llm.provider import llm_gateway
from app.core.logging import get_logger
from app.db.repository import AgentLogRepository
from app.schemas.models import AgentLog, Step, StepStatus
from app.tools.registry import ToolExecutionError, execute_tool, get_tool_by_name

logger = get_logger(__name__)

EXECUTOR_SYSTEM_PROMPT = """You are the Execution Agent for a Smart Study Schedule system.

You are given ONE step to execute. You have access to specific tools.
Your job is to:
1. Understand the step objective
2. Decide which tool(s) to invoke and with what parameters
3. Execute the tools
4. Return the result

CRITICAL RULES:
- Use ONLY the exact parameter names listed below for each tool
- Do NOT invent parameters like "goal", "objective", or "input" - these will cause errors
- If a tool has no parameters, pass an empty object {{}}
- All parameter values should be strings unless otherwise specified

AVAILABLE TOOLS FOR THIS STEP:
{tool_descriptions}

CONTEXT FROM PREVIOUS STEPS:
{previous_context}

Respond with ONLY a valid JSON object (no markdown, no explanation):
{{
  "actions_taken": [
    {{
      "tool_name": "exact_tool_name_from_above",
      "parameters": {{"param_name": "value"}},
      "reasoning": "brief justification"
    }}
  ],
  "result_summary": "What was accomplished",
  "output_data": {{}}
}}
"""


class ExecutorAgent:
    """Executes a single step using its allowed tools."""

    async def execute_step(
        self,
        step: Step,
        goal_id: str,
        plan_id: str,
        previous_results: Optional[Dict[str, Any]] = None,
        goal_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a single step. Returns the result payload.
        """
        logger.info(
            "executor_start",
            step_id=step.step_id,
            title=step.title,
            tools=step.required_tools,
        )

        # Build tool descriptions for the prompt
        tool_descriptions = self._build_tool_descriptions(step.required_tools)
        prev_context = json.dumps(previous_results or {}, indent=2, default=str)

        goal_info = f"ORIGINAL GOAL: {goal_context}\n\n" if goal_context else ""

        prompt = f"""{goal_info}STEP TO EXECUTE:
Title: {step.title}
Description: {step.description}
Expected Outcome: {step.expected_outcome}

Extract relevant information (subjects, exam name, duration, etc.) from the ORIGINAL GOAL above to populate tool parameters. Execute this step using the available tools."""

        system = EXECUTOR_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descriptions,
            previous_context=prev_context,
        )

        try:
            result_text, log = await llm_gateway.generate(
                prompt=prompt,
                system=system,
                goal_id=goal_id,
                agent_type="executor",
            )
            log.step_id = step.step_id
            log.plan_id = plan_id
            await AgentLogRepository.append(log)

            # Parse LLM's tool invocation plan
            execution_plan = self._parse_execution_plan(result_text)

            # Actually invoke the tools
            tool_results = []
            for action in execution_plan.get("actions_taken", []):
                tool_name = action.get("tool_name", "")
                params = action.get("parameters", {})
                try:
                    tool_output = await execute_tool(tool_name, params)
                    tool_results.append({
                        "tool": tool_name,
                        "status": "success",
                        "output": tool_output,
                    })
                except Exception as tool_err:
                    error_payload = self._normalize_tool_error(tool_err)
                    tool_results.append({
                        "tool": tool_name,
                        "status": "error",
                        "error": str(tool_err),
                        "error_payload": error_payload,
                    })
                    logger.warning(
                        "tool_execution_failed",
                        tool=tool_name,
                        error=str(tool_err),
                    )

            # Resuscitate output_data if LLM parsing failed but tools succeeded
            output_data = self._resuscitate_output_data(execution_plan, tool_results)

            result = {
                "step_id": step.step_id,
                "llm_plan": execution_plan,
                "tool_results": tool_results,
                "result_summary": execution_plan.get("result_summary", "") or self._generate_summary_from_tools(tool_results),
                "output_data": output_data,
                "executed_at": datetime.utcnow().isoformat(),
            }

            logger.info("executor_success", step_id=step.step_id)
            return result

        except Exception as e:
            logger.error("executor_failed", step_id=step.step_id, error=str(e))
            
            # --- HACKATHON OFFLINE FALLBACK ---
            # If the LLM completely fails, extract params from goal context
            # and run tools with smart defaults so the user gets a real schedule.
            logger.info("executor_using_offline_fallback", step_id=step.step_id)
            
            # Extract exam name and duration from goal context
            goal_text = (goal_context or step.description or "").lower()
            
            exam_name = ""
            for exam in ["gate", "upsc", "sat", "gre", "jee", "neet", "cat", "ielts", "toefl", "usmle"]:
                if exam in goal_text:
                    exam_name = exam.upper()
                    break
            
            duration_weeks = 12
            import re
            month_match = re.search(r"(\d+)\s*months?", goal_text)
            week_match = re.search(r"(\d+)\s*weeks?", goal_text)
            if month_match:
                duration_weeks = int(month_match.group(1)) * 4
            elif week_match:
                duration_weeks = int(week_match.group(1))
            
            tool_results = []
            generated_subjects = []
            
            for tool_name in step.required_tools:
                try:
                    # Build smart params based on tool name
                    params: dict = {}
                    if tool_name == "analyze_syllabus":
                        params = {"exam_name": exam_name, "duration_weeks": duration_weeks}
                    elif tool_name == "create_schedule":
                        params = {"subjects": ",".join(generated_subjects), "weeks": duration_weeks}
                    elif tool_name == "allocate_time_blocks":
                        params = {"subjects": ",".join(generated_subjects), "weeks": duration_weeks}

                    tool_output = await execute_tool(tool_name, params)
                    
                    # Capture subjects for downstream tools
                    if tool_name == "analyze_syllabus" and isinstance(tool_output, dict):
                        subj_data = tool_output.get("subjects", {})
                        if isinstance(subj_data, dict):
                            generated_subjects = list(subj_data.keys())
                            # Also cache for create_schedule if it runs later
                            try:
                                from app.tools.study_tools import _cache_subjects
                                _cache_subjects(generated_subjects)
                            except Exception:
                                pass
                    
                    tool_results.append({
                        "tool": tool_name,
                        "status": "success",
                        "output": tool_output,
                    })
                except Exception as tool_err:
                    tool_results.append({
                        "tool": tool_name,
                        "status": "error",
                        "error": str(tool_err),
                    })

            # Re-run resuscitation
            output_data = self._resuscitate_output_data({}, tool_results)

            return {
                "step_id": step.step_id,
                "error": str(e),
                "tool_results": tool_results,
                "result_summary": f"LLM offline. Auto-executed tools: {', '.join(step.required_tools)}.",
                "output_data": output_data,
                "executed_at": datetime.utcnow().isoformat(),
            }

    def _generate_summary_from_tools(self, tool_results: List[Dict[str, Any]]) -> str:
        """Generate a result summary from successful tool outputs."""
        successful = [r["tool"] for r in tool_results if r.get("status") == "success"]
        if successful:
            return f"Tools executed successfully: {', '.join(successful)}"
        return ""

    def _build_tool_descriptions(self, tool_names: List[str]) -> str:
        """Build a description string for the tools available to this step, including parameter schemas."""
        descriptions = []
        for name in tool_names:
            tool = get_tool_by_name(name)
            if tool:
                desc = tool.get('description', 'No description')
                params = tool.get('parameters', {})
                
                # Build explicit parameter signature
                if params:
                    param_lines = []
                    for pname, pdesc in params.items():
                        param_lines.append(f"    - {pname}: {pdesc}")
                    param_block = "\n".join(param_lines)
                    descriptions.append(f"- {name}: {desc}\n  PARAMETERS (use ONLY these exact names):\n{param_block}")
                else:
                    descriptions.append(f"- {name}: {desc}\n  PARAMETERS: none (call with empty {{}})")
            else:
                descriptions.append(f"- {name}: (tool not found)")
        return "\n".join(descriptions) if descriptions else "No specific tools assigned."

    def _parse_execution_plan(self, text: str) -> Dict[str, Any]:
        """Parse the LLM's execution response with robust JSON extraction."""
        cleaned = self._extract_json_from_response(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("executor_parse_fallback", raw=cleaned[:200])
            return {
                "actions_taken": [],
                "result_summary": cleaned[:500],
                "output_data": {},
                "_parse_failed": True,
            }

    def _extract_json_from_response(self, text: str) -> str:
        """Extract JSON object from LLM response, stripping conversational text."""
        import re

        cleaned = text.strip()

        # Remove markdown code fences
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        fence_match = re.search(fence_pattern, cleaned, re.IGNORECASE)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        # Extract JSON between first '{' and last '}'
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return cleaned[first_brace : last_brace + 1]

        return cleaned

    def _resuscitate_output_data(
        self,
        execution_plan: Dict[str, Any],
        tool_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Always merge successful tool outputs into output_data so the evaluator
        and frontend can see the actual generated artifacts (like schedules).
        """
        output_data = execution_plan.get("output_data", {}) or {}

        successful_outputs = [
            r.get("output")
            for r in tool_results
            if r.get("status") == "success" and isinstance(r.get("output"), dict)
        ]
        
        if successful_outputs:
            for out in successful_outputs:
                output_data.update(out)
            output_data["resuscitated"] = True

        return output_data

    def _normalize_tool_error(self, err: Exception) -> Dict[str, Any]:
        """Normalize tool execution errors so evaluator/replanner receive structured context."""
        if isinstance(err, ToolExecutionError):
            return err.payload
        return {
            "error_code": "TOOL_EXECUTION_ERROR",
            "component": "Tool_Unknown",
            "trace": str(err),
            "agent_recovery_action": "Replanner must inspect failure and adapt plan.",
        }
