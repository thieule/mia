"""Unit tests for linux_deploy MCP host allowlist helpers."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_linux_deploy_module():
    os.environ.setdefault("AI_TOOL_SECRET", "unit-test-secret-for-linux-deploy")
    path = ROOT / "servers" / "linux_deploy" / "server.py"
    spec = importlib.util.spec_from_file_location("linux_deploy_server_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ld():
    return _load_linux_deploy_module()


def test_allowed_hosts_parses_csv(ld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUX_DEPLOY_ALLOWED_HOSTS", " Foo.com , 10.0.0.1 ")
    assert ld._allowed_hosts() == frozenset({"foo.com", "10.0.0.1"})


def test_hostname_from_target_user_at_host(ld) -> None:
    assert ld._hostname_from_target("deploy@staging.example") == "staging.example"


def test_normalize_ssh_target_requires_default_user(ld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINUX_DEPLOY_DEFAULT_USER", raising=False)
    with pytest.raises(ValueError, match="LINUX_DEPLOY_DEFAULT_USER"):
        ld._normalize_ssh_target("only-hostname")


def test_normalize_ssh_target_with_default_user(ld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUX_DEPLOY_DEFAULT_USER", "deploy")
    assert ld._normalize_ssh_target("srv") == "deploy@srv"


def test_ensure_allowed_rejects_unknown(ld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUX_DEPLOY_ALLOWED_HOSTS", "good.example")
    with pytest.raises(RuntimeError, match="not in LINUX_DEPLOY_ALLOWED_HOSTS"):
        ld._ensure_allowed("deploy@evil.example")


def test_ensure_allowed_empty_list(ld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINUX_DEPLOY_ALLOWED_HOSTS", raising=False)
    with pytest.raises(RuntimeError, match="LINUX_DEPLOY_ALLOWED_HOSTS is empty"):
        ld._ensure_allowed("deploy@any.example")
