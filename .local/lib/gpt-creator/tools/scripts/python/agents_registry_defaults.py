#!/usr/bin/env python3
"""Emit first registry defaults (client, adapter, model) as newline-separated values."""

import sys


def main() -> int:
    try:
        from agents_registry import AgentRegistry  # type: ignore
    except Exception:
        print("\n\n")
        return 0

    try:
        reg = AgentRegistry.load()
        clients = reg.list_clients()
        if clients:
            first = clients[0]
            client = (first.get("name") or "").strip()
            adapter = (first.get("adapter") or "").strip()
            model = (first.get("defaultModel") or (first.get("models") or [None])[0] or "").strip()
            print(client)
            print(adapter)
            print(model)
            return 0
    except Exception:
        pass

    print("")
    print("")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
