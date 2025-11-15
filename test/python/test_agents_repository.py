import os
import sqlite3
from pathlib import Path

from scripts.python.agents.repository import AgentRepository
from scripts.python.agents.model import AgentCreate, AgentFilter, AgentUpdate


def _create_repo(tmp_path: Path) -> AgentRepository:
    db_path = tmp_path / "tasks.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agents ("
        "id TEXT PRIMARY KEY, name TEXT, name_normalized TEXT UNIQUE, client TEXT, model TEXT,"
        "client_api_key TEXT, client_api_base TEXT, client_api_org TEXT,"
        "job_doc TEXT, job_doc_sha256 TEXT, job_summary TEXT,"
        "character_doc TEXT, character_doc_sha256 TEXT, character_summary TEXT,"
        "tags_json TEXT, is_active INTEGER DEFAULT 1, last_used_at TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name_normalized ON agents(name_normalized)")
    conn.close()
    repo = AgentRepository(db_path)
    return repo


def sample_agent(name: str = "Fixer") -> AgentCreate:
    return AgentCreate(
        name=name,
        client="openai",
        model="gpt-5.1-codex",
        job_doc="Do the work.\n",
        job_doc_sha256="sha-job",
        job_summary="Do the work",
        character_doc="Be strict.\n",
        character_doc_sha256="sha-char",
        character_summary="Strict tone",
        tags_json='["fixer"]',
    )


def test_create_and_fetch(tmp_path: Path):
    os.environ["OPENAI_API_KEY"] = "test-key"
    repo = _create_repo(tmp_path)
    created = repo.create(sample_agent("Alpha"))
    assert created.name == "Alpha"
    fetched = repo.get_by_name("alpha")
    assert fetched.id == created.id
    assert fetched.job_summary == "Do the work"


def test_list_filters(tmp_path: Path):
    os.environ["OPENAI_API_KEY"] = "test-key"
    repo = _create_repo(tmp_path)
    repo.create(sample_agent("Alpha"))
    repo.create(
        AgentCreate(
            name="Beta",
            client="openai",
            model="gpt-5-codex",
            job_doc="Test",
            job_doc_sha256="sha",
            job_summary="job",
            character_doc="character",
            character_doc_sha256="sha2",
            character_summary="char",
            tags_json="[]",
        )
    )
    repo.create(sample_agent("Gamma"))

    results = repo.list(AgentFilter(client="openai", name_like="a"))
    assert len(results) == 3

    active = repo.list(AgentFilter(active=True))
    assert len(active) == 3


def test_soft_and_hard_delete(tmp_path: Path):
    os.environ["OPENAI_API_KEY"] = "test-key"
    repo = _create_repo(tmp_path)
    repo.create(sample_agent("Delta"))
    repo.soft_delete("Delta")
    assert repo.get_by_name("delta").is_active is False
    repo.reinstate("Delta")
    assert repo.get_by_name("delta").is_active is True
    repo.hard_delete("Delta")
    assert repo.get_by_name("delta") is None
