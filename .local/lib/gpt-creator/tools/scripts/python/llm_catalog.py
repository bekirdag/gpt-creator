#!/usr/bin/env python3
"""Fetch and cache the Catwalk LLM catalog."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback handled below
    httpx = None  # type: ignore

from agents.llm_store import LLMCatalogStore

CATALOG_URL = os.getenv("GC_LLM_CATALOG_URL", "https://catwalk.charm.sh/v2/providers")
DEFAULT_TTL_SECONDS = int(os.getenv("GC_LLM_CATALOG_TTL", "86400"))


def _default_cache_path() -> Path:
    override = os.getenv("GC_LLM_CATALOG_CACHE", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".config" / "gpt-creator" / "cache" / "llm_catalog.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _strip_env_placeholder(value: Optional[str]) -> str:
    if not value:
        return ""
    text = value.strip()
    if text.startswith("$"):
        return text[1:]
    return text


def _normalize_model(raw: Dict[str, Any]) -> Dict[str, Any]:
    model_id = (raw.get("id") or raw.get("name") or "").strip()
    name = (raw.get("name") or model_id).strip()
    payload = {
        "id": model_id,
        "name": name,
        "contextWindow": raw.get("context_window"),
        "defaultMaxTokens": raw.get("default_max_tokens"),
        "canReason": raw.get("can_reason"),
        "supportsAttachments": raw.get("supports_attachments"),
        "costPer1MIn": raw.get("cost_per_1m_in"),
        "costPer1MOut": raw.get("cost_per_1m_out"),
        "costPer1MInCached": raw.get("cost_per_1m_in_cached"),
        "costPer1MOutCached": raw.get("cost_per_1m_out_cached"),
        "reasoningLevels": raw.get("reasoning_levels") or [],
        "defaultReasoningEffort": raw.get("default_reasoning_effort"),
        "options": raw.get("options") or {},
    }
    return payload


def _normalize_provider(raw: Dict[str, Any]) -> Dict[str, Any]:
    provider_id = (raw.get("id") or raw.get("name") or "").strip()
    name = (raw.get("name") or provider_id).strip()
    models = [_normalize_model(entry) for entry in (raw.get("models") or [])]
    return {
        "id": provider_id,
        "name": name,
        "type": (raw.get("type") or "").strip(),
        "apiKeyHint": _strip_env_placeholder(raw.get("api_key")),
        "apiEndpointHint": _strip_env_placeholder(raw.get("api_endpoint")),
        "defaultLargeModel": raw.get("default_large_model_id") or "",
        "defaultSmallModel": raw.get("default_small_model_id") or "",
        "models": models,
        "adapter": raw.get("adapter"),
        "source": raw.get("source") or "catalog",
        "fetched_at": raw.get("fetched_at"),
    }


def _fetch_remote(url: str) -> List[Dict[str, Any]]:
    if httpx is not None:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
    else:  # pragma: no cover - exercised in environments without httpx
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "gpt-creator/llm-catalog"})
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:  # type: ignore[attr-defined]
            raise RuntimeError(f"Catalog request failed: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("Catalog payload must be a list")
    return payload


def _write_cache(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_cache(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_catalog(
    *,
    refresh: bool = False,
    cache_path: Optional[Path] = None,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Return catalog data (providers + metadata)."""
    path = cache_path or _default_cache_path()
    ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS
    cache_data = _read_cache(path)
    if not refresh and cache_data:
        fetched_at = cache_data.get("fetched_at", "")
        fetched_dt = _parse_iso(fetched_at)
        if fetched_dt and (datetime.now(timezone.utc) - fetched_dt).total_seconds() < ttl:
            cache_data["source"] = "cache"
            cache_data["cache_path"] = str(path)
            cache_data.setdefault("providers", [])
            return cache_data
    try:
        raw = _fetch_remote(CATALOG_URL)
        providers = [_normalize_provider(entry) for entry in raw]
        payload = {
            "providers": providers,
            "fetched_at": _now_iso(),
            "ttl_seconds": ttl,
            "source": "network",
            "cache_path": str(path),
        }
        _write_cache(path, payload)
        return payload
    except Exception:
        if cache_data:
            cache_data["source"] = "cache-fallback"
            cache_data["cache_path"] = str(path)
            cache_data.setdefault("providers", [])
            return cache_data
        raise


def _cli_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    providers = data.get("providers") or []
    return {
        "providers": len(providers),
        "fetched_at": data.get("fetched_at"),
        "source": data.get("source"),
        "cache_path": data.get("cache_path"),
        "ttl_seconds": data.get("ttl_seconds", DEFAULT_TTL_SECONDS),
    }


def _sync_db_if_requested(data: Dict[str, Any], db_path_arg: Optional[str]) -> None:
    if not db_path_arg:
        return
    providers = data.get("providers") or []
    if not providers:
        return
    store = LLMCatalogStore(Path(db_path_arg))
    store.sync(
        providers,
        source=data.get("source") or "catalog",
        fetched_at=data.get("fetched_at"),
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Catwalk LLM catalog.")
    parser.add_argument("--refresh", action="store_true", help="Force refresh ignoring cache TTL.")
    parser.add_argument("--cache-path", help="Override cache path.")
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS, help="TTL in seconds for cached catalog (default: 86400).")
    parser.add_argument("--json", action="store_true", help="Print raw providers JSON instead of summary.")
    parser.add_argument("--db-path", help="Optional tasks.db path to persist providers/models tables.")
    args = parser.parse_args(argv)
    cache_override = Path(args.cache_path) if args.cache_path else None
    try:
        data = load_catalog(refresh=args.refresh, cache_path=cache_override, ttl_seconds=args.ttl)
    except Exception as exc:
        print(f"Catalog sync failed: {exc}", file=os.sys.stderr)
        return 1
    try:
        _sync_db_if_requested(data, args.db_path)
    except Exception as exc:
        print(f"Catalog database sync failed: {exc}", file=os.sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(json.dumps(_cli_summary(data), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
