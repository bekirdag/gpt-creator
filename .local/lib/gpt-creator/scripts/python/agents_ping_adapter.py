#!/usr/bin/env python3
"""Ping an adapter using llm_client_factory based on a summary payload."""

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


def load_summary(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {}


def main() -> int:
    summary_raw = os.environ.get("SUMMARY") or (sys.argv[1] if len(sys.argv) > 1 else "{}")
    data = load_summary(summary_raw)
    adapter = (data.get("adapter") or "").strip()
    model = (data.get("model") or "").strip()
    cfg = data.get("adapterConfig") or {}
    if not adapter or not model:
        print("missing adapter or model")
        return 2

    add_python_paths()
    from llm_client_factory import create_llm_client  # type: ignore

    config = {
        "adapterConfig": cfg,
        "apiKeyEnv": data.get("apiKeyEnv"),
        "apiBaseEnv": data.get("apiBaseEnv"),
        "apiBase": data.get("apiBase"),
        "orgEnv": data.get("orgEnv"),
        "maxContextTokens": data.get("maxContextTokens"),
        "maxOutputTokens": data.get("maxOutputTokens"),
    }
    client = create_llm_client(adapter, config)
    result = client.send_chat(["ping"], model=model)
    print(getattr(result, "content", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
