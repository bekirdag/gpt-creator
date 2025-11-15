import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "python" / "agents_cli.py"


def _project_paths(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    tasks_dir = project / ".gpt-creator" / "staging" / "plan" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return project


def _cli(project: Path, args: list[str], env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CLI_PATH), "--project", str(project)]
    cmd.extend(args)
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "test-key")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_create_list_show_select(tmp_path: Path):
    project = _project_paths(tmp_path)
    job_doc = tmp_path / "job.md"
    job_doc.write_text("Document role.\n", encoding="utf-8")
    char_doc = tmp_path / "char.md"
    char_doc.write_text("Personality description.\n", encoding="utf-8")

    create_result = _cli(
        project,
        [
            "create",
            "--name",
            "CLI-Agent",
            "--client",
            "openai",
            "--model",
            "gpt-5.1-codex",
            "--job-doc",
            str(job_doc),
            "--character-doc",
            str(char_doc),
        ],
    )
    assert create_result.returncode == 0

    create_json_result = _cli(
        project,
        [
            "create",
            "--name",
            "CLI-Agent-JSON",
            "--client",
            "openai",
            "--model",
            "gpt-5.1-codex",
            "--job-doc",
            str(job_doc),
            "--character-doc",
            str(char_doc),
            "--json",
        ],
    )
    assert create_json_result.returncode == 0
    create_json_payload = json.loads(create_json_result.stdout)
    assert create_json_payload["agent"]["name"] == "CLI-Agent-JSON"
    assert create_json_payload["warnings"] == []

    missing_key_result = _cli(
        project,
        [
            "create",
            "--name",
            "CLI-Agent-Missing",
            "--client",
            "openai",
            "--model",
            "gpt-5.1-codex",
            "--job-doc",
            str(job_doc),
            "--character-doc",
            str(char_doc),
            "--json",
            "--allow-missing-key",
        ],
        env_overrides={"OPENAI_API_KEY": ""},  # force missing key warning
    )
    assert missing_key_result.returncode == 0
    missing_payload = json.loads(missing_key_result.stdout)
    assert missing_payload["agent"]["name"] == "CLI-Agent-Missing"
    assert missing_payload["warnings"]

    list_result = _cli(project, ["list", "--json"])
    assert list_result.returncode == 0
    agents = json.loads(list_result.stdout)
    assert any(entry["name"] == "CLI-Agent" for entry in agents)

    show_result = _cli(project, ["show", "--name", "CLI-Agent", "--json"])
    payload = json.loads(show_result.stdout)
    assert payload["name"] == "CLI-Agent"

    select_result = _cli(project, ["select", "--name", "CLI-Agent", "--full"])
    select_payload = json.loads(select_result.stdout)
    assert select_payload["kind"] == "agent"
    assert "## Role / Job" in select_payload["prompt"]["header"]
    llm_result = _cli(project, ["llms", "--json"])
    assert llm_result.returncode == 0
    llm_entries = json.loads(llm_result.stdout)
    assert any(entry["provider"].lower() == "openai" for entry in llm_entries)
    assert "credential_warning" in llm_entries[0]

    install_preview = _cli(project, ["install-llm", "--provider", "openai", "--json"])
    assert install_preview.returncode == 0
    install_payload = json.loads(install_preview.stdout)
    assert install_payload["provider"].lower() == "openai"
    assert install_payload["commands"]["default"]
    assert "credential_warning" in install_payload

    sync_result = _cli(project, ["llms-sync", "--json"])
    assert sync_result.returncode == 0
    sync_payload = json.loads(sync_result.stdout)
    assert sync_payload["seeded"] >= 1
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_cmd = bin_dir / "codex"
    fake_cmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_cmd.chmod(0o755)
    env_override = {"PATH": f"{bin_dir}:{os.environ.get('PATH','')}"}
    check_result = _cli(project, ["llms-check", "--provider", "openai", "--json", "--dry-run"], env_overrides=env_override)
    assert check_result.returncode == 0
    check_payload = json.loads(check_result.stdout)
    assert check_payload[0]["status"] in {"installed", "not_applicable", "missing"}
    assert "credential_warning" in check_payload[0]
    assert "health_status" in check_payload[0]
    health_result = _cli(project, ["llms-check", "--provider", "openai", "--json", "--dry-run", "--health-check"], env_overrides=env_override)
    assert health_result.returncode == 0
    health_payload = json.loads(health_result.stdout)
    assert health_payload[0]["health_status"] in {"ok", "error", "skipped", "unavailable"}

    tasks_db = project / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"
    with sqlite3.connect(tasks_db) as conn:
        cursor = conn.execute("UPDATE llm_providers SET install_status = 'missing' WHERE id = ?", ("openai",))
        conn.commit()
        assert cursor.rowcount >= 1

    missing_result = _cli(project, ["llms", "--status", "missing", "--json"])
    assert missing_result.returncode == 0
    missing_payload = json.loads(missing_result.stdout)
    assert missing_payload
    assert all((entry.get("install_status") or "").lower() == "missing" for entry in missing_payload)

    needs_key_result = _cli(project, ["llms", "--needs-key", "--json"], env_overrides={"OPENAI_API_KEY": ""})
    assert needs_key_result.returncode == 0
    needs_key_payload = json.loads(needs_key_result.stdout)
    assert needs_key_payload
    assert all(entry.get("credential_warning") for entry in needs_key_payload)


def test_cli_export_import(tmp_path: Path):
    project_a = _project_paths(tmp_path / "A")
    job_doc = tmp_path / "job_a.md"
    job_doc.write_text("Agent Alpha role.\n", encoding="utf-8")
    char_doc = tmp_path / "char_a.md"
    char_doc.write_text("Alpha tone.\n", encoding="utf-8")
    _cli(
        project_a,
        [
            "create",
            "--name",
            "Alpha",
            "--client",
            "openai",
            "--model",
            "gpt-5.1-codex",
            "--job-doc",
            str(job_doc),
            "--character-doc",
            str(char_doc),
        ],
    )
    export_path = tmp_path / "agents.json"
    result = _cli(project_a, ["export", "--output", str(export_path)])
    assert result.returncode == 0
    assert export_path.exists()

    project_b = _project_paths(tmp_path / "B")
    import_result = _cli(project_b, ["import", "--input", str(export_path)])
    assert import_result.returncode == 0
    payload = json.loads(import_result.stdout)
    assert payload["imported"] == 1
