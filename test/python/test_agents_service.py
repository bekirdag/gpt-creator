import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agents import AgentService, DocSource  # type: ignore  # noqa: E402
from agents_registry import AgentRegistry  # type: ignore  # noqa: E402
from agents.summarizer import AgentSummarizer  # type: ignore  # noqa: E402

os.environ.setdefault("GC_AGENT_CATALOG_DISABLE", "1")


def _write_doc(tmp_path: Path, name: str, content: str) -> Path:
    doc_path = tmp_path / name
    doc_path.write_text(content, encoding="utf-8")
    return doc_path


def test_service_create_list_compose(tmp_path: Path):
    os.environ["OPENAI_API_KEY"] = "test-key"
    project = tmp_path / "project"
    tasks_db = project / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"
    tasks_db.parent.mkdir(parents=True, exist_ok=True)

    job_doc = _write_doc(tmp_path, "job.md", "Fix bugs swiftly.\nKeep diffs tidy.")
    char_doc = _write_doc(tmp_path, "char.md", "Strict tone.\nPrefer concise summaries.")

    service = AgentService(tasks_db)
    agent = service.create_agent(
        name="Fixer-A",
        client="openai",
        model="gpt-5.1-codex",
        job_doc=DocSource(str(job_doc)),
        character_doc=DocSource(str(char_doc)),
        tags="fixer,strict",
    )
    assert agent.name == "Fixer-A"
    assert "Fix bugs" in agent.job_summary
    assert sorted(agent.tags) == ["fixer", "strict"]
    assert agent.llm_provider_id.lower() == "openai"
    assert agent.llm_model_id == "gpt-5.1-codex"

    listed = service.list_agents()
    assert len(listed) == 1
    prompt_bundle = service.compose_prompt(agent)
    assert "## Role / Job" in prompt_bundle.header
    assert "Strict tone" in prompt_bundle.header


def test_service_edit_resummarize(tmp_path: Path):
    os.environ["OPENAI_API_KEY"] = "test-key"
    project = tmp_path / "project"
    tasks_db = project / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"
    tasks_db.parent.mkdir(parents=True, exist_ok=True)

    job_doc = _write_doc(tmp_path, "job.md", "First summary.\n")
    char_doc = _write_doc(tmp_path, "char.md", "First char.\n")

    service = AgentService(tasks_db)
    service.create_agent(
        name="Writer",
        client="openai",
        model="gpt-5.1-codex",
        job_doc=DocSource(str(job_doc)),
        character_doc=DocSource(str(char_doc)),
        tags=None,
    )

    new_job = _write_doc(tmp_path, "job_new.md", "Updated role description.\n")
    updated = service.update_agent(
        "Writer",
        job_doc=DocSource(str(new_job)),
        resummarize=True,
        summarize=True,
        summarize_model="gpt-summarizer",
        summarize_client="openai",
    )
    assert "Updated role" in updated.job_summary
    assert updated.is_active
    service.delete_agent("Writer")
    inactive = service.get_agent("Writer")
    assert inactive is not None and inactive.is_active is False
