#!/usr/bin/env python3
"""Enrich an agent payload file with registry defaults."""

import json
import sys
from pathlib import Path
from typing import Any


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
        else:
            return value
    return None


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    path = Path(sys.argv[1])
    registry_raw = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    agent = data.get("agent")
    if not isinstance(agent, dict):
        agent = {}
        data["agent"] = agent
    registry = {}
    if registry_raw:
        try:
            registry = json.loads(registry_raw)
        except Exception:
            registry = {}

    adapter = first_non_empty(agent.get("adapter"), registry.get("adapter"))
    if adapter:
        agent["adapter"] = adapter

    adapter_cfg = agent.get("adapterConfig")
    reg_cfg = registry.get("adapterConfig") if isinstance(registry, dict) else None
    if not adapter_cfg and reg_cfg:
        agent["adapterConfig"] = reg_cfg

    for key, reg_key in (("maxContextTokens", "maxContextTokens"), ("maxOutputTokens", "maxOutputTokens")):
        if agent.get(key) is None and isinstance(registry, dict) and registry.get(reg_key) is not None:
            agent[key] = registry[reg_key]

    if isinstance(registry, dict):
        if not agent.get("client_api_base") and registry.get("apiBase"):
            agent["client_api_base"] = registry.get("apiBase")
        if not agent.get("client_api_key_env") and registry.get("apiKeyEnv"):
            agent["client_api_key_env"] = registry.get("apiKeyEnv")
        if not agent.get("client_api_org_env") and registry.get("orgEnv"):
            agent["client_api_org_env"] = registry.get("orgEnv")
        if not agent.get("client_api_base_env") and registry.get("apiBaseEnv"):
            agent["client_api_base_env"] = registry.get("apiBaseEnv")

    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
