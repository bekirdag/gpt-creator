#!/usr/bin/env python3
"""
Wait for MySQL inside a container to respond to mysqladmin ping.
"""

from __future__ import annotations

import subprocess
import sys
import time


def is_mysql_ready(container: str) -> bool:
    cmd = [
        "docker",
        "exec",
        "-i",
        container,
        "sh",
        "-lc",
        "mysqladmin ping -h 127.0.0.1 --silent",
    ]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: wait_for_mysql.py <container> <timeout_seconds> <interval_seconds>", file=sys.stderr)
        return 1
    container = argv[0]
    timeout = float(argv[1])
    interval = float(argv[2])

    start = time.time()
    while time.time() - start < timeout:
        if is_mysql_ready(container):
            return 0
        time.sleep(max(interval, 0.1))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
