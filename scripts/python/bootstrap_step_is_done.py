import json
import sys
from pathlib import Path


def check_step(path_str: str, step: str) -> int:
    file_path = Path(path_str)
    if not file_path.exists():
        return 1
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return 1
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    steps = data.get("steps") or {}
    if not isinstance(steps, dict):
        return 1
    status = steps.get(step, {}).get("status")
    return 0 if status == "done" else 1


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    return check_step(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    raise SystemExit(main())
