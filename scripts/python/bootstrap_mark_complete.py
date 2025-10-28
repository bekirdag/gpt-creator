import json
import sys
import time
from pathlib import Path


def mark_complete(path_str: str) -> int:
    target = Path(path_str)
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        data = {}
    except Exception:
        data = {}
    data["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    return mark_complete(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
