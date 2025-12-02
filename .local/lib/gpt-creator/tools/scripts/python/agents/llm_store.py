from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ensure_agents_schema import ensure_agents_schema
from .model import iso_timestamp

if TYPE_CHECKING:  # pragma: no cover
    from agents_registry import AgentRegistry


class LLMCatalogStore:
    """Persist synced LLM catalog data inside tasks.db."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def sync(self, providers: List[Dict[str, Any]], *, source: str, fetched_at: Optional[str]) -> None:
        if not providers:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.cursor()
            ensure_agents_schema(cur)
            conn.execute("PRAGMA foreign_keys = OFF")
            cur.execute(
                "SELECT id, install_status, install_checked_at, install_hint, install_command, install_command_macos, install_command_windows FROM llm_providers"
            )
            existing_status = {
                row[0]: {
                    "install_status": row[1],
                    "install_checked_at": row[2],
                    "install_hint": row[3],
                    "install_command": row[4],
                    "install_command_macos": row[5],
                    "install_command_windows": row[6],
                }
                for row in cur.fetchall()
            }
            cur.execute("DELETE FROM llm_models")
            provider_rows = []
            model_rows = []
            for provider in providers:
                provider_id = (provider.get("id") or "").strip()
                if not provider_id:
                    continue
                preserved = existing_status.get(provider_id, {})
                commands = provider.get("installCommands") or {}
                provider_rows.append(
                    (
                        provider_id,
                        provider.get("name") or provider_id,
                        provider.get("type") or "",
                        provider.get("adapter") or "",
                        provider.get("source") or source or "catalog",
                        provider.get("fetched_at") or fetched_at,
                        provider.get("apiKeyHint") or "",
                        provider.get("apiEndpointHint") or "",
                        json.dumps(provider),
                        preserved.get("install_status") or "unknown",
                        preserved.get("install_checked_at"),
                        preserved.get("install_hint") or provider.get("install_hint"),
                        preserved.get("install_command") or provider.get("install_command") or commands.get("default"),
                        preserved.get("install_command_macos") or provider.get("install_command_macos") or commands.get("macos"),
                        preserved.get("install_command_windows") or provider.get("install_command_windows") or commands.get("windows"),
                    )
                )
                for model in provider.get("models") or []:
                    model_id = (model.get("id") or "").strip()
                    if not model_id:
                        continue
                    model_rows.append(
                        (
                            provider_id,
                            model_id,
                            model.get("name") or model_id,
                            model.get("contextWindow"),
                            model.get("defaultMaxTokens"),
                            _bool_to_int(model.get("canReason")),
                            _bool_to_int(model.get("supportsAttachments")),
                            json.dumps(model),
                        )
                    )
            now = iso_timestamp()
            if provider_rows:
                cur.executemany(
                    """
                    INSERT INTO llm_providers (
                        id, name, type, adapter, source, fetched_at,
                        api_key_hint, api_endpoint_hint, metadata_json,
                        install_status, install_checked_at, install_hint,
                        install_command, install_command_macos, install_command_windows,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        type=excluded.type,
                        adapter=excluded.adapter,
                        source=excluded.source,
                        fetched_at=excluded.fetched_at,
                        api_key_hint=excluded.api_key_hint,
                        api_endpoint_hint=excluded.api_endpoint_hint,
                        metadata_json=excluded.metadata_json,
                        install_status=excluded.install_status,
                        install_checked_at=COALESCE(excluded.install_checked_at, llm_providers.install_checked_at),
                        install_hint=COALESCE(excluded.install_hint, llm_providers.install_hint),
                        install_command=COALESCE(excluded.install_command, llm_providers.install_command),
                        install_command_macos=COALESCE(excluded.install_command_macos, llm_providers.install_command_macos),
                        install_command_windows=COALESCE(excluded.install_command_windows, llm_providers.install_command_windows),
                        created_at=COALESCE(llm_providers.created_at, excluded.created_at),
                        updated_at=excluded.updated_at
                    """,
                    [
                        row + (now, now)  # type: ignore[operator]
                        for row in provider_rows
                    ],
                )
            if model_rows:
                cur.executemany(
                    """
                    INSERT INTO llm_models (
                        provider_id, model_id, name,
                        context_window, default_max_tokens,
                        can_reason, supports_attachments,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    model_rows,
                )
            conn.commit()
        finally:
            try:
                conn.execute("PRAGMA foreign_keys = ON")
            except Exception:
                pass
            conn.close()

    def ensure_provider_model(
        self,
        provider_id: str,
        provider_name: str,
        *,
        adapter: Optional[str] = None,
        source: str = "registry",
        model_id: str,
        model_name: str,
        provider_metadata: Optional[Dict[str, Any]] = None,
        model_metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        provider_id = provider_id.strip()
        model_id = model_id.strip()
        if not provider_id or not model_id:
            return provider_id, model_id
        provider_payload = provider_metadata or {}
        model_payload = model_metadata or {}
        provider_payload.setdefault("id", provider_id)
        provider_payload.setdefault("name", provider_name)
        model_payload.setdefault("id", model_id)
        model_payload.setdefault("name", model_name)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.cursor()
            ensure_agents_schema(cur)
            conn.execute("PRAGMA foreign_keys = OFF")
            now = iso_timestamp()
            cur.execute(
                """
                SELECT install_status, install_checked_at, install_hint,
                       install_command, install_command_macos, install_command_windows
                  FROM llm_providers WHERE id = ?
                """,
                (provider_id,),
            )
            existing = cur.fetchone()
            install_status = existing[0] if existing and existing[0] else "unknown"
            install_checked_at = existing[1] if existing else None
            install_hint = existing[2] if existing else None
            existing_cmd = existing[3] if existing else None
            existing_cmd_macos = existing[4] if existing else None
            existing_cmd_windows = existing[5] if existing else None
            cur.execute(
                """
                INSERT INTO llm_providers (
                    id, name, type, adapter, source, fetched_at,
                    api_key_hint, api_endpoint_hint, metadata_json,
                    install_status, install_checked_at, install_hint,
                    install_command, install_command_macos, install_command_windows,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  type=excluded.type,
                  adapter=excluded.adapter,
                  source=excluded.source,
                  metadata_json=excluded.metadata_json,
                  updated_at=excluded.updated_at
                """,
                (
                    provider_id,
                    provider_name,
                    provider_payload.get("type") or "",
                    adapter or provider_payload.get("adapter") or "",
                    source or provider_payload.get("source") or "registry",
                    provider_payload.get("fetched_at"),
                    provider_payload.get("apiKeyHint") or "",
                    provider_payload.get("apiEndpointHint") or "",
                    json.dumps(provider_payload),
                    install_status,
                    install_checked_at,
                    install_hint,
                    existing_cmd or provider_payload.get("install_command") or "",
                    existing_cmd_macos or provider_payload.get("install_command_macos") or "",
                    existing_cmd_windows or provider_payload.get("install_command_windows") or "",
                    now,
                    now,
                ),
            )
            cur.execute(
                """
                INSERT INTO llm_models (
                  provider_id, model_id, name,
                  context_window, default_max_tokens,
                  can_reason, supports_attachments,
                  metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, model_id) DO UPDATE SET
                  name=excluded.name,
                  context_window=excluded.context_window,
                  default_max_tokens=excluded.default_max_tokens,
                  can_reason=excluded.can_reason,
                  supports_attachments=excluded.supports_attachments,
                  metadata_json=excluded.metadata_json
                """,
                (
                    provider_id,
                    model_id,
                    model_name,
                    model_payload.get("contextWindow"),
                    model_payload.get("defaultMaxTokens"),
                    _bool_to_int(model_payload.get("canReason")),
                    _bool_to_int(model_payload.get("supportsAttachments")),
                    json.dumps(model_payload),
                ),
            )
            conn.commit()
        finally:
            try:
                conn.execute("PRAGMA foreign_keys = ON")
            except Exception:
                pass
            conn.close()
        return provider_id, model_id

    def seed_from_registry(
        self,
        registry: AgentRegistry,
        *,
        provider_filter: Optional[str] = None,
        model_filter: Optional[str] = None,
    ) -> int:
        count = 0
        clients = registry.list_clients()
        for entry in clients:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            if provider_filter and name.lower() != provider_filter.lower():
                continue
            models = entry.get("models") or []
            if not models:
                default_model = entry.get("defaultModel")
                if default_model:
                    models = [default_model]
            for model in models:
                if model_filter and model != model_filter:
                    continue
                cfg = registry.get_client_config(name)
                adapter = cfg.adapter if cfg else entry.get("adapter")
                install_commands = cfg.install_commands if cfg else entry.get("installCommands") or {}
                provider_meta = {
                    "adapter": adapter,
                    "installCommands": install_commands,
                    "install_command": install_commands.get("default"),
                    "install_command_macos": install_commands.get("macos"),
                    "install_command_windows": install_commands.get("windows"),
                    "apiKeyEnv": cfg.api_key_env if cfg else "",
                    "envVars": cfg.env_vars if cfg else [],
                }
                self.ensure_provider_model(
                    name,
                    entry.get("label") or name,
                    adapter=adapter,
                    source="registry",
                    model_id=model,
                    model_name=model,
                    provider_metadata=provider_meta,
                    model_metadata={"id": model, "name": model, "source": "registry"},
                )
                count += 1
        return count


def _bool_to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    return 1 if bool(value) else 0
