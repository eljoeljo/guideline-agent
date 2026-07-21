"""Intake agent for collecting structured Responsible AI information."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.tools import ToolContext

from config import DEFAULT_MODEL
from tools import question_loader, response_store
from tools.applicability_engine import (
    PLAN_PATH,
    create_applicability_plan,
    load_project_profile,
)
from tools.decision_trace import append_trace
from tools.interview_plan import (
    CURRENT_ITEM_STATE_KEY,
    INTERVIEW_COMPLETE_STATE_KEY,
    PLAN_STATE_KEY,
    PROJECT_PROFILE_STATE_KEY,
    RESPONSES_STATE_KEY,
    get_next_interview_item,
    submit_interview_answer,
)
from .instructions import INTAKE_AGENT_INSTRUCTIONS


def get_all_questions() -> list[dict[str, Any]]:
    """Load all intake questions in the shape expected by the local runner."""

    questions = question_loader.load_questions()
    # Convert from Question objects to plain dicts so the local runner can easily inspect them
    return [
        {
            "id": question.id,
            "section": (
                question.raw.get("section")
                or question.raw.get("lifecycle_phase")
                or question.raw.get("lifecycle_stage")
            ),
            "question": question.question,
            "field": question.field,
            "answer_type": question.raw.get("answer_type", "long_text"),
            "choices": question.raw.get("choices", []),
            "applies_if": question.raw.get("applicability", {}).get(
                "applies_if", []
            ),
        }
        for question in questions
    ]


def _should_ask_question(question: dict[str, Any], responses: dict[str, Any]) -> bool:
    """Determine whether a question should be asked based on prior responses."""

    applies_if = question.get("applies_if", [])
    if not applies_if:
        return True

    # Conditional questions only appear when the earlier answer pattern says they are relevant. Missing answers are treated as "do not ask yet".
    for condition in applies_if:
        
        field = condition.get("field")
        operator = condition.get("operator", "equals")
        
        if field is None:
            continue

        actual_value = responses.get(field)
        
        if actual_value is None:
            return False
        
        expected_value = condition.get("value")
        
        if operator == "equals" and actual_value != expected_value:
            return False
        
        if operator == "not_equals" and actual_value == expected_value:
            return False
    return True


def run_interview(
    questions: list[dict[str, Any]] | None = None,
    responses_path: Path | None = None,
) -> dict[str, Any]:
    """Run a simple local interview loop and persist responses to disk."""

    question_list = questions if questions is not None else get_all_questions()
    responses: dict[str, Any] = {}

    for question in question_list:
        
        if not _should_ask_question(question, responses):
            # Skip questions that are not applicable based on earlier answers.
            
            continue

        prompt = question["question"]
        answer = input(f"{prompt}\n")
        responses[question["field"]] = answer

    response_store.save_responses(responses, path=responses_path)
    return responses


def _count_decisions(
    decisions: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for decision in decisions:
        
        status = decision["decision"]
        counts[status] = counts.get(status, 0) + 1

    return counts


def build_applicability_plan(
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Build the structured applicability plan for the current project."""

    project_profile = tool_context.state.get(
        PROJECT_PROFILE_STATE_KEY
    )

    if not isinstance(project_profile, dict):
        # If the state was just created, we still need a real profile from disk.
        project_profile = load_project_profile()
        tool_context.state[PROJECT_PROFILE_STATE_KEY] = project_profile

    plan = create_applicability_plan(
        project_profile=project_profile,
    )

    tool_context.state[PLAN_STATE_KEY] = plan
    tool_context.state[INTERVIEW_COMPLETE_STATE_KEY] = False
    tool_context.state[CURRENT_ITEM_STATE_KEY] = None

    return {
        "status": "success",
        "project_name": plan["project_name"],
        "total_questions": plan["total_questions"],
        "decision_counts": _count_decisions(plan["decisions"]),
    }


def get_interview_status(
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Return current interview progress and applicability counts."""

    responses = tool_context.state.get(RESPONSES_STATE_KEY)
    # Fall back to any persisted responses on disk when state is missing.

    if not isinstance(responses, dict):
        responses = dict(response_store.load_responses())
        tool_context.state[RESPONSES_STATE_KEY] = responses

    plan = tool_context.state.get(PLAN_STATE_KEY)
    decision_counts: dict[str, int] = {}

    if isinstance(plan, dict):
        decision_counts = _count_decisions(
            plan.get("decisions", [])
        )

    return {
        "status": "success",
        "interview_complete": bool(
            tool_context.state.get(
                INTERVIEW_COMPLETE_STATE_KEY,
                False,
            )
        ),
        "answered_count": len(responses),
        "responses": responses,
        "current_item": tool_context.state.get(
            CURRENT_ITEM_STATE_KEY
        ),
        "decision_counts": decision_counts,
    }


def reset_interview(
    tool_context: ToolContext,
) -> dict[str, Any]:
    """
    Clear interview answers and the generated applicability plan.

    The project profile is intentionally preserved.
    """

    # Clear persisted responses and reset runtime state.

    response_store.clear_responses()

    tool_context.state[RESPONSES_STATE_KEY] = {}
    tool_context.state[CURRENT_ITEM_STATE_KEY] = None
    tool_context.state[INTERVIEW_COMPLETE_STATE_KEY] = False
    tool_context.state[PLAN_STATE_KEY] = None

    if PLAN_PATH.exists():
        PLAN_PATH.unlink()

    append_trace(
        event_type="interview_reset",
        payload={"project_profile_preserved": True},
    )

    return {
        "status": "success",
        "message": (
            "The interview and applicability plan were reset. "
            "The project profile was preserved."
        ),
    }


def create_agent() -> Agent:
    """Create the LLM-powered Responsible AI intake agent."""

    return Agent(
        name="ResponsibleAIIntakeAgent",
        model=DEFAULT_MODEL,
        description=(
            "A conversational Responsible AI intake assistant that plans "
            "question applicability, asks only relevant questions, resolves "
            "clarifications, and stores auditable responses."
        ),
        instruction=INTAKE_AGENT_INSTRUCTIONS,
        tools=[
            build_applicability_plan,
            get_next_interview_item,
            submit_interview_answer,
            get_interview_status,
            reset_interview,
        ],
    )
