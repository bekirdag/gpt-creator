#!/usr/bin/env python3
"""Emit adapter metadata extracted from an agents registry JSON blob."""

from __future__ import annotations

import json
import sys
from typing import Any, Iterable, Tuple


FieldSpec = Tuple[str, bool]


FIELDS: Iterable[FieldSpec] = (
    ("adapter", False),
    ("maxContextTokens", True),
    ("maxOutputTokens", True),
    ("apiBase", True),
    ("apiKeyEnv", True),
    ("orgEnv", True),
    ("apiBaseEnv", True),
)


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _safe_value(value: Any, coerce_truthy: bool) -> str:
    if value is None:
        return ""
    if coerce_truthy and not value:
        return ""
    return str(value)


def main() -> None:
    data = _read_payload()
    for field, coerce_truthy in FIELDS:
        print(_safe_value(data.get(field, ""), coerce_truthy))


if __name__ == "__main__":
    main()
