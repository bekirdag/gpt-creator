import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from llm_client import CommandLLMClient  # type: ignore  # noqa: E402
from llm_client_factory import create_llm_client  # type: ignore  # noqa: E402


def _write_fake_cli(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_cli.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_command_llm_client_executes_command(tmp_path: Path):
    cli_script = _write_fake_cli(
        tmp_path,
        """
import sys

def main():
    model = sys.argv[1]
    payload = sys.stdin.read().strip()
    print(f"{model}:{payload}")

if __name__ == "__main__":
    main()
""",
    )
    client = CommandLLMClient(
        ["python3", str(cli_script), "{model}"],
        prompt_template="{system}||{messages}",
        message_joiner="|",
    )
    result = client.send_chat(["line-1", "line-2"], "gemini-test", system="sys")
    assert "gemini-test" in result.content
    assert "sys" in result.content
    assert "line-1|line-2" in result.content


def test_factory_command_adapter_passes_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cli_script = _write_fake_cli(
        tmp_path,
        """
import json
import os
import sys

def main():
    payload = sys.stdin.read().strip()
    model = sys.argv[1]
    data = {
        "model": model,
        "payload": payload,
        "api": os.getenv("GEMINI_API_KEY", ""),
        "mode": os.getenv("RUN_MODE", ""),
    }
    print(json.dumps(data))

if __name__ == "__main__":
    main()
""",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    config = {
        "apiKeyEnv": "GEMINI_API_KEY",
        "adapterConfig": {
            "command": ["python3", str(cli_script), "{model}"],
            "env": {"RUN_MODE": "test"},
            "promptTemplate": "{system}::{messages}",
            "messageJoiner": ";",
        },
    }
    client = create_llm_client("command", config)
    result = client.send_chat(["hello", "world"], "gemini-1.5-pro", system="sys")
    data = json.loads(result.content)
    assert data["model"] == "gemini-1.5-pro"
    assert data["payload"] == "sys::hello;world"
    assert data["api"] == "secret-key"
    assert data["mode"] == "test"
