#!/usr/bin/env python3
"""Load an agent file and overlay registry defaults."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


def add_python_paths() -> None:
    root = os.environ.get("GC_CLI_ROOT") or os.environ.get("CLI_ROOT") or ""
    if root:
        root_path = Path(root)
        for candidate in [root_path / "tools" / "scripts" / "python", root_path / "scripts" / "python"]:
            if candidate.exists():
                sys.path.insert(0, str(candidate))


def load_agent(path: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if path and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    agent = data.get("agent") if isinstance(data, dict) else {}
    if not isinstance(agent, dict):
        agent = {}
    return agent


def registry_overlay(agent: Dict[str, Any]) -> Dict[str, Any]:
    client = (agent.get("client") or "").strip()
    model = (agent.get("model") or "").strip()
    adapter = (agent.get("adapter") or "").strip()
    adapter_cfg = agent.get("adapterConfig") or {}
    max_ctx = agent.get("maxContextTokens")
    max_out = agent.get("maxOutputTokens")
    api_base = agent.get("client_api_base") or ""
    api_key_env = agent.get("client_api_key_env") or ""
    org_env = agent.get("client_api_org_env") or ""
    api_base_env = agent.get("client_api_base_env") or ""
    add_python_paths()
    try:
        from agents_registry import AgentRegistry  # type: ignore

        reg = AgentRegistry.load().validate_pair(client, model)
        model = (reg.get("model") or model or "").strip()
        adapter = adapter or (reg.get("adapter") or "").strip()
        adapter_cfg = adapter_cfg or (reg.get("adapterConfig") or {})
        max_ctx = max_ctx or reg.get("maxContextTokens")
        max_out = max_out or reg.get("maxOutputTokens")
        api_base = api_base or reg.get("apiBase") or ""
        api_key_env = api_key_env or reg.get("apiKeyEnv") or ""
        org_env = org_env or reg.get("orgEnv") or ""
        api_base_env = api_base_env or reg.get("apiBaseEnv") or ""
    except Exception:
        pass
    return {
        "agent": agent.get("name") or agent.get("name_normalized") or "",
        "client": client,
        "model": model,
        "adapter": adapter,
        "adapterConfig": adapter_cfg,
        "maxContextTokens": max_ctx,
        "maxOutputTokens": max_out,
        "apiBase": api_base,
        "apiKeyEnv": api_key_env,
        "apiBaseEnv": api_base_env,
        "orgEnv": org_env,
    }


def main() -> int:
    agent_file = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else Path("")
    agent = load_agent(agent_file)
    summary = registry_overlay(agent)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
