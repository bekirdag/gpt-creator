#!/usr/bin/env python3
import base64
import json
import sys
from pathlib import Path


def sha256(data: bytes) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def externalize(json_path: Path, run_dir: Path, project_root: Path) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
    changes = data.get("changes") or []
    out_changes = []

    blobs_dir = run_dir / "blobs"
    patches_dir = run_dir / "patches"

    for idx, change in enumerate(changes, 1):
        if isinstance(change, str) and change.startswith("--- "):
            payload = change.encode("utf-8", "ignore")
            fingerprint = sha256(payload)[:16]
            patch_path = patches_dir / f"patch_{idx}_{fingerprint}.patch"
            write_text(patch_path, change)
            out_changes.append(
                {"type": "patch", "patch_path": relpath(patch_path, project_root)}
            )
            continue

        if isinstance(change, dict):
            if "contents_path" in change or "patch_path" in change:
                out_changes.append(change)
                continue

            if "path" in change and "contents" in change:
                contents = change.get("contents", "")
                encoding = change.get("encoding")
                if encoding == "base64":
                    try:
                        contents = base64.b64decode(contents).decode("utf-8", "ignore")
                    except Exception:
                        contents = ""
                elif not isinstance(contents, str):
                    contents = json.dumps(contents, ensure_ascii=False)

                payload = contents.encode("utf-8", "ignore")
                fingerprint = sha256(payload)[:16]
                ext = Path(change["path"]).suffix or ".txt"
                blob_path = blobs_dir / f"{fingerprint}{ext}"
                write_text(blob_path, contents)

                updated = {
                    key: value
                    for key, value in change.items()
                    if key not in ("contents", "encoding")
                }
                updated["contents_path"] = relpath(blob_path, project_root)
                out_changes.append(updated)
                continue

        out_changes.append(change)

    data["changes"] = out_changes
    json_path.write_text(
        json.dumps(data, ensure_ascii=True, separators=(",", ":")),
        encoding="ascii",
    )


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        sys.stderr.write(
            "usage: wot_externalize_blobs.py <envelope.json> <run_dir> <project_root>\n"
        )
        return 2
    json_path = Path(argv[1])
    run_dir = Path(argv[2])
    project_root = Path(argv[3])
    externalize(json_path, run_dir, project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
