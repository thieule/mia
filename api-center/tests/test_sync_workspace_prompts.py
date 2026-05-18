"""Scan workspace for all prompt markdown files."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sync_agent_prompts_skills_from_workspace import (  # noqa: E402
    _iter_workspace_prompt_files,
    _prompt_kind_and_label,
)


def test_iter_skips_skills_and_working_queue(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("# agents", encoding="utf-8")
    (ws / "policy" / "RULE.md").parent.mkdir(parents=True)
    (ws / "policy" / "RULE.md").write_text("rule", encoding="utf-8")
    (ws / "skills" / "x").mkdir(parents=True)
    (ws / "skills" / "x" / "SKILL.md").write_text("skill", encoding="utf-8")
    (ws / "working_queue" / "pending").mkdir(parents=True)
    (ws / "working_queue" / "pending" / "t.json").write_text("{}", encoding="utf-8")

    paths = {p.relative_to(ws).as_posix() for p in _iter_workspace_prompt_files(ws)}
    assert "AGENTS.md" in paths
    assert "policy/RULE.md" in paths
    assert not any(p.startswith("skills/") for p in paths)
    assert not any(p.startswith("working_queue/") for p in paths)


def test_bootstrap_kind_for_root_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    fp = ws / "SOUL.md"
    fp.write_text("soul", encoding="utf-8")
    kind, label = _prompt_kind_and_label(ws, fp)
    assert kind == "bootstrap_soul"
    assert label == "SOUL.md"
