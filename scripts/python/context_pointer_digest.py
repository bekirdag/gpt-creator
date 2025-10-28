import hashlib
import os
from pathlib import Path


def main() -> int:
    path = Path(os.environ.get("GC_CONTEXT_POINTER_FILE", ""))
    chunk = b""
    try:
        with path.open("rb") as handle:
            chunk = handle.read(8192)
    except Exception:
        chunk = b""

    if not chunk:
        print("")
    else:
        print(hashlib.sha256(chunk).hexdigest()[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
