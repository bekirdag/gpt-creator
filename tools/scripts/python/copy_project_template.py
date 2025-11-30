import shutil
import sys
from pathlib import Path


def copy_template(src_dir: Path, dest_dir: Path) -> None:
    for path in src_dir.rglob("*"):
        if path.name in {".git", ".DS_Store"}:
            continue
        rel = path.relative_to(src_dir)
        target = dest_dir / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            print(f"SKIP {rel}")
            continue
        shutil.copy2(path, target)
        print(f"COPY {rel}")


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    if not src.exists():
        return 1
    copy_template(src, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
