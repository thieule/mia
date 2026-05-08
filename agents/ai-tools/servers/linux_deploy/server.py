"""Linux deploy MCP — SSH and rsync to allowlisted servers only.

Requires on the gateway host: ``ssh`` and (for rsync) ``rsync`` on PATH.
Authentication: key-based SSH (``BatchMode=yes``) — no interactive passwords.

Environment:
  LINUX_DEPLOY_ALLOWED_HOSTS   Comma-separated hostnames or IPs (required for any remote call).
  LINUX_DEPLOY_DEFAULT_USER    Used when *host* has no ``user@`` prefix.
  LINUX_DEPLOY_IDENTITY_FILE   Optional ``-i`` path for ssh/rsync.
  LINUX_DEPLOY_STRICT_HOST_KEY_CHECKING  SSH option value (default ``accept-new``).
  LINUX_DEPLOY_SSH_PORT        Optional port (digits only).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from shared.auth import validate_startup_secret

validate_startup_secret()

mcp = FastMCP("linux_deploy")

_MAX_CAPTURE = 48_000


def _allowed_hosts() -> frozenset[str]:
    raw = os.environ.get("LINUX_DEPLOY_ALLOWED_HOSTS", "").strip()
    if not raw:
        return frozenset()
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return frozenset(parts)


def _hostname_from_target(user_host: str) -> str:
    """Return lowercase hostname/IP part from ``user@host`` or plain ``host``."""
    u = user_host.strip()
    if "@" in u:
        u = u.split("@", 1)[1]
    # Strip IPv6 bracket form [::1] — minimal support
    if u.startswith("[") and "]" in u:
        inner = u[1 : u.index("]")]
        return inner.lower()
    # Strip trailing :port if present (host:22) — not valid for IPv6 without brackets
    if ":" in u and not u.startswith("["):
        maybe_host, maybe_port = u.rsplit(":", 1)
        if maybe_port.isdigit():
            return maybe_host.lower()
    return u.lower()


def _normalize_ssh_target(host: str) -> str:
    """Return ``user@host`` suitable for ssh/rsync."""
    h = host.strip()
    if not h:
        raise ValueError("host must be non-empty.")
    if "\n" in h or "\x00" in h:
        raise ValueError("invalid host string.")
    if "@" in h:
        return h
    default_user = os.environ.get("LINUX_DEPLOY_DEFAULT_USER", "").strip()
    if not default_user:
        raise ValueError(
            "host must be user@host or set LINUX_DEPLOY_DEFAULT_USER in the gateway environment.",
        )
    return f"{default_user}@{h}"


def _ensure_allowed(user_host: str) -> None:
    allowed = _allowed_hosts()
    if not allowed:
        raise RuntimeError(
            "LINUX_DEPLOY_ALLOWED_HOSTS is empty — refusing all remote deploy calls.",
        )
    hn = _hostname_from_target(user_host)
    if hn not in allowed:
        raise RuntimeError(
            f"Host '{hn}' is not in LINUX_DEPLOY_ALLOWED_HOSTS.",
        )


def _strict_host_key_checking() -> str:
    v = os.environ.get("LINUX_DEPLOY_STRICT_HOST_KEY_CHECKING", "accept-new").strip()
    return v or "accept-new"


def _ssh_base_opts() -> list[str]:
    opts = [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=30",
        "-o",
        f"StrictHostKeyChecking={_strict_host_key_checking()}",
    ]
    port = os.environ.get("LINUX_DEPLOY_SSH_PORT", "").strip()
    if port:
        if not port.isdigit() or int(port) < 1 or int(port) > 65535:
            raise ValueError("LINUX_DEPLOY_SSH_PORT must be 1–65535.")
        opts.extend(["-o", f"Port={port}"])
    identity = os.environ.get("LINUX_DEPLOY_IDENTITY_FILE", "").strip()
    if identity:
        opts.extend(["-i", identity])
    return opts


def _truncate(out: str | None, limit: int = _MAX_CAPTURE) -> str:
    if not out:
        return ""
    if len(out) <= limit:
        return out
    return out[:limit] + f"\n… truncated ({len(out)} chars total)"


@mcp.tool()
def ssh_exec(host: str, remote_command: str, timeout_seconds: int = 300) -> str:
    """Run a single non-interactive shell command on a Linux host via SSH.

    Use for deploy steps: git pull, docker compose, systemctl, etc. Host must appear
    in LINUX_DEPLOY_ALLOWED_HOSTS. Requires passwordless/key-based SSH from the gateway.

    Args:
        host: Target ``user@hostname`` or ``hostname`` (with LINUX_DEPLOY_DEFAULT_USER set).
        remote_command: One remote shell command line (no NUL bytes).
        timeout_seconds: Hard cap for the SSH session (default 300).

    Returns:
        JSON with exit_code, stdout, stderr, success flag.
    """
    if "\x00" in remote_command:
        return json.dumps({"success": False, "error": "remote_command must not contain NUL."})
    target = _normalize_ssh_target(host)
    _ensure_allowed(target)
    if not shutil.which("ssh"):
        return json.dumps({"success": False, "error": "ssh binary not found on PATH."})

    ssh_cmd = ["ssh", *_ssh_base_opts(), target, remote_command]
    try:
        proc = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(timeout_seconds, 3600)),
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "success": False,
                "error": f"ssh timed out after {timeout_seconds}s",
                "host": target,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc), "host": target}, indent=2)

    return json.dumps(
        {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "host": target,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        },
        indent=2,
    )


@mcp.tool()
def rsync_upload(
    local_path: str,
    remote_dest: str,
    delete_extraneous: bool = False,
    dry_run: bool = False,
    timeout_seconds: int = 600,
) -> str:
    """Upload files to a Linux host using rsync over SSH.

    *remote_dest* must look like ``user@host:/absolute/path/``. The remote host part
    must be allowlisted. Requires ``rsync`` on the gateway PATH.

    Args:
        local_path: Local file or directory path (absolute recommended).
        remote_dest: ``user@host:/path`` rsync destination.
        delete_extraneous: If true, pass ``--delete`` (dangerous — mirrors deletes).
        dry_run: If true, ``--dry-run`` only.
        timeout_seconds: Max wall time (default 600).

    Returns:
        JSON with exit_code, stdout/stderr summary, success flag.
    """
    local_path = local_path.strip()
    remote_dest = remote_dest.strip()
    if not local_path or not remote_dest:
        return json.dumps({"success": False, "error": "local_path and remote_dest are required."})

    if ":" not in remote_dest:
        return json.dumps(
            {"success": False, "error": "remote_dest must be user@host:/path"},
            indent=2,
        )
    remote_spec, remote_path = remote_dest.split(":", 1)
    if not remote_path.startswith("/"):
        return json.dumps(
            {"success": False, "error": "remote path must be absolute (/...)."},
            indent=2,
        )

    target = _normalize_ssh_target(remote_spec)
    _ensure_allowed(target)
    full_remote = f"{target}:{remote_path}"

    if not shutil.which("rsync"):
        return json.dumps({"success": False, "error": "rsync binary not found on PATH."})

    ssh_part = "ssh " + " ".join(_ssh_base_opts())
    rsync_cmd = [
        "rsync",
        "-avz",
        "--compress-delay=1",
        "-e",
        ssh_part,
    ]
    if dry_run:
        rsync_cmd.append("--dry-run")
    if delete_extraneous:
        rsync_cmd.append("--delete")
    rsync_cmd.extend([local_path, full_remote])

    lp = Path(local_path).expanduser()
    if not lp.exists():
        return json.dumps({"success": False, "error": f"local_path does not exist: {lp}"})

    try:
        proc = subprocess.run(
            rsync_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(timeout_seconds, 7200)),
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"success": False, "error": f"rsync timed out after {timeout_seconds}s"},
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, indent=2)

    return json.dumps(
        {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "remote_dest": full_remote,
            "dry_run": dry_run,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        },
        indent=2,
    )


@mcp.tool()
def deploy_allowed_hosts() -> str:
    """List configured allowlisted hostnames (from LINUX_DEPLOY_ALLOWED_HOSTS).

    Does not connect remotely — safe to call to verify configuration.
    """
    hosts = sorted(_allowed_hosts())
    return json.dumps(
        {
            "allowed_hosts": hosts,
            "configured": bool(hosts),
            "hint": "Set LINUX_DEPLOY_ALLOWED_HOSTS on the gateway to enable ssh_exec/rsync_upload.",
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
