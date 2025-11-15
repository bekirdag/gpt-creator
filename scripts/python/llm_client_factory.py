#!/usr/bin/env python3
"""Factory for llm clients."""

from __future__ import annotations

import os
import shlex
from typing import Any, Dict, Sequence

from llm_client import (
    CodexCLIClient,
    LLMClient,
    AnthropicClient,
    XAIClient,
    CommandLLMClient,
)


def _normalize_command(values: Sequence[str] | str | None) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        return shlex.split(values)
    return [str(part) for part in values]


def _resolve_env_map(raw_env: Dict[str, Any] | None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not raw_env:
        return env
    for key, value in raw_env.items():
        if value is None:
            continue
        text = str(value)
        if text.startswith("${") and text.endswith("}"):
            ref = text[2:-1]
            env[key] = os.getenv(ref, "")
        else:
            env[key] = text
    return env


def create_llm_client(adapter: str, config: dict | None = None) -> LLMClient:
    adapter_key = (adapter or "").strip().lower()
    config = config or {}
    max_context = config.get("maxContextTokens")
    max_output = config.get("maxOutputTokens")
    if adapter_key in {"codex_cli", "openai_cli", "openai"}:
        return CodexCLIClient(max_context_tokens=max_context, max_output_tokens=max_output)
    if adapter_key == "anthropic":
        api_key_env = config.get("apiKeyEnv") or "ANTHROPIC_API_KEY"
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        base = config.get("apiBase") or "https://api.anthropic.com"
        headers = config.get("defaultHeaders") or {}
        return AnthropicClient(
            api_key,
            base,
            headers=headers,
            retry_config=config.get("retry"),
            max_context_tokens=max_context,
            max_output_tokens=max_output,
        )
    if adapter_key == "xai":
        api_key_env = config.get("apiKeyEnv") or "GROK_API_KEY"
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ValueError("GROK_API_KEY not set")
        base = config.get("apiBase") or "https://api.x.ai/v1"
        headers = config.get("defaultHeaders") or {}
        return XAIClient(
            api_key,
            base,
            headers=headers,
            retry_config=config.get("retry"),
            max_context_tokens=max_context,
            max_output_tokens=max_output,
        )
    if adapter_key == "command":
        adapter_cfg = config.get("adapterConfig") or {}
        command_template = _normalize_command(adapter_cfg.get("command"))
        if not command_template:
            base_binary = adapter_cfg.get("binary") or "codex"
            command_template = [base_binary]
            command_template.extend(_normalize_command(adapter_cfg.get("args")))
        if not command_template:
            raise ValueError("command adapter requires a command or binary")
        env_overrides = _resolve_env_map(adapter_cfg.get("env"))
        for env_key_name in ("apiKeyEnv", "apiBaseEnv", "orgEnv"):
            env_var = config.get(env_key_name)
            if env_var and env_var not in env_overrides:
                env_value = os.getenv(env_var, "")
                if env_value:
                    env_overrides[env_var] = env_value
        joiner = adapter_cfg.get("messageJoiner") or adapter_cfg.get("joiner") or "\n\n"
        prompt_template = adapter_cfg.get("promptTemplate") or "{system}\n\n{messages}"
        timeout_seconds = adapter_cfg.get("timeoutSeconds")
        try:
            timeout = float(timeout_seconds) if timeout_seconds else None
        except (TypeError, ValueError):
            timeout = None
        return CommandLLMClient(
            command_template,
            env=env_overrides,
            prompt_template=prompt_template,
            message_joiner=joiner,
            timeout=timeout,
            max_context_tokens=max_context,
            max_output_tokens=max_output,
        )
    raise ValueError(f"Unsupported LLM adapter '{adapter}'")
