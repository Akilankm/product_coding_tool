"""Robust JSON extraction helpers for LLM outputs."""

from __future__ import annotations

import json
import re
from typing import Any


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    match = _JSON_FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"value": obj}
    except json.JSONDecodeError:
        pass
    # Recover first JSON object substring.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else {"value": obj}
        except json.JSONDecodeError:
            return {"_parse_error": raw[:2000]}
    return {"_parse_error": raw[:2000]}


__all__ = ["parse_json_object"]
