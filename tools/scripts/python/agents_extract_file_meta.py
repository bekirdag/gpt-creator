#!/usr/bin/env python3
"""Extract adapter/limits/api metadata from an agent JSON file."""

import json
import sys
from pathlib import Path
from typing import Any


def pick(*values: Any) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    path = Path(sys.argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    agent = data.get("agent") or {}
    if not isinstance(agent, dict):
        agent = data
    resolved = data.get("resolved") or {}
    if not isinstance(resolved, dict):
        resolved = {}

    adapter = pick(resolved.get("adapter"), agent.get("adapter"))
    max_ctx = pick(resolved.get("maxContextTokens"), agent.get("maxContextTokens"))
    max_out = pick(resolved.get("maxOutputTokens"), agent.get("maxOutputTokens"))
    api_base = pick(resolved.get("apiBase"), agent.get("client_api_base"))
    api_key_env = pick(agent.get("client_api_key_env"), resolved.get("apiKeyEnv"))
    org_env = pick(agent.get("client_api_org_env"), resolved.get("orgEnv"))
    api_base_env = pick(agent.get("client_api_base_env"), resolved.get("apiBaseEnv"))

    print("\n".join([adapter, max_ctx, max_out, api_base, api_key_env, org_env, api_base_env]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
