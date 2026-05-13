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


def _java_modifiers_node(decl_node: Any) -> Any | None:
    for ch in decl_node.named_children:
        if ch.type == "modifiers":
            return ch
    return None


def _java_first_string_literal(node: Any, src: bytes) -> str | None:
    stack = list(node.named_children)
    while stack:
        n = stack.pop()
        if n.type == "string_literal":
            raw = _node_text(n, src).strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                return raw[1:-1]
            return raw
        stack.extend(n.named_children)
    return None


def _java_annotation_pairs(modifiers_node: Any | None, src: bytes) -> list[tuple[str, str | None]]:
    """(tên annotation đơn giản hoặc FQCN, chuỗi literal đầu tiên trong ngoặc nếu có)."""
    out: list[tuple[str, str | None]] = []
    if modifiers_node is None:
        return out
    for ch in modifiers_node.named_children:
        if ch.type == "marker_annotation":
            nm = ch.child_by_field_name("name")
            if nm:
                out.append((_node_text(nm, src).strip(), None))
        elif ch.type == "annotation":
            nm = ch.child_by_field_name("name")
            name = _node_text(nm, src).strip() if nm else ""
            out.append((name, _java_first_string_literal(ch, src)))
    return out


def _java_short_name(ann: str) -> str:
    return ann.split(".")[-1]


def _java_http_from_mapping(short: str) -> str | None:
    return {
        "GetMapping": "GET",
        "PostMapping": "POST",
        "PutMapping": "PUT",
        "DeleteMapping": "DELETE",
        "PatchMapping": "PATCH",
    }.get(short)


def _join_http_paths(prefix: str, sub: str) -> str:
    p = (prefix or "").strip()
    s = (sub or "").strip()
    if not p:
        return s or "/"
    if not s:
        return p if p.startswith("/") else "/" + p
    if p.endswith("/") and s.startswith("/"):
        return p[:-1] + s
    if not p.endswith("/") and not s.startswith("/"):
        return p + "/" + s
    return p + s


def _ts_decorator_calls(node: Any, src: bytes) -> list[tuple[str, str | None]]:
    """Các decorator dạng @Name hoặc @Name('arg') trên node class/method."""
    out: list[tuple[str, str | None]] = []
    for ch in node.children:
        if ch.type != "decorator":
            continue
        expr = ch.named_children[0] if ch.named_children else None
        if expr is None:
            continue
        if expr.type == "call_expression":
            fn = expr.child_by_field_name("function")
            args = expr.child_by_field_name("arguments")
            name: str | None = None
            if fn and fn.type == "identifier":
                name = _node_text(fn, src).strip()
            elif fn and fn.type == "member_expression":
                prop = fn.child_by_field_name("property")
                if prop:
                    name = _node_text(prop, src).strip()
            first_str: str | None = None
            if args:
                first_str = _java_first_string_literal(args, src)
            if name:
                out.append((name, first_str))
        elif expr.type == "identifier":
            out.append((_node_text(expr, src).strip(), None))
    return out


def _ts_http_from_decorator(name: str) -> str | None:
    n = name.lower()
    if n == "get":
        return "GET"
    if n == "post":
        return "POST"
    if n == "put":
        return "PUT"
    if n == "delete":
        return "DELETE"
    if n == "patch":
        return "PATCH"
    return None


def _semantic_io_edges_from_lines(
    path: str,
    content: str,
    symbols: list[dict[str, Any]],
    lang: str,
) -> list[dict[str, Any]]:
    """
    Heuristic I/O: JDBC/JPA, Kafka, HTTP client — gán vào hàm chứa dòng khớp.
    """
    funcs = [s for s in symbols if s.get("kind") == "function" and s.get("qualname")]
    if not funcs:
        return []
    lines = content.splitlines()
    edges: list[dict[str, Any]] = []

    def owner_fn(line_no: int) -> str | None:
        candidates = [s for s in funcs if int(s.get("lineno") or 0) <= line_no]
        if not candidates:
            return None
        return str(max(candidates, key=lambda s: int(s.get("lineno") or 0))["qualname"])

    patterns: list[tuple[str, str, str]] = []
    if lang == "java":
        patterns = [
            (r"\bjdbcTemplate\s*\.\s*(?:query|update|execute)\s*\(", "READS_FROM", "jdbc"),
            (r"\b(\w+)\.(?:findBy|findAll|save|deleteBy|countBy)\w*\s*\(", "READS_FROM", "jpa_repository"),
            (r"\bKafkaTemplate\s*<[^>]+>\s*\)?\s*\.\s*send\s*\(", "EMITS_EVENT", "kafka_template"),
            (r"\bkafkaTemplate\s*\.\s*send\s*\(", "EMITS_EVENT", "kafka_template"),
            (r"\bRestTemplate\s*\.\s*(?:getForObject|postForObject|exchange|execute)\s*\(", "INVOKES_EXTERNAL", "rest_template"),
            (r"\bWebClient\s*\.\s*builder\s*\(", "INVOKES_EXTERNAL", "webclient"),
            (r"\bHttpClient\s*\.\s*new", "INVOKES_EXTERNAL", "http_client"),
        ]
    elif lang in ("typescript", "tsx", "javascript"):
        patterns = [
            (r"\bfetch\s*\(\s*[`\"']https?://", "INVOKES_EXTERNAL", "fetch"),
            (r"\baxios\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*[`\"']https?://", "INVOKES_EXTERNAL", "axios"),
            (r"\.(?:produce|send)\s*\(\s*['\"]", "EMITS_EVENT", "kafka_producer_guess"),
            (r"\bprisma\s*\.\s*\w+\s*\.\s*(?:findMany|findFirst|create|update|delete|upsert)\s*\(", "READS_FROM", "prisma"),
        ]
    elif lang == "python":
        patterns = [
            (r"\bsession\s*\.\s*(?:execute|scalar|scalars|query)\s*\(", "READS_FROM", "sqlalchemy_session"),
            (r"\bconnection\s*\.\s*(?:execute|cursor)\s*\(", "READS_FROM", "db_connection"),
            (r"\bcursor\s*\.\s*execute\s*\(", "READS_FROM", "db_cursor"),
            (r"\brequests\.(?:get|post|put|delete|patch)\s*\(\s*['\"]https?://", "INVOKES_EXTERNAL", "requests"),
            (r"\bhttpx\.(?:get|post|put|delete|patch)\s*\(\s*['\"]https?://", "INVOKES_EXTERNAL", "httpx"),
            (r"\bclient\s*\.\s*(?:get|post|put|delete)\s*\(\s*['\"]https?://", "INVOKES_EXTERNAL", "http_client"),
            (r"\bKafkaProducer\s*\(", "EMITS_EVENT", "kafka_producer"),
            (r"\bproducer\s*\.\s*send\s*\(", "EMITS_EVENT", "kafka_send"),
        ]
    elif lang == "go":
        patterns = [
            (r"\bhttp\.(?:Get|Post|Do)\s*\(", "INVOKES_EXTERNAL", "net_http"),
            (r"\bdb\s*\.\s*(?:Query|QueryRow|Exec)\s*\(", "READS_FROM", "database_sql"),
        ]

    for i, line in enumerate(lines, start=1):
        for pat, rel, hint in patterns:
            if re.search(pat, line, flags=re.IGNORECASE):
                qn = owner_fn(i)
                if qn:
                    edges.append(
                        {
                            "function": qn,
                            "rel": rel,
                            "target": f"{hint}@{path}:{i}",
                            "lineno": i,
                        }
                    )
                break
    return edges


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


def _extract_ts_family(root: Any, src: bytes, lang_id: str, file_path: str = "") -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    defined_short: set[str] = set()
    raw_calls: list[tuple[str, str]] = []
    semantic: dict[str, Any] = {
        "controllers": [],
        "endpoints": [],
        "decorators": [],
        "field_constraints": [],
        "dto_schemas": [],
        "accepts_bindings": [],
        "io_edges": [],
    }
    nest_class_prefix: dict[str, str] = {}
    nest_controller_classes: set[str] = set()
    _decor_cap = 240

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
                for dn, arg in _ts_decorator_calls(node, src):
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": dn, "target": qual, "lineno": _line(node), "target_kind": "class"}
                        )
                    if dn == "Controller":
                        nest_controller_classes.add(qual)
                        nest_class_prefix[qual] = (arg or "").strip()
                        semantic["controllers"].append({"qualname": qual, "lineno": _line(node)})
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
                scope_stack.append(nm)
                for c in node.named_children:
                    walk(c)
                scope_stack.pop()
            else:
                for c in node.named_children:
                    walk(c)
            return

        if t == "property_signature":
            if scope_stack:
                dto_qual = ".".join(scope_stack)
                field_nm: str | None = None
                for c in node.named_children:
                    if c.type in ("property_identifier", "private_property_identifier", "identifier"):
                        field_nm = _node_text(c, src).strip()
                        break
                for dn, arg in _ts_decorator_calls(node, src):
                    if dn in ("Min", "Max", "IsEmail", "IsOptional", "ValidateNested", "IsInt", "IsString", "IsBoolean"):
                        semantic["field_constraints"].append(
                            {
                                "dto": dto_qual,
                                "field": field_nm or "?",
                                "constraint": dn,
                                "arg": arg,
                                "lineno": _line(node),
                            }
                        )
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {
                                "name": dn,
                                "target": f"{dto_qual}.{field_nm or '?'}",
                                "lineno": _line(node),
                                "target_kind": "field",
                            }
                        )
                if field_nm and any(
                    x.get("dto") == dto_qual and x.get("field") == field_nm for x in semantic["field_constraints"]
                ):
                    if not any(x.get("qualname") == dto_qual for x in semantic["dto_schemas"]):
                        semantic["dto_schemas"].append({"qualname": dto_qual, "lineno": _line(node)})
            for c in node.named_children:
                walk(c)
            return

        if t == "public_field_definition":
            if scope_stack:
                cls_qual = ".".join(scope_stack)
                field_nm = _field_name(node, src)
                for dn, arg in _ts_decorator_calls(node, src):
                    if dn in ("Min", "Max", "IsEmail", "IsOptional", "ValidateNested", "IsInt", "IsString"):
                        semantic["field_constraints"].append(
                            {
                                "dto": cls_qual,
                                "field": field_nm or "?",
                                "constraint": dn,
                                "arg": arg,
                                "lineno": _line(node),
                            }
                        )
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {
                                "name": dn,
                                "target": f"{cls_qual}.{field_nm or '?'}",
                                "lineno": _line(node),
                                "target_kind": "field",
                            }
                        )
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
                class_qual = ".".join(scope_stack) if scope_stack else ""
                for dn, arg in _ts_decorator_calls(node, src):
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": dn, "target": qual, "lineno": _line(node), "target_kind": "function"}
                        )
                    http = _ts_http_from_decorator(dn)
                    if http and class_qual in nest_controller_classes:
                        sub = (arg or "").strip()
                        full = _join_http_paths(nest_class_prefix.get(class_qual, ""), sub)
                        semantic["endpoints"].append(
                            {"method": http, "path": full, "handler": qual, "lineno": _line(node)}
                        )
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

    content = src.decode("utf-8", errors="replace")
    semantic["io_edges"].extend(_semantic_io_edges_from_lines(file_path, content, symbols, lang_id))

    return {"symbols": symbols, "calls": internal_calls, "parse_ok": True, "language": lang_id, "semantic": semantic}


def _extract_java(root: Any, src: bytes, file_path: str = "") -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    scope_stack: list[str] = []
    semantic: dict[str, Any] = {
        "controllers": [],
        "endpoints": [],
        "decorators": [],
        "field_constraints": [],
        "dto_schemas": [],
        "accepts_bindings": [],
        "io_edges": [],
    }
    java_controller_prefix: dict[str, str] = {}
    java_web_classes: set[str] = set()
    _decor_cap = 240

    def walk(node: Any) -> None:
        t = node.type
        if t == "class_declaration":
            nm = _field_name(node, src)
            if nm:
                symbols.append({"qualname": nm, "kind": "class", "lineno": _line(node), "end_lineno": _line(node)})
                cqual = ".".join(scope_stack + [nm])
                mods = _java_modifiers_node(node)
                pairs = _java_annotation_pairs(mods, src)
                prefix = ""
                is_web = False
                for fq, sarg in pairs:
                    sh = _java_short_name(fq)
                    if sh in ("RestController", "Controller"):
                        is_web = True
                    if sh == "RequestMapping" and sarg:
                        prefix = sarg
                if is_web:
                    java_web_classes.add(cqual)
                    java_controller_prefix[cqual] = prefix
                    semantic["controllers"].append({"qualname": cqual, "lineno": _line(node)})
                for fq, _ in pairs:
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": _java_short_name(fq), "target": cqual, "lineno": _line(node), "target_kind": "class"}
                        )
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
                cqual = ".".join(scope_stack + [nm])
                mods = _java_modifiers_node(node)
                for fq, _ in _java_annotation_pairs(mods, src):
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": _java_short_name(fq), "target": cqual, "lineno": _line(node), "target_kind": "interface"}
                        )
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
                class_key = ".".join(scope_stack) if scope_stack else ""
                mods = _java_modifiers_node(node)
                pairs = _java_annotation_pairs(mods, src)
                for fq, sarg in pairs:
                    sh = _java_short_name(fq)
                    if len(semantic["decorators"]) < _decor_cap:
                        semantic["decorators"].append(
                            {"name": sh, "target": qual, "lineno": _line(node), "target_kind": "function"}
                        )
                    http = _java_http_from_mapping(sh)
                    if class_key in java_web_classes:
                        if http:
                            full = _join_http_paths(java_controller_prefix.get(class_key, ""), sarg or "")
                            semantic["endpoints"].append(
                                {"method": http, "path": full, "handler": qual, "lineno": _line(node)}
                            )
                        elif sh == "RequestMapping" and sarg:
                            full = _join_http_paths(java_controller_prefix.get(class_key, ""), sarg)
                            semantic["endpoints"].append(
                                {"method": "GET", "path": full, "handler": qual, "lineno": _line(node)}
                            )
                formal = node.child_by_field_name("parameters")
                if formal and class_key in java_web_classes:
                    for param in formal.named_children:
                        if param.type != "formal_parameter":
                            continue
                        pm = _java_modifiers_node(param)
                        ann_pairs = _java_annotation_pairs(pm, src)
                        has_body = any(_java_short_name(fq) == "RequestBody" for fq, _ in ann_pairs)
                        if not has_body:
                            continue
                        typ = param.child_by_field_name("type")
                        dto_name: str | None = None
                        if typ and typ.type == "type_identifier":
                            dto_name = _node_text(typ, src).strip()
                        elif typ and typ.type == "generic_type":
                            base = typ.child_by_field_name("type")
                            if base and base.type == "type_identifier":
                                dto_name = _node_text(base, src).strip()
                        if dto_name:
                            semantic["accepts_bindings"].append(
                                {"handler": qual, "dto": dto_name, "lineno": _line(param)}
                            )
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
        if t == "field_declaration" and scope_stack:
            dto_qual = ".".join(scope_stack)
            field_name: str | None = None
            for c in node.named_children:
                if c.type == "variable_declarator":
                    fn = c.child_by_field_name("name")
                    if fn:
                        field_name = _node_text(fn, src).strip()
                        break
            mods = _java_modifiers_node(node)
            for fq, sarg in _java_annotation_pairs(mods, src):
                sh = _java_short_name(fq)
                if sh in ("Min", "Max", "NotNull", "Size", "Email", "Pattern", "DecimalMin", "DecimalMax", "Positive", "Negative"):
                    semantic["field_constraints"].append(
                        {
                            "dto": dto_qual,
                            "field": field_name or "?",
                            "constraint": sh,
                            "arg": sarg,
                            "lineno": _line(node),
                        }
                    )
            if field_name and any(
                x.get("dto") == dto_qual and x.get("field") == field_name for x in semantic["field_constraints"]
            ):
                if not any(x.get("qualname") == dto_qual for x in semantic["dto_schemas"]):
                    semantic["dto_schemas"].append({"qualname": dto_qual, "lineno": _line(node)})
            for c in node.named_children:
                walk(c)
            return
        for c in node.named_children:
            walk(c)

    walk(root)
    content = src.decode("utf-8", errors="replace")
    semantic["io_edges"].extend(_semantic_io_edges_from_lines(file_path, content, symbols, "java"))
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "java", "semantic": semantic}


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
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "go", "semantic": {}}


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
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "html", "semantic": {}}


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
    return {"symbols": symbols, "calls": [], "parse_ok": True, "language": "css", "semantic": {}}


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
        "javascript": lambda r, s: _extract_ts_family(r, s, "javascript", path),
        "typescript": lambda r, s: _extract_ts_family(r, s, "typescript", path),
        "tsx": lambda r, s: _extract_ts_family(r, s, "tsx", path),
        "java": lambda r, s: _extract_java(r, s, path),
        "go": _extract_go,
        "html": _extract_html,
        "css": _extract_css,
    }
    fn = extractors.get(lang_id)
    if not fn:
        return {"symbols": [], "calls": [], "parse_ok": False, "reason": "no_extractor"}
    out = fn(root, src_b)
    out.setdefault("semantic", {})
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
