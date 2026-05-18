"""Kiểm tra allowlist và logic path cho ingest local (không cần Neo4j)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from second_brain.ingest_local import (
    _collect_walk_paths,
    _path_under_allowed_root,
    apply_local_code_scan,
)


class TestIngestLocal(unittest.TestCase):
    def test_path_under_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td).resolve()
            sub = (base / "a" / "b").resolve()
            sub.mkdir(parents=True)
            self.assertTrue(_path_under_allowed_root(sub, [base]))
            outside = Path(td).parent / "other_sidecar"
            self.assertFalse(_path_under_allowed_root(outside, [base]))

    def test_collect_walk_skips_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "node_modules" / "x").mkdir(parents=True)
            (root / "node_modules" / "x" / "bad.py").write_text("a=1\n", encoding="utf-8")
            (root / "pkg").mkdir()
            (root / "pkg" / "ok.py").write_text("def f():\n    pass\n", encoding="utf-8")
            found = _collect_walk_paths(root, None, max_files=20)
            self.assertEqual(found, ["pkg/ok.py"])

    def test_disabled_without_env(self) -> None:
        with patch.dict(os.environ, {"SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS": ""}, clear=False):
            out = apply_local_code_scan("/tmp", project_id=1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "local_scan_disabled")

    def test_root_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            allowed_parent = Path(td).resolve()
            ok = allowed_parent / "allowed_sub"
            ok.mkdir()
            bad = allowed_parent / "outside"
            bad.mkdir()
            with patch.dict(
                os.environ,
                {"SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS": str(ok)},
                clear=False,
            ):
                out = apply_local_code_scan(str(bad), project_id=1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "root_not_allowed")


if __name__ == "__main__":
    unittest.main()
