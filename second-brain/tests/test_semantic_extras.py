"""Kiểm tra trích trace_refs / returns / enforces (Python, không cần Neo4j)."""

from __future__ import annotations

import ast
import unittest

from second_brain.code_static_python import _python_trace_refs, analyze_python_source


class TestSemanticExtras(unittest.TestCase):
    def test_trace_refs_docstring(self) -> None:
        src = '''
class X:
    def foo(self) -> None:
        """Implements story #7 and task 2."""
        pass
'''
        tree = ast.parse(src)
        refs = _python_trace_refs(tree, src)
        self.assertTrue(any(7 in r.get("story_ids", []) for r in refs))
        self.assertTrue(any(2 in r.get("task_ids", []) for r in refs))

    def test_returns_response_model(self) -> None:
        src = """
from pydantic import BaseModel
from fastapi import APIRouter
router = APIRouter()

class OutM(BaseModel):
    x: int

@router.get(\"/a\", response_model=OutM)
def h() -> None:
    pass
"""
        r = analyze_python_source("api.py", src)
        sem = r.get("semantic") or {}
        rb = sem.get("returns_bindings") or []
        self.assertTrue(any(b.get("dto") == "OutM" for b in rb))


if __name__ == "__main__":
    unittest.main()
