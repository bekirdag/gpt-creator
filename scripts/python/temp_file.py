import os
import pathlib
import sys
import tempfile


def create_temp_file(dir_path: pathlib.Path, prefix: str, suffix: str) -> str:
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(dir_path))
    os.close(fd)
    return temp_path


def main() -> int:
    if len(sys.argv) < 4:
        return 1
    dir_path = pathlib.Path(sys.argv[1])
    prefix = sys.argv[2]
    suffix = sys.argv[3]
    print(create_temp_file(dir_path, prefix, suffix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
