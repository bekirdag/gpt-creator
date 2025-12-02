import hashlib
import pathlib
import sys


def sha256_file(path: pathlib.Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    path = pathlib.Path(sys.argv[1])
    if not path.is_file():
        return 1
    print(sha256_file(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
