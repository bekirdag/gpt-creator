#!/usr/bin/env python3
"""
Load budget configuration from .gpt-creator/config.yml with sensible defaults.
Outputs a JSON object to stdout so shell callers can parse limits and policies.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

DEFAULT_STAGE_LIMITS = {
    "retrieve": 8000,
    "plan": 10000,
    "patch": 20000,
    "verify": 8000,
}

DEFAULT_OFFENDER_CFG = {
    "window_runs": 10,
    "top_k": 3,
    "auto_abandon": True,
    "dominance_threshold": 0.5,
    "actions": {},
}


def load_yaml_config(project_root: Path) -> Dict[str, Any]:
    config_path = project_root / ".gpt-creator" / "config.yml"
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    try:
        data = yaml.safe_load(text)  # type: ignore[attr-defined]
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def normalise_stage_limits(raw: Any) -> Dict[str, int]:
    limits: Dict[str, int] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                limits[str(key)] = number
    return limits


def normalise_offender_cfg(raw: Any) -> Dict[str, Any]:
    cfg = DEFAULT_OFFENDER_CFG.copy()
    if isinstance(raw, dict):
        window = raw.get("window_runs")
        if isinstance(window, int) and window > 0:
            cfg["window_runs"] = window
        top_k = raw.get("top_k")
        if isinstance(top_k, int) and top_k > 0:
            cfg["top_k"] = top_k
        auto = raw.get("auto_abandon")
        if isinstance(auto, bool):
            cfg["auto_abandon"] = auto
        elif isinstance(auto, str):
            cfg["auto_abandon"] = auto.strip().lower() in {"1", "true", "yes", "on"}
        threshold = raw.get("dominance_threshold")
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            value = cfg["dominance_threshold"]
        if 0.0 < value <= 1.0:
            cfg["dominance_threshold"] = value
        actions = raw.get("actions")
        if isinstance(actions, dict):
            cfg["actions"] = {str(k): str(v) for k, v in actions.items()}
    return cfg


def main() -> int:
    project_root = Path(os.getcwd())
    argv = sys.argv
    if len(argv) > 1:
        project_root = Path(argv[1]).resolve()
    config_root = load_yaml_config(project_root)
    budget_cfg = config_root.get("budget") if isinstance(config_root, dict) else None

    stage_limits = DEFAULT_STAGE_LIMITS.copy()
    offender_cfg = DEFAULT_OFFENDER_CFG.copy()

    if isinstance(budget_cfg, dict):
        custom_limits = normalise_stage_limits(budget_cfg.get("per_stage_limits"))
        stage_limits.update(custom_limits)
        offender_cfg = normalise_offender_cfg(budget_cfg.get("offenders"))

    payload = {
        "per_stage_limits": stage_limits,
        "offenders": offender_cfg,
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
