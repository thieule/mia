"""P3: Gợi ý cấu trúc lesson từ text — LLM tuỳ chọn hoặc heuristic."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def _heuristic_lesson(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    if not t:
        return {
            "title": "",
            "problem": "",
            "what_we_learned": "",
            "recommended_action": "",
            "tags": [],
            "confidence": "empty",
        }
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    title = (lines[0][:200] if lines else t[:120]) + ("…" if len(t) > 120 else "")
    return {
        "title": title,
        "problem": t[:8000],
        "what_we_learned": "",
        "recommended_action": "",
        "tags": sorted(set(re.findall(r"#([\w-]+)", t)))[:20],
        "confidence": "heuristic_only",
    }


def propose_lesson_json(text: str) -> dict[str, Any]:
    url = (os.environ.get("SECOND_BRAIN_EXTRACT_LLM_URL") or "").strip().rstrip("/")
    if not url:
        return _heuristic_lesson(text)
    key = (os.environ.get("SECOND_BRAIN_EXTRACT_LLM_KEY") or "").strip()
    model = (os.environ.get("SECOND_BRAIN_EXTRACT_LLM_MODEL") or "gpt-4o-mini").strip()
    sys_prompt = (
        "You extract a lesson-learned summary from engineering discussion text. "
        "Reply with ONLY valid JSON: "
        '{"title","problem","what_we_learned","recommended_action","tags"(string array)}'
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
            out["confidence"] = "llm"
            return out
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _heuristic_lesson(text)
