import json
import os
import sys
from pathlib import Path


def inspect_containers() -> int:
    raw = os.environ.get("INSPECT_JSON", "")
    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f"Unable to parse docker inspect output: {exc}")
        return 1

    if not isinstance(data, list):
        data = [data]

    if not data:
        print("No container state data returned by docker inspect.")
        return 1

    pending = []
    failures = []
    healthy = []

    for entry in data:
        name = (entry.get("Name") or "").lstrip("/")
        labels = entry.get("Config", {}).get("Labels", {}) or {}
        service = labels.get("com.docker.compose.service") or name
        state = entry.get("State") or {}
        status = (state.get("Status") or "").lower()
        health = (state.get("Health", {}).get("Status") or "").lower()
        exit_code = state.get("ExitCode")

        detail = f"{service}: status={status or 'unknown'}"
        if health:
            detail += f", health={health}"
        if exit_code not in (None, 0):
            detail += f", exit_code={exit_code}"

        if status == "running":
            if health in ("", "healthy"):
                healthy.append(detail)
            elif health == "starting":
                pending.append(detail)
            else:
                failures.append(detail)
        elif status in ("created", "starting"):
            pending.append(detail)
        else:
            failures.append(detail)

    if failures:
        print("Container failures detected:")
        for line in failures:
            print(f"  - {line}")
        return 1

    if pending:
        print("Containers still starting:")
        for line in pending:
            print(f"  - {line}")
        return 2

    print("All containers running and healthy:")
    for line in healthy:
        print(f"  - {line}")
    return 0


def main() -> int:
    return inspect_containers()


if __name__ == "__main__":
    raise SystemExit(main())
