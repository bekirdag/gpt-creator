#!/usr/bin/env python3
"""Simulate a workload iteration using an agent summary."""

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
    iteration = os.environ.get("ITERATION") or (sys.argv[2] if len(sys.argv) > 2 else "1")
    data = load_summary(summary_raw)
    adapter = (data.get("adapter") or "").strip()
    model = (data.get("model") or "").strip()
    cfg = data.get("adapterConfig") or {}
    if not adapter or not model:
        print("missing adapter or model")
        return 1

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
    prompt = [
        {"role": "system", "content": "You are running a self-test. Output only the line to append to test.txt. No prose, no formatting."},
        {"role": "user", "content": f"Append the number {iteration} as its own line."},
    ]
    result = client.send_chat(prompt, model=model)
    content = getattr(result, "content", "") or ""
    if not content:
        print("empty response")
        return 1
    line = content.strip().splitlines()[0].strip()
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
