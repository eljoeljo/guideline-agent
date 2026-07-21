"""Structured models for checklist applicability planning.

These Pydantic models define the schema for applicability decisions,
clarification groups, and the final plan returned by the planner.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ApplicabilityStatus = Literal[
    "ask",
    "skip",
    "answered_from_project",
    "needs_clarification",
    "manual_review",
]

# Model for evidence used to support a decision, including source type, reference
class EvidenceItem(BaseModel):
    """A piece of project evidence supporting an applicability decision."""

    source_type: Literal[
        "project_profile",
        "project_document",
        "user_response",
        "deterministic_rule",
    ]

    reference: str = Field(
        description=(
            "A profile field, document section, response field, or rule identifier."
        )
    )

    excerpt: str | None = Field(
        default=None,
        description="A short supporting excerpt or value.",
    )


class ApplicabilityDecision(BaseModel):
    """Applicability decision for one checklist question."""

    question_id: str
    decision: ApplicabilityStatus

    reason: str = Field(
        description="A concise, user-auditable explanation."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the applicability decision.",
    )

    evidence: list[EvidenceItem] = Field(default_factory=list)

    clarification_question: str | None = Field(
        default=None,
        description=(
            "A short question to ask when applicability cannot yet be determined."
        ),
    )

    target_profile_field: str | None = Field(
        default=None,
        description=(
            "Project profile field that the clarification should populate."
        ),
    )

    extracted_answer: str | None = Field(
        default=None,
        description=(
            "Answer extracted from project context when decision is "
            "answered_from_project."
        ),
    )

    decision_source: Literal["llm", "rule"] = "llm"


class ApplicabilityBatch(BaseModel):
    """Applicability decisions for one lifecycle-phase batch."""

    lifecycle_phase: str
    decisions: list[ApplicabilityDecision]


class ClarificationGroup(BaseModel):
    """One clarification capable of resolving multiple checklist decisions."""

    target_profile_field: str
    clarification_question: str
    affected_question_ids: list[str]
    reasons: list[str] = Field(default_factory=list)


class ApplicabilityPlan(BaseModel):
    """Complete applicability plan for the project."""

    project_name: str
    decisions: list[ApplicabilityDecision]
    total_questions: int
