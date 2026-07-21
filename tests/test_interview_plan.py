"""Unit tests for interview plan loading behavior."""

import tempfile
import unittest
from pathlib import Path

from tools import interview_plan


class InterviewPlanTests(unittest.TestCase):
    class DummyToolContext:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}

    def test_load_plan_raises_for_empty_plan_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "applicability_plan.json"
            path.write_text("", encoding="utf-8")
            interview_plan.PLAN_PATH = path

            with self.assertRaises(ValueError) as context:
                interview_plan._load_plan(self.DummyToolContext())

        self.assertIn("empty", str(context.exception))

    def test_load_plan_raises_for_malformed_plan_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "applicability_plan.json"
            path.write_text("{ invalid json }", encoding="utf-8")
            interview_plan.PLAN_PATH = path

            with self.assertRaises(ValueError) as context:
                interview_plan._load_plan(self.DummyToolContext())

        self.assertIn("malformed JSON", str(context.exception))


if __name__ == "__main__":
    unittest.main()
