#!/usr/bin/env python3
"""Tao thu muc projects/<name> tu projects/_template (cau hinh + workflows mau)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "projects" / "_template"
PROJECTS = ROOT / "projects"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Sao chep _template thanh mot instance workflow cho mot du an."
    )
    p.add_argument("name", help="Directory name: projects/<name> (lowercase, no space).")
    args = p.parse_args()
    name = args.name.strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        print("Invalid name.", file=sys.stderr)
        return 2
    target = (PROJECTS / name).resolve()
    if not TEMPLATE.is_dir():
        print("Missing template:", TEMPLATE, file=sys.stderr)
        return 1
    if target.exists():
        print("Already exists:", target, file=sys.stderr)
        return 1
    shutil.copytree(
        TEMPLATE,
        target,
        ignore=shutil.ignore_patterns(),
    )
    (target / "workspace").mkdir(exist_ok=True)
    (target / "workspace" / "agent").mkdir(exist_ok=True)
    (target / "workspace" / "admin").mkdir(exist_ok=True)
    print("Created:", target)
    print("Next:")
    print(f"  1) copy {target / 'EXAMPLE_.env'} -> {target / '.env'}  (fill keys)")
    print(
        f"  2) python {ROOT / 'main.py'} --project-dir {target} -w {target / 'workflows' / 'pipeline.example.yaml'} --request \"...\"",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
