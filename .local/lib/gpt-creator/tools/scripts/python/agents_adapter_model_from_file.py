#!/usr/bin/env python3
"""Extract adapter/model from an agent file with registry fallback."""

import json
import os
import sys
from pathlib import Path


def add_python_paths() -> None:
    root = os.environ.get("GC_CLI_ROOT") or os.environ.get("CLI_ROOT") or ""
    if root:
        root_path = Path(root)
        for candidate in [root_path / "tools" / "scripts" / "python", root_path / "scripts" / "python"]:
            if candidate.exists():
                sys.path.insert(0, str(candidate))


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    path = Path(sys.argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("")
        print("")
        return 0
    agent = data.get("agent") or {}
    if not isinstance(agent, dict):
        agent = {}
    adapter = (agent.get("adapter") or "").strip()
    model = (agent.get("model") or agent.get("name") or "").strip()
    client = (agent.get("client") or "").strip()
    if (not adapter or not model) and client:
        add_python_paths()
        try:
            from agents_registry import AgentRegistry  # type: ignore

            reg = AgentRegistry.load().validate_pair(client, model)
            adapter = adapter or (reg.get("adapter") or "").strip()
            model = (reg.get("model") or model).strip()
        except Exception:
            pass
    print(adapter)
    print(model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
