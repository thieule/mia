"""Trích ADR/MADR từ văn bản — LLM OpenAI-compatible tuỳ chọn hoặc heuristic."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def _heuristic_adr(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    if not t:
        return {
            "title": "",
            "status": "Proposed",
            "context": "",
            "decision": "",
            "consequences": "",
            "confidence": "empty",
        }
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    title = (lines[0][:200] if lines else t[:120]) + ("…" if len(t) > 120 else "")
    return {
        "title": title,
        "status": "Proposed",
        "context": t[:12000],
        "decision": "",
        "consequences": "",
        "confidence": "heuristic_only",
    }


def propose_adr_json(text: str) -> dict[str, Any]:
    url = (os.environ.get("SECOND_BRAIN_ADR_LLM_URL") or os.environ.get("SECOND_BRAIN_EXTRACT_LLM_URL") or "").strip().rstrip("/")
    if not url:
        return _heuristic_adr(text)
    key = (os.environ.get("SECOND_BRAIN_ADR_LLM_KEY") or os.environ.get("SECOND_BRAIN_EXTRACT_LLM_KEY") or "").strip()
    model = (os.environ.get("SECOND_BRAIN_ADR_LLM_MODEL") or os.environ.get("SECOND_BRAIN_EXTRACT_LLM_MODEL") or "gpt-4o-mini").strip()
    sys_prompt = (
        "You extract an Architecture Decision Record from discussion or spec text. "
        "Reply with ONLY valid JSON with keys: "
        '"title","status","context","decision","consequences". '
        "status must be one of: Proposed, Accepted, Superseded. "
        "Title should be concise; include ADR code in title if present in text (e.g. ADR-001)."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text[:24000]},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
        choice = (raw.get("choices") or [{}])[0]
        msg = (choice.get("message") or {}).get("content") or "{}"
        out = json.loads(msg)
        if isinstance(out, dict):
            st = str(out.get("status") or "Proposed").strip()
            if st not in ("Proposed", "Accepted", "Superseded"):
                st = "Proposed"
            out["status"] = st
            out["confidence"] = "llm"
            return out
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _heuristic_adr(text)


def normalize_madr_status(status: str) -> str:
    s = (status or "").strip()
    if s.lower() in ("proposed", "accepted", "superseded"):
        return s[:1].upper() + s[1:].lower()
    return "Proposed"
