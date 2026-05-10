"""
Phân tích cấu trúc đa ngôn ngữ (Tree-sitter) + Python (ast).
Hỗ trợ: JavaScript/JSX, TypeScript/TSX, Java, Go, HTML, CSS; Python qua code_static_python.
Vue: trích khối <script> đầu tiên rồi parse như TS.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Callable

_log = logging.getLogger(__name__)

EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".vue": "vue",
}


def _node_text(node: Any, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _field_name(node: Any, src: bytes) -> str | None:
    n = node.child_by_field_name("name")
    if n is None:
        return None
    t = _node_text(n, src).strip()
    return t or None


def _line(node: Any) -> int:
    return int(node.start_point[0]) + 1


@lru_cache(maxsize=16)
def _language(lang_id: str):
    try:
        from tree_sitter import Language
    except ImportError:
        return None

    try:
        if lang_id == "javascript":
            import tree_sitter_javascript as m

            return Language(m.language())
        if lang_id == "typescript":
            import tree_sitter_typescript as m

            return Language(m.language_typescript())
        if lang_id == "tsx":
            import tree_sitter_typescript as m

            return Language(m.language_tsx())
        if lang_id == "java":
            import tree_sitter_java as m

            return Language(m.language())
        if lang_id == "go":
            import tree_sitter_go as m

            return Language(m.language())
        if lang_id == "html":
            import tree_sitter_html as m

            return Language(m.language())
        if lang_id == "css":
            import tree_sitter_css as m

            return Language(m.language())
    except ImportError as e:
        _log.debug("tree-sitter language %s unavailable: %s", lang_id, e)
        return None
    return None


@lru_cache(maxsize=16)
def _parser(lang_id: str):
    try:
        from tree_sitter import Parser
    except ImportError:
        return None

    lang = _language(lang_id)
    if lang is None:
        return None
    p = Parser()
    p.language = lang
    return p


def _extract_ts_family(root: Any, src: bytes, lang_id: str) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    defined_short: set[str] = set()
    raw_calls: list[tuple[str, str]] = []

    def callee_from_call(node: Any) -> str | None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return None
        if fn.type == "identifier":
            return _node_text(fn, src).strip()
        if fn.type == "member_expression":
            prop = fn.child_by_field_name("property")
            if prop:
                return _node_text(prop, src).strip()
        return None

    def record_calls_inside(scope_qual: str, body_node: Any | None) -> None:
        if body_node is None:
            return
        stack_nodes = [body_node]
        while stack_nodes:
            n = stack_nodes.pop()
            if n.type == "call_expression":
                ce = callee_from_call(n)
                if ce:
                    raw_calls.append((scope_qual, ce))
            stack_nodes.extend(n.named_children)

    scope_stack: list[str] = []

    def walk(node: Any) -> None:
        t = node.type

        if t == "class_declaration":
            nm = _field_name(node, src)
            if nm:
                qual = ".".join(scope_stack + [nm])
                symbols.append({"qualname": qual, "kind": "class", "lineno": _line(node), "end_lineno": _line(node)})
                defined_short.add(nm.split(".")[-1])
                scope_stack.append(nm)
                for c in node.named_children:
                    walk(c)
                scope_stack.pop()
            else:
                for c in node.named_children:
                    walk(c)
            return

        if t == "interface_declaration" and lang_id != "javascript":
            nm = _field_name(node, src)
            if nm:
                qual = ".".join(scope_stack + [nm])
                symbols.append({"qualname": qual, "kind": "interface", "lineno": _line(node), "end_lineno": _line(node)})
                defined_short.add(nm)
            for c in node.named_children:
                walk(c)
            return

        if t == "function_declaration":
            nm = _field_name(node, src)
            body = node.child_by_field_name("body")
            if nm:
                qual = ".".join(scope_stack + [nm])
                symbols.append({"qualname": qual, "kind": "function", "lineno": _line(node), "end_lineno": _line(node)})
                defined_short.add(nm.split(".")[-1])
                if body:
                    record_calls_inside(qual, body)
            if body:
                walk(body)
            else:
                for c in node.named_children:
                    walk(c)
            return

        if t == "method_definition":
            nm = _field_name(node, src)
            body = node.child_by_field_name("body")
            if nm:
                qual = ".".join(scope_stack + [nm])
                symbols.append({"qualname": qual, "kind": "function", "lineno": _line(node), "end_lineno": _line(node)})
                defined_short.add(nm)
                if body:
                    record_calls_inside(qual, body)
                    walk(body)
                return
            for c in node.named_children:
                walk(c)
            return

        if t == "lexical_declaration" or t == "variable_declaration":
            for c in node.named_children:
                if c.type != "variable_declarator":
                    continue
                vn = c.child_by_field_name("name")
                val = c.child_by_field_name("value")
                if vn is None or val is None:
                    continue
                vname = _node_text(vn, src).strip()
                if val.type in ("arrow_function", "function_expression"):
                    qual = ".".join(scope_stack + [vname]) if vname else vname
                    if qual:
                        symbols.append(
                            {"qualname": qual, "kind": "function", "lineno": _line(val), "end_lineno": _line(val)}
                        )
                        defined_short.add(vname)
                        body = val.child_by_field_name("body")
                        record_calls_inside(qual, body)
                        if body:
                            walk(body)
            for c in node.named_children:
                walk(c)
            return

        for c in node.named_children:
            walk(c)

    walk(root)

    qual_by_short: dict[str, str] = {}
    for s in symbols:
        q = str(s["qualname"])
        qual_by_short[q.split(".")[-1]] = q

    internal_calls: list[tuple[str, str]] = []
    for caller_q, callee_short in raw_calls:
        if callee_short in defined_short and callee_short in qual_by_short:
            internal_calls.append((caller_q, qual_by_short[callee_short]))

    return {"symbols": symbols, "calls": internal_calls, "parse_ok": True, "language": lang_id}


def _extract_java(root: Any, src: bytes) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    scope_stack: list[str] = []

    def walk(node: Any) -> None:
        t = node.type
        if t == "class_declaration":
            nm = _field_name(node, src)
            if nm:
                symbols.append({"qualname": nm, "kind": "class", "lineno": _line(node), "end_lineno": _line(node)})
                scope_stack.append(nm)
                for c in node.named_children:
                    walk(c)
                scope_stack.pop()
            else:
                for c in node.named_children:
                    walk(c)
            return
        if t == "interface_declaration":
            nm = _field_name(node, src)
            if nm:
                symbols.append({"qualname": nm, "kind": "interface", "lineno": _line(node), "end_lineno": _line(node)})
                scope_stack.append(nm)
                for c in node.named_children:
                    walk(c)
                scope_stack.pop()
            else:
                for c in node.named_children:
                    walk(c)
            return
        if t == "method_declaration":
            nm = _field_name(node, src)
            if nm:
                qual = ".".join(scope_stack + [nm]) if scope_stack else nm
                symbols.append({"qualname": qual, "kind": "function", "lineno": _line(node), "end_lineno": _line(node)})
            for c in node.named_children:
                walk(c)
            return
        if t == "constructor_declaration":
            if scope_stack:
                qual = f"{scope_stack[-1]}.<init>"
                symbols.append({"qualname": qual, "kind": "constructor", "lineno": _line(node), "end_lineno": _line(node)})
            for c in node.named_children:
                walk(c)
            return
        for c in node.named_children:
            walk(c)

    walk(root)
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "java"}


def _extract_go(root: Any, src: bytes) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    pkg = ""

    def walk(node: Any) -> None:
        nonlocal pkg
        t = node.type
        if t == "package_clause":
            ident = node.child_by_field_name("name")
            if ident:
                pkg = _node_text(ident, src).strip()
            return
        if t == "function_declaration":
            nm = _field_name(node, src)
            if nm:
                qual = f"{pkg}.{nm}" if pkg else nm
                symbols.append({"qualname": qual, "kind": "function", "lineno": _line(node), "end_lineno": _line(node)})
            for c in node.named_children:
                walk(c)
            return
        if t == "method_declaration":
            recv = node.child_by_field_name("receiver")
            nm = _field_name(node, src)
            recv_s = ""
            if recv:
                recv_s = _node_text(recv, src).strip().replace("\n", " ")[:80]
            if nm:
                qual = f"({recv_s}).{nm}" if recv_s else nm
                qual = f"{pkg}.{qual}" if pkg else qual
                symbols.append({"qualname": qual, "kind": "function", "lineno": _line(node), "end_lineno": _line(node)})
            for c in node.named_children:
                walk(c)
            return
        if t == "type_declaration":
            for c in node.named_children:
                if c.type == "type_spec":
                    nm = _field_name(c, src)
                    if nm:
                        qual = f"{pkg}.{nm}" if pkg else nm
                        symbols.append({"qualname": qual, "kind": "type", "lineno": _line(c), "end_lineno": _line(c)})
                walk(c)
            return
        for c in node.named_children:
            walk(c)

    walk(root)
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "go"}


def _extract_html(root: Any, src: bytes) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    count = 0
    max_syms = 120

    def walk(node: Any, path: list[str]) -> None:
        nonlocal count
        if count >= max_syms:
            return
        if node.type == "element":
            tag = None
            for ch in node.named_children:
                if ch.type != "start_tag":
                    continue
                for cc in ch.named_children:
                    if cc.type == "tag_name":
                        tag = _node_text(cc, src).strip().lower()
                        break
            if tag:
                np = path + [tag]
                qual = "/".join(np[-6:])
                symbols.append({"qualname": f"{qual}@{_line(node)}", "kind": "element", "lineno": _line(node), "end_lineno": _line(node)})
                count += 1
                for ch in node.named_children:
                    walk(ch, np)
            else:
                for ch in node.named_children:
                    walk(ch, path)
            return
        for ch in node.named_children:
            walk(ch, path)

    walk(root, [])
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "html"}


def _extract_css(root: Any, src: bytes) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if node.type == "rule_set":
            sel = node.child_by_field_name("selectors")
            if sel:
                txt = _node_text(sel, src).strip()
                txt = re.sub(r"\s+", " ", txt)[:240]
                if txt:
                    symbols.append(
                        {
                            "qualname": f"{txt}@{_line(node)}",
                            "kind": "rule",
                            "lineno": _line(node),
                            "end_lineno": _line(node),
                        }
                    )
        for c in node.named_children:
            walk(c)

    walk(root)
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "css"}


def _vue_script_source(content: str) -> str | None:
    m = re.search(
        r"<script\b[^>]*>([\s\S]*?)</script>",
        content,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1).strip()


def analyze_with_treesitter(path: str, content: str, lang_id: str) -> dict[str, Any]:
    if lang_id == "vue":
        inner = _vue_script_source(content)
        if not inner:
            return {"symbols": [], "calls": [], "parse_ok": False, "reason": "vue_no_script"}
        path_virt = path + ".__script__.ts"
        return analyze_with_treesitter(path_virt, inner, "typescript")

    parser = _parser(lang_id)
    if parser is None:
        return {"symbols": [], "calls": [], "parse_ok": False, "reason": "treesitter_unavailable"}

    src_b = content.encode("utf-8")
    tree = parser.parse(src_b)
    root = tree.root_node
    if root.has_error and lang_id in ("javascript", "typescript", "tsx"):
        _log.debug("parse has_error %s %s", path, lang_id)

    extractors: dict[str, Callable[[Any, bytes], dict[str, Any]]] = {
        "javascript": lambda r, s: _extract_ts_family(r, s, "javascript"),
        "typescript": lambda r, s: _extract_ts_family(r, s, "typescript"),
        "tsx": lambda r, s: _extract_ts_family(r, s, "tsx"),
        "java": _extract_java,
        "go": _extract_go,
        "html": _extract_html,
        "css": _extract_css,
    }
    fn = extractors.get(lang_id)
    if not fn:
        return {"symbols": [], "calls": [], "parse_ok": False, "reason": "no_extractor"}
    out = fn(root, src_b)
    out["language"] = lang_id
    return out


def analyze_code_file(path: str, content: str) -> dict[str, Any]:
    ext = ""
    if "." in path.rsplit("/", 1)[-1]:
        ext = "." + path.rsplit(".", 1)[-1].lower()
    lang = EXT_TO_LANG.get(ext)
    if lang == "python":
        from second_brain.code_static_python import analyze_python_source

        return analyze_python_source(path, content)
    if lang:
        return analyze_with_treesitter(path, content, lang)
    return {"symbols": [], "calls": [], "parse_ok": False, "reason": "unsupported_ext", "extension": ext}
