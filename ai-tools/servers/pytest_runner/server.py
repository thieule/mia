"""Pytest runner MCP server — execute and report API/integration test suites."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from shared.auth import validate_startup_secret

validate_startup_secret()

mcp = FastMCP("pytest_runner")

_DEFAULT_RUNS = ROOT.parent / "mia" / "workspace-mia" / "agent" / "test-runs"
RUNS_DIR = Path(os.environ.get("TEST_RUNS_PATH",  str(_DEFAULT_RUNS)))

_MAX_OUTPUT_CHARS = 3000


def _make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _load_env_file(path: str) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file into a dict."""
    env: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


def _build_pytest_cmd(
    suite_path: str,
    report_path: Path,
    mode: str,
    iterations: int,
    markers: str,
    extra: list[str],
) -> list[str]:
    cmd = [
        sys.executable, "-m", "pytest",
        suite_path,
        "--json-report",
        f"--json-report-file={report_path}",
        "--tb=short",
        "-v",
    ]
    if mode == "smoke":
        cmd += ["-m", "smoke"]
    elif mode == "stress" and iterations > 1:
        cmd += [f"--count={iterations}"]
    if markers:
        cmd += ["-m", markers]
    cmd += extra
    return cmd


def _parse_report(report_path: Path) -> tuple[dict, list[dict]]:
    """Return (summary_dict, failures_list) from a pytest-json-report file."""
    if not report_path.exists():
        return {}, []
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, []

    summary = data.get("summary", {})
    tests = data.get("tests", [])
    failures = [
        {
            "test_id": t.get("nodeid"),
            "outcome": t.get("outcome"),
            "message": str((t.get("call") or {}).get("longrepr", ""))[:2000],
        }
        for t in tests
        if t.get("outcome") in ("failed", "error")
    ]
    return {
        "total": summary.get("total", 0),
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "errors": summary.get("error", 0),
        "skipped": summary.get("skipped", 0),
        "duration_seconds": round(data.get("duration", 0), 2),
    }, failures


@mcp.tool()
def test_run(
    suite_path: str,
    mode: str = "once",
    environment_file: str = "",
    iterations: int = 1,
    markers: str = "",
    extra_args: str = "",
) -> str:
    """Run a pytest test suite and return structured results.

    Args:
        suite_path: Absolute or relative path to a .py test file or directory.
        mode: Execution mode:
              'once'       — standard single pass (default).
              'smoke'      — only tests marked @pytest.mark.smoke.
              'stress'     — repeat the suite <iterations> times (requires pytest-repeat).
              'regression' — full suite, no filtering.
        environment_file: Optional path to a .env file; its vars are injected into the runner.
        iterations: Number of times to repeat the suite when mode='stress'. Default 1.
        markers: Raw pytest marker expression, e.g. 'api and not slow'.
        extra_args: Additional raw pytest CLI flags as a space-separated string.

    Returns:
        JSON string with run_id, success flag, summary counts, failure details, and output tail.
        Use the run_id with test_run_result() to retrieve results later.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = _make_run_id()
    report_path = RUNS_DIR / f"{run_id}.json"

    env = os.environ.copy()
    if environment_file:
        env.update(_load_env_file(environment_file))

    extra = extra_args.split() if extra_args.strip() else []
    cmd = _build_pytest_cmd(suite_path, report_path, mode, iterations, markers, extra)

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        result = {
            "run_id": run_id, "success": False, "exit_code": -1,
            "error": "Test run timed out after 600 seconds.",
            "started_at": started_at,
        }
        _save_result(run_id, result)
        return json.dumps(result, indent=2)
    except Exception as exc:
        result = {
            "run_id": run_id, "success": False, "exit_code": -1,
            "error": str(exc), "started_at": started_at,
        }
        _save_result(run_id, result)
        return json.dumps(result, indent=2)

    summary, failures = _parse_report(report_path)

    result = {
        "run_id": run_id,
        "suite_path": suite_path,
        "mode": mode,
        "iterations": iterations,
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "summary": summary,
        "failures": failures,
        "started_at": started_at,
        "stdout_tail": proc.stdout[-_MAX_OUTPUT_CHARS:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-1000:] if proc.stderr else "",
    }
    _save_result(run_id, result)
    return json.dumps(result, indent=2)


@mcp.tool()
def test_run_result(run_id: str) -> str:
    """Retrieve the full result of a previous test run by its run_id.

    Args:
        run_id: The run identifier returned by test_run().

    Returns:
        JSON string with the stored result, or an error message if not found.
    """
    result_path = RUNS_DIR / f"{run_id}_result.json"
    if not result_path.exists():
        return json.dumps({"error": f"No result found for run_id '{run_id}'."})
    return result_path.read_text(encoding="utf-8")


def _save_result(run_id: str, data: dict) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{run_id}_result.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
