import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import budget_offenders  # noqa: E402
import generate_budget_report  # noqa: E402
import load_budget_config  # noqa: E402
import load_output_limits  # noqa: E402


def _run_python_script(script: Path, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(script), *[str(arg) for arg in args]]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
        check=True,
    )


def test_load_output_limits_cli(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    script_path = SCRIPTS_DIR / "load_output_limits.py"

    result_defaults = _run_python_script(script_path, [project_root])
    lines = [line for line in result_defaults.stdout.splitlines() if line.strip()]
    defaults_map = dict(line.split("=", 1) for line in lines)
    for key, value in load_output_limits.DEFAULT_LIMITS.items():
        assert int(defaults_map[key]) == value

    config_dir = project_root / ".gpt-creator"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.joinpath("config.yml").write_text(
        "\n".join(
            [
                "llm:",
                "  output_limits:",
                "    plan: 512",
                "    status: 420",
                "    verify: 777",
                "    patch: 9000",
                "    hard_cap: 9500",
            ]
        ),
        encoding="utf-8",
    )

    result_custom = _run_python_script(script_path, [project_root])
    custom_map = dict(line.split("=", 1) for line in result_custom.stdout.splitlines() if line.strip())
    assert custom_map == {"plan": "512", "status": "420", "verify": "777", "patch": "9000", "hard_cap": "9500"}


def test_load_budget_config_cli(tmp_path: Path):
    project_root = tmp_path / "root"
    project_root.mkdir()
    script_path = SCRIPTS_DIR / "load_budget_config.py"

    result_defaults = _run_python_script(script_path, [project_root])
    payload = json.loads(result_defaults.stdout)
    assert payload["per_stage_limits"] == load_budget_config.DEFAULT_STAGE_LIMITS
    assert payload["offenders"]["window_runs"] == load_budget_config.DEFAULT_OFFENDER_CFG["window_runs"]
    assert payload["offenders"]["auto_abandon"] is True

    config_dir = project_root / ".gpt-creator"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.joinpath("config.yml").write_text(
        "\n".join(
            [
                "budget:",
                "  per_stage_limits:",
                "    retrieve: 4000",
                "    plan: 12000",
                "  offenders:",
                "    window_runs: 5",
                "    top_k: 2",
                "    dominance_threshold: 0.7",
                "    auto_abandon: false",
                "    actions:",
                "      show-file: range-only",
                "      rg: narrow",
            ]
        ),
        encoding="utf-8",
    )

    result_custom = _run_python_script(script_path, [project_root])
    data = json.loads(result_custom.stdout)
    assert data["per_stage_limits"]["retrieve"] == 4000
    assert data["per_stage_limits"]["plan"] == 12000
    offenders = data["offenders"]
    assert offenders["window_runs"] == 5
    assert offenders["top_k"] == 2
    assert pytest.approx(offenders["dominance_threshold"], rel=1e-6) == 0.7
    assert offenders["auto_abandon"] is False
    assert offenders["actions"] == {"show-file": "range-only", "rg": "narrow"}


def test_budget_offenders_stage_and_tool_detection():
    entries = [
        {
            "run_id": "run-001",
            "ts": "2025-01-01T00:00:00Z",
            "stage": "plan",
            "total_tokens": 9000,
            "tool_bytes": {"show-file": 6000, "rg": 1000},
        },
        {
            "run_id": "run-001",
            "ts": "2025-01-01T00:02:00Z",
            "stage": "plan",
            "total_tokens": 7000,
            "tool_bytes": {"show-file": 2000},
        },
        {
            "run_id": "run-001",
            "ts": "2025-01-01T00:03:00Z",
            "stage": "verify",
            "total_tokens": 3000,
            "tool_bytes": {"tests": 5000},
        },
    ]
    grouped = budget_offenders.group_by_run(entries)
    assert "run-001" in grouped
    latest = grouped["run-001"]
    assert latest["stages"]["plan"] == 16000
    assert latest["tools"]["show-file"] == 8000

    stage_offenders = budget_offenders.detect_stage_offenders(latest, {"plan": 10000, "verify": 5000})
    assert stage_offenders == [{"stage": "plan", "total_tokens": 16000, "limit": 10000}]

    tool_offenders = budget_offenders.detect_tool_offenders(
        latest,
        top_k=2,
        dominance=0.5,
        actions={"show-file": "range-only", "tests": "summary"},
    )
    assert tool_offenders[0]["tool"] == "show-file"
    assert tool_offenders[0]["action"] == "range-only"
    assert 0.5 <= tool_offenders[0]["share"] <= 1.0


def test_generate_budget_report_highlights_limits():
    entries = [
        {
            "run_id": "run-xyz",
            "stage": "plan",
            "total_tokens": 12000,
            "duration_ms": 1800,
            "pruned_items": {"doc_snippets_elided": {"count": 2, "bytes": 4096}},
            "tool_bytes": {"show-file": 4096},
        },
        {
            "run_id": "run-xyz",
            "stage": "plan",
            "total_tokens": 4000,
            "duration_ms": 200,
            "pruned_items": {"segments_elided": {"count": 1, "bytes": 1024}},
        },
        {
            "run_id": "run-xyz",
            "stage": "verify",
            "total_tokens": 1000,
            "duration_ms": 600,
            "pruned_items": {"tests": {"count": 1}},
            "tool_bytes": {"tests": 2048},
            "blocked_quota": True,
        },
        {
            "run_id": "run-other",
            "stage": "plan",
            "total_tokens": 1000,
        },
    ]
    report = generate_budget_report.build_report(
        entries,
        "run-xyz",
        stage_limits={"plan": 10000, "verify": 2000},
        tool_actions={"show-file": "range-only", "tests": "summary"},
    )
    assert "| plan | 16.0K |" in report
    assert "over limit" in report
    assert "verify" in report and "blocked" in report
    assert "Top Burners" in report
    assert "`show-file`" in report and "remedy: range-only" in report
