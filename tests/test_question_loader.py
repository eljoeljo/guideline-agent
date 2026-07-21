"""Unit tests for question loader and answer normalization utilities."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.applicability_engine import normalize_answer
from tools.question_loader import load_questions


class QuestionLoaderTests(unittest.TestCase):
    def test_load_questions_from_top_level_object(self) -> None:
        sample_data = {
            "cgp_legend": {},
            "questions": [
                {
                    "id": "01",
                    "field": "q_01",
                    "question": "Is the project following policy?",
                    "answer_type": "yes_no_with_explanation",
                    "choices": ["yes", "no", "not_sure"],
                    "applicability": {
                        "applies_if": [],
                        "status": "unmapped",
                        "notes": "Test item",
                    },
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "questions.json"
            path.write_text(json.dumps(sample_data), encoding="utf-8")

            questions = load_questions(path=path)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].id, "01")
        self.assertEqual(questions[0].field, "q_01")
        self.assertEqual(questions[0].raw["answer_type"], "yes_no_with_explanation")
        self.assertEqual(
            questions[0].raw["applicability"]["applies_if"], []
        )

    def test_normalize_answer_handles_yes_no_with_explanation(self) -> None:
        self.assertEqual(
            normalize_answer("Yes", "yes_no_with_explanation"),
            "yes",
        )
        self.assertEqual(
            normalize_answer("No", "yes_no_with_follow_up"),
            "no",
        )


if __name__ == "__main__":
    unittest.main()
