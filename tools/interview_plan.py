"""Execution tools for an LLM-generated applicability plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext

from tools import question_loader, response_store
from tools.applicability_engine import (
    PLAN_PATH,
    load_project_profile,
    replan_questions,
    save_project_profile,
)
from tools.decision_trace import append_trace


# State keys used in the tool context to persist interview progress.
PLAN_STATE_KEY = "applicability_plan"
CURRENT_ITEM_STATE_KEY = "current_interview_item"
PROJECT_PROFILE_STATE_KEY = "project_profile"
RESPONSES_STATE_KEY = "intake_responses"
INTERVIEW_COMPLETE_STATE_KEY = "intake_complete"


UNKNOWN_ANSWERS = {
    "unknown",
    "not sure",
    "unsure",
    "i don't know",
    "i do not know",
    "not yet determined",
}


def _load_plan(tool_context: ToolContext) -> dict[str, Any]:
    """Load the current applicability plan from context or disk."""

    plan = tool_context.state.get(PLAN_STATE_KEY)

    if isinstance(plan, dict):
        # The current in-memory plan is the authoritative source during a run.
        return plan

    if not PLAN_PATH.exists():
        raise FileNotFoundError(
            "No applicability plan exists. Build the plan first."
        )

    raw_plan = PLAN_PATH.read_text(encoding="utf-8")
    if not raw_plan.strip():
        raise ValueError(
            f"Applicability plan file {PLAN_PATH} is empty. Rebuild it."
        )

    try:
        plan = json.loads(raw_plan)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Applicability plan file {PLAN_PATH} is malformed JSON."
        ) from exc

    tool_context.state[PLAN_STATE_KEY] = plan
    return plan


def _load_project_profile(
    tool_context: ToolContext,
) -> dict[str, Any]:
    profile = tool_context.state.get(PROJECT_PROFILE_STATE_KEY)

    if isinstance(profile, dict):
        return dict(profile)

    profile = load_project_profile()
    tool_context.state[PROJECT_PROFILE_STATE_KEY] = profile
    return profile


def _load_responses(
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Load interview responses from context or persisted storage."""

    responses = tool_context.state.get(RESPONSES_STATE_KEY)

    if isinstance(responses, dict):
        return dict(responses)

    responses = dict(response_store.load_responses())
    tool_context.state[RESPONSES_STATE_KEY] = responses
    return responses


def _question_lookup() -> dict[str, dict[str, Any]]:
    """Build a lookup table for questions keyed by question ID."""

    questions = question_loader.load_questions()

    # Transform the raw question models into lightweight lookup
    return {
        question.id: {
            "question_id": question.id,
            "original_question": question.question,
            "field": question.field,
            "lifecycle_phase": (
                question.raw.get("lifecycle_phase")
                or question.raw.get("section")
            ),
            "lifecycle_stage": question.raw.get("lifecycle_stage"),
            "answer_type": question.raw.get(
                "answer_type",
                "long_text",
            ),
            "choices": question.raw.get("choices", []),
            "subquestions": question.raw.get("subquestions", []),
        }
        for question in questions
    }





def _clarification_groups(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Group clarification decisions by target profile field."""

    groups: dict[str, dict[str, Any]] = {}

    # Clarification questions are grouped by the profile field they affect 
    
    for decision in plan["decisions"]:
        
        if decision["decision"] != "needs_clarification":
            continue

        target = decision.get("target_profile_field")
        question = decision.get("clarification_question")

        if not target or not question:
            continue

        group = groups.setdefault(
            target,
            {
                "target_profile_field": target,
                "clarification_question": question,
                "affected_question_ids": [],
                "reasons": [],
            },
        )
        group["affected_question_ids"].append(
            decision["question_id"]
        )
        group["reasons"].append(decision["reason"])

    return list(groups.values())


def _normalize_profile_answer(answer: str) -> bool | None | str:
    """Normalize a clarification answer into a boolean, explicit unknown, or raw text."""

    cleaned = answer.strip().lower()

    # Treat common uncertainty phrases as an explicit "unknown" answer 
    if cleaned in UNKNOWN_ANSWERS:
        return None

    if (
        cleaned in {"yes", "y", "true", "yeah", "yep"}
        or cleaned.startswith("yes ")
        or cleaned.startswith("yes,")
    ):
        return True

    if (
        cleaned in {"no", "n", "false", "nope"}
        or cleaned.startswith("no ")
        or cleaned.startswith("no,")
    ):
        return False

    return answer.strip()


def _is_explicit_unknown(answer: str) -> bool:
    return answer.strip().lower() in UNKNOWN_ANSWERS


def _assess_answer(
    answer: str,
    current_item: dict[str, Any],
) -> dict[str, Any]:
    """Validate a user answer against the current interview item."""

    stripped = answer.strip()
    cleaned = stripped.lower()

    # Reject empty answers up front
    if not stripped:
        return {
            "status": "invalid_answer",
            "error_message": "The answer cannot be empty.",
        }

    if _is_explicit_unknown(stripped):
        return {
            "status": "accepted",
            "normalized_answer": stripped,
            "answer_quality": "explicit_unknown",
        }

    answer_type = current_item.get("answer_type", "long_text")
    subquestions = current_item.get("subquestions", [])

    if answer_type == "yes_no":
        if cleaned not in {"yes", "no", "y", "n"}:
            return {
                "status": "needs_follow_up",
                "follow_up_question": "Please answer yes or no.",
            }
        return {
            "status": "accepted",
            "normalized_answer": (
                "yes" if cleaned in {"yes", "y"} else "no"
            ),
            "answer_quality": "complete",
        }

    requires_explanation = answer_type in {
        "yes_no_with_follow_up",
        "yes_no_with_explanation",
        "long_text",
        "text",
    }

    # For compound questions, prompt for a longer answer if the user response is too short to address multiple subquestions.
    if len(subquestions) > 1 and len(stripped.split()) < 6:
        return {
            "status": "needs_follow_up",
            "follow_up_question": (
                "Please address each part of the question with concrete "
                "details. You can structure the response using a., b., and c."
            ),
        }

    return {
        "status": "accepted",
        "normalized_answer": stripped,
        "answer_quality": "complete",
    }


def get_next_interview_item(
    tool_context: ToolContext,
) -> dict[str, Any]:
    """
    Return one clarification or checklist question at a time.

    Clarifications are deduplicated by target project-profile field. A single
    answer can therefore replan multiple affected checklist questions.
    """

    plan = _load_plan(tool_context)
    profile = _load_project_profile(tool_context)
    responses = _load_responses(tool_context)
    questions = _question_lookup()

    # If a clarification answer was already stored in the project profile, no need to ask it
    for group in _clarification_groups(plan):
        
        target = group["target_profile_field"]
        
        if profile.get(target) is not None:
            
            plan = replan_questions(
                project_profile=profile,
                question_ids=group["affected_question_ids"],
                current_plan=plan,
            )
            tool_context.state[PLAN_STATE_KEY] = plan

    # Store answers that were extracted from the project context

    for decision in plan["decisions"]:
        
        question_id = decision["question_id"]
        question = questions.get(question_id)

        if question is None:
            continue

        field = question["field"]
        if field in responses:
            continue

        if decision["decision"] == "answered_from_project":
            extracted_answer = decision.get("extracted_answer")
            if not extracted_answer:
                continue

            responses[field] = {
                "answer": extracted_answer,
                "answer_source": "project_context",
                "question_id": question_id,
                "item_type": "checklist_question",
                "answer_quality": "extracted",
            }

            append_trace(
                event_type="answer_extracted_from_project",
                payload={
                    "question_id": question_id,
                    "field": field,
                    "answer": extracted_answer,
                },
            )

    tool_context.state[RESPONSES_STATE_KEY] = responses
    response_store.save_responses(responses)

    # Ask each missing project fact only once, then move on to checklist items.
    for group in _clarification_groups(plan):
        target = group["target_profile_field"]
        clarification_field = f"clarification_{target}"

        if clarification_field in responses:
            continue

        item = {
            "item_type": "clarification",
            "question_id": None,
            "field": clarification_field,
            "target_profile_field": target,
            "affected_question_ids": group["affected_question_ids"],
            "question": group["clarification_question"],
            "reason": " ".join(group["reasons"]),
        }

        tool_context.state[CURRENT_ITEM_STATE_KEY] = item
        tool_context.state[INTERVIEW_COMPLETE_STATE_KEY] = False

        append_trace(
            event_type="question_selected",
            payload=item,
        )

        return {
            "status": "question",
            **item,
        }

    # Ask applicable checklist questions.
    for decision in plan["decisions"]:
        if decision["decision"] != "ask":
            continue

        question_id = decision["question_id"]
        question = questions.get(question_id)

        if question is None:
            continue

        if question["field"] in responses:
            continue

        item = {
            "item_type": "checklist_question",
            "question_id": question_id,
            "field": question["field"],
            "question": question["original_question"],
            "lifecycle_phase": question["lifecycle_phase"],
            "lifecycle_stage": question["lifecycle_stage"],
            "answer_type": question["answer_type"],
            "choices": question["choices"],
            "subquestions": question["subquestions"],
            "selection_reason": decision["reason"],
            "confidence": decision["confidence"],
            "decision_source": decision.get(
                "decision_source",
                "llm",
            ),
            "evidence": decision.get("evidence", []),
        }

        tool_context.state[CURRENT_ITEM_STATE_KEY] = item
        tool_context.state[INTERVIEW_COMPLETE_STATE_KEY] = False

        append_trace(
            event_type="question_selected",
            payload={
                "question_id": question_id,
                "field": question["field"],
                "selection_reason": decision["reason"],
                "confidence": decision["confidence"],
                "decision_source": decision.get(
                    "decision_source",
                    "llm",
                ),
                "evidence": decision.get("evidence", []),
            },
        )

        return {
            "status": "question",
            **item,
        }

    tool_context.state[CURRENT_ITEM_STATE_KEY] = None
    tool_context.state[INTERVIEW_COMPLETE_STATE_KEY] = True

    manual_review = [
        decision["question_id"]
        for decision in plan["decisions"]
        if decision["decision"] == "manual_review"
    ]

    append_trace(
        event_type="interview_completed",
        payload={
            "answered_count": len(responses),
            "manual_review_question_ids": manual_review,
        },
    )

    return {
        "status": "complete",
        "message": "All planned interview questions have been completed.",
        "manual_review_question_ids": manual_review,
        "responses": responses,
    }


def submit_interview_answer(
    answer: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Validate and store the answer to the active interview item."""

    current_item = tool_context.state.get(CURRENT_ITEM_STATE_KEY)

    if not isinstance(current_item, dict):
        return {
            "status": "error",
            "error_message": "There is no active interview question.",
        }

    field = current_item["field"]
    item_type = current_item.get("item_type")
    responses = _load_responses(tool_context)

    append_trace(
        event_type="answer_received",
        payload={
            "question_id": current_item.get("question_id"),
            "field": field,
            "item_type": item_type,
            "answer": answer.strip(),
        },
    )

    if item_type == "clarification":
        # Clarifications also update the underlying project profile
    
        target_field = current_item.get("target_profile_field")
        affected_ids = current_item.get(
            "affected_question_ids",
            [],
        )

        if not target_field:
            return {
                "status": "error",
                "error_message": (
                    "The clarification item has no target profile field."
                ),
            }

        normalized_value = _normalize_profile_answer(answer)
        profile = _load_project_profile(tool_context)
        profile[target_field] = normalized_value

        save_project_profile(profile)
        tool_context.state[PROJECT_PROFILE_STATE_KEY] = profile

        responses[field] = {
            "answer": answer.strip(),
            "normalized_value": normalized_value,
            "answer_source": "user",
            "question_id": None,
            "item_type": "clarification",
            "target_profile_field": target_field,
            "affected_question_ids": affected_ids,
        }

        response_store.save_responses(responses)
        tool_context.state[RESPONSES_STATE_KEY] = responses

        append_trace(
            event_type="project_profile_updated",
            payload={
                "target_profile_field": target_field,
                "value": normalized_value,
                "affected_question_ids": affected_ids,
            },
        )

        plan = _load_plan(tool_context)
        updated_plan = replan_questions(
            project_profile=profile,
            question_ids=affected_ids,
            current_plan=plan,
        )

        tool_context.state[PLAN_STATE_KEY] = updated_plan
        tool_context.state[CURRENT_ITEM_STATE_KEY] = None

        append_trace(
            event_type="interview_answer_recorded",
            payload={
                "question_id": None,
                "field": field,
                "item_type": "clarification",
                "answer": answer.strip(),
                "normalized_value": normalized_value,
            },
        )

        return {
            "status": "success",
            "stored_field": field,
            "updated_profile_field": target_field,
            "updated_profile_value": normalized_value,
            "replanned_question_ids": affected_ids,
        }

    assessment = _assess_answer(
        answer,
        current_item,
    )

    if assessment["status"] != "accepted":
        append_trace(
            event_type="answer_needs_follow_up",
            payload={
                "question_id": current_item.get("question_id"),
                "field": field,
                **assessment,
            },
        )

        # Keep current item active so the next submission is associated with the same checklist question.
        return assessment

    normalized_answer = assessment["normalized_answer"]
    question_id = current_item.get("question_id")

    # Checklist question answers are stored as structured records
    responses[field] = {
        "answer": normalized_answer,
        "answer_source": "user",
        "question_id": question_id,
        "item_type": "checklist_question",
        "answer_quality": assessment.get(
            "answer_quality",
            "complete",
        ),
    }

    tool_context.state[RESPONSES_STATE_KEY] = responses
    tool_context.state[CURRENT_ITEM_STATE_KEY] = None
    response_store.save_responses(responses)

    append_trace(
        event_type="interview_answer_recorded",
        payload={
            "question_id": question_id,
            "field": field,
            "item_type": "checklist_question",
            "answer": normalized_answer,
            "answer_quality": assessment.get(
                "answer_quality",
                "complete",
            ),
        },
    )

    return {
        "status": "success",
        "stored_field": field,
        "stored_answer": normalized_answer,
        "question_id": question_id,
    }
    