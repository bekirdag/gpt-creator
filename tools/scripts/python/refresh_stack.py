#!/usr/bin/env python3
"""
Refresh stack tasks: prune/prepare docker services and emit env hints.
This helper encapsulates the compose service filtering and emits any warnings/errors.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: refresh_stack.py <compose.yml> <service> [service...]", file=sys.stderr)
        return 1
    compose_path = Path(argv[0])
    services = argv[1:]
    if not compose_path.is_file():
        print(f"Compose file not found: {compose_path}", file=sys.stderr)
        return 1
    keep = set(services)
    # reuse compose pruning logic
    from prune_compose_services import prune_compose  # type: ignore

    prune_compose(compose_path, keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
