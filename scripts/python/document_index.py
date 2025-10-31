import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple, Set, Dict, Sequence, Any

from task_binder import (
    DEFAULT_MAX_BYTES as BINDER_DEFAULT_MAX_BYTES,
    DEFAULT_TTL_SECONDS as BINDER_DEFAULT_TTL_SECONDS,
    load_for_prompt as binder_load_for_prompt,
    prepare_binder_payload,
    write_binder as binder_write,
)

APPROX_CHARS_PER_TOKEN = 4
ESTIMATE_MARGIN = 1.06
DEFAULT_SOFT_LIMIT_RATIO = 0.85
DEFAULT_MIN_OUTPUT_TOKENS = 1024
MODEL_CONTEXTS: Dict[str, int] = {
    "gpt-5-codex": 128000,
    "gpt-5": 128000,
    "gpt-4.1": 128000,
    "gpt-4.1-coder": 128000,
    "gpt-4.1-mini": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "o4": 128000,
    "o4-mini": 128000,
}

DESCRIPTION_MAX_LINES = int(os.getenv("GC_PROMPT_DESCRIPTION_MAX_LINES", "400"))
DESCRIPTION_MAX_CHARS = int(os.getenv("GC_PROMPT_DESCRIPTION_MAX_CHARS", "40000"))
ACCEPTANCE_MAX_ITEMS = int(os.getenv("GC_PROMPT_ACCEPTANCE_MAX_ITEMS", "120"))
ACCEPTANCE_MAX_CHARS = int(os.getenv("GC_PROMPT_ACCEPTANCE_MAX_CHARS", "32000"))
FREEFORM_SECTION_MAX_CHARS = int(os.getenv("GC_PROMPT_FREEFORM_MAX_CHARS", "24000"))

_progress_enabled = os.getenv("GC_PROMPT_PROGRESS", "1").strip().lower() not in {"0", "false", "off"}


def emit_progress(message: str) -> None:
    if not _progress_enabled:
        return
    try:
        sys.stderr.write(f"[prompt] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass
SEGMENT_TYPE_PRIORITY: Dict[str, Tuple[int, bool]] = {
    "lead-in": (100, True),
    "documentation-assets": (98, True),
    "story": (95, True),
    "task": (94, True),
    "acceptance": (92, True),
    "guardrails": (90, True),
    "output-contract": (90, True),
    "supplemental": (82, True),
    "section": (80, True),
    "doc-search": (60, False),
    "doc-catalog-intro": (58, False),
    "doc-catalog-entry": (55, False),
    "known-command-failures": (48, False),
    "command-efficiency": (42, False),
    "workspace-snapshots": (38, False),
    "build-artifacts": (30, False),
}


def _approximate_tokens(text: str) -> int:
    length = len(text or "")
    if length <= 0:
        return 0
    return (length + APPROX_CHARS_PER_TOKEN - 1) // APPROX_CHARS_PER_TOKEN


def _resolve_model_context(model_name: str) -> int:
    name = (model_name or "").strip().lower()
    if not name:
        return 128000
    if name in MODEL_CONTEXTS:
        return MODEL_CONTEXTS[name]
    # try to match prefix
    for key, value in MODEL_CONTEXTS.items():
        if name.startswith(key):
            return value
    return 128000


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _parse_float(value: Any, *, fallback: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(result) or math.isinf(result):
        return fallback
    return result


def _parse_int(value: Any, *, fallback: int) -> int:
    try:
        result = int(str(value).strip().replace("_", ""))
    except (TypeError, ValueError):
        return fallback
    return result


def _load_runner_config(project_root: Optional[Path]) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "perTask": {
            "hardLimit": None,
            "softLimitRatio": DEFAULT_SOFT_LIMIT_RATIO,
            "minOutputTokens": DEFAULT_MIN_OUTPUT_TOKENS,
        },
        "runner": {
            "stopOnOverbudget": True,
        },
        "binder": {
            "enabled": True,
            "ttlSeconds": BINDER_DEFAULT_TTL_SECONDS,
            "maxSizeBytes": BINDER_DEFAULT_MAX_BYTES,
            "clearOnMigration": False,
        },
    }
    if project_root is None:
        return config
    config_path = project_root / ".gpt-creator" / "config.yml"
    if not config_path.exists():
        return config
    try:
        import yaml  # type: ignore
    except Exception:
        return config
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config
    if isinstance(loaded, dict):
        per_task = loaded.get("perTask")
        if isinstance(per_task, dict):
            if "hardLimit" in per_task:
                config["perTask"]["hardLimit"] = per_task["hardLimit"]
            if "softLimitRatio" in per_task:
                config["perTask"]["softLimitRatio"] = per_task["softLimitRatio"]
            if "minOutputTokens" in per_task:
                config["perTask"]["minOutputTokens"] = per_task["minOutputTokens"]
        quota_cfg = loaded.get("quota")
        if isinstance(quota_cfg, dict) and "hard_limit_per_task" in quota_cfg:
            config["perTask"]["hardLimit"] = quota_cfg["hard_limit_per_task"]
        runner = loaded.get("runner")
        if isinstance(runner, dict) and "stopOnOverbudget" in runner:
            config["runner"]["stopOnOverbudget"] = runner["stopOnOverbudget"]
        binder_cfg = loaded.get("binder")
        if isinstance(binder_cfg, dict):
            if "enabled" in binder_cfg:
                config["binder"]["enabled"] = binder_cfg["enabled"]
            if "ttlSeconds" in binder_cfg:
                config["binder"]["ttlSeconds"] = binder_cfg["ttlSeconds"]
            if "maxSizeBytes" in binder_cfg:
                config["binder"]["maxSizeBytes"] = binder_cfg["maxSizeBytes"]
            if "clearOnMigration" in binder_cfg:
                config["binder"]["clearOnMigration"] = binder_cfg["clearOnMigration"]
    return config


def _normalize_heading(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.strip()).lower()


def _resolve_section_type(heading: Optional[str]) -> Tuple[str, int, bool]:
    normalized = _normalize_heading(heading)
    mapping = {
        "": "lead-in",
        "documentation assets": "documentation-assets",
        "story": "story",
        "task": "task",
        "acceptance criteria": "acceptance",
        "guardrails": "guardrails",
        "output json schema": "output-contract",
        "supplemental instruction prompts": "supplemental",
        "documentation search hits": "doc-search",
        "documentation catalog": "doc-catalog",
        "known command failures": "known-command-failures",
        "command efficiency alerts": "command-efficiency",
        "workspace directory snapshots": "workspace-snapshots",
        "build artifacts (opt-in)": "build-artifacts",
    }
    if normalized in mapping:
        seg_type = mapping[normalized]
    else:
        # match partial keys
        seg_type = "section"
        if normalized.startswith("build artifacts"):
            seg_type = "build-artifacts"
        elif normalized.startswith("documentation catalog"):
            seg_type = "doc-catalog"
        elif normalized.startswith("documentation search hits"):
            seg_type = "doc-search"
    score, must_keep = SEGMENT_TYPE_PRIORITY.get(seg_type, SEGMENT_TYPE_PRIORITY["section"])
    return seg_type, score, must_keep


def _split_sections(lines: Sequence[str]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    current: List[str] = []
    current_heading: Optional[str] = None
    heading_pattern = re.compile(r"^##\s+(.*)$")

    for line in lines:
        match = heading_pattern.match(line.strip())
        if match:
            if current:
                sections.append({"heading": current_heading, "lines": current})
            current = [line]
            current_heading = match.group(1).strip()
        else:
            if not current and line.strip():
                # lead-in before first heading
                current_heading = None
            current.append(line)
    if current:
        sections.append({"heading": current_heading, "lines": current})

    return sections


def _strip_empty_ends(block: List[str]) -> List[str]:
    start = 0
    end = len(block)
    while start < end and not block[start].strip():
        start += 1
    while end > start and not block[end - 1].strip():
        end -= 1
    return block[start:end]


DOC_ENTRY_BULLET_RE = re.compile(r"^-+\s*(DOC-[A-Z0-9]+)\b")


def _build_doc_entry_segment(entry_lines: List[str], *, order: int) -> Dict[str, Any]:
    lines = _strip_empty_ends(entry_lines)
    if not lines:
        return {}
    first = lines[0].strip()
    doc_id = ""
    rel_path = ""
    doc_match = re.match(r"^-+\s*(DOC-[A-Z0-9]+)\s*(?:\[[^\]]+\])?\s*—\s*(.+)$", first)
    if doc_match:
        doc_id = doc_match.group(1).strip()
        rel_path = doc_match.group(2).strip()
    fallback_text = first
    segment_text = "\n".join(lines).rstrip()
    seg_type = "doc-catalog-entry"
    score, must_keep = SEGMENT_TYPE_PRIORITY.get(seg_type, SEGMENT_TYPE_PRIORITY["section"])
    return {
        "id": f"{seg_type}:{order:02d}:{doc_id or order}",
        "type": seg_type,
        "score": score,
        "must_keep": must_keep,
        "full_text": segment_text,
        "fallback_text": fallback_text,
        "path": rel_path,
        "doc_id": doc_id,
        "order": order,
    }


def _split_doc_section_lines(lines: List[str]) -> Tuple[List[str], List[List[str]]]:
    if not lines:
        return [], []
    intro_lines: List[str] = []
    entry_blocks: List[List[str]] = []
    current_block: List[str] = []
    for raw_line in lines[1:]:
        stripped_line = raw_line.lstrip()
        indent = len(raw_line) - len(stripped_line)
        is_bullet = stripped_line.startswith("- ")
        is_doc_entry = bool(DOC_ENTRY_BULLET_RE.match(stripped_line))
        if is_bullet and is_doc_entry and indent < 2:
            if current_block:
                entry_blocks.append(current_block)
            current_block = [raw_line]
        else:
            if current_block:
                current_block.append(raw_line)
            else:
                intro_lines.append(raw_line)
    if current_block:
        entry_blocks.append(current_block)
    return intro_lines, entry_blocks


def _build_doc_catalog_segments(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = section["lines"]
    if not lines:
        return []
    intro_lines, entry_blocks = _split_doc_section_lines(lines)

    segments: List[Dict[str, Any]] = []
    intro_text_lines = [lines[0]] + _strip_empty_ends(intro_lines)
    intro_text = "\n".join(intro_text_lines).rstrip()
    seg_type, score, must_keep = _resolve_section_type(section["heading"])
    segments.append(
        {
            "id": f"{seg_type}:intro",
            "type": "doc-catalog-intro",
            "score": SEGMENT_TYPE_PRIORITY.get("doc-catalog-intro", (score, must_keep))[0],
            "must_keep": SEGMENT_TYPE_PRIORITY.get("doc-catalog-intro", (score, must_keep))[1],
            "full_text": intro_text,
            "fallback_text": None,
            "path": None,
            "doc_id": None,
            "order": -1,
        }
    )
    for idx, block in enumerate(entry_blocks):
        segment = _build_doc_entry_segment(block, order=idx)
        if segment:
            segments.append(segment)
    return segments


def _build_doc_search_segments(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = section["lines"]
    if not lines:
        return []
    intro_lines, entry_blocks = _split_doc_section_lines(lines)

    segments: List[Dict[str, Any]] = []
    intro_text_lines = [lines[0]] + _strip_empty_ends(intro_lines)
    intro_text = "\n".join(intro_text_lines).rstrip()
    seg_type, score, must_keep = _resolve_section_type(section["heading"])
    segments.append(
        {
            "id": f"{seg_type}:intro",
            "type": "doc-search",
            "score": SEGMENT_TYPE_PRIORITY.get("doc-search", (score, must_keep))[0],
            "must_keep": SEGMENT_TYPE_PRIORITY.get("doc-search", (score, must_keep))[1],
            "full_text": intro_text,
            "fallback_text": None,
            "path": None,
            "doc_id": None,
            "order": -1,
        }
    )
    for idx, block in enumerate(entry_blocks):
        entry_lines = _strip_empty_ends(block)
        if not entry_lines:
            continue
        first = entry_lines[0].strip()
        doc_id = ""
        rel_path = ""
        doc_match = re.match(r"^-+\s*(DOC-[A-Z0-9]+)\s*(?:\[[^\]]+\])?\s*—\s*(.+)$", first)
        if doc_match:
            doc_id = doc_match.group(1).strip()
            rel_path = doc_match.group(2).strip()
        fallback_text = first
        segment_text = "\n".join(entry_lines).rstrip()
        segments.append(
            {
                "id": f"doc-search:{idx:02d}:{doc_id or idx}",
                "type": "doc-search-entry",
                "score": 54,
                "must_keep": False,
                "full_text": segment_text,
                "fallback_text": fallback_text,
                "path": rel_path,
                "doc_id": doc_id,
                "order": idx,
            }
        )
    return segments


def _build_generic_segment(section: Dict[str, Any], order: int) -> Dict[str, Any]:
    lines = section["lines"]
    if not lines:
        return {}
    seg_type, score, must_keep = _resolve_section_type(section["heading"])
    text = "\n".join(_strip_empty_ends(lines)).rstrip()
    heading_key = _normalize_heading(section["heading"]) or "lead-in"
    return {
        "id": f"{seg_type}:{order:02d}:{heading_key}",
        "type": seg_type,
        "score": score,
        "must_keep": must_keep,
        "full_text": text,
        "fallback_text": None,
        "path": None,
        "doc_id": None,
        "order": order,
    }


def _build_segments_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    sections = _split_sections(lines)
    segments: List[Dict[str, Any]] = []
    for idx, section in enumerate(sections):
        heading = section["heading"]
        seg_type, _, _ = _resolve_section_type(heading)
        if seg_type == "doc-catalog":
            segments.extend(_build_doc_catalog_segments(section))
        elif seg_type == "doc-search":
            segments.extend(_build_doc_search_segments(section))
        else:
            segment = _build_generic_segment(section, idx)
            if segment:
                segments.append(segment)
    return segments


def _initialise_segment_metrics(segments: List[Dict[str, Any]]) -> None:
    for segment in segments:
        full_text = segment.get("full_text") or ""
        fallback_text = segment.get("fallback_text")
        segment["full_tokens"] = _approximate_tokens(full_text)
        segment["current_text"] = full_text
        segment["current_tokens"] = segment["full_tokens"]
        if fallback_text:
            segment["fallback_tokens"] = _approximate_tokens(fallback_text)
        else:
            segment["fallback_tokens"] = None
        segment["fallback_used"] = False
        segment["dropped"] = False


def _recalculate_total_tokens(segments: List[Dict[str, Any]]) -> int:
    return sum(segment["current_tokens"] for segment in segments if not segment["dropped"])


def _apply_pruning(
    segments: List[Dict[str, Any]],
    soft_limit: int,
    hard_limit: int,
    *,
    margin: float,
) -> Tuple[int, Dict[str, int], int]:
    _initialise_segment_metrics(segments)
    pruned_items: Dict[str, int] = {}
    pruned_bytes = 0

    def bump(metric: str, amount: int = 1) -> None:
        pruned_items[metric] = pruned_items.get(metric, 0) + amount

    def estimated_total(tokens: int) -> int:
        return math.ceil(tokens * margin)

    total_tokens = _recalculate_total_tokens(segments)
    total_estimated = estimated_total(total_tokens)

    if soft_limit > 0 and total_estimated <= soft_limit:
        return total_estimated, pruned_items, pruned_bytes

    # Stage 1 — degrade via fallback (lowest priority first)
    fallback_candidates = [
        segment
        for segment in segments
        if not segment["must_keep"]
        and not segment["dropped"]
        and segment.get("fallback_text")
        and segment.get("fallback_tokens") is not None
        and segment.get("fallback_tokens") < segment["current_tokens"]
    ]
    fallback_candidates.sort(key=lambda seg: (seg["score"], -(seg["current_tokens"] - seg["fallback_tokens"])))

    for segment in fallback_candidates:
        if soft_limit > 0 and estimated_total(total_tokens) <= soft_limit:
            break
        original_tokens = segment["current_tokens"]
        fallback_tokens = segment["fallback_tokens"]
        fallback_text = segment["fallback_text"]
        if fallback_tokens is None or fallback_text is None:
            continue
        segment["current_text"] = fallback_text
        segment["current_tokens"] = fallback_tokens
        segment["fallback_used"] = True
        total_tokens -= (original_tokens - fallback_tokens)
        total_estimated = estimated_total(total_tokens)
        full_text = segment.get("full_text") or ""
        pruned_bytes += max(0, len(full_text) - len(fallback_text))
        if segment["type"].startswith("doc-"):
            bump("doc_snippets_elided")
        else:
            bump("segments_elided")
        bump("artefacts_elided")

    # Stage 2 — drop lowest priority optional segments
    drop_candidates = [
        segment
        for segment in segments
        if not segment["must_keep"]
        and not segment["dropped"]
    ]
    drop_candidates.sort(key=lambda seg: (seg["score"], seg["current_tokens"]))

    for segment in drop_candidates:
        if soft_limit > 0 and estimated_total(total_tokens) <= soft_limit:
            break
        if segment["dropped"]:
            continue
        total_tokens -= segment["current_tokens"]
        pruned_bytes += len(segment["current_text"])
        segment["dropped"] = True
        segment["current_text"] = ""
        segment["current_tokens"] = 0
        metric = "segments_dropped"
        bump(metric)

    total_estimated = estimated_total(_recalculate_total_tokens(segments))
    if hard_limit > 0 and total_estimated > hard_limit:
        # Unable to satisfy hard cap even after pruning; signal via return value
        return total_estimated, pruned_items, pruned_bytes

    return total_estimated, pruned_items, pruned_bytes


project_root_path: Optional[Path] = None
staging_root: Optional[Path] = None


def _resolve_display_path(path_obj: Path) -> Path:
    try:
        return path_obj.resolve()
    except Exception:
        return path_obj


def _select_display_path(candidates: List[Path]) -> str:
    filtered = [candidate for candidate in candidates if candidate is not None]
    for candidate in filtered:
        resolved = _resolve_display_path(candidate)
        if resolved.exists():
            return str(resolved)
    if filtered:
        return str(_resolve_display_path(filtered[-1]))
    return ""


def _first_existing_path(candidates: List[Path]) -> Optional[Path]:
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.exists():
            return resolved
    return None


def _git_rev_parse(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _summarise_problem(title: str, description_lines: Sequence[str]) -> str:
    pieces: List[str] = []
    if title:
        pieces.append(title.strip())
    if description_lines:
        desc = " ".join(line.strip() for line in description_lines[:3] if line.strip())
        if desc:
            pieces.append(desc)
    summary = " — ".join(pieces) if pieces else ""
    summary = _normalise_space(summary)
    return summary[:480]


def _dedupe_preserve_order(items: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for item in items:
        key = (item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())
    return result


def _tokenize_text_for_search(value: str) -> List[str]:
    tokens: List[str] = []
    for match in re.findall(r"[A-Za-z0-9_/.-]{3,}", value or ""):
        token = match.strip("._-/")
        if len(token) < 3:
            continue
        tokens.append(token.lower())
    return tokens


def _collect_search_terms(
    task_title: str,
    document_reference: str,
    tags: Sequence[str],
    acceptance_items: Sequence[str],
    story_title: str,
) -> List[str]:
    raw_terms: List[str] = []

    def add_term(term: str) -> None:
        if not term:
            return
        stripped = term.strip()
        if len(stripped) < 3:
            return
        raw_terms.append(stripped)

    for chunk in re.split(r"[\n,;]+", document_reference or ""):
        add_term(chunk)
    for tag in tags or []:
        add_term(str(tag))
    for line in (acceptance_items or [])[:3]:
        add_term(line)
    add_term(task_title or "")
    add_term(story_title or "")

    for token in _tokenize_text_for_search(task_title):
        add_term(token)
    for token in _tokenize_text_for_search(story_title):
        add_term(token)
    if document_reference:
        for token in _tokenize_text_for_search(document_reference):
            add_term(token)

    return _dedupe_preserve_order(raw_terms)[:16]


def _build_fts_query(terms: Sequence[str]) -> str:
    clauses: List[str] = []
    for term in terms:
        safe = term.replace('"', " ").strip()
        if not safe:
            continue
        clauses.append(f'"{safe}"')
    return " OR ".join(clauses)


def _run_fts_search(db_path: Optional[Path], terms: Sequence[str], limit: int) -> List[Dict[str, object]]:
    if not db_path or not db_path.exists() or not terms:
        return []
    query = _build_fts_query(terms)
    if not query:
        return []
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT doc_id,
                       snippet(documentation_search, 1, '[', ']', ' … ', 32) AS excerpt
                  FROM documentation_search
                 WHERE documentation_search MATCH ?
                 LIMIT ?
                """,
                (query, limit),
            ).fetchall()
    except sqlite3.Error:
        return []

    hits: List[Dict[str, object]] = []
    for row in rows:
        doc_id = (row["doc_id"] or "").strip()
        if not doc_id:
            continue
        hits.append(
            {
                "doc_id": doc_id,
                "method": "fts",
                "snippet": (row["excerpt"] or "").strip(),
            }
        )
    return hits


def _hash_embedding_vector(text: str, dims: int) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8", "replace")).digest()
    values: List[float] = []
    seed = digest
    while len(values) < dims:
        for idx in range(0, len(seed), 4):
            if len(values) >= dims:
                break
            chunk = seed[idx : idx + 4]
            if len(chunk) < 4:
                chunk = chunk.ljust(4, b"\0")
            val = int.from_bytes(chunk, "big", signed=False)
            values.append((val % 1000) / 1000.0)
        seed = hashlib.sha256(seed).digest()
    norm = math.sqrt(sum(val * val for val in values)) or 1.0
    return [val / norm for val in values]


def _run_vector_search(
    vector_index_path: Optional[Path],
    terms: Sequence[str],
    limit: int,
    exclude: Set[str],
) -> List[Dict[str, object]]:
    if not vector_index_path or not vector_index_path.exists() or not terms or limit <= 0:
        return []
    query_text = " ".join(terms).strip()
    if not query_text:
        return []
    try:
        conn = sqlite3.connect(str(vector_index_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []

    hits: List[Tuple[float, Dict[str, object]]] = []
    try:
        rows = conn.execute(
            "SELECT doc_id, section_id, surface, vector_json, dims FROM vectors"
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return []
    finally:
        conn.close()

    for row in rows:
        doc_id = (row["doc_id"] or "").strip()
        if not doc_id or doc_id in exclude:
            continue
        vector_json = row["vector_json"]
        dims = row["dims"] or 0
        try:
            vector = json.loads(vector_json or "[]")
        except Exception:
            continue
        if dims <= 0:
            dims = len(vector)
        if dims <= 0 or len(vector) != dims:
            continue
        query_vector = _hash_embedding_vector(query_text, dims)
        if len(query_vector) != len(vector):
            continue
        score = float(sum(a * b for a, b in zip(query_vector, vector)))
        hits.append(
            (
                score,
                {
                    "doc_id": doc_id,
                    "method": "vector",
                    "score": score,
                    "surface": row["surface"],
                },
            )
        )

    hits.sort(key=lambda item: item[0], reverse=True)
    results: List[Dict[str, object]] = []
    for score, payload in hits:
        if len(results) >= limit:
            break
        doc_id = payload.get("doc_id")
        if not doc_id or doc_id in exclude:
            continue
        results.append(payload)
        exclude.add(doc_id)
    return results


def _run_ripgrep_search(
    project_root: Optional[Path],
    terms: Sequence[str],
    limit: int,
    exclude: Set[str],
) -> List[Dict[str, object]]:
    if not project_root or not project_root.exists() or limit <= 0:
        return []
    if shutil.which("rg") is None:
        return []
    query_term = next((term for term in terms if len(term) >= 3), "")
    if not query_term:
        return []
    docs_dir = project_root / "docs"
    if not docs_dir.exists():
        return []
    cmd = [
        "rg",
        "--with-filename",
        "--no-heading",
        "--line-number",
        "--max-count",
        "2",
        "--max-filesize",
        "512K",
        query_term,
        str(docs_dir),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if proc.returncode not in (0, 1):
        return []

    hits: List[Dict[str, object]] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path_str, line_number, snippet = parts
        candidate_path = Path(path_str).resolve()
        entry = _build_doc_entry(candidate_path)
        if not entry:
            continue
        doc_id = entry.get("doc_id")
        if not doc_id or doc_id in exclude:
            continue
        hits.append(
            {
                "doc_id": doc_id,
                "method": "ripgrep",
                "line": line_number,
                "snippet": snippet.strip(),
            }
        )
        exclude.add(doc_id)
        if len(hits) >= limit:
            break
    return hits


DB_PATH, STORY_SLUG, TASK_INDEX, PROMPT_PATH, CONTEXT_TAIL_PATH, MODEL_NAME, PROJECT_ROOT, STAGING_DIR = sys.argv[1:9]
TASK_INDEX = int(TASK_INDEX)


def _relative_path_for_prompt(path_obj: Path) -> str:
    for base in filter(None, [project_root_path, staging_root]):
        if not base:
            continue
        try:
            return str(path_obj.relative_to(base))
        except ValueError:
            continue
    return str(path_obj)


def _build_doc_entry(path_obj: Path):
    try:
        stat = path_obj.stat()
    except OSError:
        return None
    mtime_ns = getattr(stat, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat.st_mtime * 1_000_000_000)
    size = int(stat.st_size)
    try:
        resolved_str = str(path_obj.resolve())
    except Exception:
        resolved_str = str(path_obj)
    doc_id = "DOC-" + hashlib.sha256(resolved_str.encode("utf-8", "replace")).hexdigest()[:8].upper()
    existing = documents_store.get(doc_id)
    if isinstance(existing, dict):
        try:
            existing_mtime = int(existing.get("mtime_ns", 0))
        except Exception:
            existing_mtime = -1
        try:
            existing_size = int(existing.get("size", -1))
        except Exception:
            existing_size = -1
        if existing_mtime == int(mtime_ns) and existing_size == size:
            entry = existing.copy()
            entry["doc_id"] = doc_id
            entry["rel_path"] = entry.get("rel_path") or _relative_path_for_prompt(path_obj)
            return entry
    headings = []
    try:
        with path_obj.open("r", encoding="utf-8", errors="replace") as handle:
            for lineno, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                title = None
                level = None
                suffix = path_obj.suffix.lower()
                if suffix in {".md", ".markdown"}:
                    match = re.match(r"^(#{1,4})\\s+(.*)$", stripped)
                    if match:
                        level = len(match.group(1))
                        title = match.group(2).strip()
                if title is None:
                    match = re.match(r"^((?:\\d+\\.)+\\d*|\\d+|[A-Z][.)]|[IVXLCM]+\\.)\\s+(.*)$", stripped)
                    if match:
                        title = match.group(2).strip()
                        level = level or 2
                if title:
                    headings.append({
                        "title": title,
                        "line": lineno,
                        "level": int(level or 1),
                    })
                if len(headings) >= 80:
                    break
    except Exception:
        headings = []
    entry = {
        "doc_id": doc_id,
        "path": str(path_obj),
        "rel_path": _relative_path_for_prompt(path_obj),
        "mtime_ns": int(mtime_ns),
        "size": size,
        "headings": headings,
    }
    documents_store[doc_id] = {
        key: value for key, value in entry.items() if key != "doc_id"
    }
    doc_catalog_changed["value"] = True
    return entry


def _load_doc_snippet(path_obj: Path, doc_entry: dict) -> str:
    doc_id = doc_entry.get("doc_id")
    if not doc_id:
        return ""
    cached = snippet_store.get(doc_id)
    current_mtime = doc_entry.get("mtime_ns")
    if isinstance(cached, dict) and cached.get("mtime_ns") == current_mtime:
        return cached.get("preview") or ""
    preview_lines: list[str] = []
    try:
        with path_obj.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                if idx >= 80:
                    break
                stripped = line.strip()
                if stripped:
                    preview_lines.append(stripped)
    except Exception:
        preview_lines = []
    snippet_text = _condense_snippet(preview_lines, "", max_chars=360)
    snippet_store[doc_id] = {"preview": snippet_text, "mtime_ns": current_mtime}
    doc_catalog_changed["value"] = True
    return snippet_text

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cwd_path = Path.cwd()
project_root_path = cwd_path
if PROJECT_ROOT:
    project_root_candidate = Path(PROJECT_ROOT)
    if not project_root_candidate.is_absolute():
        project_root_candidate = cwd_path / project_root_candidate
    try:
        project_root_path = project_root_candidate.resolve()
    except Exception:
        project_root_path = project_root_candidate

staging_root: Optional[Path] = None
if STAGING_DIR:
    staging_candidate = Path(STAGING_DIR)
    if not staging_candidate.is_absolute():
        staging_candidate = project_root_path / staging_candidate
    try:
        staging_root = staging_candidate.resolve()
    except Exception:
        staging_root = staging_candidate
else:
    staging_root = project_root_path / ".gpt-creator" / "staging"

plan_instruction_dir: Optional[Path] = None
if staging_root:
    plan_candidate = staging_root / "plan"
    if plan_candidate.exists():
        plan_instruction_dir = plan_candidate

instruction_prompts: List[Tuple[str, List[str]]] = []
runner_config = _load_runner_config(project_root_path)

emit_progress(f"Preparing prompt for story '{STORY_SLUG}' task index {TASK_INDEX}")

story_row = cur.execute(
    'SELECT story_id, story_title, epic_key, epic_title, sequence FROM stories WHERE story_slug = ?',
    (STORY_SLUG,)
).fetchone()
if story_row is None:
    raise SystemExit(f"Story slug not found: {STORY_SLUG}")

task_rows = cur.execute(
    'SELECT task_id, title, description, estimate, assignees_json, tags_json, acceptance_json, dependencies_json, '
    'tags_text, story_points, dependencies_text, assignee_text, document_reference, idempotency, rate_limits, rbac, '
    'messaging_workflows, performance_targets, observability, acceptance_text, endpoints, sample_create_request, '
    'sample_create_response, user_story_ref_id, epic_ref_id, status, last_progress_at, last_progress_run, '
    'last_log_path, last_output_path, last_prompt_path, last_notes_json, last_commands_json, last_apply_status, '
    'last_changes_applied, last_tokens_total, last_duration_seconds, locked_by_migration, migration_epoch, '
    'reopened_by_migration, last_verified_commit, status_reason '
    'FROM tasks WHERE story_slug = ? ORDER BY position ASC',
    (STORY_SLUG,)
).fetchall()
conn.close()

if TASK_INDEX < 0 or TASK_INDEX >= len(task_rows):
    raise SystemExit(2)

task = task_rows[TASK_INDEX]
binder_cfg = runner_config.get("binder", {})
binder_enabled_config = _parse_bool(binder_cfg.get("enabled"), default=True)
binder_enabled_env = os.getenv("GC_BINDER_ENABLED", "").strip()
if binder_enabled_env:
    binder_enabled = _parse_bool(binder_enabled_env, default=binder_enabled_config)
else:
    binder_enabled = binder_enabled_config

binder_ttl = _parse_int(binder_cfg.get("ttlSeconds"), fallback=BINDER_DEFAULT_TTL_SECONDS)
binder_ttl_env = os.getenv("GC_BINDER_TTL_SECONDS", "").strip()
if binder_ttl_env:
    binder_ttl = _parse_int(binder_ttl_env, fallback=binder_ttl)
if binder_ttl < 0:
    binder_ttl = 0

binder_max_bytes = _parse_int(binder_cfg.get("maxSizeBytes"), fallback=BINDER_DEFAULT_MAX_BYTES)
binder_max_env = os.getenv("GC_BINDER_MAX_BYTES", "").strip()
if binder_max_env:
    binder_max_bytes = _parse_int(binder_max_env, fallback=binder_max_bytes)
if binder_max_bytes < 0:
    binder_max_bytes = 0

binder_clear_on_migration_cfg = _parse_bool(binder_cfg.get("clearOnMigration"), default=False)
binder_clear_env = os.getenv("GC_BINDER_CLEAR_ON_MIGRATION", "").strip()
if binder_clear_env:
    binder_clear_on_migration = _parse_bool(binder_clear_env, default=binder_clear_on_migration_cfg)
else:
    binder_clear_on_migration = binder_clear_on_migration_cfg

task_identifier = (task["task_id"] or "").strip()
task_title = (task["title"] or "").strip()


def _row_get(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


epic_slug_source = (
    (_row_get(story_row, "epic_key") or "").strip()
    or (_row_get(story_row, "epic_title") or "").strip()
    or (_row_get(story_row, "story_id") or "").strip()
    or STORY_SLUG
)

binder_status = "disabled"
binder_reason = ""
binder_data: Dict[str, Any] = {}
binder_path: Optional[Path] = None
current_git_head = _git_rev_parse(project_root_path)
if binder_enabled and task_identifier:
    emit_progress("Loading binder cache")
    binder_result = binder_load_for_prompt(
        project_root_path,
        epic_slug=epic_slug_source,
        story_slug=STORY_SLUG,
        task_id=task_identifier,
        ttl_seconds=binder_ttl,
        max_bytes=binder_max_bytes,
    )
    binder_status = binder_result.status
    binder_reason = binder_result.reason
    binder_data = binder_result.binder or {}
    binder_path = binder_result.path
else:
    binder_enabled = False
    binder_status = "disabled"
    binder_reason = "disabled"

binder_hit = binder_status == "hit"
binder_doc_refs = []
if binder_hit:
    binder_doc_refs = list(binder_data.get("doc_refs") or [])
documentation_db_path = os.getenv("GC_DOCUMENTATION_DB_PATH", "").strip()
doc_catalog_env_raw = os.getenv("GC_DOC_CATALOG_PATH", "").strip()

doc_library_candidates: List[Path] = []
doc_index_candidates: List[Path] = []
doc_catalog_candidates: List[Path] = []

if doc_catalog_env_raw:
    doc_catalog_candidates.append(Path(doc_catalog_env_raw))

if staging_root:
    doc_library_candidates.extend([
        staging_root / "doc-library.md",
        staging_root / "plan" / "docs" / "doc-library.md",
    ])
    doc_index_candidates.extend([
        staging_root / "doc-index.md",
        staging_root / "plan" / "docs" / "doc-index.md",
    ])
    doc_catalog_candidates.append(staging_root / "plan" / "work" / "doc-catalog.json")

doc_library_candidates.append(project_root_path / "docs" / "doc-library.md")
doc_index_candidates.append(project_root_path / "docs" / "doc-index.md")
if not doc_catalog_candidates:
    doc_catalog_candidates.append(project_root_path / ".gpt-creator" / "staging" / "plan" / "work" / "doc-catalog.json")

doc_library_path_str = _select_display_path(doc_library_candidates)
doc_index_path_str = _select_display_path(doc_index_candidates)
doc_catalog_path_str = _select_display_path(doc_catalog_candidates)
doc_library_shim_str = _select_display_path([project_root_path / "docs" / "doc-library.md"])
doc_index_shim_str = _select_display_path([project_root_path / "docs" / "doc-index.md"])

documentation_db_display = _select_display_path([Path(documentation_db_path)]) if documentation_db_path else ""

vector_index_path = None
vector_index_path_str = ""
if documentation_db_path:
    db_path_obj = Path(documentation_db_path)
    vector_index_candidates = []
    resolved_db = _resolve_display_path(db_path_obj)
    vector_index_candidates.append(resolved_db.parent / "documentation-vector-index.sqlite")
    vector_index_candidates.append(db_path_obj.parent / "documentation-vector-index.sqlite")
    vector_index_path = _first_existing_path(vector_index_candidates)
    vector_index_path_str = _select_display_path(vector_index_candidates)

example_query = "sqlite3 \"$GC_DOCUMENTATION_DB_PATH\" \"SELECT doc_id,surface FROM documentation_search WHERE documentation_search MATCH 'lockout' LIMIT 5;\""

catalog_reference_docs: List[str] = []
for filename in ("document-catalog-indexing.md", "document-catalog-metadata.md", "document-catalog-pipeline.md"):
    doc_candidate = project_root_path / "docs" / filename
    doc_candidate_str = _select_display_path([doc_candidate])
    if doc_candidate_str:
        catalog_reference_docs.append(f"`{doc_candidate_str}`")

documentation_asset_lines: List[str] = []
if doc_library_path_str:
    library_line = f"- Library overview: `{doc_library_path_str}` — review via `gpt-creator show-file {doc_library_path_str} --range START:END` for tags and owners."
    if doc_library_shim_str and doc_library_shim_str != doc_library_path_str:
        library_line += f" Shim fallback lives at `{doc_library_shim_str}`."
    documentation_asset_lines.append(library_line)
elif doc_library_shim_str:
    documentation_asset_lines.append(
        f"- Library overview (shim): `{doc_library_shim_str}` — review via `gpt-creator show-file {doc_library_shim_str} --range START:END` for tags and owners."
    )

if doc_index_path_str:
    index_line = f"- Headings index: `{doc_index_path_str}` lists section anchors so you can jump straight to the right slice."
    if doc_index_shim_str and doc_index_shim_str != doc_index_path_str:
        index_line += f" Shim fallback lives at `{doc_index_shim_str}`."
    documentation_asset_lines.append(index_line)
elif doc_index_shim_str:
    documentation_asset_lines.append(
        f"- Headings index (shim): `{doc_index_shim_str}` lists section anchors so you can jump straight to the right slice."
    )

if doc_catalog_path_str:
    documentation_asset_lines.append(
        f"- JSON catalog (doc/snippet map) at `{doc_catalog_path_str}` keeps scripted lookups fast while prompts stay lean."
    )

if catalog_reference_docs:
    documentation_asset_lines.append(
        f"- Deep-dive docs: {', '.join(catalog_reference_docs)} explain indexing, metadata, and pipelines powering these caches."
    )

def parse_json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return []

def parse_int_field(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value).strip()))
        except Exception:
            return None

def format_duration(seconds_value):
    seconds = parse_int_field(seconds_value)
    if seconds is None or seconds <= 0:
        return ""
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if sec or not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


DEFAULT_WORK_PROMPT = """## work-on-tasks Prompt
- Load the task details and acceptance criteria from the context section.
- Consult the documentation catalog or search hits before modifying files.
- Outline a concise plan, execute the required edits, and capture verification steps.
- Record follow-up actions when blockers remain.
"""

def clamp_text(text: str, limit: int) -> str:
    if limit <= 0 or not text:
        return text
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _truncate_lines(lines: Sequence[str], *, max_lines: int, max_chars: int) -> Tuple[List[str], bool, int]:
    if max_lines <= 0 and max_chars <= 0:
        return list(lines), False, sum(len(line) + 1 for line in lines)
    trimmed: List[str] = []
    total_chars = 0
    truncated = False
    char_limit = max(max_chars, 0)
    line_limit = max(max_lines, 0)
    for line in lines:
        prospective_chars = total_chars + len(line) + 1
        if line_limit and len(trimmed) >= line_limit:
            truncated = True
            break
        if char_limit and prospective_chars > char_limit:
            truncated = True
            break
        trimmed.append(line)
        total_chars = prospective_chars
    return trimmed, truncated, total_chars


def _truncate_bullets(items: Sequence[str], *, max_items: int, max_chars: int) -> Tuple[List[str], bool, int]:
    if max_items <= 0 and max_chars <= 0:
        return list(items), False, sum(len(item) + 1 for item in items)
    trimmed: List[str] = []
    total_chars = 0
    truncated = False
    item_limit = max(max_items, 0)
    char_limit = max(max_chars, 0)
    for item in items:
        prospective_chars = total_chars + len(item) + 1
        if item_limit and len(trimmed) >= item_limit:
            truncated = True
            break
        if char_limit and prospective_chars > char_limit:
            truncated = True
            break
        trimmed.append(item)
        total_chars = prospective_chars
    return trimmed, truncated, total_chars


def collect_instruction_prompts(plan_dir: Optional[Path], project_root: Optional[Path]) -> List[Tuple[str, List[str]]]:
    prompts: List[Tuple[str, List[str]]] = []
    search_roots: List[Path] = []
    if plan_dir and plan_dir.exists():
        search_roots.append(plan_dir)
    if project_root:
        for relative in ("src/prompts", "docs/prompts", ".gpt-creator/prompts"):
            candidate = project_root / relative
            if candidate.exists():
                search_roots.append(candidate)
    if not search_roots:
        return prompts

    seen: Set[Path] = set()
    for base_dir in search_roots:
        try:
            iterator = sorted(base_dir.rglob("*prompt.md"))
        except (OSError, RuntimeError):
            continue
        for candidate in iterator:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if resolved in seen or not candidate.is_file():
                continue
            seen.add(resolved)
            try:
                raw = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raw = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text = raw.strip()
            if not text:
                continue
            rel_repr = candidate.name
            if project_root:
                try:
                    rel_repr = str(candidate.relative_to(project_root)).replace("\\", "/")
                except ValueError:
                    pass
            if rel_repr == candidate.name and plan_dir:
                try:
                    rel_repr = str(candidate.relative_to(plan_dir)).replace("\\", "/")
                except ValueError:
                    rel_repr = candidate.name
            prompts.append((rel_repr, text.splitlines()))
    return prompts

instruction_prompts = collect_instruction_prompts(plan_instruction_dir, project_root_path)

if not instruction_prompts:
    fallback_prompt_paths = [
        project_root_path / "src" / "prompts" / "iterate" / "work_on_tasks.prompt.md",
        project_root_path / "docs" / "prompts" / "work_on_tasks.prompt.md",
    ]
    for prompt_path in fallback_prompt_paths:
        if not prompt_path.exists():
            continue
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if prompt_text.strip():
            try:
                rel_label = str(prompt_path.relative_to(project_root_path))
            except ValueError:
                rel_label = prompt_path.name
            instruction_prompts = [(rel_label, prompt_text.strip().splitlines())]
            break
    else:
        instruction_prompts = [("builtin/work_on_tasks.prompt.md", DEFAULT_WORK_PROMPT.strip().splitlines())]

def build_log_excerpt(path_obj: Path, max_lines: int = 40, max_chars: int = 160) -> list[str]:
    try:
        raw = path_obj.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [f"(unable to read log: {exc})"]
    lines_local = raw.splitlines()
    if not lines_local:
        return []
    excerpt = []
    if len(lines_local) > max_lines:
        trimmed = len(lines_local) - max_lines
        excerpt.append(f"... trimmed {trimmed} earlier line(s) ...")
        subset = lines_local[-max_lines:]
    else:
        subset = lines_local
    for line in subset:
        excerpt.append(clamp_text(line, max_chars))
    return excerpt

def clean(value: str) -> str:
    return (value or '').strip()


def project_display_name(root: str) -> str:
    if not root:
        return "Project"
    try:
        name = Path(root).name.strip()
    except Exception:
        name = ""
    if not name:
        return "Project"
    tokens = [token for token in re.split(r'[^A-Za-z0-9]+', name) if token]
    if not tokens:
        return "Project"
    words = []
    for token in tokens:
        if len(token) <= 3:
            words.append(token.upper())
        elif token.isupper():
            words.append(token)
        else:
            words.append(token.capitalize())
    return ' '.join(words) or "Project"

assignees = parse_json_list(task['assignees_json'])
tags = parse_json_list(task['tags_json'])
acceptance = parse_json_list(task['acceptance_json'])
dependencies = parse_json_list(task['dependencies_json'])

description = clean(task['description'])
if description:
    description_lines = description.splitlines()
else:
    description_lines = []

desc_trimmed, desc_truncated, _ = _truncate_lines(
    description_lines,
    max_lines=DESCRIPTION_MAX_LINES,
    max_chars=DESCRIPTION_MAX_CHARS,
)
if desc_truncated:
    truncated_sections["description"] = {
        "original_lines": len(description_lines),
        "original_chars": len(description),
        "max_lines": DESCRIPTION_MAX_LINES,
        "max_chars": DESCRIPTION_MAX_CHARS,
    }
description_lines = desc_trimmed

tags_text = clean(task['tags_text'])
story_points = clean(task['story_points'])
dependencies_text = clean(task['dependencies_text'])
assignee_text = clean(task['assignee_text'])
document_reference = clean(task['document_reference'])
idempotency_text = clean(task['idempotency'])
rate_limits = clean(task['rate_limits'])
rbac_text = clean(task['rbac'])
messaging_workflows = clean(task['messaging_workflows'])
performance_targets = clean(task['performance_targets'])
observability_text = clean(task['observability'])
acceptance_text_extra = (task['acceptance_text'] or '').strip() if task['acceptance_text'] else ''
endpoints_text = (task['endpoints'] or '').strip() if task['endpoints'] else ''
sample_create_request = (task['sample_create_request'] or '').strip() if task['sample_create_request'] else ''
sample_create_response = (task['sample_create_response'] or '').strip() if task['sample_create_response'] else ''
user_story_ref_id = clean(task['user_story_ref_id'])
epic_ref_id = clean(task['epic_ref_id'])

task_status = clean(task['status'])
last_progress_at = clean(task['last_progress_at'])
last_progress_run = clean(task['last_progress_run'])
last_apply_status = clean(task['last_apply_status'])
last_log_path = clean(task['last_log_path'])
last_output_path = clean(task['last_output_path'])
last_prompt_path = clean(task['last_prompt_path'])
last_changes_applied = parse_int_field(task['last_changes_applied']) or 0
last_tokens_total = parse_int_field(task['last_tokens_total'])
last_duration_seconds = parse_int_field(task['last_duration_seconds'])
last_notes = parse_json_list(task['last_notes_json'])
last_commands = parse_json_list(task['last_commands_json'])
locked_by_migration = int(task['locked_by_migration'] or 0)
migration_epoch = parse_int_field(_row_get(task, 'migration_epoch'))
last_verified_commit = clean(_row_get(task, 'last_verified_commit'))
status_reason = clean(_row_get(task, 'status_reason'))

project_display = project_display_name(PROJECT_ROOT)
repo_path = PROJECT_ROOT or '.'
try:
    prompt_dir = Path(PROMPT_PATH).resolve().parent
except Exception:
    prompt_dir = Path(".").resolve()

sample_limit_env = os.getenv("GC_PROMPT_SAMPLE_LINES", "").strip()
try:
    sample_limit = int(sample_limit_env) if sample_limit_env else 80
except ValueError:
    sample_limit = 80
if sample_limit < 0:
    sample_limit = 0

compact_mode = os.getenv("GC_PROMPT_COMPACT", "").strip().lower() not in {"", "0", "false"}

truncated_sections: Dict[str, Dict[str, int]] = {}

lines = []
lines.append(f"# You are Codex (model: {MODEL_NAME})")
lines.append("")
lines.append(f"You are assisting the {project_display} delivery team. Implement the task precisely using the repository at: {repo_path}")
lines.append("")
lines.append("## Documentation Assets")
if documentation_db_display:
    lines.append(f"- Central catalogue lives in `{documentation_db_display}` (tables `documentation` and `documentation_changes`).")
    lines.append("- Use it to locate PDR/SDS/RFP/OpenAPI/SQL dumps, diagrams, and samples before making changes.")
    lines.append("- After modifying a document, update the registry (e.g. `python3 src/lib/doc_registry.py register --runtime-dir .gpt-creator …`) so change history stays accurate.")
    lines.append("- Capture relevant doc references from the registry in your summary so the team can follow up.")
    lines.append(f"- Keyword search via `documentation_search` FTS (e.g. `{example_query}`).")
    if vector_index_path_str:
        lines.append(f"- Semantic index lives at `{vector_index_path_str}`; refresh with `python3 src/lib/doc_indexer.py --runtime-dir .gpt-creator` after major doc edits.")
else:
    lines.append("- Documentation registry database not detected; rely on the reference files below and register new/updated docs with `python3 src/lib/doc_registry.py register --runtime-dir .gpt-creator …` when possible.")

if documentation_asset_lines:
    lines.extend(documentation_asset_lines)
else:
    lines.append("- (No documentation assets detected; ensure doc-library and doc-index are generated before editing.)")

lines.append("")
lines.append("## Story")

epic_id = clean(story_row['epic_key'])
epic_title = clean(story_row['epic_title'])
story_id = clean(story_row['story_id'])
story_title = clean(story_row['story_title'])
sequence = story_row['sequence']

if compact_mode:
    story_label = story_id or STORY_SLUG
    if story_label and story_title:
        summary = f"- {story_label} — {story_title}"
    elif story_label:
        summary = f"- {story_label}"
    elif story_title:
        summary = f"- {story_title}"
    else:
        summary = "- Story details unavailable"
    extras = []
    if epic_id or epic_title:
        epic_bits = [bit for bit in [epic_id, epic_title] if bit]
        extras.append("epic " + " — ".join(epic_bits))
    if sequence:
        extras.append(f"order {sequence}")
    if extras:
        summary += f" ({'; '.join(extras)})"
    lines.append(summary)
else:
    if epic_id or epic_title:
        parts = [part for part in [epic_id, epic_title] if part]
        lines.append("- Epic: " + " — ".join(parts))
    if story_id or story_title:
        parts = [part for part in [story_id, story_title] if part]
        lines.append("- Story: " + " — ".join(parts))
    if sequence:
        lines.append(f"- Story order: {sequence}")

lines.append("")
lines.append("## Task")
task_id = clean(task['task_id'])
task_title = clean(task['title'])
estimate = clean(task['estimate'])

if compact_mode:
    task_label = task_id or f"Task {TASK_INDEX + 1}"
    summary = f"- {task_label}"
    if task_title:
        summary += f" — {task_title}"
    lines.append(summary)
    meta_bits = []
    if estimate:
        meta_bits.append(f"estimate {estimate}")
    if story_points and story_points != estimate:
        meta_bits.append(f"story points {story_points}")
    if assignees or assignee_text:
        assigned = ", ".join(assignees) if assignees else assignee_text
        meta_bits.append(f"assignees {assigned}")
    if tags:
        tags_summary = ", ".join(tags[:3])
        if len(tags) > 3:
            tags_summary += "…"
        meta_bits.append(f"tags {tags_summary}")
    elif tags_text:
        meta_bits.append(f"tags {tags_text}")
    if document_reference:
        meta_bits.append(f"doc {document_reference}")
    if rate_limits:
        meta_bits.append(f"rate limits {rate_limits}")
    if meta_bits:
        lines.append(f"- Details: {'; '.join(meta_bits)}")
else:
    if task_id:
        lines.append(f"- Task ID: {task_id}")
    if task_title:
        lines.append(f"- Title: {task_title}")
    if estimate:
        lines.append(f"- Estimate: {estimate}")
    if assignees:
        lines.append("- Assignees: " + ", ".join(assignees))
    elif assignee_text:
        lines.append(f"- Assignee: {assignee_text}")
    if tags:
        lines.append("- Tags: " + ", ".join(tags))
    elif tags_text:
        lines.append(f"- Tags: {tags_text}")
    if story_points and story_points != estimate:
        lines.append(f"- Story points: {story_points}")
    elif story_points and not estimate:
        lines.append(f"- Story points: {story_points}")
    if document_reference:
        lines.append(f"- Document reference: {document_reference}")
    if idempotency_text:
        lines.append(f"- Idempotency: {idempotency_text}")
    if rate_limits:
        lines.append(f"- Rate limits: {rate_limits}")
    if rbac_text:
        lines.append(f"- RBAC: {rbac_text}")
    if messaging_workflows:
        lines.append(f"- Messaging & workflows: {messaging_workflows}")
    if performance_targets:
        lines.append(f"- Performance targets: {performance_targets}")
    if observability_text:
        lines.append(f"- Observability: {observability_text}")
    if user_story_ref_id and user_story_ref_id.lower() != story_id.lower():
        lines.append(f"- User story reference ID: {user_story_ref_id}")
    if epic_ref_id and epic_ref_id.lower() != epic_id.lower():
        lines.append(f"- Epic reference ID: {epic_ref_id}")

lines.append("")
lines.append("### Description")
if description_lines:
    lines.extend(description_lines)
    if "description" in truncated_sections:
        lines.append("(Description truncated for prompt budget; consult task backlog for full text.)")
else:
    lines.append("(No additional description provided.)")

if acceptance:
    acceptance_trimmed, acceptance_truncated, _ = _truncate_bullets(
        acceptance,
        max_items=ACCEPTANCE_MAX_ITEMS,
        max_chars=ACCEPTANCE_MAX_CHARS,
    )
    lines.append("")
    lines.append("### Acceptance Criteria")
    for item in acceptance_trimmed:
        lines.append(f"- {item}")
    if acceptance_truncated:
        lines.append("- … (additional acceptance criteria omitted; see task backlog)")
        truncated_sections["acceptance"] = {
            "original_items": len(acceptance),
            "max_items": ACCEPTANCE_MAX_ITEMS,
            "max_chars": ACCEPTANCE_MAX_CHARS,
        }
elif acceptance_text_extra:
    lines.append("")
    lines.append("### Acceptance Criteria")
    acceptance_extra_lines = acceptance_text_extra.splitlines()
    acceptance_extra_trimmed, acceptance_extra_truncated, _ = _truncate_lines(
        acceptance_extra_lines,
        max_lines=ACCEPTANCE_MAX_ITEMS,
        max_chars=ACCEPTANCE_MAX_CHARS,
    )
    lines.extend(acceptance_extra_trimmed)
    if acceptance_extra_truncated:
        lines.append("… (additional acceptance text omitted; see task backlog)")
        truncated_sections["acceptance_text"] = {
            "original_lines": len(acceptance_extra_lines),
            "max_lines": ACCEPTANCE_MAX_ITEMS,
            "max_chars": ACCEPTANCE_MAX_CHARS,
        }

if dependencies:
    lines.append("")
    lines.append("### Dependencies")
    for dep in dependencies:
        lines.append(f"- {dep}")
elif dependencies_text:
    lines.append("")
    lines.append("### Dependencies")
    lines.extend(dependencies_text.splitlines())

if endpoints_text:
    lines.append("")
    lines.append("### Endpoints")
    lines.extend(endpoints_text.splitlines())

binder_summary_lines: List[str] = []
if binder_hit:
    binder_summary_lines.append("")
    binder_summary_lines.append("## Task Binder Summary")
    if binder_data.get("problem"):
        binder_summary_lines.append(binder_data.get("problem"))
    invariants_section = binder_data.get("invariants") or []
    if invariants_section:
        binder_summary_lines.append("")
        binder_summary_lines.append("### Invariants")
        for item in invariants_section[:10]:
            binder_summary_lines.append(f"- {item}")
    acceptance_section = binder_data.get("acceptance") or []
    if acceptance_section:
        binder_summary_lines.append("")
        binder_summary_lines.append("### Acceptance Checklist")
        for item in acceptance_section[:12]:
            binder_summary_lines.append(f"- {item}")
    files_section = binder_data.get("files") or {}
    primary_files = files_section.get("primary") or []
    related_files = files_section.get("related") or []
    deps_files = files_section.get("deps") or []
    if primary_files or related_files or deps_files:
        binder_summary_lines.append("")
        binder_summary_lines.append("### Key Files")
        if primary_files:
            binder_summary_lines.append(f"- Primary: {', '.join(primary_files[:6])}")
        if related_files:
            binder_summary_lines.append(f"- Related: {', '.join(related_files[:6])}")
        if deps_files:
            binder_summary_lines.append(f"- Dependencies: {', '.join(deps_files[:6])}")
    if binder_doc_refs:
        binder_summary_lines.append("")
        binder_summary_lines.append("### Doc References")
        for ref in binder_doc_refs[:8]:
            doc_label = ref.get("doc_id") or ref.get("rel_path") or "doc"
            reason = ref.get("reason") or ref.get("snippet") or ""
            if reason:
                binder_summary_lines.append(f"- {doc_label} — {reason}")
            else:
                binder_summary_lines.append(f"- {doc_label}")
    evidence_section = (binder_data.get("evidence") or {}).get("notes") or []
    if evidence_section:
        binder_summary_lines.append("")
        binder_summary_lines.append("### Evidence Notes")
        for note in evidence_section[:8]:
            binder_summary_lines.append(f"- {note}")

lines.extend(binder_summary_lines)

doc_snippets_enabled = os.getenv("GC_PROMPT_DOC_SNIPPETS", "").strip().lower() not in {"", "0", "false"}

has_previous_attempt = any([
    last_progress_at,
    last_apply_status,
    last_log_path,
    last_output_path,
    last_notes,
    last_commands,
])

if has_previous_attempt:
    def resolve_history_path(raw_path: str) -> Optional[Path]:
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if candidate.is_absolute():
            candidates = [candidate]
        else:
            candidates = []
            for base in [prompt_dir, project_root_path, staging_root]:
                if not base:
                    continue
                base_path = base if isinstance(base, Path) else Path(base)
                candidates.append(base_path / candidate)
            candidates.append(candidate)
        for option in candidates:
            try:
                resolved = option.resolve()
            except Exception:
                resolved = option
            if resolved.exists():
                return resolved
        return candidates[0] if candidates else candidate

    def render_relative(path_obj: Path) -> str:
        for root in filter(None, [project_root_path, staging_root]):
            if isinstance(root, Path):
                try:
                    return str(path_obj.relative_to(root))
                except ValueError:
                    continue
        return str(path_obj)

    lines.append("")
    lines.append("### Previous Attempt Summary")

    status_bits = []
    if task_status:
        status_bits.append(task_status)
    if last_apply_status:
        status_bits.append(f"apply:{last_apply_status}")
    if last_changes_applied:
        status_bits.append(f"changes:{last_changes_applied}")
    if status_bits:
        lines.append(f"- Status: {', '.join(status_bits)}")

    metrics_bits = []
    if last_progress_at:
        metrics_bits.append(f"at {last_progress_at}")
    if last_progress_run:
        metrics_bits.append(f"run {last_progress_run}")
    if last_tokens_total is not None:
        metrics_bits.append(f"tokens {last_tokens_total}")
    duration_text = format_duration(last_duration_seconds)
    if duration_text:
        metrics_bits.append(f"duration {duration_text}")
    if metrics_bits:
        lines.append(f"- Metrics: {', '.join(metrics_bits)}")

    if last_notes:
        lines.append("- Notes:")
        for note in last_notes[:4]:
            lines.append(f"  - {clamp_text(note, 220)}")

    if last_commands:
        lines.append("- Prior command attempts:")
        for cmd in last_commands[:3]:
            lines.append(f"  - {clamp_text(cmd, 160)}")

    log_excerpt_lines: list[str] = []
    log_display = ""
    if last_log_path:
        resolved_path = resolve_history_path(last_log_path)
        if isinstance(resolved_path, Path) and resolved_path.exists():
            log_display = render_relative(resolved_path)
            log_excerpt_lines = build_log_excerpt(resolved_path)
        else:
            log_display = last_log_path
    if log_display:
        lines.append(f"- Log: {log_display}")
        if log_excerpt_lines:
            lines.append("```text")
            lines.extend(log_excerpt_lines)
            lines.append("```")

    if last_output_path:
        output_path_resolved = resolve_history_path(last_output_path)
        if isinstance(output_path_resolved, Path) and output_path_resolved.exists():
            lines.append(f"- Output: {render_relative(output_path_resolved)}")
        else:
            lines.append(f"- Output: {last_output_path}")

    if last_prompt_path:
        prompt_path_resolved = resolve_history_path(last_prompt_path)
        if isinstance(prompt_path_resolved, Path) and prompt_path_resolved.exists():
            lines.append(f"- Prompt: {render_relative(prompt_path_resolved)}")
        else:
            lines.append(f"- Prompt: {last_prompt_path}")

def _split_items(raw: str):
    if not raw:
        return []
    items = re.split(r'[\n;,]+', raw)
    return [item.strip() for item in items if item and item.strip()]

def _collect_candidate_files(ref: str):
    candidates = []
    if not ref:
        return candidates
    ref_stripped = ref.strip()
    ref_lower = ref_stripped.lower()

    def add_path(candidate: Path):
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.is_file():
            if resolved not in candidates:
                candidates.append(resolved)

    # Direct path attempts relative to project or staging roots
    for base in filter(None, [project_root_path, staging_root]):
        candidate = base / ref_stripped
        if candidate.is_file():
            add_path(candidate)
    # If ref looks like filename only, search staging dir for matches
    if staging_root and ("." in ref_stripped or "/" not in ref_stripped):
        for match in staging_root.rglob(ref_stripped):
            add_path(match)

    keyword_map = {
        "sds": ["sds.*"],
        "pdr": ["pdr.*"],
        "openapi": ["openapi.*"],
        "swagger": ["openapi.*"],
        "erd": ["*.mmd"],
        "mermaid": ["*.mmd"],
        "schema": ["*.sql", "*.yaml", "*.yml"],
    }
    if staging_root:
        for keyword, patterns in keyword_map.items():
            if keyword in ref_lower:
                for pattern in patterns:
                    for match in staging_root.glob(pattern):
                        add_path(match)

    return candidates

def classify_directory_crawl(command: str) -> Optional[str]:
    if not command:
        return None
    stripped = command.strip()
    if not stripped:
        return None
    tokens = stripped.split()
    if not tokens:
        return None
    cmd = tokens[0]
    args = tokens[1:]
    non_option_args = [tok for tok in args if not tok.startswith('-')]
    if cmd == 'ls':
        if not non_option_args:
            return "ls with no explicit target"
        return None
    if cmd == 'find':
        target = non_option_args[0] if non_option_args else ''
        if not target or target in {'.', './', '..'}:
            return "find without explicit target"
        return None
    if cmd == 'rg':
        if '--files' in tokens:
            return "rg --files directory scan"
        return None
    if cmd == 'fd':
        return "fd directory scan"
    if cmd == 'tree':
        if not non_option_args:
            return "tree with no explicit target"
        return None
    return None

def resolve_workdir(cwd: str, project_root_path: Optional[pathlib.Path]) -> pathlib.Path:
    if cwd:
        candidate = pathlib.Path(cwd)
        if candidate.is_absolute():
            return candidate
        base = project_root_path or pathlib.Path.cwd()
        return base / candidate
    return project_root_path or pathlib.Path.cwd()

def _extract_snippet(path: Path, term: str, limit: int):
    if limit <= 0:
        return ([], False)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return ([f"(failed to read {path.name}: {exc})"], False)
    lines_local = text.splitlines()
    if not lines_local:
        return ([], False)
    search_terms: list[str] = []
    if term:
        search_terms.append(term.strip())
        search_terms.extend(
            [token for token in re.split(r'[^a-z0-9/_\-.]+', term.lower()) if len(token) >= 3]
        )

    match_index = None
    for needle in search_terms:
        if not needle:
            continue
        needle_lower = needle.lower()
        for idx, line in enumerate(lines_local):
            if needle_lower in line.lower():
                match_index = idx
                break
        if match_index is not None:
            break

    if match_index is None:
        start = 0
    else:
        start = max(0, match_index - max(5, limit // 2))
    end = min(len(lines_local), start + limit)
    snippet = lines_local[start:end]
    truncated = end < len(lines_local)
    if match_index is not None and start > 0:
        snippet.insert(0, "... (preceding lines omitted)")
    if truncated:
        snippet.append("... (additional content truncated)")
    return (snippet, truncated)

def _minify_payload(value: str) -> str:
    if not value:
        return ""
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except Exception:
        return raw
    try:
        return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return raw

def _chunk_text(text: str, width: int = 160) -> list[str]:
    if not text:
        return []
    return [text[i:i + width] for i in range(0, len(text), width)]

def _normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def _condense_snippet(snippet_lines, term, max_chars=420):
    core = " ".join(line.strip() for line in snippet_lines if line.strip())
    if not core:
        return ""
    core = _normalise_space(core)
    if term:
        lowered = core.lower()
        idx = lowered.find(term.lower())
        if idx > 0:
            start = max(0, idx - 180)
            core = core[start:]
    sentences = re.split(r'(?<=[.!?])\s+', core)
    assembled: list[str] = []
    total = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        assembled.append(sentence)
        total += len(sentence)
        if total >= max_chars:
            break
    summary = " ".join(assembled) if assembled else core
    summary = summary.strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "…"
    return summary

def append_sample_section(title: str, value: str):
    if not value:
        return
    lines.append("")
    heading = f"### {title}"
    payload = _minify_payload(value)
    if sample_limit <= 0:
        digest_src = payload.encode("utf-8", "replace")
        digest = hashlib.sha256(digest_src).hexdigest()[:12]
        preview = payload[:120]
        if payload and len(payload) > 120:
            preview = preview.rstrip() + "…"
        lines.append(f"{heading} (digest — pass --sample-lines N to view payload)")
        if preview:
            preview_clean = preview.replace("\n", " ").strip()
            lines.append(f"- preview: `{preview_clean}`")
        source_lines = len(value.splitlines()) or 1
        lines.append(f"- original lines: {source_lines}; minified chars: {len(payload)}")
        lines.append(f"- sha256: {digest}")
        return

    sample_chunks = _chunk_text(payload)
    truncated = 0
    if sample_limit and len(sample_chunks) > sample_limit:
        truncated = len(sample_chunks) - sample_limit
        sample_chunks = sample_chunks[:sample_limit]
        heading = f"{heading} (first {sample_limit} chunk{'s' if sample_limit != 1 else ''} of minified payload)"

    lines.append(heading)
    if sample_chunks:
        lines.extend(sample_chunks)
    else:
        lines.append("(payload empty after normalisation)")
    if truncated:
        lines.append(f"... ({truncated} additional chunk{'s' if truncated != 1 else ''} truncated)")
        lines.append("... (raise --sample-lines to include more of the payload)")

if sample_create_request:
    append_sample_section("Sample Create Request", sample_create_request)

if sample_create_response:
    append_sample_section("Sample Create Response", sample_create_response)

doc_catalog_entries = []
doc_catalog_path = os.getenv("GC_DOC_CATALOG_PATH", "").strip()
doc_catalog_data = {"version": 1, "documents": {}, "snippets": {}}
doc_catalog_changed = {"value": False}
if doc_catalog_path:
    catalog_path_obj = Path(doc_catalog_path)
    if catalog_path_obj.exists():
        try:
            loaded = json.loads(catalog_path_obj.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                docs_section = loaded.get("documents")
                if isinstance(docs_section, dict):
                    doc_catalog_data["documents"] = docs_section
                for key, value in loaded.items():
                    if key != "documents":
                        doc_catalog_data[key] = value
        except Exception:
            pass
documents_store = doc_catalog_data.setdefault("documents", {})
snippet_store = doc_catalog_data.setdefault("snippets", {})
documentation_db_path = os.getenv("GC_DOCUMENTATION_DB_PATH", "").strip()
doc_catalog_entries_from_db = False

if not binder_hit:
    if documentation_db_path:
        registry_rows = []
        try:
            registry_conn = sqlite3.connect(documentation_db_path)
            registry_conn.row_factory = sqlite3.Row
            registry_cur = registry_conn.cursor()
            registry_cur.execute(
                """
                SELECT
                  doc_id,
                  doc_type,
                  COALESCE(staging_path, source_path) AS resolved_path,
                  rel_path,
                  title,
                  size_bytes,
                  mtime_ns,
                  sha256,
                  tags_json,
                  metadata_json
                FROM documentation
                WHERE status = 'active'
                ORDER BY doc_type, COALESCE(rel_path, file_name, resolved_path)
                """
            )
            registry_rows = registry_cur.fetchall()
        except Exception:
            registry_rows = []
        finally:
            try:
                registry_conn.close()
            except Exception:
                pass
        for row in registry_rows:
            path_value = (row["resolved_path"] or "").strip()
            rel_path = (row["rel_path"] or path_value or "").strip()
            metadata_raw = row["metadata_json"]
            headings_payload = []
            if metadata_raw:
                try:
                    metadata_obj = json.loads(metadata_raw)
                    candidate_headings = metadata_obj.get("headings")
                    if isinstance(candidate_headings, list):
                        headings_payload = candidate_headings
                except Exception:
                    pass
            snippet_text = ""
            candidate_path = Path(path_value) if path_value else None
            doc_entry_payload = {
                "doc_id": row["doc_id"],
                "rel_path": rel_path,
                "headings": headings_payload,
                "mtime_ns": row["mtime_ns"] or 0,
                "size": row["size_bytes"] or 0,
            }
            if candidate_path and candidate_path.exists():
                snippet_text = _load_doc_snippet(candidate_path, doc_entry_payload)
                if not headings_payload:
                    fallback = _build_doc_entry(candidate_path)
                    if fallback:
                        headings_payload = fallback.get("headings", [])
                        doc_entry_payload["headings"] = headings_payload
                        snippet_text = _load_doc_snippet(candidate_path, doc_entry_payload)
            preview_headings = []
            for heading in headings_payload[:12]:
                if isinstance(heading, dict):
                    title = heading.get("title") or ""
                    line = heading.get("line")
                    if line:
                        preview_headings.append(f"{title} (line {line})")
                    else:
                        preview_headings.append(title)
                else:
                    preview_headings.append(str(heading))
            doc_catalog_entries.append(
                {
                    "doc_id": row["doc_id"],
                    "rel_path": rel_path,
                    "headings": preview_headings,
                    "snippet": snippet_text,
                }
            )
        if doc_catalog_entries:
            doc_catalog_entries_from_db = True

    if (not doc_catalog_entries_from_db) and doc_snippets_enabled and (staging_root or project_root_path):
        seen_paths = set()
        references = _split_items(document_reference)
        endpoints_list = _split_items(endpoints_text)
        candidates = []
        for reference in references:
            for candidate in _collect_candidate_files(reference):
                try:
                    candidate_resolved = candidate.resolve()
                except Exception:
                    candidate_resolved = candidate
                key = str(candidate_resolved)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                candidates.append(candidate_resolved)
        if staging_root and endpoints_list:
            openapi_candidates = list(staging_root.glob("openapi.*"))
            for candidate in openapi_candidates:
                try:
                    candidate_resolved = candidate.resolve()
                except Exception:
                    candidate_resolved = candidate
                key = str(candidate_resolved)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                candidates.append(candidate_resolved)
        for path_obj in candidates:
            if not path_obj.exists() or not path_obj.is_file():
                continue
            doc_entry = _build_doc_entry(path_obj)
            if not doc_entry:
                continue
            snippet_text = _load_doc_snippet(path_obj, doc_entry)
            preview_headings = []
            for heading in doc_entry.get("headings", [])[:12]:
                title = heading.get("title") or ""
                line_no = heading.get("line")
                if line_no:
                    preview_headings.append(f"{title} (line {line_no})")
                else:
                    preview_headings.append(title)
            doc_catalog_entries.append({
                "doc_id": doc_entry["doc_id"],
                "rel_path": doc_entry["rel_path"],
                "headings": preview_headings,
                "snippet": snippet_text,
            })

if doc_catalog_path and doc_catalog_changed["value"]:
    try:
        Path(doc_catalog_path).write_text(json.dumps(doc_catalog_data, indent=2), encoding="utf-8")
    except Exception:
        pass

search_terms = _collect_search_terms(
    task_title,
    document_reference,
    tags,
    acceptance,
    story_title,
)
doc_search_hits: List[Dict[str, object]] = []
search_summary_payload: List[Dict[str, object]] = []

if binder_hit and binder_doc_refs:
    emit_progress("Reusing binder documentation references")
    task_ref = task_identifier or f"{STORY_SLUG}:{TASK_INDEX + 1}"
    for ref in binder_doc_refs[:12]:
        entry = {
            "doc_id": ref.get("doc_id"),
            "method": ref.get("method") or "binder",
            "rel_path": ref.get("rel_path"),
            "snippet": ref.get("snippet"),
            "reason": ref.get("reason"),
        }
        search_summary_payload.append(entry)
    if task_ref and search_summary_payload:
        search_map = doc_catalog_data.setdefault("search_hits", {})
        search_map[task_ref] = search_summary_payload
        doc_catalog_changed["value"] = True
else:
    if search_terms:
        emit_progress("Running documentation search")
        seen_doc_ids: Set[str] = {
            entry.get("doc_id", "").strip()
            for entry in doc_catalog_entries
            if entry.get("doc_id")
        }
        seen_doc_ids.discard("")
        db_path_obj: Optional[Path] = None
        if documentation_db_path:
            try:
                candidate_path = Path(documentation_db_path)
                if candidate_path.exists():
                    db_path_obj = candidate_path.resolve()
                else:
                    db_path_obj = None
            except Exception:
                db_path_obj = Path(documentation_db_path)
        doc_search_hits.extend(_run_fts_search(db_path_obj, search_terms, 12))
        for hit in list(doc_search_hits):
            doc_id = (hit.get("doc_id") or "").strip()
            if not doc_id:
                doc_search_hits.remove(hit)
                continue
            seen_doc_ids.add(doc_id)
        remaining_hits = 12 - len(doc_search_hits)
        if remaining_hits > 0:
            doc_search_hits.extend(_run_vector_search(vector_index_path, search_terms, remaining_hits, seen_doc_ids))
        remaining_hits = 12 - len(doc_search_hits)
        if remaining_hits > 0:
            doc_search_hits.extend(_run_ripgrep_search(project_root_path, search_terms, remaining_hits, seen_doc_ids))

    if doc_search_hits:
        lines.append("")
        lines.append("## Documentation Search Hits")
        emit_progress(f"Found {len(doc_search_hits)} documentation search hit(s)")
        for hit in doc_search_hits[:12]:
            doc_id = (hit.get("doc_id") or "").strip()
            if not doc_id:
                continue
            entry = documents_store.get(doc_id, {})
            rel_path = entry.get("rel_path") or entry.get("path") or doc_id
            method = hit.get("method", "fts")
            snippet_text = _normalise_space(hit.get("snippet") or "")
            lines.append(f"- {doc_id} [{method}] — {rel_path}")
            if snippet_text:
                lines.append(f"  Snippet: {snippet_text[:280]}")
            search_summary_payload.append(
                {
                    "doc_id": doc_id,
                    "method": method,
                    "rel_path": rel_path,
                    "snippet": snippet_text[:500],
                }
            )
        task_ref = task_identifier or f"{STORY_SLUG}:{TASK_INDEX + 1}"
        if task_ref:
            search_map = doc_catalog_data.setdefault("search_hits", {})
            search_map[task_ref] = search_summary_payload
            doc_catalog_changed["value"] = True

if doc_catalog_entries:
    lines.append("")
    lines.append("## Documentation Catalog")
    lines.append("Use the catalog below to pick a section, then run `gpt-creator show-file <path> --range START:END` for a narrow excerpt. Avoid cat/sed on these manuals.")
    emit_progress(f"Including {len(doc_catalog_entries[:6])} documentation catalog entries")
    for entry in doc_catalog_entries[:6]:
        rel_path = entry['rel_path']
        lines.append(f"- {entry['doc_id']} — {rel_path}")
        headings_preview = entry.get("headings") or []
        if headings_preview:
            lines.append("  Sections:")
            for heading in headings_preview[:6]:
                lines.append(f"    • {heading}")
        else:
            lines.append(f"  (No headings detected; use `gpt-creator show-file {rel_path} --range START:END` to inspect a specific slice.)")
        snippet_text = (entry.get("snippet") or "").strip()
        if snippet_text:
            snippet_clean = _normalise_space(snippet_text)[:280].rstrip()
            lines.append(f"  Snippet: {snippet_clean}")
        lines.append("")

guard_entries = []

command_failure_cache = os.getenv("GC_COMMAND_FAILURE_CACHE", "").strip()
failure_entries = []
if command_failure_cache:
    cache_path = Path(command_failure_cache)
    if cache_path.exists():
        try:
            cache_raw = cache_path.read_text(encoding='utf-8')
            cache_data = json.loads(cache_raw) if cache_raw.strip() else {}
        except Exception:
            cache_data = {}
        if isinstance(cache_data, dict):
            for value in cache_data.values():
                try:
                    failure_count = int(value.get("count") or 0)
                except Exception:
                    failure_count = 0
                if failure_count < 2:
                    continue
                command_text = str(value.get("command") or "").strip()
                if not command_text:
                    continue
                summary_text = (value.get("last_summary") or value.get("summary") or "").strip()
                summary_text = re.sub(r'\s+', ' ', summary_text)
                exit_code_val = value.get("exit")
                last_seen_val = value.get("last_seen") or ""
                failure_entries.append((last_seen_val, failure_count, exit_code_val, command_text, summary_text))
            failure_entries.sort(key=lambda item: item[0], reverse=True)

if failure_entries:
    lines.append("")
    lines.append("## Known Command Failures")
    lines.append("The following commands have already failed; do not rerun them until the underlying issue is addressed. Summarise the cached failure instead of executing the command again.")
    max_failures = 4
    for _, failure_count, exit_code_val, command_text, summary_text in failure_entries[:max_failures]:
        exit_label = f"exit {exit_code_val}" if exit_code_val not in (None, "", 0) else "failed"
        plural = "s" if failure_count != 1 else ""
        if summary_text and len(summary_text) > 200:
            summary_text = summary_text[:197] + "..."
        suffix = f" — {summary_text}" if summary_text else ""
        lines.append(f"- `{command_text}` ({exit_label}, {failure_count} attempt{plural}){suffix}")
        remediation_note = failure_remediation_notes.get(command_text.strip())
        if not remediation_note:
            remediation_note = remediation_message(command_text, failure_count, exit_code_val)
        if remediation_note:
            lines.append(f"  -> {remediation_note}")

stream_cache = os.getenv("GC_COMMAND_STREAM_CACHE", "").strip()
stream_entries = []
if stream_cache:
    stream_path = Path(stream_cache)
    if stream_path.exists():
        try:
            stream_raw = stream_path.read_text(encoding="utf-8")
            stream_data = json.loads(stream_raw) if stream_raw.strip() else {}
        except Exception:
            stream_data = {}
        if isinstance(stream_data, dict):
            sorted_entries = sorted(
                stream_data.values(),
                key=lambda item: item.get("last_seen", ""),
                reverse=True,
            )
            for entry in sorted_entries[:4]:
                summary_text = (entry.get("summary") or "").strip()
                advice_text = (entry.get("advice") or "").strip()
                try:
                    occurrences = int(entry.get("count") or 0)
                except Exception:
                    occurrences = 0
                if summary_text:
                    summary_text = re.sub(r"\s+", " ", summary_text)
                    advice_text = re.sub(r"\s+", " ", advice_text)
                    stream_entries.append((summary_text, advice_text, occurrences))

scan_cache = os.getenv("GC_COMMAND_SCAN_CACHE", "").strip()
scan_entries = []
if scan_cache:
    scan_path = Path(scan_cache)
    if scan_path.exists():
        try:
            scan_raw = scan_path.read_text(encoding="utf-8")
            scan_data = json.loads(scan_raw) if scan_raw.strip() else {}
        except Exception:
            scan_data = {}
        if isinstance(scan_data, dict):
            sorted_scans = sorted(
                scan_data.values(),
                key=lambda item: item.get("last_seen", ""),
                reverse=True,
            )
            for entry in sorted_scans[:4]:
                command_text = (entry.get("command") or "").strip()
                preview_lines = entry.get("lines") or []
                if not command_text or not preview_lines:
                    continue
                cwd_display = (entry.get("cwd_display") or entry.get("cwd") or "").strip()
                message_text = (entry.get("message") or "").strip()
                try:
                    occurrences = int(entry.get("count") or 0)
                except Exception:
                    occurrences = 0
                try:
                    line_count_val = int(entry.get("line_count") or len(preview_lines))
                except Exception:
                    line_count_val = len(preview_lines)
                truncated_flag = bool(entry.get("truncated"))
                cleaned_lines = []
                for raw_line in preview_lines[:6]:
                    cleaned = (raw_line or "").strip()
                    if cleaned:
                        cleaned_lines.append(cleaned)
                if not cleaned_lines and line_count_val > 0:
                    cleaned_lines.append("(no cached output)")
                scan_entries.append({
                    "command": command_text,
                    "cwd": cwd_display,
                    "message": message_text,
                    "occurrences": occurrences,
                    "lines": cleaned_lines,
                    "line_count": line_count_val,
                    "truncated": truncated_flag or (line_count_val > len(cleaned_lines)),
                })

if stream_entries:
    lines.append("")
    lines.append("## Command Efficiency Alerts")
    lines.append("Recent runs paged files with sequential sed/cat chunks. Pivot to targeted searches or cached viewers instead of streaming large slices.")
    for summary_text, advice_text, occurrences in stream_entries:
        entry_line = summary_text
        if occurrences > 1:
            entry_line += f" (seen {occurrences}x)"
        if advice_text:
            entry_line += f" — {advice_text}"
        lines.append(f"- {entry_line}")

if scan_entries:
    lines.append("")
    lines.append("## Workspace Directory Snapshots")
    lines.append("Reuse these cached listings instead of rerunning ls/find on the same paths; refresh only if the tree changes.")
    for entry in scan_entries:
        summary_line = f"- `{entry['command']}`"
        details = []
        cwd_display = entry.get("cwd") or ""
        if cwd_display:
            details.append(f"cwd {cwd_display}")
        occurrences = entry.get("occurrences") or 0
        if isinstance(occurrences, int) and occurrences > 1:
            details.append(f"seen {occurrences}x")
        message_text = entry.get("message") or ""
        if message_text:
            details.append(message_text)
        if details:
            summary_line += " — " + "; ".join(details)
        lines.append(summary_line)
        preview_lines = entry.get("lines") or []
        if preview_lines:
            preview_text = ", ".join(preview_lines)
            if len(preview_text) > 200:
                preview_text = preview_text[:197] + "..."
            lines.append(f"    {preview_text}")
        else:
            lines.append("    (no cached output)")
        line_count_val = entry.get("line_count")
        extra_count = 0
        if isinstance(line_count_val, int):
            extra_count = max(0, line_count_val - len(preview_lines))
        if extra_count > 0:
            lines.append(f"    ... (+{extra_count} more)")
        elif entry.get("truncated"):
            lines.append("    ... (truncated)")

file_cache = os.getenv("GC_COMMAND_FILE_CACHE", "").strip()
build_entries = []
file_entries = []
if file_cache:
    file_cache_path = Path(file_cache)
    if file_cache_path.exists():
        try:
            file_raw = file_cache_path.read_text(encoding="utf-8")
            file_data = json.loads(file_raw) if file_raw.strip() else {}
        except Exception:
            file_data = {}
        if isinstance(file_data, dict):
            sorted_files = sorted(
                file_data.values(),
                key=lambda item: item.get("last_seen", ""),
                reverse=True,
            )
            max_file_entries = 6
            max_build_entries = 4
            for entry in sorted_files:
                if len(file_entries) >= max_file_entries and len(build_entries) >= max_build_entries:
                    break
                summary_text = (entry.get("summary") or "").strip()
                excerpt_text = (entry.get("excerpt") or "").strip()
                try:
                    occurrences = int(entry.get("count") or 0)
                except Exception:
                    occurrences = 0
                rel_path = (entry.get("rel_path") or entry.get("path") or "").strip()
                range_value = entry.get("range")
                mode_value = entry.get("mode")
                category = entry.get("category") or ""
                if summary_text:
                    summary_text = re.sub(r"\s+", " ", summary_text)
                    excerpt_text = re.sub(r"\s+", " ", excerpt_text)
                    payload = {
                        "summary": summary_text,
                        "excerpt": excerpt_text,
                        "occurrences": occurrences,
                        "rel_path": rel_path,
                        "range": range_value,
                        "mode": mode_value,
                    }
                    if category == "build-artifact":
                        if len(build_entries) < max_build_entries:
                            build_entries.append(payload)
                        continue
                    file_entries.append(payload)

if build_entries:
    lines.append("")
    lines.append("## Build Artifacts (opt-in)")
    lines.append("Compiled outputs in dist/build/coverage directories are suppressed; inspect sources first and only open these artifacts when absolutely necessary.")
    for entry in build_entries:
        summary_text = entry.get("summary") or ""
        rel_path = entry.get("rel_path") or ""
        occurrences = entry.get("occurrences") or 0
        info_line = summary_text
        if rel_path:
            info_line += f" [{rel_path}]"
        if isinstance(occurrences, int) and occurrences > 1:
            info_line += f" (seen {occurrences}x)"
        lines.append(f"- {info_line}")
        if rel_path:
            lines.append(f"  -> If the compiled output is required, run `gpt-creator show-file \"{rel_path}\" --head 120`; otherwise focus on the source file.")

if file_entries:
    lines.append("")
    lines.append("## Cached File Excerpts")
    lines.append("Reuse the snippets below instead of repeating cat/sed on the same file; refresh only if the file changed. Prefer `gpt-creator show-file <path> --range start:end` or `rg -n '<term>' <path> -C20` to jump to new context.")
    for entry in file_entries:
        summary_text = entry.get("summary") or ""
        excerpt_text = entry.get("excerpt") or ""
        occurrences = entry.get("occurrences") or 0
        entry_line = summary_text
        if isinstance(occurrences, int) and occurrences > 1:
            entry_line += f" (seen {occurrences}x)"
        lines.append(f"- {entry_line}")
        if excerpt_text:
            preview = excerpt_text.strip()
            if len(preview) > 160:
                preview = preview[:157] + "..."
            lines.append(f"  -> {preview}")
        rel_path = entry.get("rel_path") or ""
        range_value = entry.get("range")
        command_hint = ""
        if rel_path:
            if isinstance(range_value, (list, tuple)) and len(range_value) == 2:
                try:
                    start_line = int(range_value[0])
                    end_line = int(range_value[1])
                except Exception:
                    start_line = end_line = None
                if start_line is not None and end_line is not None:
                    command_hint = f"gpt-creator show-file {rel_path} --range {start_line}:{end_line}"
            if not command_hint:
                command_hint = f"gpt-creator show-file {rel_path} --head 120"
        if command_hint:
            lines.append(f"  -> Reopen via `{command_hint}`")
        if rel_path:
            lines.append(f"  -> Use `rg -n \"<term>\" {rel_path} -C20` to search within this file without re-reading it in full.")

if guard_entries:
    lines.append("")
    lines.append("## Command Guard Alerts")
    lines.append("Resolve these issues before rerunning commands that have already failed; focus on remediation instead of immediate retries.")
    for entry in guard_entries[:4]:
        command_label = (entry.get("command") or "pnpm").strip() or "pnpm"
        issues = entry.get("issues") or []
        summary = "; ".join(issues) if issues else "Pre-check violation detected."
        lines.append(f"- {command_label} — {summary}")

lines.append("")
lines.append("## Instructions")
if compact_mode:
    lines.append("### Output Contract — STRICT")
    lines.append('Return **only** this minified JSON with **all keys present** (use [] when empty):')
    lines.append('{"plan":[],"focus":[],"changes":[],"commands":[],"notes":[]}')
    lines.append('Rules: no prose before/after, no code fences, no comments, no trailing commas.')
    lines.append('`focus` **must never be omitted** even if no edits yet (then return an empty array).')
    lines.append("")
    lines.append('Return a JSON object: {"plan":[], "focus":[], "changes":[], "commands":[], "notes":[]}.')
    lines.append("- Populate `plan` with the concrete steps you will take for this task.")
    lines.append("- List the files or symbols you edit in `focus`; you may include diffs in the same reply.")
    lines.append("- Provide actual code edits through `changes` using unified diffs only (no full file bodies).")
    lines.append("- Record shell commands you executed or recommend in `commands`.")
    lines.append("- Use `notes` for blockers, follow-up actions, or verification reminders.")
    lines.append("- Keep internal narration tight (≤3 short sentences) and focused on the current task.")
    lines.append("- Prefer pnpm for scripts; mention commands that cannot run because of network limits.")
    lines.append("- Avoid repo-wide listings/searches; jump straight to relevant files and use `gpt-creator show-file <path> --range start:end` (or --head/--tail) for slices instead of streaming whole files.")
    lines.append("- Track file views; if you begin paging with sequential sed/cat ranges, pivot to targeted `gpt-creator show-file <path> --range` or `rg -n <pattern> <path> -C20`.")
    lines.append("- When a cached excerpt below covers the context you need, cite it instead of re-running cat/sed; refresh only if the file changed.")
    lines.append("- Before running `pnpm test` or `pnpm build`, confirm dependencies are installed and prior pnpm commands succeeded; fix failures before retrying.")
    lines.append("- Review `Known Command Failures` and `Command Guard Alerts` before retrying a command; capture the remediation steps instead of rerunning immediately.")
    lines.append("")
    lines.append("## Change Format")
    lines.append("- Emit unified diffs inside the `changes` array (no full file bodies).")
    lines.append("- Large diffs will be stored under `.gpt-creator/artifacts/patches/`; report the artifact path with hunk and line counts in `notes`.")
    lines.append("- Omit keys with no content; no markdown fences or extra prose.")

    lines.append("")
    lines.append("## Guardrails")
    lines.append("- Stay within this task's scope; avoid spinning up unrelated plans or subprojects.")
    lines.append("- Consult only the referenced docs or clearly relevant files; skip broad repo sweeps.")
    lines.append("- Keep command usage lean and focused on assets needed for the acceptance criteria.")
    lines.append("- Do not run directory-wide listings/searches outside the declared `focus`; revise the plan + focus first.")
    lines.append("- Wrap up once deliverables are met; record blockers or follow-ups succinctly in `notes`.")

    lines.append("")
    lines.append("## Change Format")
    lines.append("- Emit unified diffs inside the `changes` array (no full file bodies).")
    lines.append("- Large diffs will be stored under `.gpt-creator/artifacts/patches/`; report the artifact path with hunk and line counts in `notes`.")
    lines.append("- Omit keys with no content; no markdown fences or extra prose.")
else:
    lines.append("### Output Contract — STRICT")
    lines.append('Return **only** this minified JSON with **all keys present** (use [] when empty):')
    lines.append('{"plan":[],"focus":[],"changes":[],"commands":[],"notes":[]}')
    lines.append('Rules: no prose before/after, no code fences, no comments, no trailing commas.')
    lines.append('`focus` **must never be omitted** even if no edits yet (then return an empty array).')
    lines.append("")
    lines.append('Return a JSON object: {"plan":[], "focus":[], "changes":[], "commands":[], "notes":[]}.')
    lines.append("- Populate `plan` with concise steps that lead to the fix or feature.")
    lines.append("- List touched files or symbols in `focus`; include diffs in the same response.")
    lines.append("- Supply code updates through `changes` using unified diffs only; do not omit required edits.")
    lines.append("- Record executed or recommended shell commands in `commands`.")
    lines.append("- Use `notes` for blockers, verification needs, or follow-up actions.")
    lines.append("- Prefer pnpm for install/build scripts; avoid npm/yarn unless explicitly required.")
    lines.append("- Keep internal narration tight (≤3 short sentences) and focused on the current task.")
    lines.append("- Avoid repo-wide listings/searches; jump straight to relevant files and use `gpt-creator show-file <path> --range start:end` (or --head/--tail) for context slices instead of streaming whole files.")
    lines.append("- Track file reads; if you begin paging with sequential sed/cat ranges, switch to targeted `gpt-creator show-file <path> --range` or `rg -n <pattern> <path> -C20`.")
    lines.append("- Reuse cached excerpts below rather than repeating cat/sed; only re-read files when you know the content changed.")
    lines.append("- Before running `pnpm test` or `pnpm build`, verify dependencies (`pnpm install`) and resolve any previous pnpm failures first.")
    lines.append("- Review `Known Command Failures` and `Command Guard Alerts`; plan remediation before retrying any listed command.")
    lines.append("- Assume limited network access; note any commands that cannot run for that reason instead of failing silently.")

    lines.append("")
    lines.append("## Guardrails")
    lines.append("- Stay strictly within this task's scope; do not re-plan or chase unrelated issues.")
    lines.append("- Read only the documents or files necessary to satisfy the acceptance criteria.")
    lines.append("- Avoid long exploratory command sequences; focus on edits and checks that prove the task.")
    lines.append("- Skip directory sweeps outside your declared `focus` unless you first update the plan and focus targets.")
    lines.append("- Stop when outputs are ready; surface blockers or context gaps inside the JSON `notes`.")

    lines.append("")
    lines.append("## Output JSON schema")
    lines.append("Return a single JSON object with keys exactly as follows (omit null/empty collections when not needed):")
    lines.append("{")
    lines.append("  \"plan\": [\"short step-by-step plan items...\"],")
    lines.append("  \"focus\": [\"src/foo.ts:loadWidget\", \"pkg/utils.ts\"],")
    lines.append("  \"changes\": [")
    lines.append("    { \"type\": \"patch\", \"path\": \"relative/file/path\", \"diff\": \"UNIFIED_DIFF\" }")
    lines.append("  ],")
    lines.append("  \"commands\": [\"optional shell commands to run (e.g., pnpm install)\"],")
    lines.append("  \"notes\": [\"follow-up items or blockers\"]")
    lines.append("}")
    lines.append("- Use UTF-8, escape newlines as \\n inside JSON strings.")
    lines.append("- Diff entries must be valid unified diffs (git apply compatible) against the current workspace.")
    lines.append("- Do not emit markdown fences, commentary, or additional text outside the JSON object.")
    lines.append("- Any text before or after the JSON object will be treated as an error and retried automatically.")

if instruction_prompts:
    lines.append("")
    lines.append("## Supplemental Instruction Prompts")
    for rel_path, prompt_lines in instruction_prompts:
        lines.append(f"### {rel_path}")
        lines.extend(prompt_lines)
        if not prompt_lines or prompt_lines[-1].strip():
            lines.append("")
    if lines and lines[-1] == "":
        lines.pop()

if CONTEXT_TAIL_PATH:
    context_path = Path(CONTEXT_TAIL_PATH)
    if context_path.exists():
        tail_text = context_path.read_text(encoding='utf-8').splitlines()
        tail_mode = os.getenv("GC_CONTEXT_TAIL_MODE", "digest").strip().lower()
        tail_limit = os.getenv("GC_CONTEXT_TAIL_LIMIT", "").strip()
        if tail_mode == "digest":
            heading = "## Shared Context Digest"
        elif tail_mode == "raw":
            heading = "## Shared Context Tail"
            if tail_limit and tail_limit.isdigit():
                heading += f" (last {int(tail_limit)} line{'s' if int(tail_limit) != 1 else ''})"
        else:
            heading = "## Shared Context"
        lines.append("")
        lines.append(heading)
        lines.append("")
        lines.extend(tail_text)

segments = _build_segments_from_lines(lines)
_initialise_segment_metrics(segments)

initial_tokens_raw = sum(segment["full_tokens"] for segment in segments)
initial_token_estimate = math.ceil(initial_tokens_raw * ESTIMATE_MARGIN)

model_context = _resolve_model_context(MODEL_NAME)

reserved_output = DEFAULT_MIN_OUTPUT_TOKENS
reserved_source = "default"
config_reserved = runner_config.get("perTask", {}).get("minOutputTokens")
if config_reserved is not None:
    reserved_output = _parse_int(config_reserved, fallback=reserved_output)
    reserved_source = "config"
env_reserved = os.getenv("GC_PER_TASK_MIN_OUTPUT_OVERRIDE", "").strip()
if env_reserved:
    reserved_output = _parse_int(env_reserved, fallback=reserved_output)
    reserved_source = "env-override"
if reserved_output < 0:
    reserved_output = 0
if reserved_output >= model_context:
    reserved_output = max(1, model_context - 1)

derived_hard_limit = max(1, model_context - reserved_output)
hard_limit = derived_hard_limit
hard_limit_source = "model-derived"
config_hard = runner_config.get("perTask", {}).get("hardLimit")
if config_hard is not None:
    candidate = _parse_int(config_hard, fallback=hard_limit)
    if candidate > 0:
        hard_limit = candidate
        hard_limit_source = "config"
env_hard = os.getenv("GC_PER_TASK_HARD_LIMIT_OVERRIDE", "").strip()
if env_hard:
    candidate = _parse_int(env_hard, fallback=hard_limit)
    if candidate > 0:
        hard_limit = candidate
        hard_limit_source = "env-override"
if hard_limit <= 0:
    hard_limit = derived_hard_limit
    hard_limit_source = "model-derived"
hard_limit = min(max(1, hard_limit), model_context)

soft_limit_ratio = DEFAULT_SOFT_LIMIT_RATIO
soft_ratio_source = "default"
config_soft = runner_config.get("perTask", {}).get("softLimitRatio")
if config_soft is not None:
    soft_limit_ratio = _parse_float(config_soft, fallback=soft_limit_ratio)
    soft_ratio_source = "config"
env_soft = os.getenv("GC_PER_TASK_SOFT_RATIO_OVERRIDE", "").strip()
if env_soft:
    soft_limit_ratio = _parse_float(env_soft, fallback=soft_limit_ratio)
    soft_ratio_source = "env-override"
if soft_limit_ratio < 0:
    soft_limit_ratio = 0.0
if soft_limit_ratio > 1:
    soft_limit_ratio = 1.0

soft_limit = int(math.floor(soft_limit_ratio * hard_limit))
if hard_limit > 0 and (soft_limit <= 0 or soft_limit > hard_limit):
    soft_limit = hard_limit

stop_on_overbudget = _parse_bool(runner_config.get("runner", {}).get("stopOnOverbudget"), default=True)
stop_source = "config" if "runner" in runner_config else "default"
env_stop = os.getenv("GC_STOP_ON_OVERBUDGET_OVERRIDE", "").strip()
if env_stop:
    stop_on_overbudget = _parse_bool(env_stop, default=stop_on_overbudget)
    stop_source = "env-override"

soft_limit_initial_trigger = soft_limit > 0 and initial_token_estimate > soft_limit
hard_limit_initial_trigger = hard_limit > 0 and initial_token_estimate > hard_limit

pruned_items: Dict[str, int] = {}
pruned_bytes = 0
if soft_limit > 0 or hard_limit > 0:
    target_soft = soft_limit if soft_limit > 0 else hard_limit
    _, pruned_items, pruned_bytes = _apply_pruning(
        segments,
        target_soft,
        hard_limit,
        margin=ESTIMATE_MARGIN,
    )

final_tokens_raw = _recalculate_total_tokens(segments)
final_token_estimate = math.ceil(final_tokens_raw * ESTIMATE_MARGIN)

status = "ok"
hard_limit_final_trigger = hard_limit > 0 and final_token_estimate > hard_limit
if hard_limit_final_trigger:
    status = "blocked-quota"

segments_retained = sum(1 for segment in segments if not segment["dropped"])
segments_dropped = sum(1 for segment in segments if segment["dropped"])
segments_fallback = sum(1 for segment in segments if segment["fallback_used"])

final_segment_texts: List[str] = []
for segment in segments:
    if segment["dropped"]:
        continue
    text = segment.get("current_text") or ""
    text = text.strip()
    if text:
        final_segment_texts.append(text)

if final_segment_texts:
    final_prompt_text = "\n\n".join(final_segment_texts).rstrip() + "\n"
else:
    final_prompt_text = "\n".join(lines).rstrip() + "\n"

prompt_path = Path(PROMPT_PATH)
prompt_path.parent.mkdir(parents=True, exist_ok=True)
prompt_path.write_text(final_prompt_text, encoding='utf-8')
emit_progress(f"Wrote prompt → {prompt_path}")

binder_written_path = ""
if binder_enabled:
    acceptance_for_binder = [item for item in acceptance if item] if acceptance else []
    if not acceptance_for_binder and acceptance_text_extra:
        acceptance_for_binder = [line.strip() for line in acceptance_text_extra.splitlines() if line.strip()]
    invariants_for_binder = acceptance_for_binder or binder_data.get("invariants") or []
    doc_refs_for_binder: List[Dict[str, Any]] = []
    for ref in search_summary_payload[:8]:
        doc_refs_for_binder.append(
            {
                "doc_id": ref.get("doc_id"),
                "rel_path": ref.get("rel_path"),
                "snippet": ref.get("snippet"),
                "method": ref.get("method"),
                "reason": ref.get("reason"),
            }
        )
    if not doc_refs_for_binder and binder_doc_refs:
        doc_refs_for_binder = binder_doc_refs[:8]
    binder_files_section = dict(binder_data.get("files") or {"primary": [], "related": [], "deps": []})
    binder_files_section.setdefault("primary", [])
    binder_files_section.setdefault("related", [])
    binder_files_section.setdefault("deps", [])
    binder_evidence_section = dict(binder_data.get("evidence") or {})
    binder_tokens_section = dict(binder_data.get("last_tokens") or {})
    binder_tokens_section["prompt"] = final_token_estimate
    binder_task_key = task_identifier or (task_id or f"{STORY_SLUG}:{TASK_INDEX + 1}")
    problem_summary = _summarise_problem(task_title, description_lines)
    binder_path_obj, binder_payload = prepare_binder_payload(
        project_root=project_root_path,
        epic_slug=epic_slug_source,
        story_slug=STORY_SLUG,
        task_id=binder_task_key,
        task_title=task_title,
        problem=problem_summary,
        invariants=invariants_for_binder,
        acceptance=acceptance_for_binder,
        doc_refs=doc_refs_for_binder,
        git_head=current_git_head,
        files_section=binder_files_section,
        evidence=binder_evidence_section,
        last_tokens=binder_tokens_section,
        previous=binder_data if binder_hit else None,
        binder_status=binder_status,
    )
    binder_write(binder_path_obj, binder_payload, max_bytes=binder_max_bytes)
    binder_written_path = str(binder_path_obj)
    emit_progress(f"Binder updated → {binder_written_path}")
elif binder_path:
    binder_written_path = str(binder_path)

segments_meta: List[Dict[str, Any]] = []
for segment in segments:
    preview = (segment.get("current_text") or "").strip()
    preview = re.sub(r"\s+", " ", preview)[:160]
    segments_meta.append(
        {
            "id": segment.get("id"),
            "type": segment.get("type"),
            "score": segment.get("score"),
            "must_keep": segment.get("must_keep"),
            "tokens_full": segment.get("full_tokens"),
            "tokens_final": segment.get("current_tokens"),
            "fallback_used": segment.get("fallback_used"),
            "dropped": segment.get("dropped"),
            "path": segment.get("path"),
            "doc_id": segment.get("doc_id"),
            "order": segment.get("order"),
            "preview": preview,
        }
    )

meta: Dict[str, Any] = {
    "status": status,
    "model": MODEL_NAME,
    "model_context": model_context,
    "token_estimate_initial": initial_token_estimate,
    "token_estimate_initial_raw": initial_tokens_raw,
    "token_estimate_final": final_token_estimate,
    "token_estimate_final_raw": final_tokens_raw,
    "token_estimate_margin": ESTIMATE_MARGIN,
    "token_budget_soft": soft_limit,
    "token_budget_soft_ratio": soft_limit_ratio,
    "token_budget_soft_source": soft_ratio_source,
    "token_budget_hard": hard_limit,
    "token_budget_hard_source": hard_limit_source,
    "reserved_output": reserved_output,
    "reserved_output_source": reserved_source,
    "stop_on_overbudget": stop_on_overbudget,
    "stop_on_overbudget_source": stop_source,
    "binder": {
        "enabled": binder_enabled,
        "status": binder_status,
        "reason": binder_reason,
        "path": binder_written_path,
        "ttl_seconds": binder_ttl,
        "max_bytes": binder_max_bytes,
        "clear_on_migration": binder_clear_on_migration,
    },
    "pruned": {
        "applied": bool(pruned_items),
        "items": pruned_items,
        "bytes": pruned_bytes,
    },
    "segments": segments_meta,
    "segments_total": len(segments),
    "segments_retained": segments_retained,
    "segments_dropped": segments_dropped,
    "segments_fallback": segments_fallback,
    "soft_limit_triggered_initial": soft_limit_initial_trigger,
    "hard_limit_triggered_initial": hard_limit_initial_trigger,
    "hard_limit_triggered_final": hard_limit_final_trigger,
}

if truncated_sections:
    meta["truncated_sections"] = truncated_sections

meta_path = Path(str(prompt_path) + ".meta.json")
meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

story_points_meta = story_points or ""
status_output = task_status or ""
status_reason_output = status_reason or ""
locked_output = "1" if locked_by_migration else "0"
print(f"{task_id}\t{task_title}\t{story_points_meta}\t{status_output}\t{locked_output}\t{status_reason_output}")
