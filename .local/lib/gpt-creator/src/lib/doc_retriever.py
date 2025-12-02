#!/usr/bin/env python3
"""
Token-aware retrieval utilities for documentation content.

This module provides a cached pathway that prioritises summaries and curated excerpts
before falling back to full document text, helping downstream agents stay within
token budgets.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .doc_registry import DocRegistry


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    approx = int(len(text.split()) * 1.3)
    return max(1, approx)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")
    except OSError:
        return ""


@dataclass
class TokenBudget:
    limit: int
    spent: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def can_consume(self, tokens: int) -> bool:
        if tokens <= 0:
            return True
        return self.spent + tokens <= self.limit

    def consume(self, tokens: int) -> bool:
        if tokens <= 0:
            return True
        if not self.can_consume(tokens):
            return False
        self.spent += tokens
        return True


@dataclass
class DocumentChunk:
    doc_id: str
    kind: str
    content: str
    token_cost: int
    section_id: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class RetrievalPlan:
    doc_id: str
    chunks: List[DocumentChunk]
    total_tokens: int
    budget_limit: int
    spent_tokens: int
    satisfied: bool


class DocumentRetriever:
    def __init__(
        self,
        db_path: Path,
        *,
        default_budget: int = 2000,
        max_cache_entries: int = 256,
    ) -> None:
        self.db_path = Path(db_path)
        self.registry = DocRegistry(self.db_path)
        self.default_budget = default_budget
        self._summary_cache = self._build_lru_cache(self._load_summary_row, max_cache_entries)
        self._excerpt_cache = self._build_lru_cache(self._load_excerpt_rows, max_cache_entries)
        self._document_cache = self._build_lru_cache(self._load_document_row, max_cache_entries)

    def _build_lru_cache(self, loader, maxsize: int):
        @lru_cache(maxsize=maxsize)
        def cache(doc_id: str):
            return loader(doc_id)

        return cache

    def warm_cache(self, doc_ids: Sequence[str]) -> None:
        for doc_id in doc_ids:
            self._summary_cache(doc_id)
            self._excerpt_cache(doc_id)
            self._document_cache(doc_id)

    def clear_cache(self) -> None:
        self._summary_cache.cache_clear()
        self._excerpt_cache.cache_clear()
        self._document_cache.cache_clear()

    def plan(
        self,
        doc_id: str,
        *,
        budget: Optional[TokenBudget] = None,
        include_full_text: bool = False,
        max_excerpts: int = 5,
    ) -> RetrievalPlan:
        budget = budget or TokenBudget(self.default_budget)
        chunks: List[DocumentChunk] = []

        summary = self._summary_cache(doc_id)
        if summary:
            for label, field in (("summary_short", "summary_short"), ("summary_long", "summary_long")):
                text = (summary.get(field) or "").strip()
                if not text:
                    continue
                tokens = _estimate_tokens(text)
                if not budget.consume(tokens):
                    continue
                chunks.append(
                    DocumentChunk(
                        doc_id=doc_id,
                        kind=label,
                        content=text,
                        token_cost=tokens,
                        metadata={"field": field},
                    )
                )
            key_points = summary.get("key_points_json")
            if key_points:
                try:
                    points = json.loads(key_points) or []
                except Exception:
                    points = []
                if points:
                    text = "\n".join(f"- {point}" for point in points if point)
                    tokens = _estimate_tokens(text)
                    if budget.consume(tokens):
                        chunks.append(
                            DocumentChunk(
                                doc_id=doc_id,
                                kind="key_points",
                                content=text,
                                token_cost=tokens,
                                metadata={"count": len(points)},
                            )
                        )

        excerpts = self._excerpt_cache(doc_id) or []
        for row in excerpts[: max(0, max_excerpts)]:
            content = row.get("content") or ""
            if not content:
                continue
            tokens = row.get("token_length") or _estimate_tokens(content)
            if not budget.consume(tokens):
                continue
            chunks.append(
                DocumentChunk(
                    doc_id=doc_id,
                    kind="excerpt",
                    content=content,
                    token_cost=tokens,
                    section_id=row.get("section_id"),
                    metadata={
                        "excerpt_id": row.get("excerpt_id"),
                        "justification": row.get("justification"),
                    },
                )
            )

        if include_full_text and budget.remaining > 0:
            doc_row = self._document_cache(doc_id)
            if doc_row:
                path = None
                for candidate in ("staging_path", "source_path"):
                    if doc_row.get(candidate):
                        candidate_path = Path(doc_row[candidate])
                        if candidate_path.exists():
                            path = candidate_path
                            break
                if path:
                    text = _read_text(path)
                    tokens = _estimate_tokens(text)
                    if budget.consume(tokens):
                        chunks.append(
                            DocumentChunk(
                                doc_id=doc_id,
                                kind="full_text",
                                content=text,
                                token_cost=tokens,
                                metadata={"path": str(path)},
                            )
                        )

        total_tokens = sum(chunk.token_cost for chunk in chunks)
        return RetrievalPlan(
            doc_id=doc_id,
            chunks=chunks,
            total_tokens=total_tokens,
            budget_limit=budget.limit,
            spent_tokens=budget.spent,
            satisfied=budget.spent <= budget.limit,
        )

    def _load_summary_row(self, doc_id: str) -> Optional[Dict[str, object]]:
        with sqlite3_connect(self.db_path) as conn:
            self.registry.ensure_schema(conn)
            row = conn.execute(
                """
                SELECT summary_short, summary_long, key_points_json
                FROM documentation_summaries
                WHERE doc_id = ?
                """,
                (doc_id,),
            ).fetchone()
            return dict(row) if row else None

    def _load_excerpt_rows(self, doc_id: str) -> List[Dict[str, object]]:
        with sqlite3_connect(self.db_path) as conn:
            self.registry.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT excerpt_id, section_id, content, justification, token_length
                FROM documentation_excerpts
                WHERE doc_id = ?
                ORDER BY
                  CASE WHEN token_length IS NULL THEN 1 ELSE 0 END,
                  token_length,
                  excerpt_id
                """,
                (doc_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _load_document_row(self, doc_id: str) -> Optional[Dict[str, object]]:
        with sqlite3_connect(self.db_path) as conn:
            self.registry.ensure_schema(conn)
            row = conn.execute(
                """
                SELECT doc_id, source_path, staging_path, tokens_estimate
                FROM documentation
                WHERE doc_id = ?
                """,
                (doc_id,),
            ).fetchone()
            return dict(row) if row else None


def sqlite3_connect(path: Path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn
