from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from ensure_agents_schema import ensure_agents_schema
from .model import (
    Agent,
    AgentCreate,
    AgentFilter,
    AgentUpdate,
    LLMFilter,
    LLMInfo,
    iso_timestamp,
)


class AgentRepository:
    def __init__(self, db_path: Path, read_only: bool = False):
        self.db_path = Path(db_path)
        self.read_only = read_only

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys = ON")
            except Exception:
                pass
            return conn
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_agents_schema(conn.cursor())
        conn.commit()
        return conn

    def ensure_schema(self) -> None:
        if not self.db_path.exists():
            return
        with self._connect():
            pass

    def _row_to_agent(self, row: sqlite3.Row) -> Agent:
        return Agent.from_row(row)

    def create(self, payload: AgentCreate) -> Agent:
        with self._connect() as conn:
            agent_id = str(uuid.uuid4())
            now = iso_timestamp()
            normalized = payload.name.strip().lower()
            try:
                conn.execute(
                """
                INSERT INTO agents (
                  id, name, name_normalized, client, model,
                  llm_provider_id, llm_model_id,
                  client_api_key, client_api_base, client_api_org,
                  job_doc, job_doc_sha256, job_summary,
                  character_doc, character_doc_sha256, character_summary,
                  tags_json, custom_guardrails, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    payload.name,
                    normalized,
                    payload.client,
                    payload.model,
                    payload.llm_provider_id,
                    payload.llm_model_id,
                    payload.client_api_key,
                    payload.client_api_base,
                    payload.client_api_org,
                    payload.job_doc,
                    payload.job_doc_sha256,
                    payload.job_summary,
                    payload.character_doc,
                    payload.character_doc_sha256,
                    payload.character_summary,
                    payload.tags_json or "[]",
                    payload.guardrails,
                    now,
                    now,
                ),
            )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Agent with that name already exists") from exc
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return self._row_to_agent(row)

    def list(self, filters: Optional[AgentFilter] = None) -> List[Agent]:
        filters = filters or AgentFilter()
        clauses: List[str] = []
        params: List[object] = []
        if filters.client:
            clauses.append("client = ?")
            params.append(filters.client)
        if filters.model:
            clauses.append("model = ?")
            params.append(filters.model)
        if filters.active is True:
            clauses.append("is_active = 1")
        elif filters.active is False:
            clauses.append("is_active = 0")
        if filters.name_like:
            clauses.append("name_normalized LIKE ?")
            params.append(f"%{filters.name_like.lower()}%")
        if filters.tags:
            for tag in filters.tags:
                clauses.append("tags_json LIKE ?")
                params.append(f'%"{tag}"%')
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_clause = f"LIMIT {int(filters.limit)}" if filters.limit else ""
        query = f"SELECT * FROM agents {where} ORDER BY name COLLATE NOCASE ASC {limit_clause}"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_agent(row) for row in rows]

    def get_by_name(self, name: str) -> Optional[Agent]:
        normalized = (name or "").strip().lower()
        if not normalized:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE name_normalized = ?", (normalized,)
            ).fetchone()
            return self._row_to_agent(row) if row else None

    def list_llms(self, filters: Optional[LLMFilter] = None) -> List[LLMInfo]:
        filters = filters or LLMFilter()
        clauses: List[str] = []
        params: List[object] = []
        if filters.provider:
            clauses.append("p.id = ?")
            params.append(filters.provider)
        if filters.adapter:
            clauses.append("p.adapter = ?")
            params.append(filters.adapter)
        if filters.source:
            clauses.append("p.source = ?")
            params.append(filters.source)
        if filters.model:
            clauses.append("m.model_id = ?")
            params.append(filters.model)
        if filters.name_like:
            clauses.append("(p.name LIKE ? OR m.name LIKE ? OR m.model_id LIKE ?)")
            token = f"%{filters.name_like}%"
            params.extend([token, token, token])
        if filters.statuses:
            normalized = [status.strip().lower() for status in filters.statuses if status and status.strip()]
            if normalized:
                regular = [status for status in normalized if status != "unknown"]
                status_parts: List[str] = []
                if regular:
                    placeholders = ",".join("?" for _ in regular)
                    status_parts.append(f"LOWER(IFNULL(p.install_status, '')) IN ({placeholders})")
                    params.extend(regular)
                if "unknown" in normalized:
                    status_parts.append("(p.install_status IS NULL OR TRIM(p.install_status) = '')")
                if status_parts:
                    clauses.append(f"({' OR '.join(status_parts)})")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_clause = f"LIMIT {int(filters.limit)}" if filters.limit else ""
        query = f"""
        SELECT
          p.id AS provider_id,
          p.name AS provider_name,
          p.adapter AS adapter,
          p.source AS source,
          p.install_status AS install_status,
          p.install_checked_at AS install_checked_at,
          p.install_hint AS install_hint,
          m.model_id AS model_id,
          m.name AS model_name,
          m.context_window AS context_window,
          m.default_max_tokens AS default_max_tokens,
          p.metadata_json AS metadata_json
        FROM llm_models m
        JOIN llm_providers p ON p.id = m.provider_id
        {where_clause}
        ORDER BY p.name COLLATE NOCASE ASC, m.model_id COLLATE NOCASE ASC
        {limit_clause}
        """
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            results: List[LLMInfo] = []
            for row in rows:
                metadata = {}
                raw_metadata = row["metadata_json"]
                if raw_metadata:
                    try:
                        metadata = json.loads(raw_metadata)
                    except Exception:
                        metadata = {}
                results.append(
                    LLMInfo(
                        provider_id=row["provider_id"],
                        provider_name=row["provider_name"],
                        adapter=row["adapter"],
                        source=row["source"],
                        install_status=row["install_status"],
                        install_checked_at=row["install_checked_at"],
                        install_hint=row["install_hint"],
                        model_id=row["model_id"],
                        model_name=row["model_name"],
                        context_window=row["context_window"],
                        default_max_tokens=row["default_max_tokens"],
                        metadata=metadata,
                    )
                )
            return results

    def list_llm_providers(
        self,
        *,
        provider_id: Optional[str] = None,
        adapter: Optional[str] = None,
    ) -> List[dict]:
        clauses: List[str] = []
        params: List[object] = []
        if provider_id:
            clauses.append("id = ?")
            params.append(provider_id)
        if adapter:
            clauses.append("adapter = ?")
            params.append(adapter)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
        SELECT id, name, adapter, source, metadata_json,
               install_status, install_checked_at, install_hint,
               install_command, install_command_macos, install_command_windows
          FROM llm_providers
          {where_clause}
          ORDER BY name COLLATE NOCASE ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            records = []
            for row in rows:
                records.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "adapter": row["adapter"],
                        "source": row["source"],
                        "metadata_json": row["metadata_json"],
                        "install_status": row["install_status"],
                        "install_checked_at": row["install_checked_at"],
                        "install_hint": row["install_hint"],
                        "install_command": row["install_command"],
                        "install_command_macos": row["install_command_macos"],
                        "install_command_windows": row["install_command_windows"],
                    }
                )
            return records

    def update_llm_install_status(
        self,
        provider_id: str,
        *,
        status: str,
        hint: Optional[str],
        checked_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE llm_providers
                   SET install_status = ?,
                       install_checked_at = ?,
                       install_hint = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (status, checked_at, hint, iso_timestamp(), provider_id),
            )

    def get_by_id(self, agent_id: str) -> Optional[Agent]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return self._row_to_agent(row) if row else None

    def update(self, agent_name: str, patch: AgentUpdate) -> Agent:
        if patch.is_empty():
            raise ValueError("No changes specified")
        normalized = agent_name.strip().lower()
        assignments = []
        params: List[object] = []
        for key, value in patch.fields.items():
            assignments.append(f"{key} = ?")
            params.append(value)
        assignments.append("updated_at = ?")
        params.append(iso_timestamp())
        params.append(normalized)
        with self._connect() as conn:
            ensure_agents_schema(conn.cursor())
            conn.execute(
                f"""
                UPDATE agents
                   SET {', '.join(assignments)}
                 WHERE name_normalized = ?
                """,
                tuple(params),
            )
            row = conn.execute(
                "SELECT * FROM agents WHERE name_normalized = ?", (normalized,)
            ).fetchone()
            if not row:
                raise ValueError(f"Agent '{agent_name}' not found")
            return self._row_to_agent(row)

    def soft_delete(self, agent_name: str) -> Agent:
        return self.update(agent_name, AgentUpdate({"is_active": 0}))

    def reinstate(self, agent_name: str) -> Agent:
        return self.update(agent_name, AgentUpdate({"is_active": 1}))

    def hard_delete(self, agent_name: str) -> None:
        normalized = agent_name.strip().lower()
        with self._connect() as conn:
            conn.execute("DELETE FROM agents WHERE name_normalized = ?", (normalized,))

    def touch_last_used(self, agent_name: str) -> None:
        normalized = agent_name.strip().lower()
        with self._connect() as conn:
            conn.execute(
                "UPDATE agents SET last_used_at = ?, updated_at = ? WHERE name_normalized = ?",
                (iso_timestamp(), iso_timestamp(), normalized),
            )
