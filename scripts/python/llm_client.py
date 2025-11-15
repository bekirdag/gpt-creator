#!/usr/bin/env python3
"""Lightweight LLM client abstraction."""

from __future__ import annotations

import os
import subprocess
import json
import time
from dataclasses import dataclass
from typing import List, Sequence, Dict, Any, Optional

import httpx


@dataclass
class TokenCounts:
    prompt: int
    completion: int


@dataclass
class ChatResult:
    content: str
    tokens: TokenCounts
    model: str


class LLMClient:
    """Base interface for adapters."""

    def __init__(self, *, max_context_tokens: Optional[int] = None, max_output_tokens: Optional[int] = None):
        self._max_context_tokens = max_context_tokens or 0
        self._max_output_tokens = max_output_tokens or 0

    def send_chat(self, messages: Sequence[str], model: str, **kwargs) -> ChatResult:  # pragma: no cover - interface
        raise NotImplementedError

    def count_tokens(self, messages: Sequence[str], model: str) -> TokenCounts:  # pragma: no cover - interface
        raise NotImplementedError

    def max_context_tokens(self, model: str) -> int:
        return self._max_context_tokens

    def max_output_tokens(self, model: str) -> int:
        return self._max_output_tokens


class CodexCLIClient(LLMClient):
    """Thin wrapper around the existing codex CLI."""

    def __init__(self, binary: str = "codex", *, max_context_tokens: Optional[int] = None, max_output_tokens: Optional[int] = None):
        super().__init__(max_context_tokens=max_context_tokens, max_output_tokens=max_output_tokens)
        self.binary = binary

    def send_chat(self, messages: Sequence[str], model: str, **kwargs) -> ChatResult:
        prompt = "\n\n".join(messages)
        proc = subprocess.run(
            [self.binary, "exec", "--model", model],
            input=prompt.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        content = proc.stdout.decode("utf-8", "ignore")
        return ChatResult(content=content, tokens=TokenCounts(prompt=0, completion=0), model=model)

    def count_tokens(self, messages: Sequence[str], model: str) -> TokenCounts:
        return TokenCounts(prompt=0, completion=0)


class CommandLLMClient(LLMClient):
    """Adapter that shells out to an arbitrary CLI client."""

    def __init__(
        self,
        command_template: Sequence[str],
        env: Optional[Dict[str, str]] = None,
        *,
        prompt_template: str = "{system}\n\n{messages}",
        message_joiner: str = "\n\n",
        encoding: str = "utf-8",
        timeout: Optional[float] = None,
        strip_output: bool = True,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        super().__init__(max_context_tokens=max_context_tokens, max_output_tokens=max_output_tokens)
        if not command_template:
            raise ValueError("command_template must contain at least one token")
        self.command_template = [str(token) for token in command_template]
        self.env = dict(env or {})
        self.prompt_template = prompt_template
        self.message_joiner = message_joiner
        self.encoding = encoding
        self.timeout = timeout
        self.strip_output = strip_output

    def _format_command(self, model: str) -> List[str]:
        data = {"model": model}
        return [token.format(**data) for token in self.command_template]

    def _format_payload(self, messages: Sequence[str], system_prompt: str, model: str) -> str:
        normalized_messages = [str(msg) for msg in messages]
        joined = self.message_joiner.join(normalized_messages)
        payload = self.prompt_template.format(system=system_prompt or "", messages=joined, model=model)
        return payload

    def send_chat(self, messages: Sequence[str], model: str, **kwargs) -> ChatResult:
        system_prompt = kwargs.get("system", "")
        payload = self._format_payload(messages, system_prompt, model)
        command = self._format_command(model)
        env = os.environ.copy()
        env.update({key: value for key, value in self.env.items() if value is not None})
        proc = subprocess.run(
            command,
            input=payload.encode(self.encoding, "ignore"),
            capture_output=True,
            check=False,
            timeout=self.timeout,
            env=env,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(self.encoding, "ignore").strip()
            raise RuntimeError(f"Command adapter exited with status {proc.returncode}: {stderr}")
        content = proc.stdout.decode(self.encoding, "ignore")
        if self.strip_output:
            content = content.strip()
        return ChatResult(content=content, tokens=TokenCounts(prompt=0, completion=0), model=model)

    def count_tokens(self, messages: Sequence[str], model: str) -> TokenCounts:
        return TokenCounts(prompt=0, completion=0)


class HttpLLMClient(LLMClient):
    """Base class for HTTP adapters with retry/backoff."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        *,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        super().__init__(max_context_tokens=max_context_tokens, max_output_tokens=max_output_tokens)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.retry_config = retry_config or {}
        self.max_attempts = int(self.retry_config.get("maxAttempts", 3))
        self.initial_delay = float(self.retry_config.get("initialDelayMs", 2000)) / 1000.0
        self.backoff_factor = float(self.retry_config.get("backoffFactor", 1.5))

    def _should_retry(self, status_code: int) -> bool:
        return status_code in {408, 409, 429, 500, 502, 503, 504}

    def _request(self, method: str, path: str, payload: Dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers.update(self._auth_header())
        delay = self.initial_delay
        attempt = 1
        while True:
            response = httpx.request(method, url, headers=headers, json=payload, timeout=60.0)
            if response.status_code < 400 or attempt >= self.max_attempts or not self._should_retry(response.status_code):
                return response
            time.sleep(delay)
            delay *= self.backoff_factor
            attempt += 1

    def _auth_header(self) -> Dict[str, str]:  # pragma: no cover - provided by subclasses
        raise NotImplementedError


class AnthropicClient(HttpLLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        *,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        default_headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        if headers:
            default_headers.update(headers)
        super().__init__(api_key, base_url, default_headers, retry_config, max_context_tokens=max_context_tokens, max_output_tokens=max_output_tokens)

    def _auth_header(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key}

    def send_chat(self, messages: Sequence[str], model: str, **kwargs) -> ChatResult:
        system_prompt = kwargs.get("system", "")
        message_payload = [{"role": "user", "content": msg} for msg in messages]
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": message_payload,
            "max_output_tokens": kwargs.get("max_tokens", 1024),
        }
        response = self._request("POST", "/v1/messages", payload)
        response.raise_for_status()
        data = response.json()
        content = "\n".join(chunk.get("text", "") for chunk in data.get("content", []))
        usage = data.get("usage") or {}
        tokens = TokenCounts(prompt=usage.get("input_tokens", 0), completion=usage.get("output_tokens", 0))
        return ChatResult(content=content, tokens=tokens, model=model)


class XAIClient(HttpLLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        *,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        default_headers = {"content-type": "application/json"}
        if headers:
            default_headers.update(headers)
        super().__init__(api_key, base_url, default_headers, retry_config, max_context_tokens=max_context_tokens, max_output_tokens=max_output_tokens)

    def _auth_header(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def send_chat(self, messages: Sequence[str], model: str, **kwargs) -> ChatResult:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": msg} for msg in messages],
            "max_output_tokens": kwargs.get("max_tokens", 1024),
        }
        response = self._request("POST", "/chat/completions", payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = data.get("usage") or {}
        tokens = TokenCounts(prompt=usage.get("prompt_tokens", 0), completion=usage.get("completion_tokens", 0))
        return ChatResult(content=content, tokens=tokens, model=model)
