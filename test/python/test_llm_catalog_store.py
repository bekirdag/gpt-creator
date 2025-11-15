import sqlite3
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agents.llm_store import LLMCatalogStore  # type: ignore  # noqa: E402


def test_llm_catalog_store_sync(tmp_path: Path):
    db_path = tmp_path / "tasks.db"
    store = LLMCatalogStore(db_path)
    providers = [
        {
            "id": "openai",
            "name": "OpenAI",
            "type": "openai",
            "models": [
                {
                    "id": "gpt-5",
                    "name": "GPT-5",
                    "contextWindow": 400000,
                    "defaultMaxTokens": 128000,
                    "canReason": True,
                    "supportsAttachments": True,
                }
            ],
        }
    ]
    store.sync(providers, source="catalog", fetched_at="2024-01-01T00:00:00Z")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM llm_providers")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM llm_models")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT name FROM llm_models WHERE provider_id = 'openai'")
        assert cur.fetchone()[0] == "GPT-5"
    finally:
        conn.close()


def test_llm_catalog_store_ensure_provider_model(tmp_path: Path):
    db_path = tmp_path / "tasks.db"
    store = LLMCatalogStore(db_path)
    provider_id, model_id = store.ensure_provider_model(
        "openai",
        "OpenAI",
        adapter="command",
        source="registry",
        model_id="gpt-5.1-codex",
        model_name="GPT-5.1 Codex",
        provider_metadata={"type": "openai"},
        model_metadata={"contextWindow": 400000},
    )
    assert provider_id == "openai"
    assert model_id == "gpt-5.1-codex"
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT adapter FROM llm_providers WHERE id = 'openai'")
        assert cur.fetchone()[0] == "command"
        cur.execute("SELECT name FROM llm_models WHERE provider_id = 'openai' AND model_id = 'gpt-5.1-codex'")
        assert cur.fetchone()[0] == "GPT-5.1 Codex"
    finally:
        conn.close()
