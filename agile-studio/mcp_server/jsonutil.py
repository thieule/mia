from __future__ import annotations

import json
from typing import Any


def json_out(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, indent=2)
