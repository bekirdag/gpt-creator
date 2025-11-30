#!/usr/bin/env python3
"""
Lightweight helper to resolve LLM output token limits.

Reads `.gpt-creator/config.yml` if available (expects optional PyYAML),
merges with defaults, and prints a tab-separated list of `key=value` pairs
for shell consumers. Missing config or parse errors fall back to defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

DEFAULT_LIMITS: Dict[str, int] = {
    "plan": 450,
    "status": 350,
    "verify": 500,
    "patch": 7000,
    "hard_cap": 12000,
}


def load_yaml_config(config_path: Path) -> Dict[str, Any]:
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
        loaded = yaml.safe_load(text)  # type: ignore[attr-defined]
    except Exception:
        # fall back to empty config on parse errors
        return {}
    return loaded if isinstance(loaded, dict) else {}


def resolve_limits(raw_config: Dict[str, Any]) -> Dict[str, int]:
    limits = DEFAULT_LIMITS.copy()
    llm_cfg = raw_config.get("llm")
    if isinstance(llm_cfg, dict):
        maybe_limits = llm_cfg.get("output_limits")
        if isinstance(maybe_limits, dict):
            for key in ("plan", "status", "verify", "patch", "hard_cap"):
                if key in maybe_limits:
                    value = maybe_limits[key]
                    try:
                        parsed = int(value)
                    except (TypeError, ValueError):
                        continue
                    if parsed > 0:
                        limits[key] = parsed
    return limits


def main() -> int:
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    config_path = project_root / ".gpt-creator" / "config.yml"
    raw_config = load_yaml_config(config_path)
    limits = resolve_limits(raw_config)
    for key in ("plan", "status", "verify", "patch", "hard_cap"):
        value = limits.get(key)
        if value is None:
            continue
        sys.stdout.write(f"{key}={int(value)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
