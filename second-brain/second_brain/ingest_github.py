"""GitHub push webhook → Neo4j (Commit, CodeFile, CodeFunction) + Elasticsearch (source_type=code)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from second_brain.code_static_multilang import EXT_TO_LANG, analyze_code_file
from second_brain.commit_links import link_commit_tasks_and_stories
from second_brain.es_store import delete_by_ref, index_chunk
from second_brain.neo4j_store import node_ref, node_ref_slug, run_write

_log = logging.getLogger(__name__)


def verify_github_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    if not secret or signature_header is None:
        return False
    sig = signature_header.strip()
    if not sig.startswith("sha256="):
        return False
    digest = sig[7:]
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, digest)


def _repo_project_map() -> dict[str, int]:
    raw = (os.environ.get("SECOND_BRAIN_GITHUB_REPO_PROJECT_MAP") or "").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    out: dict[str, int] = {}
    for k, v in data.items():
        out[str(k).strip().lower()] = int(v)
    return out


def resolve_project_id(full_name: str) -> int | None:
    m = _repo_project_map()
    pid = m.get(full_name.strip().lower())
    if pid is not None:
        return pid
    fb = (os.environ.get("SECOND_BRAIN_GITHUB_DEFAULT_PROJECT_ID") or "").strip()
    return int(fb) if fb else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _github_auth_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_get_json(url: str, token: str) -> Any | None:
    req = urllib.request.Request(url, headers=_github_auth_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        _log.warning("GitHub API HTTP %s %s: %s", e.code, url, e.reason)
        return None
    except Exception as e:
        _log.warning("GitHub API failed %s: %s", url, e)
        return None


def _fetch_github_file(owner: str, repo: str, path: str, sha: str, token: str) -> str | None:
    enc = "/".join(urllib.parse.quote(segment, safe="") for segment in path.split("/"))
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{enc}?ref={urllib.parse.quote(sha)}"
    req = urllib.request.Request(url, headers=_github_auth_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        _log.warning("GitHub contents HTTP %s for %s: %s", e.code, path, e.reason)
        return None
    except Exception as e:
        _log.warning("GitHub fetch failed %s: %s", path, e)
        return None

    if isinstance(payload, list):
        return None
    if payload.get("type") != "file":
        return None
    raw_b64 = payload.get("content")
    if not isinstance(raw_b64, str):
        return None
    try:
        return base64.b64decode(raw_b64).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return None


def _github_diff_settings() -> tuple[bool, int, int, str]:
    """fetch_diff, max_patch_bytes, max_diff_files_per_commit, scope (touched|full_commit)."""
    raw = (os.environ.get("SECOND_BRAIN_GITHUB_FETCH_DIFF") or "1").strip().lower()
    fetch = raw not in ("0", "false", "no", "off")
    max_patch = int((os.environ.get("SECOND_BRAIN_GITHUB_DIFF_MAX_PATCH_BYTES") or "32000").strip() or "32000")
    max_patch = max(1024, min(max_patch, 490000))
    max_diff_files = int((os.environ.get("SECOND_BRAIN_GITHUB_DIFF_MAX_FILES") or "80").strip() or "80")
    max_diff_files = max(0, min(max_diff_files, 500))
    scope = (os.environ.get("SECOND_BRAIN_GITHUB_DIFF_INDEX_SCOPE") or "touched").strip().lower()
    if scope not in ("touched", "full_commit"):
        scope = "touched"
    return fetch, max_patch, max_diff_files, scope


def _codediff_stable_id(sha: str, path: str) -> str:
    s = sha.strip()
    h = hashlib.sha256(f"{s}\0{path}".encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"{s[:12]}_{h}"


def _fetch_commit_file_changes(owner: str, repo: str, sha: str, token: str) -> dict[str, dict[str, Any]]:
    enc = urllib.parse.quote(sha.strip(), safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{enc}"
    data = _github_get_json(url, token)
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(data, dict):
        return out
    files = data.get("files")
    if not isinstance(files, list):
        return out
    for item in files:
        if not isinstance(item, dict):
            continue
        fn = str(item.get("filename") or "").strip()
        if not fn:
            continue
        patch = item.get("patch")
        out[fn] = {
            "status": str(item.get("status") or ""),
            "additions": int(item.get("additions") or 0),
            "deletions": int(item.get("deletions") or 0),
            "changes": int(item.get("changes") or 0),
            "patch": patch if isinstance(patch, str) else None,
        }
    return out


def _index_code_diff_es(
    *,
    project_id: int,
    full_name: str,
    sha: str,
    path: str,
    commit_message_line: str,
    change: dict[str, Any] | None,
    es_event_type: str,
    max_patch_bytes: int,
) -> None:
    """Một chunk ES để điều tra issue: unified diff (nếu API trả về) + metadata."""
    ext = _codediff_stable_id(sha, path)
    dref = node_ref_slug(project_id, "codediff", ext)
    status = (change or {}).get("status") or "unknown"
    additions = int((change or {}).get("additions") or 0)
    deletions = int((change or {}).get("deletions") or 0)
    patch = (change or {}).get("patch") if change else None
    patch_str = ""
    if isinstance(patch, str) and patch.strip():
        patch_str = patch.strip()
        if len(patch_str) > max_patch_bytes:
            patch_str = patch_str[:max_patch_bytes] + "\n...(patch truncated)"
    elif change:
        patch_str = "(GitHub không trả patch — file lớn, binary, hoặc quá nhiều thay đổi)"
    else:
        patch_str = "(Không có chi tiết file trong response commit API)"

    header = (
        f"repo={full_name}\ncommit_sha={sha}\npath={path}\nstatus={status}\n"
        f"additions={additions} deletions={deletions}\ncommit_message={commit_message_line[:800]}\n---\n"
    )
    text = header + patch_str
    index_chunk(
        project_id=project_id,
        ref=dref,
        label="CodeDiff",
        text=text,
        event_type=es_event_type,
        scope="project",
        visibility="project",
        source_type="code_diff",
        tags=[sha[:12], path.rsplit("/", 1)[-1][:64]],
    )


def _delete_codefile_graph(project_id: int, path: str) -> str:
    fref = node_ref_slug(project_id, "codefile", path)
    run_write(
        """
        MATCH (f:CodeFile {ref: $fref})-[:DEFINES]->(x:CodeFunction)
        DETACH DELETE x
        """,
        {"fref": fref},
    )
    run_write(
        "MATCH (f:CodeFile {ref: $fref}) DETACH DELETE f",
        {"fref": fref},
    )
    delete_by_ref(fref)
    return fref


def _resolve_github_ref(owner: str, repo: str, ref: str, token: str) -> dict[str, Any] | None:
    enc_ref = urllib.parse.quote(ref.strip(), safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{enc_ref}"
    data = _github_get_json(url, token)
    if not isinstance(data, dict):
        return None
    sha = str(data.get("sha") or "").strip()
    commit_obj = data.get("commit") if isinstance(data.get("commit"), dict) else {}
    message = str(commit_obj.get("message") or "")
    tree = commit_obj.get("tree") if isinstance(commit_obj.get("tree"), dict) else {}
    tree_sha = str(tree.get("sha") or "").strip()
    if len(sha) < 7:
        return None
    return {"sha": sha, "message": message, "tree_sha": tree_sha or None}


def _list_tree_code_paths(
    owner: str,
    repo: str,
    tree_sha: str,
    token: str,
    *,
    max_files: int,
    path_prefix: str | None,
) -> tuple[list[str], bool]:
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(tree_sha)}?recursive=1"
    data = _github_get_json(url, token)
    if not isinstance(data, dict):
        return [], False
    if data.get("truncated") is True:
        return [], True
    tree = data.get("tree")
    if not isinstance(tree, list):
        return [], False

    prefix = (path_prefix or "").strip().replace("\\", "/")
    if prefix.endswith("/"):
        prefix = prefix[:-1]
    prefix_slash = f"{prefix}/" if prefix else ""

    out: list[str] = []
    for item in tree:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "blob":
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        if prefix:
            if not (path == prefix or path.startswith(prefix_slash)):
                continue
        base = path.rsplit("/", 1)[-1].lower()
        if "." not in base:
            continue
        ext = "." + base.rsplit(".", 1)[-1]
        if ext not in EXT_TO_LANG:
            continue
        out.append(path)

    out.sort()
    return out[:max_files], False


def _ingest_one_github_commit(
    *,
    project_id: int,
    full_name: str,
    owner: str,
    repo_name: str,
    pref: str,
    sha: str,
    message: str,
    removed: list[str],
    touched: list[str],
    token: str,
    max_files: int,
    max_bytes: int,
    ts: str,
    es_event_type: str = "github.push",
) -> dict[str, int]:
    fetch_diff, diff_max_patch, diff_max_files, diff_scope = _github_diff_settings()
    file_changes: dict[str, dict[str, Any]] = {}
    if token and fetch_diff and diff_max_files > 0:
        file_changes = _fetch_commit_file_changes(owner, repo_name, sha, token)

    cref = node_ref_slug(project_id, "commit", sha[:40])
    commit_message_line = (message or "").split("\n", 1)[0].strip()

    run_write(
        """
        MERGE (p:Project {ref: $pref})
        SET p.project_id = $project_id, p.ingested_at = coalesce(p.ingested_at, $ts)
        MERGE (c:Commit {ref: $cref})
        SET c.project_id = $project_id, c.sha = $sha, c.message = $msg,
            c.repo_full_name = $repo_fn, c.ingested_at = $ts, c.source = 'github'
        MERGE (p)-[:HAS_COMMIT]->(c)
        """,
        {
            "pref": pref,
            "project_id": project_id,
            "cref": cref,
            "sha": sha[:64],
            "msg": message[:8000],
            "repo_fn": full_name[:512],
            "ts": ts,
        },
    )

    link_commit_tasks_and_stories(
        project_id=project_id,
        pref=pref,
        cref=cref,
        message=message,
        ts=ts,
        run_write_fn=run_write,
    )

    fragment: dict[str, int] = {
        "files_indexed": 0,
        "files_removed": 0,
        "functions": 0,
        "edges": 0,
        "diffs_indexed": 0,
    }
    diff_budget = diff_max_files
    diff_paths_done: set[str] = set()

    def _try_index_diff(path: str) -> None:
        nonlocal diff_budget
        if diff_budget <= 0 or not fetch_diff or diff_max_files <= 0:
            return
        if path in diff_paths_done:
            return
        ch = file_changes.get(path) if file_changes else None
        _index_code_diff_es(
            project_id=project_id,
            full_name=full_name,
            sha=sha,
            path=path,
            commit_message_line=commit_message_line,
            change=ch,
            es_event_type=es_event_type,
            max_patch_bytes=diff_max_patch,
        )
        diff_paths_done.add(path)
        fragment["diffs_indexed"] += 1
        diff_budget -= 1

    for path in removed:
        _delete_codefile_graph(project_id, path)
        fragment["files_removed"] += 1
        _try_index_diff(path)

    file_budget = max_files
    for path in touched:
        if file_budget <= 0:
            break
        file_budget -= 1
        if not token:
            _log.debug("skip file fetch (no SECOND_BRAIN_GITHUB_TOKEN): %s", path)
            continue

        content = _fetch_github_file(owner, repo_name, path, sha, token)
        if content is None:
            continue
        if len(content.encode("utf-8", errors="ignore")) > max_bytes:
            _log.debug("skip large file %s", path)
            continue
        if "\x00" in content[:8000]:
            continue

        fref = node_ref_slug(project_id, "codefile", path)
        run_write(
            """
            MATCH (c:Commit {ref: $cref})
            MERGE (f:CodeFile {ref: $fref})
            SET f.project_id = $project_id, f.path = $path, f.repo_full_name = $repo_fn,
                f.last_commit_sha = $sha, f.ingested_at = $ts
            MERGE (c)-[:MODIFIES]->(f)
            """,
            {
                "cref": cref,
                "fref": fref,
                "project_id": project_id,
                "path": path[:2048],
                "repo_fn": full_name[:512],
                "sha": sha[:64],
                "ts": ts,
            },
        )

        run_write(
            """
            MATCH (f:CodeFile {ref: $fref})-[:DEFINES]->(x:CodeFunction)
            DETACH DELETE x
            """,
            {"fref": fref},
        )

        func_refs: dict[str, str] = {}
        meta = analyze_code_file(path, content)
        if meta.get("symbols"):
            for sym in meta.get("symbols") or []:
                qn = str(sym.get("qualname") or "")
                if not qn:
                    continue
                fq_ref = node_ref_slug(project_id, "codefunction", f"{path}::{qn}")
                func_refs[qn] = fq_ref
                fragment["functions"] += 1
                run_write(
                    """
                    MATCH (f:CodeFile {ref: $fref})
                    MERGE (fn:CodeFunction {ref: $fq})
                    SET fn.project_id = $project_id, fn.path = $path, fn.qualname = $qn,
                        fn.kind = $kind, fn.lineno = $ln, fn.ingested_at = $ts
                    MERGE (f)-[:DEFINES]->(fn)
                    """,
                    {
                        "fref": fref,
                        "fq": fq_ref,
                        "project_id": project_id,
                        "path": path[:2048],
                        "qn": qn[:512],
                        "kind": str(sym.get("kind") or "function")[:32],
                        "ln": int(sym.get("lineno") or 0),
                        "ts": ts,
                    },
                )
            for caller_q, callee_q in meta.get("calls") or []:
                cr = func_refs.get(caller_q)
                ce = func_refs.get(callee_q)
                if not cr or not ce:
                    continue
                fragment["edges"] += 1
                run_write(
                    """
                    MATCH (a:CodeFunction {ref: $cr}), (b:CodeFunction {ref: $ce})
                    WHERE a.project_id = $project_id AND b.project_id = $project_id
                    MERGE (a)-[:CALLS]->(b)
                    """,
                    {"cr": cr, "ce": ce, "project_id": project_id},
                )

        blob = f"{full_name}\n{path}\n{sha}\n\n{content[:49000]}"
        index_chunk(
            project_id=project_id,
            ref=fref,
            label="CodeFile",
            text=blob,
            event_type=es_event_type,
            scope="project",
            visibility="project",
            source_type="code",
        )
        fragment["files_indexed"] += 1
        _try_index_diff(path)

    if diff_scope == "full_commit" and file_changes and diff_budget > 0:
        for path in sorted(file_changes.keys()):
            if diff_budget <= 0:
                break
            if path in diff_paths_done:
                continue
            _try_index_diff(path)

    return fragment


def apply_github_code_refresh(
    repository: str,
    ref: str,
    *,
    project_id: int = 0,
    paths: list[str] | None = None,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """
    Đồng bộ code vào Neo4j + ES tại một commit/branch (không cần webhook push).
    Dùng cho MCP `brain_refresh_github_code`.
    """
    full_name = repository.strip()
    if "/" not in full_name or full_name.count("/") != 1:
        return {"ok": False, "error": "bad_repository", "hint": "use owner/repo"}

    owner, _, repo_name = full_name.partition("/")
    if not owner or not repo_name:
        return {"ok": False, "error": "bad_repository"}

    pid = resolve_project_id(full_name) if project_id <= 0 else project_id
    if pid is None or pid <= 0:
        return {"ok": False, "error": "unmapped_repository", "repository": full_name}

    token = (os.environ.get("SECOND_BRAIN_GITHUB_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "missing_github_token"}

    max_files = int((os.environ.get("SECOND_BRAIN_GITHUB_MAX_FILES") or "50").strip() or "50")
    max_bytes = int((os.environ.get("SECOND_BRAIN_GITHUB_MAX_FILE_BYTES") or "400000").strip() or "400000")

    resolved = _resolve_github_ref(owner, repo_name, ref, token)
    if not resolved:
        return {"ok": False, "error": "resolve_ref_failed", "ref": ref}

    sha = str(resolved["sha"])
    message = str(resolved["message"])
    tree_sha = resolved.get("tree_sha")

    explicit_paths = paths is not None and len(paths) > 0
    if explicit_paths:
        touched = list(dict.fromkeys([p.strip() for p in paths if p.strip()]))[:max_files]
        tree_truncated = False
    else:
        if not tree_sha:
            return {
                "ok": False,
                "error": "no_tree_sha",
                "hint": "pass non-empty paths list to ingest explicit files",
            }
        touched, tree_truncated = _list_tree_code_paths(
            owner,
            repo_name,
            tree_sha,
            token,
            max_files=max_files,
            path_prefix=path_prefix,
        )
        if tree_truncated:
            return {
                "ok": False,
                "error": "tree_truncated",
                "hint": "set path_prefix or pass explicit paths; repo tree too large for one GitHub API response",
            }

    pref = node_ref(pid, "project", pid)
    ts = _now()
    sub = _ingest_one_github_commit(
        project_id=pid,
        full_name=full_name,
        owner=owner,
        repo_name=repo_name,
        pref=pref,
        sha=sha,
        message=message,
        removed=[],
        touched=touched,
        token=token,
        max_files=max_files,
        max_bytes=max_bytes,
        ts=ts,
        es_event_type="github.mcp_refresh",
    )

    return {
        "ok": True,
        "repository": full_name,
        "project_id": pid,
        "ref_requested": ref.strip(),
        "resolved_sha": sha[:40],
        "paths_mode": "explicit" if explicit_paths else "tree_scan",
        "paths_touched": len(touched),
        "stats": {"commits": 1, **sub},
    }


def apply_github_push(payload: dict[str, Any]) -> dict[str, Any]:
    repo = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    full_name = str(repo.get("full_name") or "").strip()
    if not full_name:
        return {"ok": False, "error": "missing_repository"}

    project_id = resolve_project_id(full_name)
    if project_id is None or project_id <= 0:
        return {"ok": False, "error": "unmapped_repository", "repository": full_name}

    owner, _, repo_name = full_name.partition("/")
    if not owner or not repo_name:
        return {"ok": False, "error": "bad_repository_name"}

    token = (os.environ.get("SECOND_BRAIN_GITHUB_TOKEN") or "").strip()
    max_files = int((os.environ.get("SECOND_BRAIN_GITHUB_MAX_FILES") or "50").strip() or "50")
    max_bytes = int((os.environ.get("SECOND_BRAIN_GITHUB_MAX_FILE_BYTES") or "400000").strip() or "400000")

    commits_raw = payload.get("commits")
    commits = commits_raw if isinstance(commits_raw, list) else []
    if not commits and isinstance(payload.get("head_commit"), dict):
        commits = [payload["head_commit"]]

    pref = node_ref(project_id, "project", project_id)
    ts = _now()
    stats = {
        "commits": 0,
        "files_indexed": 0,
        "files_removed": 0,
        "functions": 0,
        "edges": 0,
        "diffs_indexed": 0,
    }

    for commit in commits:
        if not isinstance(commit, dict):
            continue
        sha = str(commit.get("id") or "").strip()
        if len(sha) < 7:
            continue
        message = str(commit.get("message") or "")

        removed = commit.get("removed") if isinstance(commit.get("removed"), list) else []
        touched = list(
            dict.fromkeys(
                [str(x) for x in (commit.get("added") or []) if str(x).strip()]
                + [str(x) for x in (commit.get("modified") or []) if str(x).strip()]
            )
        )

        sub = _ingest_one_github_commit(
            project_id=project_id,
            full_name=full_name,
            owner=owner,
            repo_name=repo_name,
            pref=pref,
            sha=sha,
            message=message,
            removed=[str(x) for x in removed if str(x).strip()],
            touched=touched,
            token=token,
            max_files=max_files,
            max_bytes=max_bytes,
            ts=ts,
            es_event_type="github.push",
        )
        stats["files_indexed"] += sub["files_indexed"]
        stats["files_removed"] += sub["files_removed"]
        stats["functions"] += sub["functions"]
        stats["edges"] += sub["edges"]
        stats["diffs_indexed"] += sub.get("diffs_indexed", 0)
        stats["commits"] += 1

    return {"ok": True, "repository": full_name, "project_id": project_id, "stats": stats}


def apply_github_compare(repository: str, base: str, head: str) -> dict[str, Any]:
    """
    So sánh hai ref GitHub (branch hoặc SHA) — không ghi Neo4j/ES.
    GET /repos/{owner}/{repo}/compare/{base}...{head}
    """
    full_name = repository.strip()
    if "/" not in full_name or full_name.count("/") != 1:
        return {"ok": False, "error": "bad_repository", "hint": "owner/repo"}

    owner, _, repo_name = full_name.partition("/")
    token = (os.environ.get("SECOND_BRAIN_GITHUB_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "missing_github_token"}

    max_files = int((os.environ.get("SECOND_BRAIN_GITHUB_COMPARE_MAX_FILES") or "40").strip() or "40")
    max_files = max(1, min(max_files, 200))
    max_patch = int((os.environ.get("SECOND_BRAIN_GITHUB_COMPARE_MAX_PATCH_BYTES") or "16000").strip() or "16000")
    max_patch = max(512, min(max_patch, 490000))

    b = urllib.parse.quote(base.strip(), safe="")
    h = urllib.parse.quote(head.strip(), safe="")
    url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{b}...{h}"
    data = _github_get_json(url, token)
    if not isinstance(data, dict):
        return {"ok": False, "error": "github_compare_failed", "repository": full_name}

    files_raw = data.get("files")
    files_out: list[dict[str, Any]] = []
    if isinstance(files_raw, list):
        for item in files_raw[:max_files]:
            if not isinstance(item, dict):
                continue
            patch = item.get("patch")
            ps = patch.strip() if isinstance(patch, str) else ""
            if len(ps) > max_patch:
                ps = ps[:max_patch] + "\n...(truncated)"
            files_out.append(
                {
                    "filename": item.get("filename"),
                    "status": item.get("status"),
                    "additions": item.get("additions"),
                    "deletions": item.get("deletions"),
                    "changes": item.get("changes"),
                    "patch": ps if ps else None,
                }
            )

    return {
        "ok": True,
        "repository": full_name,
        "base": base.strip(),
        "head": head.strip(),
        "ahead_by": data.get("ahead_by"),
        "behind_by": data.get("behind_by"),
        "total_commits": data.get("total_commits"),
        "merge_base_commit": (
            data.get("merge_base_commit").get("sha")
            if isinstance(data.get("merge_base_commit"), dict)
            else None
        ),
        "files": files_out,
        "files_truncated": isinstance(files_raw, list) and len(files_raw) > len(files_out),
    }
