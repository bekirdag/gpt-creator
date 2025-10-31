"""Utilities for composing prompt sections without duplicate preambles."""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Sequence, Tuple

_DEFAULT_PREAMBLE_TITLES = "System,System Prompt,Preamble,Rules,Assistant Rules"


def _preamble_titles() -> List[str]:
    raw = os.getenv("GC_PREAMBLE_TITLES", _DEFAULT_PREAMBLE_TITLES)
    titles = [entry.strip().lower() for entry in raw.split(",") if entry.strip()]
    return titles or [title.strip().lower() for title in _DEFAULT_PREAMBLE_TITLES.split(",")]


def _is_preamble(title: str) -> bool:
    return (title or "").strip().lower() in _preamble_titles()


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def emit_preamble_once(sections: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    seen = False
    result: List[Tuple[str, str]] = []
    for title, body in sections:
        if _is_preamble(title):
            if seen:
                continue
            seen = True
        result.append((title, body))
    return result


def dedupe_and_coalesce(sections: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    normalized: List[Tuple[str, str]] = []
    seen_keys = set()
    for title, body in sections:
        title_clean = (title or "").strip()
        body_clean = _normalize_text(body or "")
        if not body_clean:
            continue
        key = (title_clean.lower(), body_clean.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if normalized and normalized[-1][0].strip().lower() == title_clean.lower():
            merged = _normalize_text(normalized[-1][1] + "\n\n" + body_clean)
            normalized[-1] = (normalized[-1][0], merged)
        else:
            normalized.append((title_clean, body_clean))
    return normalized


def format_sections(sections: Iterable[Tuple[str, str]]) -> str:
    blocks: List[str] = []
    previous_title = None
    for title, body in sections:
        title_clean = (title or "").strip()
        body_clean = _normalize_text(body or "")
        if not body_clean:
            continue
        if title_clean:
            heading = f"## {title_clean}"
            if previous_title == heading:
                blocks.append("\n" + body_clean)
            else:
                if blocks:
                    blocks.append("\n")
                blocks.append(heading + "\n\n" + body_clean)
                previous_title = heading
        else:
            if blocks:
                blocks.append("\n")
            blocks.append(body_clean)
            previous_title = None
    return "".join(blocks).rstrip() + "\n"


__all__ = [
    "emit_preamble_once",
    "dedupe_and_coalesce",
    "format_sections",
]
