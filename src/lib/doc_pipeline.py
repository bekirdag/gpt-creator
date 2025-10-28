#!/usr/bin/env python3
"""
Heuristic documentation pipeline that refreshes summaries, keywords, and excerpts.

This implementation avoids external dependencies so the catalog can stay in sync
whenever `gpt-creator scan` runs.
"""

from __future__ import annotations

import argparse
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

try:
    from .doc_registry import DocRegistry, ExcerptInput, SummaryInput  # type: ignore
except Exception:  # pragma: no cover
    from doc_registry import DocRegistry, ExcerptInput, SummaryInput  # type: ignore

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "have",
    "your",
    "will",
    "into",
    "about",
    "their",
    "there",
    "which",
    "should",
    "being",
    "such",
    "using",
    "when",
    "where",
    "while",
    "within",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runtime_db_path(runtime_dir: Path) -> Path:
    return runtime_dir / "staging" / "plan" / "tasks" / "tasks.db"


def _read_text(paths: Iterable[Optional[str]]) -> str:
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="latin-1")
            except OSError:
                continue
        except OSError:
            continue
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.3))


def _paragraphs(text: str) -> List[str]:
    items = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return items


def _generate_keywords(text: str, tags: Sequence[str], limit: int = 12) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9]{3,}", text.lower())
    counter = Counter(token for token in tokens if token not in STOPWORDS)
    keywords: List[str] = []
    keywords.extend(tag.lower() for tag in tags if tag)
    for token, _count in counter.most_common(limit * 2):
        if token in keywords:
            continue
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords[:limit]


def _extract_key_points(sections: Sequence[Dict[str, object]], limit: int = 5) -> List[str]:
    points: List[str] = []
    for row in sections:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        if row.get("parent_section_id") is None:
            # Skip synthetic root.
            continue
        points.append(title)
        if len(points) >= limit:
            break
    return points


def _select_excerpts(paragraphs: Sequence[str], limit: int = 5) -> List[str]:
    excerpts: List[str] = []
    for para in paragraphs:
        if 40 <= len(para) <= 800:
            excerpts.append(para)
        elif len(para) > 800:
            excerpts.append(para[:800].rstrip() + "…")
        if len(excerpts) >= limit:
            break
    return excerpts


def run_pipeline(project_root: Path, runtime_dir: Path) -> None:
    db_path = _runtime_db_path(runtime_dir)
    registry = DocRegistry(db_path)
    docs = registry.fetch_all()
    doc_ids = [doc["doc_id"] for doc in docs]
    sections_map = registry.fetch_sections(doc_ids)
    now = _iso_now()
    summary_payloads: List[SummaryInput] = []
    excerpt_payloads: Dict[str, List[ExcerptInput]] = {}

    for doc in docs:
        doc_id = doc["doc_id"]
        text = _read_text([doc.get("staging_path"), doc.get("source_path")])
        clean_text = text.strip()
        if not clean_text:
            continue
        paragraphs = _paragraphs(clean_text)
        preview = " ".join(paragraphs[:3]) if paragraphs else clean_text
        summary_short = _truncate(clean_text.replace("\n", " "), 300)
        summary_long = _truncate(preview.replace("\n", " "), 1200)
        sections = sections_map.get(doc_id, [])
        key_points = _extract_key_points(sections)
        tags = doc.get("tags") or []
        keywords = _generate_keywords(clean_text, tags)
        source_version = doc.get("sha256")

        summary_payloads.append(
            SummaryInput(
                doc_id=doc_id,
                summary_short=summary_short,
                summary_long=summary_long,
                key_points=key_points,
                keywords=keywords,
                embedding_id=None,
                last_generated_at=now,
                generator_source="heuristic",
                source_version=source_version,
            )
        )

        excerpts = _select_excerpts(paragraphs)
        excerpt_payloads[doc_id] = [
            ExcerptInput(
                excerpt_id=str(uuid.uuid4()),
                doc_id=doc_id,
                section_id=None,
                content=content,
                justification=None,
                token_length=_estimate_tokens(content),
                embedding_id=None,
                created_at=now,
                updated_at=now,
                source_version=source_version,
            )
            for content in excerpts
        ]

    registry.upsert_summaries(summary_payloads)
    registry.replace_excerpts_bulk(excerpt_payloads)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate documentation summaries and excerpts.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--runtime-dir", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()
    runtime_dir = Path(args.runtime_dir).resolve()
    run_pipeline(project_root, runtime_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
