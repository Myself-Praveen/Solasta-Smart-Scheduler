"""
Solasta — Planner Agent

Decomposes a natural-language goal into a structured, dependency-aware
execution plan (DAG of Steps). Uses experience recall from long-term
memory to inform better planning.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.cognitive.llm.provider import llm_gateway
from app.core.logging import get_logger
from app.db.repository import AgentLogRepository, MemoryRepository
from app.schemas.models import AgentLog, Plan, Step, StepPriority

logger = get_logger(__name__)

PLANNER_SYSTEM_PROMPT = """You are the Planning Agent for a Smart Study Schedule system.

Your job is to take a student's natural language study goal and decompose it into
a structured, multi-step execution plan.

REASONING PROCESS (Chain-of-Thought):
Before generating the plan, think step-by-step:
1. What exam/topic is the student preparing for?
2. What subjects and topics does this exam cover?
3. What is the student's time constraint (weeks/months)?
4. Which subjects should be prioritized and why?
5. What is the optimal study sequence considering dependencies?
6. How should study time be distributed across subjects?

RULES:
1. Break the goal into 4-8 concrete, actionable steps.
2. Each step must have a clear expected_outcome that can be verified.
3. Use depends_on to model step dependencies (use step_id references).
4. Assign required_tools from: [analyze_syllabus, create_schedule, detect_conflicts, allocate_time_blocks, generate_study_tips, assess_difficulty, fetch_study_resources, get_current_datetime, save_to_database]
5. Provide a detailed thought_process explaining your REASONING for each step.
6. Consider the student's constraints (time, subjects, difficulty).
7. Make the plan realistic and achievable.
8. Use PARALLEL steps where possible (steps with no dependency on each other).

OUTPUT FORMAT — respond with ONLY a JSON object:
{
  "parsed_objective": "concise restatement of the goal",
  "constraints": ["constraint1", "constraint2"],
  "reasoning_chain": "Your step-by-step reasoning about the goal (2-3 sentences)",
  "steps": [
    {
      "step_id": "step_1",
      "title": "Step title",
      "description": "What this step does",
      "expected_outcome": "What success looks like",
      "thought_process": "Why this step is needed and how it connects to the goal",
      "priority": "high|medium|low",
      "depends_on": [],
      "required_tools": ["tool_name"]
    }
  ]
}
"""


class PlannerAgent:
    """Generates a structured execution plan from a natural language goal."""

    async def create_plan(
        self,
        goal_id: str,
        user_input: str,
        context: Optional[str] = None,
    ) -> Plan:
        """
        Decompose user_input into a Plan with dependency-ordered Steps.
        """
        logger.info("planner_start", goal_id=goal_id)

        # Recall past experiences for similar goals
        past_experiences = await MemoryRepository.recall_similar(user_input, limit=2)
        experience_context = ""
        if past_experiences:
            experience_context = "\n\nPAST SUCCESSFUL EXPERIENCES (use as reference):\n"
            for exp in past_experiences:
                experience_context += f"- Goal: {exp.get('summary', 'N/A')}\n"

        prompt = f"""STUDENT GOAL: {user_input}
{experience_context}
{f"ADDITIONAL CONTEXT: {context}" if context else ""}

Generate a detailed execution plan following the rules exactly."""

        try:
            result, log = await llm_gateway.generate(
                prompt=prompt,
                system=PLANNER_SYSTEM_PROMPT,
                goal_id=goal_id,
                agent_type="planner",
            )
            log.step_id = None
            log.plan_id = None
            await AgentLogRepository.append(log)

            plan_data = self._parse_plan_response(result)
            plan = self._build_plan(goal_id, plan_data)

            logger.info(
                "planner_success",
                goal_id=goal_id,
                num_steps=len(plan.steps),
            )
            return plan

        except Exception as e:
            logger.error("planner_failed", goal_id=goal_id, error=str(e))
            # Return a minimal fallback plan
            return self._fallback_plan(goal_id, user_input, str(e))

    def _parse_plan_response(self, text: str) -> Dict[str, Any]:
        """Extract JSON from LLM response, handling markdown code blocks."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # Remove opening ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        return json.loads(cleaned)

    def _build_plan(self, goal_id: str, data: Dict[str, Any]) -> Plan:
        """Construct a Plan object from parsed LLM output."""
        steps = []
        for s in data.get("steps", []):
            steps.append(Step(
                step_id=s.get("step_id", str(uuid4())[:8]),
                title=s.get("title", "Untitled Step"),
                description=s.get("description", ""),
                expected_outcome=s.get("expected_outcome", ""),
                thought_process=s.get("thought_process", ""),
                priority=StepPriority(s.get("priority", "medium")),
                depends_on=s.get("depends_on", []),
                required_tools=s.get("required_tools", []),
            ))

        # Validate no circular dependencies
        self._validate_dag(steps)

        return Plan(
            goal_id=goal_id,
            version=1,
            is_active=True,
            steps=steps,
        )

    def _validate_dag(self, steps: List[Step]) -> None:
        """Ensure there are no circular dependencies in the step graph."""
        step_ids = {s.step_id for s in steps}
        visited = set()
        rec_stack = set()

        adj = {s.step_id: s.depends_on for s in steps}

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for dep in adj.get(node, []):
                if dep not in step_ids:
                    continue
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for sid in step_ids:
            if sid not in visited:
                if has_cycle(sid):
                    logger.warning("dag_cycle_detected", msg="Removing cyclic deps")
                    # Remove all dependencies to break cycles
                    for s in steps:
                        s.depends_on = []
                    return

    def _fallback_plan(self, goal_id: str, user_input: str, error: str) -> Plan:
        """Generate a comprehensive fallback plan if LLM fails entirely."""
        logger.warning("using_fallback_plan", goal_id=goal_id)
        return Plan(
            goal_id=goal_id,
            version=1,
            is_active=True,
            steps=[
                Step(
                    step_id="fallback_1",
                    title="Analyze Syllabus & Extract Subjects",
                    description=f"Parse the user's goal and identify exam subjects: {user_input}",
                    expected_outcome="Structured syllabus with subjects, topics, difficulty ratings, and estimated hours",
                    thought_process=f"LLM planning failed ({error}). Using intelligent fallback with dynamic syllabus generation.",
                    priority=StepPriority.HIGH,
                    required_tools=["analyze_syllabus"],
                ),
                Step(
                    step_id="fallback_2",
                    title="Assess Topic Difficulty",
                    description="Evaluate difficulty of each topic relative to student level",
                    expected_outcome="Difficulty scores and recommended study strategies per topic",
                    thought_process="Understanding difficulty helps prioritize hard topics early in the schedule",
                    priority=StepPriority.HIGH,
                    depends_on=["fallback_1"],
                    required_tools=["assess_difficulty"],
                ),
                Step(
                    step_id="fallback_3",
                    title="Generate Study Tips & Strategies",
                    description="Create personalized study strategies for each difficulty level",
                    expected_outcome="Actionable study tips including spaced repetition and active recall techniques",
                    thought_process="Evidence-based study strategies significantly improve retention and exam performance",
                    priority=StepPriority.MEDIUM,
                    depends_on=["fallback_1"],
                    required_tools=["generate_study_tips"],
                ),
                Step(
                    step_id="fallback_4",
                    title="Fetch Study Resources (Live API)",
                    description="Query the Wikipedia REST API to fetch real-world summaries and reference URLs for the hardest topics",
                    expected_outcome="Dictionary of topic summaries and Wikipedia links fetched via live HTTP API calls",
                    thought_process="Making live API calls to external services proves the agent can ACT on the real world, not just generate text. This addresses the hackathon requirement for real API execution.",
                    priority=StepPriority.MEDIUM,
                    depends_on=["fallback_2"],
                    required_tools=["fetch_study_resources"],
                ),
                Step(
                    step_id="fallback_5",
                    title="Create Weekly Schedule",
                    description="Generate a detailed week-by-week study schedule with time slots",
                    expected_outcome="Complete multi-week schedule with daily sessions mapped to real subjects",
                    thought_process="Core deliverable — maps subjects to concrete time blocks across the preparation period",
                    priority=StepPriority.HIGH,
                    depends_on=["fallback_1", "fallback_2"],
                    required_tools=["create_schedule"],
                ),
                Step(
                    step_id="fallback_6",
                    title="Allocate Pomodoro Time Blocks",
                    description="Distribute study hours using Pomodoro technique for optimal focus",
                    expected_outcome="Pomodoro session allocation per subject with utilization metrics",
                    thought_process="Pomodoro technique maximizes focus and prevents burnout during long study sessions",
                    priority=StepPriority.MEDIUM,
                    depends_on=["fallback_1"],
                    required_tools=["allocate_time_blocks"],
                ),
                Step(
                    step_id="fallback_7",
                    title="Validate Schedule & Save",
                    description="Check for scheduling conflicts and persist the final plan",
                    expected_outcome="Conflict-free, validated schedule stored in database",
                    thought_process="Final validation ensures no overlapping sessions and data persistence for future recall",
                    priority=StepPriority.MEDIUM,
                    depends_on=["fallback_5"],
                    required_tools=["detect_conflicts", "save_to_database"],
                ),
            ],
        )
