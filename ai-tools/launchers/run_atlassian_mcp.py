"""Thin launcher for mcp-atlassian.

Spawned by mia as an MCP stdio server. Credentials are injected by mia
via the 'env' block in config/flo.config.json -- they never appear in agent context.

Running via this launcher (rather than the `mcp-atlassian` entry-point script directly)
ensures we always use the same Python interpreter that started mia, with no PATH
dependency on where pip installed the script.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure a-tools root is importable (for shared.auth)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.auth import validate_startup_secret  # noqa: E402

validate_startup_secret()

from mcp_atlassian import main  # noqa: E402

sys.exit(main() or 0)
