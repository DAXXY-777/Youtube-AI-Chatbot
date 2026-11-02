"""Check the shared relay v1 contract fixtures without making network calls."""

from copy import deepcopy
import json
from pathlib import Path
import time
import unittest
from uuid import UUID


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "relay-v1-cases.json"


def make_message(templates: dict, name: str, now_ms: int) -> dict:
    """Return an independent message with a live deadline, where needed."""
    message = deepcopy(templates[name])
    if message.get("deadline_ms") == "$NOW_PLUS_15000":
        message["deadline_ms"] = now_ms + 15_000
    return message


def apply_invalid_case(templates: dict, case: dict, now_ms: int) -> str:
    """Materialize an invalid fixture as the text a WebSocket would receive."""
    if "raw_frame" in case:
        return case["raw_frame"]

    message = make_message(templates, case["base"], now_ms)
    message.update(case.get("set", {}))
    for key in case.get("remove", []):
        message.pop(key)
    if "repeat" in case:
        change = case["repeat"]
        message[change["field"]] = change["character"] * change["count"]
    return json.dumps(message)


class RelayFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FIXTURE_PATH.open(encoding="utf-8") as file:
            cls.fixtures = json.load(file)

    def test_fixture_has_expected_cases(self):
        self.assertEqual(self.fixtures["fixture_format"], "relay-v1-cases")
        self.assertEqual(
            set(self.fixtures["valid_templates"]),
            {"ask", "reply", "job_error"},
        )
        invalid_cases = self.fixtures["invalid_cases"]
        self.assertEqual(len(invalid_cases), 10)
        names = [case["name"] for case in invalid_cases]
        self.assertEqual(len(names), len(set(names)), "Duplicate case names")
        self.assertTrue(all(case.get("reject_reason") for case in invalid_cases))

    def test_valid_templates_are_serializable(self):
        templates = self.fixtures["valid_templates"]
        now_ms = int(time.time() * 1000)
        for name in ("ask", "reply", "job_error"):
            with self.subTest(name=name):
                message = make_message(templates, name, now_ms)
                self.assertEqual(message["v"], 1)
                self.assertEqual(message["type"], name)
                self.assertEqual(UUID(message["id"]).version, 4)
                encoded = json.dumps(message).encode("utf-8")
                self.assertLessEqual(len(encoded), 16_384)
                self.assertEqual(json.loads(encoded), message)
                if name == "ask":
                    self.assertGreater(message["deadline_ms"], now_ms)
                    self.assertLessEqual(message["deadline_ms"] - now_ms, 30_000)
                    self.assertLessEqual(len(message["prompt"]), 1_500)
                elif name == "reply":
                    self.assertLessEqual(len(message["text"]), 280)

    def test_invalid_cases_can_be_materialized(self):
        templates = self.fixtures["valid_templates"]
        now_ms = int(time.time() * 1000)
        for case in self.fixtures["invalid_cases"]:
            with self.subTest(name=case["name"]):
                frame = apply_invalid_case(templates, case, now_ms)
                self.assertIsInstance(frame, str)
                if case["name"] == "malformed_json":
                    with self.assertRaises(json.JSONDecodeError):
                        json.loads(frame)
                else:
                    message = json.loads(frame)
                    original = make_message(templates, case["base"], now_ms)
                    self.assertNotEqual(message, original, "Fixture must change the base")


if __name__ == "__main__":
    unittest.main()
