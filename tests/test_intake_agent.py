"""Unit tests for the intake agent question loading and local interview flow."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.intake_agent import get_all_questions, run_interview


class IntakeAgentTests(unittest.TestCase):
    def test_get_all_questions_includes_condition_metadata(self) -> None:
        questions = get_all_questions()

        self.assertTrue(any(q["field"] == "q_01" for q in questions))

        first_question = next(q for q in questions if q["field"] == "q_01")
        self.assertEqual(first_question["answer_type"], "long_text")
        self.assertEqual(first_question["applies_if"], [])

    def test_run_interview_uses_applicability_logic_and_persists_responses(self) -> None:
        questions = [
            {
                "id": "Q001",
                "field": "uses_ai_or_ml",
                "question": "Does this project use AI or machine learning?",
                "answer_type": "yes_no",
                "applies_if": [],
            },
            {
                "id": "Q002",
                "field": "project_type",
                "question": "Which type of project is this?",
                "answer_type": "choice",
                "applies_if": [
                    {"field": "uses_ai_or_ml", "operator": "equals", "value": "yes"}
                ],
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            responses_path = Path(temp_dir) / "responses.json"
            with patch("builtins.input", side_effect=["yes", "generative_ai"]):
                responses = run_interview(questions=questions, responses_path=responses_path)

            self.assertEqual(responses["uses_ai_or_ml"], "yes")
            self.assertEqual(responses["project_type"], "generative_ai")
            self.assertEqual(json.loads(responses_path.read_text(encoding="utf-8")), responses)


if __name__ == "__main__":
    unittest.main()
