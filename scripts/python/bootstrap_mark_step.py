import json
import sys
import time
from pathlib import Path


def load_state(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def write_state(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def mark_step(path_str: str, step: str, status: str) -> int:
    target = Path(path_str)
    if status == "reset":
        if not target.exists():
            return 0
        data = load_state(target)
        steps = data.get("steps", {})
        if not isinstance(steps, dict):
            steps = {}
        if step in steps:
            steps.pop(step, None)
            data["steps"] = steps
        write_state(target, data)
        return 0

    data = load_state(target)
    steps = data.setdefault("steps", {})
    if not isinstance(steps, dict):
        steps = {}
        data["steps"] = steps
    steps[step] = {
        "status": status,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if status == "done":
        data["last_completed"] = step
    elif status == "failed":
        data["failed_step"] = step
    else:
        data.pop("failed_step", None)
    write_state(target, data)
    return 0


def main() -> int:
    if len(sys.argv) < 4:
        return 1
    file_path, step, status = sys.argv[1:4]
    return mark_step(file_path, step, status)


if __name__ == "__main__":
    raise SystemExit(main())
