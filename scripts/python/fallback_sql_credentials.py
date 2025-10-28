import re
import sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        return 1
    path = Path(sys.argv[1])
    try:
        text = path.read_text()
    except Exception:
        return 1
    user_match = re.search(r"CREATE USER IF NOT EXISTS '([^']+)'", text)
    password_match = re.search(r"IDENTIFIED BY '([^']+)'", text)
    if user_match and password_match:
        print(user_match.group(1))
        print(password_match.group(1))
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
