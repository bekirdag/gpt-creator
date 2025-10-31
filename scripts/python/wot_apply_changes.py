#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def apply_patch(repo: Path, patch_text: str) -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".patch") as tf:
        tf.write(patch_text)
        tf.flush()
        subprocess.run(
            ["git", "-C", str(repo), "apply", "--check", tf.name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(["git", "-C", str(repo), "apply", tf.name], check=True)
    os.unlink(tf.name)


def write_file(repo: Path, rel: str, contents: Any, encoding: str | None = None) -> None:
    path = (repo / rel).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if encoding == "base64":
        contents = base64.b64decode(contents).decode("utf-8", "ignore")
    Path(path).write_text(str(contents), encoding="utf-8")


def main(json_path: str, repo_path: str) -> int:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    repo = Path(repo_path).resolve()
    for change in data.get("changes") or []:
        if isinstance(change, str) and change.startswith("--- "):
            apply_patch(repo, change)
            continue

        if isinstance(change, dict):
            if change.get("type") == "patch" and "patch_path" in change:
                patch_file = (repo / change["patch_path"]).resolve()
                patch_text = patch_file.read_text(encoding="utf-8", errors="ignore")
                apply_patch(repo, patch_text)
                continue

            if "path" in change and "contents" in change:
                write_file(
                    repo,
                    change["path"],
                    change["contents"],
                    change.get("encoding"),
                )
                continue

            if "path" in change and "contents_path" in change:
                contents_file = (repo / change["contents_path"]).resolve()
                contents = contents_file.read_text(encoding="utf-8", errors="ignore")
                write_file(repo, change["path"], contents, None)
                continue
        else:
            continue
    return 0


if __name__ == "__main__":
    try:
        repo_arg = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
        sys.exit(main(sys.argv[1], repo_arg))
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr.decode())
        else:
            sys.stderr.write(str(exc))
        sys.exit(12)
