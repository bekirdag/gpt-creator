import json
import sys
from pathlib import Path


def count_story_tasks(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    tasks = payload.get("tasks")
    if isinstance(tasks, list):
        return len(tasks)
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        return 1

    path = Path(sys.argv[1])
    total = count_story_tasks(path)
    print(total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
