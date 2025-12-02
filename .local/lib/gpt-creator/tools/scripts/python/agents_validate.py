#!/usr/bin/env python3
"""Validation helpers for agent inputs (names, docs, tags)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from agents_registry import AgentRegistry

MAX_DOC_BYTES = 512 * 1024
SUMMARY_LIMIT = 160
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. \-]{0,63}$")
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")
MAX_TAGS = 12


def _normalize_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _compute_sha(text: str) -> str:
    digest = hashlib.sha256()
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def summarize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = lines[0] if lines else ""
    if not summary:
        summary = text.strip()
    if not summary:
        return ""
    if len(summary) <= SUMMARY_LIMIT:
        return summary
    return summary[: SUMMARY_LIMIT - 1].rstrip() + "…"


@dataclass
class DocBundle:
    text: str
    summary: str
    sha256: str


def read_doc(path: str, *, stdin_payload: Optional[str] = None) -> DocBundle:
    raw: str
    if path == "-":
        if stdin_payload is None:
            raise ValueError("stdin payload required when doc path is '-'")
        raw = stdin_payload
    else:
        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"Document not found: {path}")
        size = file_path.stat().st_size
        if size > MAX_DOC_BYTES:
            raise ValueError(f"Document exceeds max size ({MAX_DOC_BYTES} bytes)")
        raw = file_path.read_text(encoding="utf-8")
    normalized = _normalize_text(raw)
    encoded = normalized.encode("utf-8")
    if len(encoded) > MAX_DOC_BYTES:
        raise ValueError(f"Document exceeds max size ({MAX_DOC_BYTES} bytes)")
    summary = summarize_text(normalized)
    sha = _compute_sha(normalized)
    return DocBundle(text=normalized, summary=summary, sha256=sha)


def validate_name(name: str) -> str:
    candidate = (name or "").strip()
    if not candidate:
        raise ValueError("Agent name is required")
    if not NAME_PATTERN.fullmatch(candidate):
        raise ValueError(
            "Agent name must be 1-64 chars (letters, numbers, spaces, '_', '-', '.') "
            "and start with a letter/number"
        )
    return candidate


def parse_tags(raw: str) -> List[str]:
    if not raw:
        return []
    tokens = [token.strip() for token in re.split(r"[,\s]+", raw) if token.strip()]
    cleaned: List[str] = []
    seen = set()
    for token in tokens:
        lower = token.lower()
        if lower in seen:
            continue
        if not TAG_PATTERN.fullmatch(token):
            raise ValueError(f"Invalid tag '{token}'")
        cleaned.append(token)
        seen.add(lower)
        if len(cleaned) >= MAX_TAGS:
            break
    return cleaned


def validate_client_model(client: str, model: str, registry: Optional[AgentRegistry] = None) -> dict:
    active_registry = registry or AgentRegistry.load()
    return active_registry.validate_pair(client, model)


def prepare_agent_payload(
    *,
    name: str,
    client: str,
    model: str,
    job_doc: DocBundle,
    character_doc: DocBundle,
    tags: Iterable[str],
) -> dict:
    """Return normalized payload ready for insertion."""
    validated_name = validate_name(name)
    validated_pair = validate_client_model(client, model)
    normalized_tags = json.dumps(list(tags))
    return {
        "name": validated_name,
        "client": validated_pair["client"],
        "model": validated_pair["model"],
        "job_doc": job_doc.text,
        "job_doc_sha256": job_doc.sha256,
        "job_summary": job_doc.summary,
        "character_doc": character_doc.text,
        "character_doc_sha256": character_doc.sha256,
        "character_summary": character_doc.summary,
        "tags_json": normalized_tags,
    }


def main(argv: List[str]) -> int:
    if len(argv) == 3 and argv[0] == "summary":
        bundle = read_doc(argv[1])
        print(summarize_text(bundle.text))
        return 0
    print("Usage: agents_validate.py summary <doc-path>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
