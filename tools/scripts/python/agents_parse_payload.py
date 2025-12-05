#!/usr/bin/env python3
"""Parse an agent payload file and emit tab-separated fields."""

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
        return 1
    path = Path(sys.argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 1
    if not isinstance(data, dict):
        return 1
    kind = data.get("kind") or ""
    agent = data.get("agent") or {}
    if not isinstance(agent, dict):
        agent = {}
    resolved = data.get("resolved") or {}
    if not isinstance(resolved, dict):
        resolved = {}
    client = pick(resolved.get("client"), agent.get("client"))
    model = pick(resolved.get("model"), agent.get("model"))
    name = pick(agent.get("name"), agent.get("name_normalized"))
    api_key = pick(agent.get("client_api_key"))
    api_base = pick(agent.get("client_api_base"), resolved.get("apiBase"))
    api_org = pick(agent.get("client_api_org"), agent.get("client_api_org_env"), resolved.get("orgEnv"))
    adapter = pick(resolved.get("adapter"), agent.get("adapter"))
    max_ctx = pick(resolved.get("maxContextTokens"), agent.get("maxContextTokens"))
    max_out = pick(resolved.get("maxOutputTokens"), agent.get("maxOutputTokens"))
    api_key_env = pick(agent.get("client_api_key_env"), resolved.get("apiKeyEnv"))
    api_base_env = pick(agent.get("client_api_base_env"), resolved.get("apiBaseEnv"))
    api_org_env = pick(agent.get("client_api_org_env"), resolved.get("orgEnv"))
    print(
        "\t".join(
            [
                kind,
                client,
                model,
                name,
                api_key,
                api_base,
                api_org,
                adapter,
                max_ctx,
                max_out,
                api_key_env,
                api_base_env,
                api_org_env,
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
