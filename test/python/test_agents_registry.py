from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agents_registry import AgentRegistry, ClientConfig  # type: ignore  # noqa: E402


def _make_client_config(name: str) -> ClientConfig:
    return ClientConfig(
        name=name,
        label=name.title(),
        default_model=f"{name}-default",
        models=[f"{name}-default"],
        env_vars=[],
        retry={},
        adapter="command",
        max_context_tokens=None,
        max_output_tokens=None,
        api_key_env="",
        api_base_env="",
        default_api_base="",
        org_env="",
        default_headers={},
        adapter_config={},
    )


def test_registry_includes_catalog_only_providers():
    clients = {"openai": _make_client_config("openai")}
    catalog_meta = {
        "providers": [
            {
                "id": "openai",
                "name": "OpenAI",
                "models": [{"id": "gpt-5"}],
                "defaultSmallModel": "gpt-5",
            },
            {
                "id": "gemini",
                "name": "Gemini",
                "models": [{"id": "gemini-1"}],
                "defaultSmallModel": "gemini-1",
            },
        ],
        "fetched_at": "2024-01-01T00:00:00Z",
        "source": "network",
    }
    registry = AgentRegistry(clients, catalog_meta)
    entries = registry.list_clients()
    assert any(entry["name"] == "openai" and entry.get("catalogModels") for entry in entries)
    assert any(entry.get("catalogOnly") and entry["name"] == "gemini" for entry in entries)
    info = registry.catalog_info()
    assert info["providerCount"] == 2
