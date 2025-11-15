#!/usr/bin/env python3
"""Ensure the agents table exists inside tasks.db."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  client TEXT NOT NULL,
  model TEXT NOT NULL,
  llm_provider_id TEXT,
  llm_model_id TEXT,
  client_api_key TEXT,
  client_api_base TEXT,
  client_api_org TEXT,
  job_doc TEXT NOT NULL,
  job_doc_sha256 TEXT NOT NULL,
  job_summary TEXT NOT NULL,
  character_doc TEXT NOT NULL,
  character_doc_sha256 TEXT NOT NULL,
  character_summary TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  custom_guardrails TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  last_used_at TEXT,
  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (llm_provider_id, llm_model_id) REFERENCES llm_models(provider_id, model_id)
)
"""

CREATE_INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name_normalized ON agents(name_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_agents_client ON agents(client)",
    "CREATE INDEX IF NOT EXISTS idx_agents_model ON agents(model)",
    "CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_agents_last_used ON agents(last_used_at)",
)

CREATE_LLM_PROVIDERS_SQL = """
CREATE TABLE IF NOT EXISTS llm_providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT,
  adapter TEXT,
  source TEXT NOT NULL DEFAULT 'catalog',
  fetched_at TEXT,
  api_key_hint TEXT,
  api_endpoint_hint TEXT,
  metadata_json TEXT NOT NULL,
  install_status TEXT NOT NULL DEFAULT 'unknown',
  install_checked_at TEXT,
  install_hint TEXT,
  install_command TEXT,
  install_command_macos TEXT,
  install_command_windows TEXT,
  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""

CREATE_LLM_MODELS_SQL = """
CREATE TABLE IF NOT EXISTS llm_models (
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  name TEXT NOT NULL,
  context_window INTEGER,
  default_max_tokens INTEGER,
  can_reason INTEGER,
  supports_attachments INTEGER,
  metadata_json TEXT NOT NULL,
  PRIMARY KEY (provider_id, model_id),
  FOREIGN KEY (provider_id) REFERENCES llm_providers(id) ON DELETE CASCADE
)
"""

CREATE_LLM_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_llm_providers_type ON llm_providers(type)",
    "CREATE INDEX IF NOT EXISTS idx_llm_models_provider ON llm_models(provider_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_models_name ON llm_models(name)",
)


def ensure_agents_schema(cur: sqlite3.Cursor) -> None:
    """Create agents table + indexes when missing."""
    cur.execute(CREATE_TABLE_SQL)
    cur.execute("PRAGMA table_info(agents)")
    existing_cols = {row[1] for row in cur.fetchall()}
    optional_cols = {
        "client_api_key": "TEXT",
        "client_api_base": "TEXT",
        "client_api_org": "TEXT",
        "custom_guardrails": "TEXT",
        "llm_provider_id": "TEXT",
        "llm_model_id": "TEXT",
    }
    for column, definition in optional_cols.items():
        if column not in existing_cols:
            cur.execute(f"ALTER TABLE agents ADD COLUMN {column} {definition}")
    for statement in CREATE_INDEX_STATEMENTS:
        cur.execute(statement)
    cur.execute(CREATE_LLM_PROVIDERS_SQL)
    cur.execute(CREATE_LLM_MODELS_SQL)
    cur.execute("PRAGMA table_info(llm_providers)")
    provider_cols = {row[1] for row in cur.fetchall()}
    provider_optional = {
        "install_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "install_checked_at": "TEXT",
        "install_hint": "TEXT",
        "install_command": "TEXT",
        "install_command_macos": "TEXT",
        "install_command_windows": "TEXT",
    }
    for column, definition in provider_optional.items():
        if column not in provider_cols:
            cur.execute(f"ALTER TABLE llm_providers ADD COLUMN {column} {definition}")
    for statement in CREATE_LLM_INDEXES:
        cur.execute(statement)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: ensure_agents_schema.py <tasks.db>", file=sys.stderr)
        return 1

    db_path = Path(argv[0])
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        ensure_agents_schema(conn.cursor())
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
