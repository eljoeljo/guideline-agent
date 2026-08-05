"""Hybrid LLM and deterministic applicability planning utilities.

Loads the project profile and checklist questions,
Constructs prompts for the applicability planner, validating planner output,
and persists the resulting applicability plan.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from google import genai

from config import DEFAULT_MODEL
from schema.applicability import (
    ApplicabilityBatch,
    ApplicabilityDecision,
    ApplicabilityPlan,
    EvidenceItem,
)
from tools.decision_trace import append_trace
from tools.run_context import get_run_paths


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

# Standard project profile and plan storage locations.
def get_default_project_profile_path() -> Path:
    
    return get_run_paths().profile


def get_default_plan_path() -> Path:
    
    return get_run_paths().plan

QUESTION_PATH = DATA_DIR / "mock_questions.json"


PLANNER_INSTRUCTIONS = """
You are planning a Responsible AI peer-review interview.

You will receive:
1. A structured project profile.
2. A batch of Responsible AI checklist questions.

For every checklist question, return exactly one decision:

- ask:
  The question applies, but the project context does not answer it.

- skip:
  Clear project evidence establishes that the question does not apply.

- answered_from_project:
  The question applies and the supplied project context already answers it.

- needs_clarification:
  Applicability depends on one specific project fact that is currently null or
  genuinely unknown.

- manual_review:
  The item is incomplete, organization-specific, policy-specific, or cannot be
  safely classified automatically.

Rules:
- Never omit a question.
- Preserve every original question ID.
- Missing information is not evidence of irrelevance.
- Do not skip an entire compound question because one example is irrelevant.
  Determine the broader purpose of the question.
- An example such as "temperature", "prompt injection", or "hallucination"
  does not automatically make the whole question LLM-only.
- Open-source software libraries are not the same as external pretrained,
  foundation, or third-party models.
- Numeric prediction systems do not generate free text.
- Use needs_clarification only when a concrete target profile field can resolve
  applicability.
- Include evidence for skip and answered_from_project.
- If decision is needs_clarification, provide clarification_question and
  target_profile_field.
- If decision is answered_from_project, provide extracted_answer.
- Keep reasons concise and auditable.
- Do not provide hidden chain-of-thought.

DECISION GUIDANCE

- Use answered_from_project when a question applies and the project profile
  already provides its answer. Do not use skip merely because the known
  answer is "no" or because the project selected an alternative approach.

- For a compound checklist item, do not skip the entire item when at least one
  substantive subquestion applies. Return ask and state which subquestions are
  applicable.

- The absence of explicit sensitive attributes does not establish the absence
  of proxy variables. Evaluate questions about proxy variables separately from
  questions about directly collected sensitive attributes.

- Human oversight of model decisions is not the same as escalation of end-user
  questions. Questions about user-query escalation require actual interaction
  with users or receipt of user queries.

- Examples in a checklist question are illustrative, not exhaustive. Determine
  applicability from the broader control objective. A question can remain
  relevant to classical ML even when some examples are specific to generative
  AI or language models.
  
A project's current lifecycle stage affects how a question should be answered,
not necessarily whether the control applies.

Do not skip a deployment, production, maintenance, or monitoring question solely
because the project is currently in development. If the system is expected to
enter that lifecycle stage, classify the question based on whether the future
control or planned process is relevant.

Use ask when the project should describe its planned control. Skip only when
the profile establishes that the project will not enter that lifecycle stage
or that the control itself is genuinely irrelevant.
"""



def load_question_database(
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load all checklist questions from the question database."""

    target = path or QUESTION_PATH
    with target.open("r", encoding="utf-8") as file:
        data = json.load(file)

    # Normalizing questions to a list of dicts
    questions = data.get("questions") if isinstance(data, dict) else data

    if not isinstance(questions, list):
        raise ValueError("Question database does not contain a questions list.")

    return questions


def load_project_profile(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load the current project profile."""

    target = path or get_default_project_profile_path()
    
    with target.open("r", encoding="utf-8") as file:
        profile = json.load(file)

    if not isinstance(profile, dict):
        raise ValueError("Project profile must be a JSON object.")

    return profile


def save_project_profile(
    profile: dict[str, Any],
    path: Path | None = None,
) -> dict[str, Any]:
    """Persist the project profile to disk."""

    if not isinstance(profile, dict):
        raise TypeError("profile must be a dictionary")
    
    target = path or get_default_project_profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    
    target.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return profile


def group_questions_by_phase(
    questions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Grouping by lifecycle phase keeps the planner prompt smaller and manageable
    for question in questions:
        phase = question.get("lifecycle_phase") or "Unassigned"
        grouped[phase].append(question)

    return dict(grouped)


def _build_planner_prompt(
    project_profile: dict[str, Any],
    lifecycle_phase: str,
    questions: list[dict[str, Any]],
) -> str:
    # We only send the fields the LLM needs for decision-making
    simplified_questions = [
        {
            "id": question["id"],
            "lifecycle_phase": question.get("lifecycle_phase"),
            "lifecycle_stage": question.get("lifecycle_stage"),
            "cgp_code": question.get("cgp_code"),
            "question": question.get("question"),
            "subquestions": question.get("subquestions", []),
            "tags": question.get("tags", []),
        }
        for question in questions
    ]

    return (
        f"{PLANNER_INSTRUCTIONS}\n\n"
        f"LIFECYCLE PHASE:\n{lifecycle_phase}\n\n"
        f"PROJECT PROFILE:\n"
        f"{json.dumps(project_profile, indent=2)}\n\n"
        f"CHECKLIST QUESTIONS:\n"
        f"{json.dumps(simplified_questions, indent=2)}"
    )


def _get_nested_value(data: dict[str, Any], reference: str) -> Any:
    current: Any = data
    for part in reference.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current



def _hydrate_evidence(
    decision: ApplicabilityDecision,
    project_profile: dict[str, Any],
) -> ApplicabilityDecision:
    """Fill missing project-profile evidence excerpts deterministically."""

    for item in decision.evidence:
        
        if item.source_type != "project_profile":
            continue
        
        if item.excerpt is not None:
            continue

        value = _get_nested_value(project_profile, item.reference)
        item.excerpt = json.dumps(value, ensure_ascii=False)

    return decision


def _validate_batch(
    batch: ApplicabilityBatch,
    expected_questions: list[dict[str, Any]],
    project_profile: dict[str, Any],
) -> list[ApplicabilityDecision]:
    """Validate, hydrate, and apply clear deterministic gates."""

    # The planner must return exactly one decision per question ID
    expected_ids = {str(question["id"]) for question in expected_questions}
    actual_ids = {str(decision.question_id) for decision in batch.decisions}

    missing_ids = expected_ids - actual_ids
    unexpected_ids = actual_ids - expected_ids

    if missing_ids:
        raise ValueError(
            f"Applicability batch omitted question IDs: {sorted(missing_ids)}"
        )

    if unexpected_ids:
        raise ValueError(
            f"Applicability batch returned unknown IDs: {sorted(unexpected_ids)}"
        )

    if len(batch.decisions) != len(expected_questions):
        raise ValueError(
            "Applicability batch did not return exactly one decision per question."
        )

    validated: list[ApplicabilityDecision] = []

    for decision in batch.decisions:
        decision.question_id = str(decision.question_id)
        decision.decision_source = "llm"
        decision.confidence = min(decision.confidence, 0.90)
        decision = _hydrate_evidence(decision, project_profile)

        if decision.decision == "skip" and not decision.evidence:
            decision.decision = "manual_review"
            decision.reason = (
                "The model attempted to skip this item without supporting "
                "project evidence."
            )
            decision.confidence = min(decision.confidence, 0.50)

        if decision.decision == "needs_clarification":
            if (
                not decision.clarification_question
                or not decision.target_profile_field
            ):
                decision.decision = "manual_review"
                decision.reason = (
                    "Applicability was unclear, but the response did not "
                    "identify a usable clarification question and target field."
                )
                decision.confidence = min(decision.confidence, 0.50)

        validated.append(decision)

    return validated


def _generate_decisions(
    project_profile: dict[str, Any],
    questions: list[dict[str, Any]],
    *,
    trace_event_type: str,
) -> list[ApplicabilityDecision]:
    """Generate decisions in lifecycle-phase batches."""

    client = genai.Client()
    grouped_questions = group_questions_by_phase(questions)

    # The planner runs in lifecycle-phase batches to stay within context limits
    all_decisions: list[ApplicabilityDecision] = []

    for lifecycle_phase, question_batch in grouped_questions.items():
        prompt = _build_planner_prompt(
            project_profile=project_profile,
            lifecycle_phase=lifecycle_phase,
            questions=question_batch,
        )

        chat = client.chats.create(model=DEFAULT_MODEL)
        response = chat.send_message(
            prompt,
            config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "response_schema": ApplicabilityBatch.model_json_schema(),
            },
        )

        parsed_response = response.parsed

        if parsed_response is None:
            if response.text is None:
                raise ValueError(
                    "Applicability planner did not return parseable output."
                )
            parsed_response = json.loads(response.text)

        batch = ApplicabilityBatch.model_validate(parsed_response)
        decisions = _validate_batch(
            batch=batch,
            expected_questions=question_batch,
            project_profile=project_profile,
        )

        for decision in decisions:
            append_trace(
                event_type=trace_event_type,
                payload=decision.model_dump(),
            )

        all_decisions.extend(decisions)

    return all_decisions


def _save_plan(
    plan: ApplicabilityPlan,
    output_path: Path | None = None,
) -> dict[str, Any]:
    
    target = output_path or get_default_plan_path()
    
    target.parent.mkdir(parents=True, exist_ok=True)
    
    target.write_text(
        plan.model_dump_json(indent=2),
        encoding="utf-8",
    )
    
    return plan.model_dump()


def create_applicability_plan(
    project_profile: dict[str, Any] | None = None,
    questions: list[dict[str, Any]] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Generate and persist a complete plan for all checklist questions."""

    profile = project_profile or load_project_profile()
    question_list = questions or load_question_database()

    decisions = _generate_decisions(
        project_profile=profile,
        questions=question_list,
        trace_event_type="applicability_decision",
    )

    plan = ApplicabilityPlan(
        project_name=profile.get("project_name", "Unnamed project"),
        decisions=decisions,
        total_questions=len(question_list),
    )

    result = _save_plan(plan, output_path)

    append_trace(
        event_type="applicability_plan_created",
        payload={
            "project_name": plan.project_name,
            "total_questions": plan.total_questions,
            "decision_counts": _count_decisions(plan.decisions),
        },
    )

    return result


def replan_questions(
    *,
    project_profile: dict[str, Any],
    question_ids: Iterable[str],
    current_plan: dict[str, Any] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Re-evaluate only the questions affected by new project information."""
    
    target = output_path or get_default_plan_path()

    requested_ids = {str(question_id) for question_id in question_ids}
    all_questions = load_question_database()
    selected_questions = [
        question
        for question in all_questions
        if str(question["id"]) in requested_ids
    ]

    found_ids = {str(question["id"]) for question in selected_questions}
    missing_ids = requested_ids - found_ids
    if missing_ids:
        raise ValueError(
            f"Cannot replan unknown question IDs: {sorted(missing_ids)}"
        )

    replanned = _generate_decisions(
        project_profile=project_profile,
        questions=selected_questions,
        trace_event_type="applicability_decision_replanned",
    )

    if current_plan is None:
        if not target.exists():
            raise FileNotFoundError(
                "No existing applicability plan is available to update."
            )
        current_plan = json.loads(target.read_text(encoding="utf-8"))

    replacement_map = {
        decision.question_id: decision
        for decision in replanned
    }

    merged_decisions: list[ApplicabilityDecision] = []

    for raw_decision in current_plan["decisions"]:
        existing = ApplicabilityDecision.model_validate(raw_decision)
        merged_decisions.append(
            replacement_map.get(existing.question_id, existing)
        )

    plan = ApplicabilityPlan(
        project_name=project_profile.get(
            "project_name",
            current_plan.get("project_name", "Unnamed project"),
        ),
        decisions=merged_decisions,
        total_questions=current_plan.get(
            "total_questions",
            len(merged_decisions),
        ),
    )

    result = _save_plan(plan, target)

    append_trace(
        event_type="questions_replanned",
        payload={
            "question_ids": sorted(requested_ids),
            "decision_counts": _count_decisions(replanned),
        },
    )

    return result


def _count_decisions(
    decisions: Iterable[ApplicabilityDecision],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for decision in decisions:
        counts[decision.decision] = counts.get(decision.decision, 0) + 1

    return counts


def normalize_answer(answer: str, answer_type: str = "text") -> str:
    """Normalize basic yes/no and choice answers."""

    if answer is None:
        return ""

    cleaned = answer.strip().lower()

    if answer_type in {
        "yes_no",
        "yes_no_with_follow_up",
        "yes_no_with_explanation",
    }:
        if cleaned in {"yes", "y", "yeah", "yep", "true"}:
            return "yes"
        if cleaned in {"no", "n", "nope", "false"}:
            return "no"
        return cleaned

    if answer_type == "choice":
        return cleaned.replace(" ", "_").replace("-", "_")

    return answer.strip()

PLAN_PATH = get_default_plan_path()
PROJECT_PROFILE_PATH = get_default_project_profile_path()
