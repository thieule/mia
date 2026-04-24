#!/usr/bin/env python3
"""Start the Mia DevOps deployment (`ai-devops/`): loads .env, installs mia-ai + ai-tools, runs gateway.

Layout (siblings under the repo root):

  core/         # mia-ai (package mia)
  ai-tools/     # local MCP (registry, pytest_runner, …)
  ai-devops/    # this folder — deploy, infra, and ops assistant

  python start.py
  python start.py --validate-only
  python start.py --skip-install
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AI_AGENT_ROOT = ROOT.parent / "core"
AI_TOOLS_ROOT = ROOT.parent / "ai-tools"
CONFIG = ROOT / "config" / "config.json"
ENV_FILE = ROOT / ".env"
WORKSPACE_DIR = "workspace"

_ADMIN_README = """# Admin area (human / approval-gated)

Canonical policies for this Mia DevOps deployment. The agent must not modify these files without explicit approval.
"""

_AGENT_README = """# Agent area (autonomous)

Runbooks, infra notes, deploy checklists, and draft manifests the agent may create; subject to `../admin/` policy.
"""


def _require_python() -> None:
    if sys.version_info < (3, 11):
        print("Mia DevOps requires Python 3.11+. Current:", sys.version, file=sys.stderr)
        sys.exit(1)


def _resolve_local_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _get_github_app_private_key() -> str:
    key_b64 = os.environ.get("GITHUB_APP_PRIVATE_KEY_B64", "").strip()
    if key_b64:
        return base64.b64decode(key_b64).decode("utf-8")

    key_inline = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    if key_inline:
        return key_inline.replace("\\n", "\n")

    key_path_raw = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH", "").strip()
    if key_path_raw:
        key_path = _resolve_local_path(key_path_raw)
        if not key_path.is_file():
            raise RuntimeError(f"GitHub App private key not found: {key_path}")
        return key_path.read_text(encoding="utf-8")

    return ""


def _build_github_app_auth_header() -> str:
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "").strip()
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").strip() or "https://api.github.com"
    private_key = _get_github_app_private_key()

    present = [bool(app_id), bool(installation_id), bool(private_key)]
    if not any(present):
        return ""
    if not all(present):
        raise RuntimeError(
            "GitHub App auth requires GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, "
            "plus one of GITHUB_APP_PRIVATE_KEY_B64, GITHUB_APP_PRIVATE_KEY, "
            "or GITHUB_APP_PRIVATE_KEY_PATH."
        )
    import httpx
    import jwt

    now = int(time.time())
    app_jwt = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": app_id},
        private_key,
        algorithm="RS256",
    )
    response = httpx.post(
        f"{api_url.rstrip('/')}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    token = response.json().get("token", "").strip()
    if not token:
        raise RuntimeError("GitHub App installation token response did not include a token.")
    return f"Bearer {token}"


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs into os.environ (file values win over existing process env)."""
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == '"' == val[-1]:
            val = val[1:-1]
        os.environ[name] = val
    if not os.environ.get("DISCORD_ADMIN_USER_IDS") and os.environ.get("DISCORD_ALLOWED_USER_ID"):
        os.environ["DISCORD_ADMIN_USER_IDS"] = os.environ["DISCORD_ALLOWED_USER_ID"]
    os.environ.setdefault("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/")
    os.environ.setdefault("GITHUB_TOKEN", "")
    os.environ.setdefault("GITHUB_API_URL", "https://api.github.com")
    os.environ.setdefault("GITHUB_APP_ID", "")
    os.environ.setdefault("GITHUB_APP_INSTALLATION_ID", "")
    os.environ.setdefault("GITHUB_APP_PRIVATE_KEY_B64", "")
    os.environ.setdefault("GITHUB_APP_PRIVATE_KEY", "")
    os.environ.setdefault("GITHUB_APP_PRIVATE_KEY_PATH", "")
    os.environ.setdefault("GEMINI_API_KEY", "")
    os.environ.setdefault("GEMINI_MODEL", "gemini-2.0-flash")
    if not os.environ.get("GITHUB_MCP_AUTH_HEADER"):
        app_header = _build_github_app_auth_header()
        if app_header:
            os.environ["GITHUB_MCP_AUTH_HEADER"] = app_header
        else:
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            os.environ["GITHUB_MCP_AUTH_HEADER"] = f"Bearer {token}" if token else ""


def _ensure_test_runs_path() -> None:
    runs = ROOT / WORKSPACE_DIR / "agent" / "test-runs"
    runs.mkdir(parents=True, exist_ok=True)
    default = str(runs.resolve())
    if not os.environ.get("TEST_RUNS_PATH_MIA_DEVOPS", "").strip():
        os.environ["TEST_RUNS_PATH_MIA_DEVOPS"] = default


def init_workspace() -> None:
    """Create workspace/admin, agent/test-runs, and README stubs (idempotent)."""
    ws = ROOT / WORKSPACE_DIR
    admin = ws / "admin"
    agent = ws / "agent"
    admin.mkdir(parents=True, exist_ok=True)
    agent.mkdir(parents=True, exist_ok=True)
    (agent / "test-runs").mkdir(parents=True, exist_ok=True)
    admin_readme = admin / "README.md"
    agent_readme = agent / "README.md"
    if not admin_readme.is_file():
        admin_readme.write_text(_ADMIN_README, encoding="utf-8")
    if not agent_readme.is_file():
        agent_readme.write_text(_AGENT_README, encoding="utf-8")
    print(f"Workspace layout ready under: {ws}", flush=True)


def run_pip_install(quiet: bool) -> None:
    """Install mia-ai from ../core and ai-tools (required for registry + pytest MCP)."""
    if not AI_AGENT_ROOT.is_dir():
        print(f"Error: core package tree not found at {AI_AGENT_ROOT}", file=sys.stderr)
        sys.exit(1)
    base_flags = ["-m", "pip", "install"]
    if quiet:
        base_flags.append("-q")
    if os.name == "nt":
        print(
            "Windows: priming mcp package (ignore-installed; matches mia pyproject mcp>=1.26,<2)...",
            flush=True,
        )
        subprocess.run(
            [sys.executable, *base_flags, "--ignore-installed", "mcp>=1.26.0,<2.0.0"],
            cwd=ROOT,
            check=True,
        )
    ai_agent_spec = f"{AI_AGENT_ROOT.resolve()}[discord]"
    subprocess.run([sys.executable, *base_flags, "-e", ai_agent_spec], cwd=ROOT, check=True)
    if AI_TOOLS_ROOT.is_dir():
        print("Installing ai-tools (Mia DevOps default; registry + pytest MCP)...", flush=True)
        subprocess.run([sys.executable, *base_flags, "-e", str(AI_TOOLS_ROOT)], cwd=ROOT, check=True)
    else:
        print(f"  Warning: ai-tools not found at {AI_TOOLS_ROOT} — local MCP servers will fail.", flush=True)


def validate_config() -> None:
    """Load config.json with env substitution; print a short status or exit with code 1."""
    sys.path.insert(0, str(AI_AGENT_ROOT))
    from mia.config.loader import load_config, resolve_config_env_vars, set_config_path

    p = CONFIG.resolve()
    if not p.is_file():
        print(f"Missing config: {p}", file=sys.stderr)
        sys.exit(1)
    set_config_path(p)
    cfg = resolve_config_env_vars(load_config(p))
    print("Config OK (Mia DevOps)", flush=True)
    print("  model:", cfg.agents.defaults.model, flush=True)
    print("  provider:", cfg.agents.defaults.provider, flush=True)
    key = cfg.providers.openrouter.api_key
    print("  openrouter key:", f"set ({len(key)} chars)" if key else "MISSING", flush=True)
    secret = os.environ.get("AI_TOOL_SECRET", "").strip()
    print(
        "  AI_TOOL_SECRET:",
        f"set ({len(secret)} chars)" if secret else "MISSING (registry + pytest MCP will not start)",
        flush=True,
    )
    gh = os.environ.get("GITHUB_MCP_AUTH_HEADER", "").strip()
    print(
        "  github MCP auth:",
        "set" if gh and gh != "Bearer " else "optional (empty - wire GITHUB_TOKEN or GitHub App)",
        flush=True,
    )
    raw = cfg.model_dump(by_alias=True)
    ch = raw.get("channels") or {}
    dc = ch.get("discord")
    if not dc:
        print("  discord: not configured", flush=True)
    else:
        print("  discord enabled:", dc.get("enabled"), flush=True)
        tok = dc.get("token") or ""
        if not dc.get("enabled"):
            print("  discord token (Mia DevOps): skipped (disabled)", flush=True)
        else:
            print("  discord token (Mia DevOps):", f"set ({len(tok)} chars)" if tok else "MISSING", flush=True)
        print("  allowFrom:", dc.get("allowFrom") or [], flush=True)
    print("  gateway port:", (raw.get("gateway") or {}).get("port"), flush=True)
    print("  restrictToWorkspace:", raw.get("tools", {}).get("restrictToWorkspace"), flush=True)


def run_gateway() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "mia",
            "gateway",
            "-c",
            str(CONFIG),
            "-v",
        ],
        cwd=ROOT,
        check=False,
    )


def main() -> None:
    _require_python()
    parser = argparse.ArgumentParser(description="Start Mia DevOps gateway (mia + optional Discord).")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Stop after config validation (no gateway).",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip pip install -e ../core[discord] and ../ai-tools",
    )
    parser.add_argument(
        "--no-workspace-init",
        action="store_true",
        help=f"Skip creating {WORKSPACE_DIR}/admin and {WORKSPACE_DIR}/agent",
    )
    parser.add_argument(
        "--quiet-pip",
        action="store_true",
        help="Pass -q to pip install",
    )
    args = parser.parse_args()

    if not ENV_FILE.is_file():
        print(
            "No .env found. Copy EXAMPLE_.env to .env in this directory and fill in secrets.",
            file=sys.stderr,
        )
        sys.exit(1)

    os.chdir(ROOT)
    load_dotenv(ENV_FILE)
    _ensure_test_runs_path()
    print(f"Loaded environment from: {ENV_FILE}", flush=True)

    if not args.no_workspace_init:
        init_workspace()

    if not args.skip_install:
        print("Ensuring Python dependencies (../core[discord] + ../ai-tools)...", flush=True)
        run_pip_install(quiet=args.quiet_pip)

    print("Validating config/config.json + environment...", flush=True)
    validate_config()

    if args.validate_only:
        print("validate-only: OK (gateway not started).", flush=True)
        return

    print("Starting Mia DevOps gateway (Ctrl+C to stop)...", flush=True)
    run_gateway()


if __name__ == "__main__":
    main()
