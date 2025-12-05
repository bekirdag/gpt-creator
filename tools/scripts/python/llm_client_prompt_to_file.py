#!/usr/bin/env python3
"""Invoke llm_client_factory and write chat response content to a file."""

import os
import sys
from pathlib import Path


def add_python_paths() -> None:
    cli_root_env = os.environ.get("CLI_ROOT")
    cli_root = Path(cli_root_env) if cli_root_env else Path(__file__).resolve().parents[2]
    candidates = [
        cli_root / "tools" / "scripts" / "python",
        cli_root / "scripts" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            sys.path.insert(0, str(candidate))


def main() -> int:
    if len(sys.argv) < 5:
        return 1
    adapter = sys.argv[1]
    model = sys.argv[2]
    prompt_path = Path(sys.argv[3])
    out_path = Path(sys.argv[4])

    add_python_paths()
    from llm_client_factory import create_llm_client  # type: ignore

    prompt_text = prompt_path.read_text(encoding="utf-8")
    client = create_llm_client(adapter, {})
    response = client.send_chat([prompt_text], model=model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(response.content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
