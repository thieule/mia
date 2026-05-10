"""Unit tests cho parse commit message (không cần Neo4j)."""

from __future__ import annotations

import os
import unittest

from second_brain.commit_links import parse_story_ids, parse_task_ids


class TestCommitLinks(unittest.TestCase):
    def test_parse_task_ids_default(self) -> None:
        self.assertEqual(parse_task_ids("Fix task #12 x"), [12])
        self.assertEqual(parse_task_ids("ticket 3 and TID: 9"), [3, 9])

    def test_parse_story_ids_default(self) -> None:
        self.assertEqual(parse_story_ids("story #44"), [44])
        self.assertEqual(parse_story_ids("ST 7 done"), [7])

    def test_parse_story_ids_fixes_optional_pattern(self) -> None:
        prev = os.environ.pop("SECOND_BRAIN_COMMIT_FIXES_PATTERN", None)
        try:
            os.environ["SECOND_BRAIN_COMMIT_FIXES_PATTERN"] = r"#(\d+)"
            self.assertEqual(parse_story_ids("fixes #100"), [100])
        finally:
            if prev is None:
                os.environ.pop("SECOND_BRAIN_COMMIT_FIXES_PATTERN", None)
            else:
                os.environ["SECOND_BRAIN_COMMIT_FIXES_PATTERN"] = prev

    def test_parse_story_slug_key_env(self) -> None:
        prev = os.environ.pop("SECOND_BRAIN_COMMIT_STORY_SLUG", None)
        try:
            os.environ["SECOND_BRAIN_COMMIT_STORY_SLUG"] = "demo"
            self.assertEqual(parse_story_ids("Close demo-99 ready"), [99])
        finally:
            if prev is None:
                os.environ.pop("SECOND_BRAIN_COMMIT_STORY_SLUG", None)
            else:
                os.environ["SECOND_BRAIN_COMMIT_STORY_SLUG"] = prev


if __name__ == "__main__":
    unittest.main()
