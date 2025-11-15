import json
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
assert SCRIPTS_DIR.exists()

import sys  # noqa: E402

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import llm_catalog  # type: ignore  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _sample_provider():
    return [
        {
            "id": "openai",
            "name": "OpenAI",
            "type": "openai",
            "api_key": "$OPENAI_API_KEY",
            "models": [
                {"id": "gpt-5", "name": "GPT-5", "context_window": 400000, "default_max_tokens": 128000}
            ],
        }
    ]


def test_load_catalog_respects_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cache_path = tmp_path / "catalog.json"
    monkeypatch.setenv("GC_LLM_CATALOG_CACHE", str(cache_path))
    payload = _sample_provider()

    def fake_get(url, timeout):
        return _FakeResponse(payload)

    monkeypatch.setattr(llm_catalog, "CATALOG_URL", "https://example.test/providers")
    monkeypatch.setattr(httpx, "get", fake_get)

    data = llm_catalog.load_catalog(refresh=True, ttl_seconds=10)
    assert data["source"] == "network"
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text())
    assert cached["providers"][0]["id"] == "openai"

    calls = {"count": 0}

    def failing_get(url, timeout):
        calls["count"] += 1
        raise httpx.RequestError("boom", request=None)

    monkeypatch.setattr(httpx, "get", failing_get)
    result = llm_catalog.load_catalog(refresh=False, ttl_seconds=0)
    assert result["source"] == "cache-fallback"
    assert result["providers"][0]["id"] == "openai"
    assert calls["count"] == 1


def test_cli_syncs_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    data = {
        "providers": _sample_provider(),
        "source": "network",
        "fetched_at": "2024-01-01T00:00:00Z",
    }
    monkeypatch.setattr(llm_catalog, "load_catalog", lambda **kwargs: data)

    captured = {}

    class DummyStore:
        def __init__(self, path):
            captured["path"] = Path(path)

        def sync(self, providers, *, source, fetched_at):
            captured["providers"] = providers
            captured["source"] = source
            captured["fetched_at"] = fetched_at

    monkeypatch.setattr(llm_catalog, "LLMCatalogStore", DummyStore)
    db_path = tmp_path / "tasks.db"
    exit_code = llm_catalog.main(["--db-path", str(db_path), "--json"])
    assert exit_code == 0
    assert captured["path"] == db_path
    assert captured["providers"] == data["providers"]
    assert captured["source"] == "network"
    assert captured["fetched_at"] == data["fetched_at"]
