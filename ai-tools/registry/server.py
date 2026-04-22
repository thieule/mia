"""Registry MCP server — always-on tool discovery for mia.

Tools exposed:
  find_tools(task)     Search the catalog by task description. Returns relevant tools.
  list_all_tools()     Return the full tool catalog.

The agent calls find_tools() first to identify which specific tools to use,
then calls those tools directly. This avoids loading all tool schemas in every
prompt turn, saving tokens on large tool sets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from shared.auth import validate_startup_secret  # noqa: E402

validate_startup_secret()

mcp = FastMCP("registry")

_CATALOG_PATH = Path(__file__).parent / "catalog.json"
_catalog: list[dict] = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


@mcp.tool()
def find_tools(task: str) -> str:
    """Find relevant tools for a given task description.

    Search the tool catalog by matching keywords in the task against tool
    names, descriptions, and tags. Returns a ranked list of matching tools
    with their descriptions so the agent knows what to call next.

    Args:
        task: Natural language description of what you need to do,
              e.g. 'search for a Jira bug in the auth service'.
    """
    task_lower = task.lower()
    scored: list[tuple[int, dict]] = []
    for entry in _catalog:
        score = 0
        if any(kw in task_lower for kw in entry.get("tags", [])):
            score += 2
        if any(word in entry["description"].lower() for word in task_lower.split()):
            score += 1
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return "No matching tools found. Use list_all_tools() to see everything available."

    lines = ["Relevant tools for your task:\n"]
    for _, entry in scored:
        lines.append(f"  {entry['name']} ({entry['server']})")
        lines.append(f"    {entry['description']}\n")
    return "\n".join(lines)


@mcp.tool()
def list_all_tools() -> str:
    """List all tools registered in the a-tools catalog with their descriptions.

    Use this when you are unsure which tool to call, or to get a full
    overview of what capabilities are available.
    """
    lines = ["All available mia tools:\n"]
    current_server = None
    for entry in _catalog:
        if entry["server"] != current_server:
            current_server = entry["server"]
            lines.append(f"[{current_server}]")
        lines.append(f"  {entry['name']}")
        lines.append(f"    {entry['description']}\n")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
