"""Ghi đồ thị Neo4j cho lớp ngữ nghĩa API / DTO / decorator / I/O (bổ sung DEFINES + CALLS)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from second_brain.neo4j_store import node_ref_slug
from second_brain.refs import node_ref


def _slug(s: str, max_len: int = 96) -> str:
    t = re.sub(r"[^a-zA-Z0-9_.-]", "_", s.strip())[:max_len]
    return t or "x"


def _ep_key(path: str, method: str, route: str, lineno: int) -> str:
    raw = f"{path}\0{method}\0{route}\0{lineno}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


def delete_semantic_for_codefile(
    *,
    project_id: int,
    fref: str,
    run_write_fn: Callable[..., None],
) -> None:
    """Xóa nút semantic gắn codefile_ref (trước khi xóa CodeFunction)."""
    run_write_fn(
        """
        MATCH (n)
        WHERE n.project_id = $project_id AND n.codefile_ref = $fref
          AND (
            n:CodeController OR n:CodeEndpoint OR n:CodeDTO OR n:CodeField
            OR n:BusinessRule OR n:CodeDecorator
            OR n:DatabaseTable OR n:KafkaTopic OR n:ExternalAPI
          )
        DETACH DELETE n
        """,
        {"project_id": project_id, "fref": fref},
    )


def merge_semantic_for_codefile(
    *,
    project_id: int,
    fref: str,
    path: str,
    semantic: dict[str, Any] | None,
    func_refs: dict[str, str],
    ts: str,
    run_write_fn: Callable[..., None],
) -> int:
    """
    MERGE CodeController / CodeEndpoint / … và các cạnh tới CodeFunction.
    Trả về số lần MERGE (e)-[:MAPS_TO]->(fn) thực hiện.
    """
    if not semantic:
        return 0
    maps_ok = 0
    ctrl_by_qual: dict[str, str] = {}
    ep_ref_by_handler: dict[str, str] = {}

    for ctrl in semantic.get("controllers") or []:
        qual = str(ctrl.get("qualname") or "").strip()
        if not qual:
            continue
        cref = node_ref_slug(project_id, "codecontroller", f"{path}::{_slug(qual, 80)}")
        ctrl_by_qual[qual] = cref
        run_write_fn(
            """
            MATCH (f:CodeFile {ref: $fref})
            MERGE (c:CodeController {ref: $cref})
            SET c.project_id = $project_id, c.codefile_ref = $fref, c.path = $path,
                c.qualname = $qual, c.ingested_at = $ts
            MERGE (f)-[:HAS_CONTROLLER]->(c)
            """,
            {
                "fref": fref,
                "cref": cref,
                "project_id": project_id,
                "path": path[:2048],
                "qual": qual[:512],
                "ts": ts,
            },
        )

    has_ep = bool(semantic.get("endpoints") or semantic.get("accepts_bindings"))
    if has_ep and not ctrl_by_qual:
        cref = node_ref_slug(project_id, "codecontroller", f"{path}::__default__")
        ctrl_by_qual["__default__"] = cref
        run_write_fn(
            """
            MATCH (f:CodeFile {ref: $fref})
            MERGE (c:CodeController {ref: $cref})
            SET c.project_id = $project_id, c.codefile_ref = $fref, c.path = $path,
                c.qualname = '__default__', c.ingested_at = $ts
            MERGE (f)-[:HAS_CONTROLLER]->(c)
            """,
            {"fref": fref, "cref": cref, "project_id": project_id, "path": path[:2048], "ts": ts},
        )

    def _ctrl_for_handler(handler: str) -> str | None:
        if "." in handler:
            cls_or_mod = handler.rsplit(".", 1)[0]
            if cls_or_mod in ctrl_by_qual:
                return ctrl_by_qual[cls_or_mod]
        for cq, cr in ctrl_by_qual.items():
            if cq != "__default__" and (handler == cq or handler.startswith(cq + ".")):
                return cr
        if "." not in handler:
            scoped = [(q, r) for q, r in ctrl_by_qual.items() if "::" in q]
            if len(scoped) == 1:
                return scoped[0][1]
        return ctrl_by_qual.get("__default__") or (next(iter(ctrl_by_qual.values())) if ctrl_by_qual else None)

    for ep in semantic.get("endpoints") or []:
        method = str(ep.get("method") or "GET").upper()[:16]
        route = str(ep.get("path") or "/")[:512]
        handler = str(ep.get("handler") or "").strip()
        ln = int(ep.get("lineno") or 0)
        if not handler:
            continue
        ek = _ep_key(path, method, route, ln)
        eref = node_ref_slug(project_id, "codeendpoint", f"{path}::{ek}")
        fn_ref = func_refs.get(handler)
        ctrl_ref = _ctrl_for_handler(handler)
        if not ctrl_ref:
            continue
        run_write_fn(
            """
            MATCH (c:CodeController {ref: $cref})
            MERGE (e:CodeEndpoint {ref: $eref})
            SET e.project_id = $project_id, e.codefile_ref = $fref, e.path = $path,
                e.http_method = $method, e.route = $route, e.handler_qualname = $handler,
                e.lineno = $ln, e.ingested_at = $ts
            MERGE (c)-[:EXPOSES]->(e)
            """,
            {
                "cref": ctrl_ref,
                "eref": eref,
                "project_id": project_id,
                "fref": fref,
                "path": path[:2048],
                "method": method,
                "route": route,
                "handler": handler[:512],
                "ln": ln,
                "ts": ts,
            },
        )
        ep_ref_by_handler[handler] = eref

        if fn_ref:
            run_write_fn(
                """
                MATCH (e:CodeEndpoint {ref: $eref}), (fn:CodeFunction {ref: $fnref})
                WHERE e.project_id = $project_id AND fn.project_id = $project_id
                MERGE (e)-[:MAPS_TO]->(fn)
                """,
                {"eref": eref, "fnref": fn_ref, "project_id": project_id},
            )
            maps_ok += 1

    dto_refs: dict[str, str] = {}
    for ds in semantic.get("dto_schemas") or []:
        qn = str(ds.get("qualname") or "").strip()
        if not qn:
            continue
        dref = node_ref_slug(project_id, "codedto", f"{path}::{_slug(qn, 64)}")
        dto_refs[qn] = dref
        run_write_fn(
            """
            MATCH (f:CodeFile {ref: $fref})
            MERGE (d:CodeDTO {ref: $dref})
            SET d.project_id = $project_id, d.codefile_ref = $fref, d.path = $path,
                d.qualname = $qn, d.lineno = $ln, d.ingested_at = $ts
            MERGE (f)-[:DECLARES_DTO]->(d)
            """,
            {
                "fref": fref,
                "dref": dref,
                "project_id": project_id,
                "path": path[:2048],
                "qn": qn[:512],
                "ln": int(ds.get("lineno") or 0),
                "ts": ts,
            },
        )

    for fc in semantic.get("field_constraints") or []:
        dto = str(fc.get("dto") or "").strip()
        field = str(fc.get("field") or "").strip()
        cons = str(fc.get("constraint") or "rule").strip()
        arg = str(fc.get("arg") or fc.get("args") or "")[:240]
        if not dto or not field:
            continue
        dref = dto_refs.get(dto)
        if not dref:
            dref = node_ref_slug(project_id, "codedto", f"{path}::{_slug(dto, 64)}")
            dto_refs[dto] = dref
            run_write_fn(
                """
                MATCH (f:CodeFile {ref: $fref})
                MERGE (d:CodeDTO {ref: $dref})
                SET d.project_id = $project_id, d.codefile_ref = $fref, d.path = $path,
                    d.qualname = $qn, d.ingested_at = $ts
                MERGE (f)-[:DECLARES_DTO]->(d)
                """,
                {"fref": fref, "dref": dref, "project_id": project_id, "path": path[:2048], "qn": dto[:512], "ts": ts},
            )
        frefield = node_ref_slug(project_id, "codefield", f"{path}::{_slug(dto, 40)}::{_slug(field, 40)}")
        bref = node_ref_slug(project_id, "businessrule", f"{path}::{_slug(dto, 32)}.{_slug(field, 32)}.{_slug(cons, 24)}")
        run_write_fn(
            """
            MATCH (d:CodeDTO {ref: $dref})
            MERGE (cf:CodeField {ref: $frefield})
            SET cf.project_id = $project_id, cf.codefile_ref = $fref, cf.name = $field,
                cf.dto_qualname = $dto, cf.ingested_at = $ts
            MERGE (d)-[:HAS_FIELD]->(cf)
            MERGE (br:BusinessRule {ref: $bref})
            SET br.project_id = $project_id, br.codefile_ref = $fref, br.kind = $cons,
                br.arg = $arg, br.ingested_at = $ts
            MERGE (cf)-[:CONSTRAINED_BY]->(br)
            """,
            {
                "dref": dref,
                "frefield": frefield,
                "bref": bref,
                "project_id": project_id,
                "fref": fref,
                "field": field[:256],
                "dto": dto[:512],
                "cons": cons[:128],
                "arg": arg,
                "ts": ts,
            },
        )

    for ab in semantic.get("accepts_bindings") or []:
        handler = str(ab.get("handler") or "").strip()
        dto_name = str(ab.get("dto") or "").strip()
        if not handler or not dto_name:
            continue
        dref = dto_refs.get(dto_name)
        if not dref:
            dref = node_ref_slug(project_id, "codedto", f"{path}::{_slug(dto_name, 64)}")
            dto_refs[dto_name] = dref
            run_write_fn(
                """
                MATCH (f:CodeFile {ref: $fref})
                MERGE (d:CodeDTO {ref: $dref})
                SET d.project_id = $project_id, d.codefile_ref = $fref, d.path = $path,
                    d.qualname = $qn, d.ingested_at = $ts
                MERGE (f)-[:DECLARES_DTO]->(d)
                """,
                {
                    "fref": fref,
                    "dref": dref,
                    "project_id": project_id,
                    "path": path[:2048],
                    "qn": dto_name[:512],
                    "ts": ts,
                },
            )
        eref = ep_ref_by_handler.get(handler)
        if eref and dref:
            run_write_fn(
                """
                MATCH (e:CodeEndpoint {ref: $eref}), (d:CodeDTO {ref: $dref})
                WHERE e.project_id = $project_id AND d.project_id = $project_id
                MERGE (e)-[:ACCEPTS]->(d)
                """,
                {"eref": eref, "dref": dref, "project_id": project_id},
            )
        fnref = func_refs.get(handler)
        if fnref and dref:
            run_write_fn(
                """
                MATCH (fn:CodeFunction {ref: $fnref}), (d:CodeDTO {ref: $dref})
                WHERE fn.project_id = $project_id AND d.project_id = $project_id
                MERGE (fn)-[:TRANSFORMS]->(d)
                """,
                {"fnref": fnref, "dref": dref, "project_id": project_id},
            )

    for dec in semantic.get("decorators") or []:
        name = str(dec.get("name") or "").strip()
        target = str(dec.get("target") or "").strip()
        tk = str(dec.get("target_kind") or "function")
        ln = int(dec.get("lineno") or 0)
        if not name or not target:
            continue
        dref = node_ref_slug(project_id, "codedecorator", f"{path}::{_slug(target, 48)}:{_slug(name, 32)}:{ln}")
        run_write_fn(
            """
            MERGE (cd:CodeDecorator {ref: $dref})
            SET cd.project_id = $project_id, cd.codefile_ref = $fref, cd.name = $name,
                cd.target = $target, cd.target_kind = $tk, cd.lineno = $ln, cd.ingested_at = $ts
            """,
            {
                "dref": dref,
                "project_id": project_id,
                "fref": fref,
                "name": name[:128],
                "target": target[:512],
                "tk": tk[:32],
                "ln": ln,
                "ts": ts,
            },
        )
        if tk == "function" and target in func_refs:
            run_write_fn(
                """
                MATCH (cd:CodeDecorator {ref: $dref}), (fn:CodeFunction {ref: $fnref})
                WHERE cd.project_id = $project_id AND fn.project_id = $project_id
                MERGE (cd)-[:DECORATES]->(fn)
                """,
                {"dref": dref, "fnref": func_refs[target], "project_id": project_id},
            )
        elif tk == "field" and "." in target:
            dto_q, _, fld = target.partition(".")
            frefield = node_ref_slug(project_id, "codefield", f"{path}::{_slug(dto_q, 40)}::{_slug(fld, 40)}")
            run_write_fn(
                """
                MATCH (cd:CodeDecorator {ref: $dref}), (cf:CodeField {ref: $frefield})
                WHERE cd.project_id = $project_id AND cf.project_id = $project_id
                MERGE (cd)-[:DECORATES]->(cf)
                """,
                {"dref": dref, "frefield": frefield, "project_id": project_id},
            )

    for io in semantic.get("io_edges") or []:
        fn_q = str(io.get("function") or "").strip()
        rel = str(io.get("rel") or "").strip().upper()
        tgt = str(io.get("target") or "").strip()[:512]
        if not fn_q or rel not in ("READS_FROM", "WRITES_TO", "EMITS_EVENT", "INVOKES_EXTERNAL") or not tgt:
            continue
        fnref = func_refs.get(fn_q)
        if not fnref:
            continue
        if rel == "READS_FROM":
            tref = node_ref_slug(project_id, "databasetable", f"{path}::{_slug(tgt, 80)}")
            run_write_fn(
                """
                MERGE (t:DatabaseTable {ref: $tref})
                SET t.project_id = $project_id, t.codefile_ref = $fref, t.hint = $tgt, t.ingested_at = $ts
                WITH t
                MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
                MERGE (fn)-[:READS_FROM]->(t)
                """,
                {"tref": tref, "fref": fref, "project_id": project_id, "tgt": tgt, "fnref": fnref, "ts": ts},
            )
        elif rel == "WRITES_TO":
            tref = node_ref_slug(project_id, "databasetable", f"{path}::{_slug(tgt, 80)}")
            run_write_fn(
                """
                MERGE (t:DatabaseTable {ref: $tref})
                SET t.project_id = $project_id, t.codefile_ref = $fref, t.hint = $tgt, t.ingested_at = $ts
                WITH t
                MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
                MERGE (fn)-[:WRITES_TO]->(t)
                """,
                {"tref": tref, "fref": fref, "project_id": project_id, "tgt": tgt, "fnref": fnref, "ts": ts},
            )
        elif rel == "EMITS_EVENT":
            kref = node_ref_slug(project_id, "kafkatopic", f"{path}::{_slug(tgt, 80)}")
            run_write_fn(
                """
                MERGE (k:KafkaTopic {ref: $kref})
                SET k.project_id = $project_id, k.codefile_ref = $fref, k.hint = $tgt, k.ingested_at = $ts
                WITH k
                MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
                MERGE (fn)-[:EMITS_EVENT]->(k)
                """,
                {"kref": kref, "fref": fref, "project_id": project_id, "tgt": tgt, "fnref": fnref, "ts": ts},
            )
        elif rel == "INVOKES_EXTERNAL":
            xref = node_ref_slug(project_id, "externalapi", f"{path}::{_slug(tgt, 80)}")
            run_write_fn(
                """
                MERGE (x:ExternalAPI {ref: $xref})
                SET x.project_id = $project_id, x.codefile_ref = $fref, x.hint = $tgt, x.ingested_at = $ts
                WITH x
                MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
                MERGE (fn)-[:INVOKES_EXTERNAL]->(x)
                """,
                {"xref": xref, "fref": fref, "project_id": project_id, "tgt": tgt, "fnref": fnref, "ts": ts},
            )

    for rb in semantic.get("returns_bindings") or []:
        handler = str(rb.get("handler") or "").strip()
        dto_name = str(rb.get("dto") or "").strip()
        if not handler or not dto_name:
            continue
        dref = dto_refs.get(dto_name)
        if not dref:
            dref = node_ref_slug(project_id, "codedto", f"{path}::{_slug(dto_name, 64)}")
            dto_refs[dto_name] = dref
            run_write_fn(
                """
                MATCH (f:CodeFile {ref: $fref})
                MERGE (d:CodeDTO {ref: $dref})
                SET d.project_id = $project_id, d.codefile_ref = $fref, d.path = $path,
                    d.qualname = $qn, d.ingested_at = $ts
                MERGE (f)-[:DECLARES_DTO]->(d)
                """,
                {
                    "fref": fref,
                    "dref": dref,
                    "project_id": project_id,
                    "path": path[:2048],
                    "qn": dto_name[:512],
                    "ts": ts,
                },
            )
        eref = ep_ref_by_handler.get(handler)
        if eref and dref:
            run_write_fn(
                """
                MATCH (e:CodeEndpoint {ref: $eref}), (d:CodeDTO {ref: $dref})
                WHERE e.project_id = $project_id AND d.project_id = $project_id
                MERGE (e)-[:RETURNS]->(d)
                """,
                {"eref": eref, "dref": dref, "project_id": project_id},
            )
        fnref = func_refs.get(handler)
        if fnref and dref:
            run_write_fn(
                """
                MATCH (fn:CodeFunction {ref: $fnref}), (d:CodeDTO {ref: $dref})
                WHERE fn.project_id = $project_id AND d.project_id = $project_id
                MERGE (fn)-[:TRANSFORMS]->(d)
                """,
                {"fnref": fnref, "dref": dref, "project_id": project_id},
            )

    for fe in semantic.get("function_enforces") or []:
        fn_q = str(fe.get("function") or "").strip()
        kind = str(fe.get("kind") or "rule").strip()[:128]
        arg = str(fe.get("arg") or "")[:400]
        ln = int(fe.get("lineno") or 0)
        fnref = func_refs.get(fn_q)
        if not fnref or not kind:
            continue
        bref = node_ref_slug(project_id, "businessrule", f"{path}::enf::{_slug(fn_q, 48)}:{_slug(kind, 32)}:{ln}")
        run_write_fn(
            """
            MERGE (br:BusinessRule {ref: $bref})
            SET br.project_id = $project_id, br.codefile_ref = $fref, br.kind = $kind,
                br.arg = $arg, br.scope = 'function', br.ingested_at = $ts
            WITH br
            MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
            MERGE (fn)-[:ENFORCES]->(br)
            """,
            {
                "bref": bref,
                "project_id": project_id,
                "fref": fref,
                "kind": kind,
                "arg": arg,
                "fnref": fnref,
                "ts": ts,
            },
        )

    for tr in semantic.get("trace_refs") or []:
        fn_q = str(tr.get("function") or "").strip()
        fnref = func_refs.get(fn_q)
        if not fnref:
            continue
        for sid in tr.get("story_ids") or []:
            try:
                si = int(sid)
            except (TypeError, ValueError):
                continue
            sref = node_ref(project_id, "story", si)
            run_write_fn(
                """
                MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
                MATCH (s:Story {ref: $sref}) WHERE s.project_id = $project_id
                MERGE (fn)-[:SATISFIES]->(s)
                """,
                {"fnref": fnref, "sref": sref, "project_id": project_id},
            )
        for tid in tr.get("task_ids") or []:
            try:
                ti = int(tid)
            except (TypeError, ValueError):
                continue
            tref = node_ref(project_id, "task", ti)
            run_write_fn(
                """
                MATCH (fn:CodeFunction {ref: $fnref}) WHERE fn.project_id = $project_id
                MATCH (t:Task {ref: $tref}) WHERE t.project_id = $project_id
                MERGE (fn)-[:SATISFIES]->(t)
                """,
                {"fnref": fnref, "tref": tref, "project_id": project_id},
            )

    return maps_ok
