"""Phân tích tĩnh Python (stdlib ast) — function/class cấp module và method cấp một (DEFINES + CALLS nội bộ)."""

from __future__ import annotations

import ast
import re
from typing import Any

from second_brain.code_static_multilang import _join_http_paths, _semantic_io_edges_from_lines


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


_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def _first_str_arg(call: ast.Call) -> str | None:
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    for kw in call.keywords:
        if kw.arg in ("path", "url") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _router_prefix_from_source(source: str, router_name: str) -> str:
    pat = rf"{re.escape(router_name)}\s*=\s*APIRouter\s*\(([^)]*)\)"
    m = re.search(pat, source, flags=re.DOTALL)
    if not m:
        return ""
    inner = m.group(1)
    pm = re.search(r"prefix\s*=\s*['\"]([^'\"]+)['\"]", inner)
    return pm.group(1).strip() if pm else ""


def _extract_python_semantic(path: str, source: str, tree: ast.Module, symbols: list[dict[str, Any]]) -> dict[str, Any]:
    semantic: dict[str, Any] = {
        "controllers": [],
        "endpoints": [],
        "decorators": [],
        "field_constraints": [],
        "dto_schemas": [],
        "accepts_bindings": [],
        "io_edges": [],
    }
    _decor_cap = 200

    def qual_class(cls: ast.ClassDef) -> str:
        return cls.name

    def qual_method(cls: ast.ClassDef, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        return f"{cls.name}.{fn.name}"

    def qual_mod_fn(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        return fn.name

    def route_from_decorator(dec: ast.expr) -> tuple[str, str] | None:
        if not isinstance(dec, ast.Call):
            return None
        f = dec.func
        if not isinstance(f, ast.Attribute):
            return None
        m = f.attr.lower()
        if m not in _HTTP_METHODS:
            return None
        path_s = _first_str_arg(dec)
        if path_s is None:
            return None
        return m.upper(), path_s

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cqual = qual_class(node)
            bases_ok = any(
                (isinstance(b, ast.Name) and b.id == "BaseModel")
                or (isinstance(b, ast.Attribute) and b.attr == "BaseModel")
                for b in node.bases
            )
            if bases_ok:
                semantic["dto_schemas"].append({"qualname": cqual, "lineno": node.lineno})
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and len(semantic["decorators"]) < _decor_cap:
                    semantic["decorators"].append(
                        {"name": dec.id, "target": cqual, "lineno": node.lineno, "target_kind": "class"}
                    )
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": dec.func.id, "target": cqual, "lineno": node.lineno, "target_kind": "class"}
                        )
            has_route_method = False
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                mq = qual_method(node, item)
                for dec in item.decorator_list:
                    r = route_from_decorator(dec)
                    if r:
                        has_route_method = True
                        method, subp = r
                        full = _join_http_paths("", subp)
                        semantic["endpoints"].append(
                            {"method": method, "path": full, "handler": mq, "lineno": item.lineno}
                        )
                    elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                        if len(semantic["decorators"]) < _decor_cap:
                            semantic["decorators"].append(
                                {"name": dec.func.id, "target": mq, "lineno": item.lineno, "target_kind": "function"}
                            )
                    elif isinstance(dec, ast.Name) and len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": dec.id, "target": mq, "lineno": item.lineno, "target_kind": "function"}
                        )
            if has_route_method:
                semantic["controllers"].append({"qualname": cqual, "lineno": node.lineno})

            for item in node.body:
                if not isinstance(item, ast.AnnAssign) or item.target is None:
                    continue
                if not isinstance(item.target, ast.Name):
                    continue
                field_nm = item.target.id
                ge = le = gt = lt = None
                if isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name):
                    if item.value.func.id != "Field":
                        continue
                    for kw in item.value.keywords:
                        if kw.arg in ("ge", "gt", "le", "lt", "min_length", "max_length") and isinstance(
                            kw.value, ast.Constant
                        ):
                            v = kw.value.value
                            if kw.arg == "ge":
                                ge = v
                            elif kw.arg == "le":
                                le = v
                            elif kw.arg == "gt":
                                gt = v
                            elif kw.arg == "lt":
                                lt = v
                    if ge is not None or le is not None or gt is not None or lt is not None:
                        parts = []
                        if ge is not None:
                            parts.append(f"ge={ge}")
                        if le is not None:
                            parts.append(f"le={le}")
                        if gt is not None:
                            parts.append(f"gt={gt}")
                        if lt is not None:
                            parts.append(f"lt={lt}")
                        semantic["field_constraints"].append(
                            {
                                "dto": cqual,
                                "field": field_nm,
                                "constraint": "Field",
                                "arg": ",".join(parts),
                                "lineno": item.lineno,
                            }
                        )
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Call):
                    fn = node.value.func
                    if isinstance(fn, ast.Name) and fn.id == "APIRouter":
                        rname = t.id
                        prefix = _router_prefix_from_source(source, rname)
                        ctrl = f"{path}::{rname}"
                        semantic["controllers"].append({"qualname": ctrl, "lineno": node.lineno, "router_var": rname})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            q = qual_mod_fn(node)
            has_route = False
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and route_from_decorator(dec):
                    has_route = True
                    break
            for dec in node.decorator_list:
                r = route_from_decorator(dec) if isinstance(dec, ast.Call) else None
                if r:
                    method, subp = r
                    rid: str | None = None
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        if isinstance(dec.func.value, ast.Name):
                            rid = dec.func.value.id
                    prefix = _router_prefix_from_source(source, rid) if rid else ""
                    full = _join_http_paths(prefix, subp)
                    semantic["endpoints"].append({"method": method, "path": full, "handler": q, "lineno": node.lineno})
                    ctrl_ref = f"{path}::{rid}" if rid else f"{path}::__app__"
                    if not any(c.get("qualname") == ctrl_ref for c in semantic["controllers"]):
                        semantic["controllers"].append({"qualname": ctrl_ref, "lineno": 1, "router_var": rid})
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": dec.func.id, "target": q, "lineno": node.lineno, "target_kind": "function"}
                        )
                elif isinstance(dec, ast.Name) and len(semantic["decorators"]) < _decor_cap:
                    semantic["decorators"].append(
                        {"name": dec.id, "target": q, "lineno": node.lineno, "target_kind": "function"}
                    )
            if has_route:
                for arg in node.args.args:
                    if arg.annotation is None:
                        continue
                    ann = arg.annotation
                    dto_name: str | None = None
                    if isinstance(ann, ast.Name):
                        dto_name = ann.id
                    elif isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
                        dto_name = ann.value.id
                    if dto_name:
                        semantic["accepts_bindings"].append(
                            {"handler": q, "dto": dto_name, "lineno": node.lineno}
                        )

    semantic["io_edges"] = _semantic_io_edges_from_lines(path, source, symbols, "python")
    return semantic


def analyze_python_source(path: str, source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {"symbols": [], "calls": [], "parse_ok": False, "language": "python", "semantic": {}}

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

    semantic = _extract_python_semantic(path, source, tree, symbols)

    internal_calls: list[tuple[str, str]] = []
    qual_by_short: dict[str, str] = {}
    for s in symbols:
        q = str(s["qualname"])
        qual_by_short[q.split(".")[-1]] = q

    for caller_q, callee_short in raw_calls:
        if callee_short in defined and callee_short in qual_by_short:
            internal_calls.append((caller_q, qual_by_short[callee_short]))

    return {"symbols": symbols, "calls": internal_calls, "parse_ok": True, "language": "python", "semantic": semantic}
