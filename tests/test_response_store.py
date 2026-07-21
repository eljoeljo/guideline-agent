"""Unit tests for the response_store persistence helpers."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.response_store import load_responses, save_responses, set_response


class ResponseStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "responses.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_set_response_persists_to_json(self) -> None:
        responses = set_response("project_name", "Checklist AI", path=self.path)

        self.assertEqual(responses["project_name"], "Checklist AI")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"project_name": "Checklist AI"})

    def test_load_responses_initializes_empty_mapping(self) -> None:
        self.assertEqual(load_responses(path=self.path), {})

    def test_save_responses_writes_mapping(self) -> None:
        payload = {"team": "Research"}
        save_responses(payload, path=self.path)

        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
