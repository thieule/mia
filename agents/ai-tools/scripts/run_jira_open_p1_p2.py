#!/usr/bin/env python3
"""One-shot Jira query: unresolved bugs with priority P1 or P2 (same client as mcp-atlassian).

Requires env (same as flo.config.json passes to the Atlassian MCP):
  JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN

Optional:
  FLO_TOOL_SECRET — not used for Jira API; only needed when starting launchers/atlassian.py

Usage (from ai-tools root, after pip install -e .):

  py -3.12 scripts/run_jira_open_p1_p2.py

Adjust JQL below if your site names priorities differently (e.g. Highest/High).
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    missing = [k for k in ("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN") if not (os.environ.get(k) or "").strip()]
    if missing:
        print("Missing required environment variables:", ", ".join(missing), file=sys.stderr)
        print("Set them in your shell (or load from your secrets) and re-run.", file=sys.stderr)
        return 2

    # Unresolved + P1/P2 — edit if your Jira uses different priority names
    jql = 'resolution is EMPTY AND type = Bug AND priority in ("P1", "P2")'

    from mcp_atlassian.jira import JiraFetcher

    fetcher = JiraFetcher()
    result = fetcher.search_issues(jql, fields="summary,status,priority,assignee", limit=50)

    print(f"Total matching (reported by Jira): {result.total}")
    print(f"Returned this page: {len(result.issues)} issue(s)\n")
    for issue in result.issues:
        pri = getattr(issue.fields.priority, "name", None) if issue.fields and issue.fields.priority else None
        st = getattr(issue.fields.status, "name", None) if issue.fields and issue.fields.status else None
        summ = (issue.fields.summary if issue.fields else None) or ""
        print(f"  {issue.key}  [{pri}]  [{st}]  {summ}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
