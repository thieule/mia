"""Phân tích tĩnh Python (stdlib ast) — function/class cấp module và method cấp một (DEFINES + CALLS nội bộ)."""

from __future__ import annotations

import ast
from typing import Any


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _collect_calls_from_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, owner_prefix: str) -> list[tuple[str, str]]:
    qual = f"{owner_prefix}.{fn.name}" if owner_prefix else fn.name
    out: list[tuple[str, str]] = []
    for sub in ast.walk(fn):
        if sub is fn:
            continue
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(sub, ast.Call):
            nm = _call_name(sub)
            if nm:
                out.append((qual, nm))
    return out


def analyze_python_source(path: str, source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {"symbols": [], "calls": [], "parse_ok": False}

    symbols: list[dict[str, Any]] = []
    raw_calls: list[tuple[str, str]] = []
    defined: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            q = node.name
            symbols.append(
                {
                    "qualname": q,
                    "kind": "class",
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", node.lineno) or node.lineno,
                }
            )
            defined.add(node.name)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mq = f"{node.name}.{item.name}"
                    symbols.append(
                        {
                            "qualname": mq,
                            "kind": "function",
                            "lineno": item.lineno,
                            "end_lineno": getattr(item, "end_lineno", item.lineno) or item.lineno,
                        }
                    )
                    defined.add(item.name)
                    raw_calls.extend(_collect_calls_from_function(item, node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                {
                    "qualname": node.name,
                    "kind": "function",
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", node.lineno) or node.lineno,
                }
            )
            defined.add(node.name)
            raw_calls.extend(_collect_calls_from_function(node, ""))

    internal_calls: list[tuple[str, str]] = []
    qual_by_short: dict[str, str] = {}
    for s in symbols:
        q = str(s["qualname"])
        qual_by_short[q.split(".")[-1]] = q

    for caller_q, callee_short in raw_calls:
        if callee_short in defined and callee_short in qual_by_short:
            internal_calls.append((caller_q, qual_by_short[callee_short]))

    return {"symbols": symbols, "calls": internal_calls, "parse_ok": True}
