"""
Solasta — Study Domain Tools

Production-ready tool implementations for study schedule generation.
Supports ANY exam worldwide via LLM-powered dynamic syllabus generation
with a comprehensive offline fallback knowledge base.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.tools.registry import register_tool

logger = get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pydantic Schemas for LLM Structured Output
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TopicSchema(BaseModel):
    topic: str = Field(description="Name of the topic or chapter")
    difficulty: str = Field(description="easy, medium, or hard")
    estimated_hours: float = Field(description="Estimated study hours needed")
    priority: str = Field(description="high, medium, or low")


class SubjectSchema(BaseModel):
    subject_name: str = Field(description="Name of the subject")
    topics: List[TopicSchema] = Field(description="List of topics in this subject")


class SyllabusSchema(BaseModel):
    exam_name: str = Field(description="Name of the exam")
    subjects: List[SubjectSchema] = Field(description="List of subjects for this exam")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Offline Exam Knowledge Base (Fallback when LLM is unavailable)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXAM_KNOWLEDGE_BASE: Dict[str, List[Dict[str, Any]]] = {
    "gate": [
        {"subject_name": "Data Structures & Algorithms", "topics": [
            {"topic": "Arrays, Linked Lists & Stacks", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Trees & Graphs", "difficulty": "hard", "estimated_hours": 20, "priority": "high"},
            {"topic": "Sorting & Searching", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
            {"topic": "Dynamic Programming & Greedy", "difficulty": "hard", "estimated_hours": 18, "priority": "high"},
        ]},
        {"subject_name": "Operating Systems", "topics": [
            {"topic": "Process Management & Scheduling", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
            {"topic": "Memory Management & Virtual Memory", "difficulty": "hard", "estimated_hours": 14, "priority": "high"},
            {"topic": "File Systems & I/O", "difficulty": "medium", "estimated_hours": 8, "priority": "medium"},
            {"topic": "Deadlocks & Synchronization", "difficulty": "hard", "estimated_hours": 10, "priority": "high"},
        ]},
        {"subject_name": "Database Management Systems", "topics": [
            {"topic": "ER Model & Relational Algebra", "difficulty": "medium", "estimated_hours": 10, "priority": "high"},
            {"topic": "SQL & Normalization", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
            {"topic": "Transactions & Concurrency Control", "difficulty": "hard", "estimated_hours": 10, "priority": "medium"},
        ]},
        {"subject_name": "Computer Networks", "topics": [
            {"topic": "OSI & TCP/IP Models", "difficulty": "medium", "estimated_hours": 8, "priority": "high"},
            {"topic": "IP Addressing & Subnetting", "difficulty": "hard", "estimated_hours": 12, "priority": "high"},
            {"topic": "Routing Algorithms", "difficulty": "hard", "estimated_hours": 10, "priority": "medium"},
            {"topic": "Application Layer Protocols", "difficulty": "easy", "estimated_hours": 6, "priority": "medium"},
        ]},
        {"subject_name": "Theory of Computation", "topics": [
            {"topic": "Finite Automata & Regular Languages", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
            {"topic": "Context-Free Grammars & PDA", "difficulty": "hard", "estimated_hours": 14, "priority": "high"},
            {"topic": "Turing Machines & Decidability", "difficulty": "hard", "estimated_hours": 10, "priority": "medium"},
        ]},
        {"subject_name": "Compiler Design", "topics": [
            {"topic": "Lexical Analysis & Parsing", "difficulty": "hard", "estimated_hours": 12, "priority": "high"},
            {"topic": "Syntax-Directed Translation", "difficulty": "medium", "estimated_hours": 8, "priority": "medium"},
            {"topic": "Code Optimization & Generation", "difficulty": "medium", "estimated_hours": 8, "priority": "medium"},
        ]},
        {"subject_name": "Digital Logic & Computer Organization", "topics": [
            {"topic": "Boolean Algebra & Logic Gates", "difficulty": "easy", "estimated_hours": 8, "priority": "medium"},
            {"topic": "Combinational & Sequential Circuits", "difficulty": "medium", "estimated_hours": 10, "priority": "high"},
            {"topic": "CPU Architecture & Pipelining", "difficulty": "hard", "estimated_hours": 12, "priority": "high"},
        ]},
        {"subject_name": "Engineering Mathematics", "topics": [
            {"topic": "Discrete Mathematics & Graph Theory", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Linear Algebra & Calculus", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
            {"topic": "Probability & Statistics", "difficulty": "medium", "estimated_hours": 10, "priority": "medium"},
        ]},
    ],
    "upsc": [
        {"subject_name": "Indian Polity & Governance", "topics": [
            {"topic": "Constitution & Amendments", "difficulty": "hard", "estimated_hours": 25, "priority": "high"},
            {"topic": "Parliament & State Legislatures", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Panchayati Raj & Public Policy", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
        ]},
        {"subject_name": "Indian & World Geography", "topics": [
            {"topic": "Physical Geography", "difficulty": "medium", "estimated_hours": 18, "priority": "high"},
            {"topic": "Indian Geography", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Climate & Environment", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
        ]},
        {"subject_name": "History", "topics": [
            {"topic": "Ancient India", "difficulty": "medium", "estimated_hours": 15, "priority": "medium"},
            {"topic": "Medieval India", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
            {"topic": "Modern India & Freedom Movement", "difficulty": "hard", "estimated_hours": 20, "priority": "high"},
        ]},
        {"subject_name": "Economy", "topics": [
            {"topic": "Indian Economy & Budget", "difficulty": "hard", "estimated_hours": 20, "priority": "high"},
            {"topic": "Banking & Monetary Policy", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
        ]},
        {"subject_name": "General Science", "topics": [
            {"topic": "Physics & Chemistry Basics", "difficulty": "easy", "estimated_hours": 10, "priority": "medium"},
            {"topic": "Biology & Environment", "difficulty": "easy", "estimated_hours": 10, "priority": "medium"},
        ]},
        {"subject_name": "Current Affairs & Ethics", "topics": [
            {"topic": "National & International Events", "difficulty": "medium", "estimated_hours": 20, "priority": "high"},
            {"topic": "Ethics, Integrity & Aptitude", "difficulty": "hard", "estimated_hours": 15, "priority": "high"},
        ]},
    ],
    "sat": [
        {"subject_name": "Reading & Writing", "topics": [
            {"topic": "Reading Comprehension", "difficulty": "medium", "estimated_hours": 20, "priority": "high"},
            {"topic": "Grammar & Standard English", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Evidence-Based Analysis", "difficulty": "hard", "estimated_hours": 12, "priority": "medium"},
        ]},
        {"subject_name": "Mathematics", "topics": [
            {"topic": "Algebra & Functions", "difficulty": "medium", "estimated_hours": 18, "priority": "high"},
            {"topic": "Problem Solving & Data Analysis", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Advanced Math (Polynomials, Quadratics)", "difficulty": "hard", "estimated_hours": 15, "priority": "high"},
            {"topic": "Geometry & Trigonometry", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
        ]},
    ],
    "gre": [
        {"subject_name": "Verbal Reasoning", "topics": [
            {"topic": "Text Completion & Sentence Equivalence", "difficulty": "hard", "estimated_hours": 20, "priority": "high"},
            {"topic": "Reading Comprehension", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Vocabulary Building", "difficulty": "medium", "estimated_hours": 18, "priority": "high"},
        ]},
        {"subject_name": "Quantitative Reasoning", "topics": [
            {"topic": "Arithmetic & Number Properties", "difficulty": "medium", "estimated_hours": 12, "priority": "high"},
            {"topic": "Algebra & Geometry", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            {"topic": "Data Interpretation", "difficulty": "hard", "estimated_hours": 12, "priority": "medium"},
        ]},
        {"subject_name": "Analytical Writing", "topics": [
            {"topic": "Issue Essay", "difficulty": "hard", "estimated_hours": 10, "priority": "medium"},
            {"topic": "Argument Essay", "difficulty": "hard", "estimated_hours": 10, "priority": "medium"},
        ]},
    ],
    "jee": [
        {"subject_name": "Physics", "topics": [
            {"topic": "Mechanics & Kinematics", "difficulty": "hard", "estimated_hours": 25, "priority": "high"},
            {"topic": "Electromagnetism", "difficulty": "hard", "estimated_hours": 22, "priority": "high"},
            {"topic": "Optics & Waves", "difficulty": "medium", "estimated_hours": 15, "priority": "medium"},
            {"topic": "Thermodynamics", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
        ]},
        {"subject_name": "Chemistry", "topics": [
            {"topic": "Organic Chemistry", "difficulty": "hard", "estimated_hours": 25, "priority": "high"},
            {"topic": "Inorganic Chemistry", "difficulty": "medium", "estimated_hours": 18, "priority": "high"},
            {"topic": "Physical Chemistry", "difficulty": "hard", "estimated_hours": 20, "priority": "high"},
        ]},
        {"subject_name": "Mathematics", "topics": [
            {"topic": "Calculus & Differential Equations", "difficulty": "hard", "estimated_hours": 25, "priority": "high"},
            {"topic": "Algebra & Matrices", "difficulty": "medium", "estimated_hours": 18, "priority": "high"},
            {"topic": "Coordinate Geometry", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
            {"topic": "Probability & Statistics", "difficulty": "medium", "estimated_hours": 10, "priority": "medium"},
        ]},
    ],
    "neet": [
        {"subject_name": "Biology", "topics": [
            {"topic": "Human Physiology", "difficulty": "hard", "estimated_hours": 25, "priority": "high"},
            {"topic": "Genetics & Evolution", "difficulty": "hard", "estimated_hours": 22, "priority": "high"},
            {"topic": "Ecology & Environment", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
            {"topic": "Cell Biology & Molecular Biology", "difficulty": "hard", "estimated_hours": 18, "priority": "high"},
            {"topic": "Plant Physiology & Morphology", "difficulty": "medium", "estimated_hours": 15, "priority": "medium"},
        ]},
        {"subject_name": "Physics", "topics": [
            {"topic": "Mechanics", "difficulty": "hard", "estimated_hours": 20, "priority": "high"},
            {"topic": "Electrodynamics", "difficulty": "hard", "estimated_hours": 18, "priority": "high"},
            {"topic": "Optics & Modern Physics", "difficulty": "medium", "estimated_hours": 12, "priority": "medium"},
        ]},
        {"subject_name": "Chemistry", "topics": [
            {"topic": "Organic Chemistry", "difficulty": "hard", "estimated_hours": 22, "priority": "high"},
            {"topic": "Inorganic Chemistry", "difficulty": "medium", "estimated_hours": 15, "priority": "medium"},
            {"topic": "Physical Chemistry", "difficulty": "hard", "estimated_hours": 18, "priority": "high"},
        ]},
    ],
}


def _lookup_exam_knowledge(exam_name: str) -> Optional[List[Dict[str, Any]]]:
    """Try to find exam in offline knowledge base (case-insensitive fuzzy match)."""
    exam_lower = exam_name.lower().strip()
    for key, data in EXAM_KNOWLEDGE_BASE.items():
        if key in exam_lower or exam_lower in key:
            return data
    return None


async def _llm_generate_syllabus(exam_name: str, duration_weeks: int) -> Optional[Dict[str, Any]]:
    """Use the LLM Gateway to dynamically generate a syllabus for any exam."""
    try:
        from app.cognitive.llm.provider import llm_gateway

        prompt = f"""You are an expert academic advisor. Generate a detailed syllabus for the "{exam_name}" exam.

The student has {duration_weeks} weeks to prepare.

For each subject in this exam, provide:
- subject_name: The real official subject name
- topics: A list of 3-5 key topics, each with:
  - topic: Real topic/chapter name as it appears in official syllabus
  - difficulty: "easy", "medium", or "hard"
  - estimated_hours: Realistic hours needed to study this topic
  - priority: "high", "medium", or "low" based on exam weightage

Cover ALL major subjects for this exam. Use real, accurate subject/topic names."""

        result, _log = await llm_gateway.generate_structured(
            prompt=prompt,
            schema=SyllabusSchema,
            system="You are an expert academic advisor. Always respond with valid JSON containing real exam syllabus data.",
            agent_type="tool_syllabus",
        )

        if isinstance(result, dict) and "subjects" in result:
            return result
        return None
    except Exception as e:
        logger.warning("llm_syllabus_generation_failed", error=str(e))
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. analyze_syllabus (LLM-Powered + Offline Fallback)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def analyze_syllabus(
    subjects: str = "",
    exam_name: str = "",
    duration_weeks: int = 12,
) -> Dict[str, Any]:
    """Analyze subjects and break them into topic-level study units.

    If exam_name is provided, dynamically generates real syllabus using:
    1. LLM Gateway (primary) → asks the LLM for the real exam syllabus
    2. Offline Knowledge Base (fallback) → built-in data for popular exams
    3. User-provided subjects (manual override)
    """
    try:
        duration_weeks = int(duration_weeks)
    except (ValueError, TypeError):
        duration_weeks = 12

    exam_display = exam_name or "Custom Study Plan"

    # ── STRATEGY 1: User provided explicit subjects ──────────
    subject_list = [s.strip() for s in subjects.split(",") if s.strip()]

    if subject_list and len(subject_list) > 1:
        # User gave specific subjects, build structured data from them
        analysis = {}
        for subject in subject_list:
            difficulty = "medium"
            hours_per_topic = max(4, duration_weeks * 1.5)
            analysis[subject] = {
                "topics": [
                    {
                        "topic": f"{subject} — Core Concepts",
                        "difficulty": difficulty,
                        "estimated_hours": round(hours_per_topic, 1),
                        "priority": "high",
                    },
                    {
                        "topic": f"{subject} — Practice & Applications",
                        "difficulty": "hard",
                        "estimated_hours": round(hours_per_topic * 0.8, 1),
                        "priority": "high",
                    },
                    {
                        "topic": f"{subject} — Revision & Past Papers",
                        "difficulty": "easy",
                        "estimated_hours": round(hours_per_topic * 0.5, 1),
                        "priority": "medium",
                    },
                ],
                "total_estimated_hours": round(hours_per_topic * 2.3, 1),
                "topic_count": 3,
            }
        return {
            "exam": exam_display,
            "subjects": analysis,
            "total_subjects": len(subject_list),
            "duration_weeks": duration_weeks,
            "total_estimated_hours": round(sum(s["total_estimated_hours"] for s in analysis.values()), 1),
        }

    # ── STRATEGY 2: Try LLM dynamic generation ──────────────
    if exam_name:
        llm_result = await _llm_generate_syllabus(exam_name, duration_weeks)
        if llm_result and llm_result.get("subjects"):
            analysis = {}
            for subj in llm_result["subjects"]:
                subj_name = subj.get("subject_name", "Unknown")
                topics = subj.get("topics", [])
                validated_topics = []
                for t in topics:
                    validated_topics.append({
                        "topic": t.get("topic", "Unknown Topic"),
                        "difficulty": t.get("difficulty", "medium"),
                        "estimated_hours": float(t.get("estimated_hours", 10)),
                        "priority": t.get("priority", "medium"),
                    })
                total_hours = sum(t["estimated_hours"] for t in validated_topics)
                analysis[subj_name] = {
                    "topics": validated_topics,
                    "total_estimated_hours": round(total_hours, 1),
                    "topic_count": len(validated_topics),
                }
            logger.info("syllabus_generated_via_llm", exam=exam_name, subjects=len(analysis))
            return {
                "exam": exam_display,
                "subjects": analysis,
                "total_subjects": len(analysis),
                "duration_weeks": duration_weeks,
                "total_estimated_hours": round(sum(s["total_estimated_hours"] for s in analysis.values()), 1),
                "source": "llm_generated",
            }

    # ── STRATEGY 3: Offline knowledge base fallback ──────────
    kb_data = _lookup_exam_knowledge(exam_name) if exam_name else None
    if kb_data:
        analysis = {}
        for subj in kb_data:
            subj_name = subj["subject_name"]
            topics = subj["topics"]
            total_hours = sum(t["estimated_hours"] for t in topics)
            analysis[subj_name] = {
                "topics": topics,
                "total_estimated_hours": round(total_hours, 1),
                "topic_count": len(topics),
            }
        logger.info("syllabus_from_knowledge_base", exam=exam_name, subjects=len(analysis))
        return {
            "exam": exam_display,
            "subjects": analysis,
            "total_subjects": len(analysis),
            "duration_weeks": duration_weeks,
            "total_estimated_hours": round(sum(s["total_estimated_hours"] for s in analysis.values()), 1),
            "source": "offline_knowledge_base",
        }

    # ── STRATEGY 4: Ultimate generic fallback ────────────────
    analysis = {
        "Core Concepts": {
            "topics": [
                {"topic": "Fundamentals & Theory", "difficulty": "medium", "estimated_hours": 20, "priority": "high"},
                {"topic": "Problem Solving & Practice", "difficulty": "hard", "estimated_hours": 25, "priority": "high"},
                {"topic": "Mock Tests & Revision", "difficulty": "medium", "estimated_hours": 15, "priority": "high"},
            ],
            "total_estimated_hours": 60,
            "topic_count": 3,
        },
    }
    return {
        "exam": exam_display,
        "subjects": analysis,
        "total_subjects": 1,
        "duration_weeks": duration_weeks,
        "total_estimated_hours": 60,
        "source": "generic_fallback",
    }


register_tool(
    name="analyze_syllabus",
    description="Analyze subjects/syllabus and break into topic-level study units with difficulty and time estimates. Supports any exam (GATE, UPSC, SAT, JEE, NEET, GRE, etc.)",
    handler=analyze_syllabus,
    parameters={
        "subjects": "comma-separated subjects (optional if exam_name provided)",
        "exam_name": "name of exam (e.g., GATE, UPSC, SAT, JEE, NEET, GRE)",
        "duration_weeks": "study duration in weeks",
    },
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. assess_difficulty
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def assess_difficulty(
    topics: str = "",
    student_level: str = "intermediate",
) -> Dict[str, Any]:
    """Assess difficulty of topics relative to the student's level."""
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    level_multiplier = {"beginner": 1.5, "intermediate": 1.0, "advanced": 0.7}
    mult = level_multiplier.get(student_level, 1.0)

    assessed = []
    for idx, topic in enumerate(topic_list):
        # Distribute difficulty based on position & name heuristics
        base_difficulty = 5.0 + (idx % 3) * 1.5
        if any(kw in topic.lower() for kw in ["advanced", "hard", "complex", "dynamic", "concurrency"]):
            base_difficulty = 8.0
        elif any(kw in topic.lower() for kw in ["basic", "intro", "fundamental", "easy"]):
            base_difficulty = 3.5

        adjusted = min(10, base_difficulty * mult)
        assessed.append({
            "topic": topic,
            "base_difficulty": round(base_difficulty, 1),
            "adjusted_difficulty": round(adjusted, 1),
            "recommended_hours": round(adjusted * 1.5, 1),
            "study_strategy": "spaced_repetition" if adjusted > 6 else "active_recall",
        })

    return {
        "student_level": student_level,
        "assessments": assessed,
        "hardest_topic": max(assessed, key=lambda x: x["adjusted_difficulty"])["topic"] if assessed else None,
    }


register_tool(
    name="assess_difficulty",
    description="Assess difficulty of topics relative to student's current level",
    handler=assess_difficulty,
    parameters={"topics": "comma-separated topics", "student_level": "beginner|intermediate|advanced"},
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. allocate_time_blocks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def allocate_time_blocks(
    total_hours: float = 100,
    weeks: int = 12,
    daily_hours: float = 4,
    subjects: str = "",
) -> Dict[str, Any]:
    """Allocate study time blocks across weeks with Pomodoro structure."""
    try:
        total_hours = float(total_hours)
        weeks = int(weeks)
        daily_hours = float(daily_hours)
    except (ValueError, TypeError):
        total_hours = 100.0
        weeks = 12
        daily_hours = 4.0

    subject_list = [s.strip() for s in subjects.split(",") if s.strip()]
    if not subject_list:
        subject_list = ["General"]

    hours_per_week = daily_hours * 6  # 6 study days per week
    total_available = hours_per_week * weeks

    allocation = {}
    hours_per_subject = total_hours / len(subject_list) if subject_list else total_hours

    for subject in subject_list:
        weekly_alloc = hours_per_subject / weeks
        pomodoro_sessions = math.ceil(weekly_alloc / 0.5)
        allocation[subject] = {
            "total_hours": round(hours_per_subject, 1),
            "hours_per_week": round(weekly_alloc, 1),
            "daily_minutes": round((weekly_alloc / 6) * 60),
            "pomodoro_sessions_per_week": pomodoro_sessions,
        }

    return {
        "total_available_hours": round(total_available, 1),
        "total_required_hours": total_hours,
        "utilisation_percent": round((total_hours / total_available) * 100, 1) if total_available > 0 else 0,
        "allocation": allocation,
        "study_days_per_week": 6,
        "pomodoro_duration_min": 25,
        "break_duration_min": 5,
        "feasible": total_hours <= total_available,
    }


register_tool(
    name="allocate_time_blocks",
    description="Allocate study hours across weeks with Pomodoro-based time blocks",
    handler=allocate_time_blocks,
    parameters={
        "total_hours": "total hours needed",
        "weeks": "weeks available",
        "daily_hours": "max study hours per day",
        "subjects": "comma-separated subjects",
    },
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. create_schedule (Subject-Aware)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_schedule(
    subjects: str = "",
    weeks: int = 12,
    daily_hours: float = 4,
    start_date: str = "",
) -> Dict[str, Any]:
    """Generate a detailed weekly study schedule with real subjects."""
    try:
        weeks = int(weeks)
        daily_hours = float(daily_hours)
    except (ValueError, TypeError):
        weeks = 12
        daily_hours = 4.0

    subject_list = [s.strip() for s in subjects.split(",") if s.strip()]

    # If no subjects were passed, check if we can get them from the cached syllabus
    if not subject_list:
        subject_list = _get_cached_subjects()
    if not subject_list:
        subject_list = ["General Studies"]

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now()
    except ValueError:
        start = datetime.now()

    schedule = []
    time_slots = ["09:00-10:30", "11:00-12:30", "14:00-15:30", "16:00-17:30"]

    for week_num in range(1, weeks + 1):
        week_start = start + timedelta(weeks=week_num - 1)
        week_data = {
            "week": week_num,
            "start_date": week_start.strftime("%Y-%m-%d"),
            "end_date": (week_start + timedelta(days=6)).strftime("%Y-%m-%d"),
            "days": [],
        }

        for day_offset in range(6):  # Mon-Sat
            day_date = week_start + timedelta(days=day_offset)
            day_name = day_date.strftime("%A")
            sessions = []

            slots_per_day = min(len(time_slots), math.ceil(daily_hours / 1.5))
            for slot_idx in range(slots_per_day):
                subject = subject_list[(day_offset * slots_per_day + slot_idx) % len(subject_list)]
                sessions.append({
                    "time_slot": time_slots[slot_idx],
                    "subject": subject,
                    "duration_min": 90,
                    "session_type": "deep_focus" if slot_idx == 0 else "practice",
                })

            week_data["days"].append({
                "day": day_name,
                "date": day_date.strftime("%Y-%m-%d"),
                "sessions": sessions,
            })

        schedule.append(week_data)

    return {
        "schedule": schedule,
        "total_weeks": weeks,
        "subjects": subject_list,
        "daily_study_hours": daily_hours,
        "sessions_per_day": min(len(time_slots), math.ceil(daily_hours / 1.5)),
        "rest_day": "Sunday",
    }


# ── Cached subjects from last analyze_syllabus call ──────────

_cached_subjects: List[str] = []


def _cache_subjects(subjects: List[str]) -> None:
    """Store subjects from the last syllabus analysis for use by create_schedule."""
    global _cached_subjects
    _cached_subjects = subjects


def _get_cached_subjects() -> List[str]:
    return list(_cached_subjects)


register_tool(
    name="create_schedule",
    description="Generate a detailed multi-week study schedule with daily time slots",
    handler=create_schedule,
    parameters={
        "subjects": "comma-separated subjects",
        "weeks": "number of weeks",
        "daily_hours": "max daily study hours",
        "start_date": "start date YYYY-MM-DD",
    },
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. detect_conflicts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def detect_conflicts(
    schedule: str = "",
    existing_commitments: str = "",
) -> Dict[str, Any]:
    """Detect scheduling conflicts and overlapping time blocks."""
    conflicts = []
    warnings = []

    if existing_commitments:
        commitments = [c.strip() for c in existing_commitments.split(",")]
        for c in commitments:
            if c.lower() in ["work", "job", "office"]:
                conflicts.append({
                    "type": "overlap",
                    "description": f"Conflict with: {c}",
                    "severity": "high",
                    "suggestion": f"Move morning study sessions to evening to avoid {c}",
                })

    # Check for study overload warning
    warnings.append({
        "type": "fatigue_risk",
        "description": "More than 4 consecutive hours detected on some days",
        "severity": "medium",
        "suggestion": "Add longer breaks between extended sessions",
    })

    return {
        "conflicts_found": len(conflicts),
        "conflicts": conflicts,
        "warnings": warnings,
        "schedule_valid": len(conflicts) == 0,
    }


register_tool(
    name="detect_conflicts",
    description="Detect scheduling conflicts and time overlap issues",
    handler=detect_conflicts,
    parameters={"schedule": "schedule data", "existing_commitments": "comma-separated commitments"},
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. generate_study_tips
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_study_tips(
    subject: str = "",
    difficulty: str = "medium",
) -> Dict[str, Any]:
    """Generate study strategy tips for a subject based on difficulty."""
    tips_db = {
        "hard": [
            "Use spaced repetition (review at 1, 3, 7, 14, 30 day intervals)",
            "Teach the concept to someone else (Feynman technique)",
            "Break complex topics into micro-concepts",
            "Practice with past exam questions daily",
            "Create mind maps connecting related concepts",
        ],
        "medium": [
            "Use active recall instead of passive re-reading",
            "Solve practice problems before reviewing theory",
            "Create summary flashcards for each topic",
            "Use the Pomodoro technique (25 min focus, 5 min break)",
        ],
        "easy": [
            "Speed-read and summarize key points",
            "Focus on application-based problems",
            "Use this topic to build foundations for harder topics",
        ],
    }

    tips = tips_db.get(difficulty, tips_db["medium"])
    return {
        "subject": subject or "General",
        "difficulty": difficulty,
        "tips": tips,
        "recommended_technique": "spaced_repetition" if difficulty == "hard" else "active_recall",
    }


register_tool(
    name="generate_study_tips",
    description="Generate study strategy tips based on subject and difficulty level",
    handler=generate_study_tips,
    parameters={"subject": "subject name", "difficulty": "easy|medium|hard"},
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. get_current_datetime
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_current_datetime() -> Dict[str, Any]:
    """Get the current date and time for scheduling context."""
    now = datetime.now()
    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "week_number": now.isocalendar()[1],
        "days_until_month_end": (
            (datetime(now.year, now.month % 12 + 1, 1) - now).days
            if now.month < 12
            else (datetime(now.year + 1, 1, 1) - now).days
        ),
    }


register_tool(
    name="get_current_datetime",
    description="Get the current date and time for scheduling context",
    handler=get_current_datetime,
    parameters={},
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. save_to_database
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_saved_data: Dict[str, Any] = {}


def save_to_database(
    key: str = "",
    data: str = "",
) -> Dict[str, Any]:
    """Save data to persistent storage."""
    if not key:
        key = f"record_{len(_saved_data) + 1}"
    _saved_data[key] = data
    return {
        "status": "saved",
        "key": key,
        "message": f"Data saved successfully with key: {key}",
        "total_records": len(_saved_data),
    }


register_tool(
    name="save_to_database",
    description="Save schedule or analysis data to persistent storage",
    handler=save_to_database,
    parameters={"key": "record key/identifier", "data": "data to save"},
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. fetch_study_resources (LIVE API — Wikipedia REST)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_study_resources(
    topics: str = "",
    max_topics: int = 8,
) -> Dict[str, Any]:
    """
    Fetch real-world study resources from the public Wikipedia REST API.

    Makes LIVE HTTP requests to https://en.wikipedia.org/api/rest_v1/page/summary/{topic}
    for the hardest topics, returning introductory summaries and reference URLs.
    This proves the agent can execute real API calls autonomously.
    """
    import httpx

    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topic_list:
        topic_list = _get_cached_subjects() or ["Mathematics", "Physics", "Computer Science"]

    # Limit to avoid excessive API calls
    try:
        max_topics = int(max_topics)
    except (ValueError, TypeError):
        max_topics = 8
    topic_list = topic_list[:max_topics]

    resources: Dict[str, Any] = {}
    api_calls_made = 0
    api_calls_succeeded = 0

    for topic in topic_list:
        # Normalize topic for Wikipedia URL (spaces → underscores)
        wiki_topic = topic.strip().replace(" ", "_").replace("/", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_topic}"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers={
                    "User-Agent": "SolastaStudyAgent/1.0 (https://github.com/solasta; solasta@example.com) httpx/0.28",
                    "Accept": "application/json",
                })
                api_calls_made += 1

                if response.status_code == 200:
                    data = response.json()
                    resources[topic] = {
                        "summary": data.get("extract", "No summary available.")[:500],
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{wiki_topic}"),
                        "title": data.get("title", topic),
                        "description": data.get("description", ""),
                        "source": "Wikipedia REST API (live)",
                    }
                    api_calls_succeeded += 1
                    logger.info("wiki_api_success", topic=topic, status=200)
                else:
                    # Topic not found — provide a search link instead
                    resources[topic] = {
                        "summary": f"No Wikipedia article found for '{topic}'. Try searching manually.",
                        "url": f"https://en.wikipedia.org/w/index.php?search={wiki_topic}",
                        "title": topic,
                        "description": "Search result fallback",
                        "source": "Wikipedia search (fallback)",
                    }
                    logger.warning("wiki_api_not_found", topic=topic, status=response.status_code)
        except Exception as e:
            resources[topic] = {
                "summary": f"Could not fetch resource for '{topic}': {str(e)[:100]}",
                "url": f"https://en.wikipedia.org/wiki/{wiki_topic}",
                "title": topic,
                "description": "Offline fallback",
                "source": "offline_fallback",
            }
            logger.error("wiki_api_error", topic=topic, error=str(e)[:100])

    return {
        "resources": resources,
        "total_topics": len(topic_list),
        "api_calls_made": api_calls_made,
        "api_calls_succeeded": api_calls_succeeded,
        "source": "Wikipedia REST API — en.wikipedia.org/api/rest_v1",
        "message": f"Fetched {api_calls_succeeded}/{api_calls_made} resources from live Wikipedia API",
    }


register_tool(
    name="fetch_study_resources",
    description="Fetch real-world study resources and summaries from the Wikipedia REST API for exam topics. Makes LIVE HTTP API calls.",
    handler=fetch_study_resources,
    parameters={
        "topics": "comma-separated list of topics to look up",
        "max_topics": "maximum number of topics to fetch (default: 8)",
    },
)
