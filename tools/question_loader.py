"""Question loader utilities for the Responsible AI checklist."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from tools.applicability_engine import BASE_DIR


@dataclass
class Question:
    """Represents a normalized checklist question loaded from JSON."""

    id: str
    question: str
    field: str
    raw: dict




DEFAULT_QUESTIONS_PATH = BASE_DIR / "data" /  "mock_questions.json" 


def _validate_question_obj(obj: dict) -> None:
    if not isinstance(obj, dict):
        raise ValueError("question item must be an object/dict")

    required = ("id", "question", "field")
    missing = [key for key in required if key not in obj]
    if missing:
        raise ValueError(f"question missing required keys: {missing}")

    if not isinstance(obj["id"], (str, int)):
        raise ValueError("question `id` must be a string or integer")

    if not isinstance(obj["question"], str):
        raise ValueError("question `question` must be a string")

    if not isinstance(obj["field"], str):
        raise ValueError("question `field` must be a string")


def load_questions(path: Optional[Path | str] = None) -> List[Question]:
    """Load and validate questions from the 88-question JSON database."""

    target = Path(path) if path is not None else DEFAULT_QUESTIONS_PATH
    if not target.exists():
        raise FileNotFoundError(f"questions file not found: {target}")

    with target.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        if "questions" not in data:
            raise ValueError(
                "questions JSON must contain a top-level 'questions' key"
            )
        data = data["questions"]

    if not isinstance(data, list):
        raise ValueError("questions JSON must contain a list of questions")

    questions: List[Question] = []
    seen_ids: set[str] = set()
    seen_fields: set[str] = set()

    # Validate each question before we keep it
    for item in data:
        _validate_question_obj(item)

        question_id = str(item["id"])
        field = item["field"]

        if question_id in seen_ids:
            raise ValueError(f"duplicate question id: {question_id}")
        if field in seen_fields:
            raise ValueError(f"duplicate question field: {field}")

        seen_ids.add(question_id)
        seen_fields.add(field)

        questions.append(
            Question(
                id=question_id,
                question=item["question"],
                field=field,
                raw=item,
            )
        )

    return questions


def get_question_by_id(
    questions: Iterable[Question],
    qid: str,
) -> Optional[Question]:
    
    for question in questions:
        
        if str(question.id) == str(qid):
            
            return question
        
    return None


def get_question_by_field(
    questions: Iterable[Question],
    field: str,
) -> Optional[Question]:
    
    for question in questions:
        
        if question.field == field:
            
            return question
    return None



__all__ = [
    "Question",
    "load_questions",
    "get_question_by_id",
    "get_question_by_field",
]