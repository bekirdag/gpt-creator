from __future__ import annotations

import logging
import os

from agents_registry import AgentRegistry
from agents_validate import summarize_text
from llm_client_factory import create_llm_client

SUMMARY_LIMIT = 160
DEFAULT_PROMPT = (
    "Summarize the following agent description in at most two short sentences. "
    "Keep the summary under 160 characters, omit sensitive data, and capture the core intent."
)

logger = logging.getLogger(__name__)


class AgentSummarizer:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def summarize(self, text: str, client: str, model: str) -> str:
        pair = self.registry.validate_pair(client, model)
        adapter = pair.get("adapter") or "codex_cli"
        try:
            llm = create_llm_client(adapter, pair)
        except Exception as exc:
            logger.warning("agent summarizer: unable to create adapter (%s)", exc)
            return summarize_text(text)
        system_prompt = os.getenv("GC_AGENT_SUMMARIZER_PROMPT", DEFAULT_PROMPT)
        max_tokens = min(int(llm.max_output_tokens(model)) or 200, 400)
        clipped_text = text[:4000]
        try:
            result = llm.send_chat(
                messages=[clipped_text],
                model=model,
                system=system_prompt,
                max_tokens=max_tokens,
            )
            summary = (result.content or "").strip()
            if not summary:
                return summarize_text(text)
            if len(summary) > SUMMARY_LIMIT:
                summary = summary[: SUMMARY_LIMIT - 1].rstrip() + "…"
            return summary
        except Exception as exc:
            logger.warning("agent summarizer: LLM summarization failed (%s)", exc)
            return summarize_text(text)
