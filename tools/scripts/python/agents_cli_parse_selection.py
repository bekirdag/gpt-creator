#!/usr/bin/env python3
"""Parse agent/model selection JSON into newline-delimited fields."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List


def _load_payload() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _write_agent_payload(data: dict[str, Any], tmp_path: Path) -> None:
    try:
        tmp_path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _print_lines(lines: List[str]) -> None:
    for line in lines:
        print(line)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(1)
    tmp_path = Path(sys.argv[1])
    data = _load_payload()
    kind = data.get("kind")
    if kind == "agent":
        _write_agent_payload(data, tmp_path)
        agent = data.get("agent") or {}
        _print_lines(
            [
                "agent",
                str(agent.get("client", "") or ""),
                str(agent.get("model", "") or ""),
                str(agent.get("name", "") or ""),
                str(agent.get("client_api_key", "") or ""),
                str(agent.get("client_api_base", "") or ""),
                str(agent.get("client_api_org", "") or ""),
            ]
        )
    elif kind == "model":
        _print_lines(
            [
                "model",
                "",
                str(data.get("model", "") or ""),
                "",
                "",
                "",
                "",
            ]
        )
    else:
        _print_lines(
            [
                "unknown",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )


if __name__ == "__main__":
    main()
