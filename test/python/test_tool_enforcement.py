import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"


def test_show_file_force_range(tmp_path: Path):
    big_file = tmp_path / "big.txt"
    big_file.write_text("\n".join(f"Line {i}" for i in range(1, 401)), encoding="utf-8")

    cache_dir = tmp_path / "cache"
    env = os.environ.copy()
    env.update(
        {
            "GC_SHOW_FILE_PROJECT": str(tmp_path),
            "GC_SHOW_FILE_PATH": str(big_file),
            "GC_SHOW_FILE_REL": "big.txt",
            "GC_SHOW_FILE_CACHE_DIR": str(cache_dir),
            "GC_SHOW_FILE_FORCE_RANGE": "1",
            "GC_SHOW_FILE_FORCE_HEAD": "50",
            "GC_SHOW_FILE_MAX_LINES": "400",
        }
    )

    script = SCRIPTS_DIR / "show_file.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    first_line = result.stdout.splitlines()[0]
    assert "lines 1-50" in first_line
    assert "Line 50" in result.stdout
    assert "Line 120" not in result.stdout


def test_focus_text_rg_narrow_adds_limits(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_path = tmp_path / "codex-output.json"
    payload = {
        "plan": [],
        "focus": [],
        "changes": [],
        "commands": ["rg foo"],
        "notes": [],
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")

    capture_path = tmp_path / "rg-capture.txt"
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    rg_stub = stub_dir / "rg"
    rg_stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "${GC_RG_CAPTURE:?}"\n',
        encoding="utf-8",
    )
    rg_stub.chmod(rg_stub.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env.update(
        {
            "GC_RG_NARROW": "1",
            "GC_RG_CAPTURE": str(capture_path),
            "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
        }
    )

    script = SCRIPTS_DIR / "focus_text.py"
    subprocess.run(
        [sys.executable, str(script), str(output_path), str(repo_root)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    executed = capture_path.read_text(encoding="utf-8").strip()
    assert "--max-count 200" in executed
    assert "--max-filesize 256K" in executed
