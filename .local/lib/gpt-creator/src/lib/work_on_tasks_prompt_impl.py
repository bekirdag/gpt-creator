from __future__ import annotations

from typing import List


def run_prompt(args: List[str]) -> None:
    if len(args) != 8:
        print("prompt requires 8 arguments", file=sys.stderr)
        sys.exit(1)
    sys.argv = [sys.argv[0]] + args
    import fnmatch
    import hashlib
    import json
    import math
    import os
    import pathlib
    import re
    import sqlite3
    import shutil
    import subprocess
    import tempfile
    import time
    from pathlib import Path
    from typing import Optional, List, Tuple, Set, Dict, Sequence

    from compose_sections import dedupe_and_coalesce, emit_preamble_once, format_sections

    try:
        from prompt_registry import (
            DEFAULT_REGISTRY_SUBDIR,
            ensure_prompt_registry,
            parse_source_env,
        )
    except ModuleNotFoundError:
        DEFAULT_REGISTRY_SUBDIR = Path("src") / "prompts" / "_registry"

        def ensure_prompt_registry(
            project_root: Path,
            *,
            registry_dir: Optional[Path] = None,
            source_dirs=None,
            clean: bool = False,
        ) -> Path:
            return (registry_dir or (project_root / DEFAULT_REGISTRY_SUBDIR)).resolve()

        def parse_source_env(project_root: Path, env_value: str | None):
            return []

    try:
        from wot_publish_prompt import publish_prompt
    except ModuleNotFoundError:
        def publish_prompt(*_args, **_kwargs):
            return None
    try:
        from prompt_safeguard import slim_prompt_markdown  # type: ignore
    except Exception:
        def slim_prompt_markdown(text: str) -> str:
            return text

    FREEFORM_SECTION_MAX_CHARS = int(os.getenv("GC_PROMPT_FREEFORM_MAX_CHARS", "12000") or "12000")
    PROMPT_SOURCE_MAX_BYTES = int(os.getenv("GC_PROMPT_SOURCE_MAX_BYTES", "262144") or "262144")
    INSTRUCTION_PROMPT_RUN_MARKER = "/.gpt-creator/staging/plan/work/"
    INSTRUCTION_PROMPT_CREATE_SDS_MARKER = "/.gpt-creator/staging/plan/create-sds/"
    INSTRUCTION_PROMPT_CREATE_JIRA_TASKS_MARKER = "/.gpt-creator/staging/plan/create-jira-tasks/"
    INSTRUCTION_PROMPT_BINDER_MARKER = "/.gpt-creator/cache/task-binder/"
    PROMPT_SNAPSHOT_MARKER = "/docs/automation/prompts/"
    HEAVY_SECTION_PATTERNS = [
        re.compile(r"^jira tasks$", re.IGNORECASE),
        re.compile(r"^0[\W_]*document control", re.IGNORECASE),
        re.compile(r"^product scope\s*&\s*functional requirements", re.IGNORECASE),
        re.compile(r"^data[, ]+integrations? [&and]+ interfaces", re.IGNORECASE),
        re.compile(r"acceptance\s*\(mem-a\)", re.IGNORECASE),
    ]
    WORK_PROMPT_ALLOWED_PREFIXES = ("work_on_tasks", "work-on-tasks")

    def _atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_file = tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            newline="\n",
            dir=str(target.parent),
            delete=False,
        )
        temp_name = temp_file.name
        try:
            with temp_file:
                temp_file.write(data)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass


    def _read_existing_input_digest(meta_path: Path) -> str:
        if not meta_path.exists():
            return ""
        try:
            with meta_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return ""
        if not isinstance(payload, dict):
            return ""
        digest = payload.get("input_digest")
        return digest if isinstance(digest, str) else ""


    def _compute_input_digest(*parts) -> str:
        hasher = hashlib.sha256()
        for part in parts:
            if part is None:
                continue
            if isinstance(part, bytes):
                chunk = part
            else:
                chunk = str(part).encode("utf-8", "replace")
            hasher.update(chunk)
            hasher.update(b"\0")
        return hasher.hexdigest()[:16]


    def _meta_same_as(meta_path: Path, sha_value: str) -> bool:
        if not meta_path.exists():
            return False
        try:
            with meta_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        existing = payload.get("sha256")
        return isinstance(existing, str) and existing == sha_value


    def _normalize_heading_runtime(value: Optional[str]) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value.strip()).lower()


    def _lines_to_sections(lines: List[str]) -> List[Tuple[str, str]]:
        sections: List[Tuple[str, str]] = []
        current_title: Optional[str] = None
        current_body: List[str] = []
        for raw_line in lines:
            if raw_line.startswith("## "):
                if current_title is None and current_body:
                    sections.append(("", "\n".join(current_body)))
                    current_body = []
                elif current_title is not None:
                    sections.append((current_title, "\n".join(current_body)))
                    current_body = []
                current_title = raw_line[3:].strip()
                continue
            current_body.append(raw_line)
        if current_title is not None:
            sections.append((current_title, "\n".join(current_body)))
        elif current_body:
            sections.append(("", "\n".join(current_body)))
        processed: List[Tuple[str, str]] = []
        for title, body in sections:
            heading = title or ""
            body_text = (body or "").strip()
            normalized_heading = _normalize_heading_runtime(heading)
            heavy_section = False
            if heading:
                for pattern in HEAVY_SECTION_PATTERNS:
                    if pattern.search(heading) or pattern.search(normalized_heading):
                        heavy_section = True
                        break
            if heavy_section:
                processed.append((heading, "(omitted; consult the documentation catalog for the full content.)"))
                continue
            if body_text and FREEFORM_SECTION_MAX_CHARS > 0 and len(body_text) > FREEFORM_SECTION_MAX_CHARS:
                truncated = body_text[:FREEFORM_SECTION_MAX_CHARS].rstrip()
                body_text = f"{truncated}\n... (section truncated; open source documentation for full details.)"
            processed.append((heading, body_text))
        return processed


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


    def _run_grep_fallback(
        project_root: Optional[Path],
        terms: Sequence[str],
        limit: int,
        exclude: Set[str],
    ) -> List[Dict[str, object]]:
        if not project_root or not project_root.exists() or limit <= 0:
            return []
        if shutil.which("grep") is None:
            return []
        docs_dir = project_root / "docs"
        if not docs_dir.exists():
            return []
        pattern_terms = [term.strip() for term in terms if len(term.strip()) >= 3]
        if not pattern_terms:
            return []
        pattern = "|".join(re.escape(term) for term in pattern_terms)
        max_per_file = max(1, min(limit, 2))
        cmd = [
            "grep",
            "-R",
            "-I",
            "-n",
            "-m",
            str(max_per_file),
            "--binary-files=without-match",
            "-E",
            pattern,
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
                    "method": "grep",
                    "line": line_number,
                    "snippet": snippet.strip(),
                }
            )
            exclude.add(doc_id)
            if len(hits) >= limit:
                break
        return hits


    def _run_ripgrep_search(
        project_root: Optional[Path],
        terms: Sequence[str],
        limit: int,
        exclude: Set[str],
    ) -> List[Dict[str, object]]:
        if not project_root or not project_root.exists() or limit <= 0:
            return []
        if shutil.which("rg") is None:
            return _run_grep_fallback(project_root, terms, limit, exclude)
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

    def _ensure_task_branch_columns(connection: sqlite3.Connection) -> None:
        try:
            info_rows = connection.execute("PRAGMA table_info(tasks)").fetchall()
        except sqlite3.Error:
            return
        existing = {row["name"] for row in info_rows}
        for column, definition in (
            ("work_branch", "TEXT"),
            ("work_branch_base", "TEXT"),
            ("work_branch_updated_at", "TEXT"),
        ):
            if column not in existing:
                try:
                    connection.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
                except sqlite3.Error:
                    pass

    _ensure_task_branch_columns(conn)
    cur = conn.cursor()

    def _guard_prompt_git_state(project_root_path: Path) -> None:
        allow_dirty_env = os.getenv("WORK_ON_TASKS_ALLOW_DIRTY", "").strip().lower()
        if allow_dirty_env in {"1", "true", "yes", "on"}:
            return
        try:
            project_root_resolved = project_root_path.resolve()
        except Exception:
            project_root_resolved = project_root_path
        git_dir = project_root_resolved / ".git"
        if not git_dir.exists():
            return
        clone_paths, owner_conflicts = _scan_dependency_directories(project_root_resolved)
        if clone_paths:
            sample = [
                _friendly_relpath(path, project_root_resolved)
                for path in clone_paths[:4]
            ]
            if len(clone_paths) > 4:
                sample.append("…")
            detail = ", ".join(sample) if sample else "repository root"
            print(
                f"[work_on_tasks] Dependency cache clones detected before prompt; remove copies like {detail} "
                "before retrying.",
                file=sys.stderr,
            )
            sys.exit(2)
        if owner_conflicts:
            sample = []
            for path, owner in owner_conflicts[:4]:
                sample.append(f"{_friendly_relpath(path, project_root_resolved)} owned by {owner}")
            if len(owner_conflicts) > 4:
                sample.append("…")
            detail = "; ".join(sample) if sample else "unknown ownership mismatch"
            print(
                f"[work_on_tasks] Dependency ownership mismatch (pre-prompt guard): {detail}. "
                "Ensure the same user owns all dependency caches.",
                file=sys.stderr,
            )
            sys.exit(2)
        dirty_ignore_raw = os.environ.get("WORK_ON_TASKS_DIRTY_IGNORE", ".gpt-creator/**:.gitignore")
        dirty_ignore_patterns = [
            pattern for pattern in (segment.strip() for segment in dirty_ignore_raw.split(":")) if pattern
        ]

        def _should_ignore(path_fragment: str) -> bool:
            if not dirty_ignore_patterns:
                return False
            normalized_path = path_fragment.lstrip("./")
            return any(fnmatch.fnmatch(normalized_path, pattern) for pattern in dirty_ignore_patterns)

        try:
            status_proc = subprocess.run(
                ['git', 'status', '--porcelain=v1', '--untracked-files=all'],
                capture_output=True,
                text=True,
                cwd=str(project_root_resolved),
                check=False,
            )
        except OSError:
            return
        if status_proc.returncode != 0:
            return
        dirty_entries: List[str] = []
        for raw_line in status_proc.stdout.splitlines():
            line = raw_line.rstrip()
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if not path or _should_ignore(path):
                continue
            label = line[:2].strip().upper() or "M"
            dirty_entries.append(f"{label} {path}")
        if dirty_entries:
            preview = dirty_entries[:6]
            summary = "; ".join(preview)
            if len(dirty_entries) > 6:
                summary += "; …"
            print(
                "[work_on_tasks] Dirty working tree detected before prompt; clean or stash local edits, "
                "or set WORK_ON_TASKS_ALLOW_DIRTY=1 to override. "
                f"Affected paths: {summary}",
                file=sys.stderr,
            )
            sys.exit(2)

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
    _guard_prompt_git_state(project_root_path)

    plan_instruction_dir: Optional[Path] = None
    if staging_root:
        plan_candidate = staging_root / "plan"
        if plan_candidate.exists():
            plan_instruction_dir = plan_candidate

    registry_env_raw = os.getenv("GC_PROMPT_REGISTRY_DIR", "").strip()
    source_env_raw = os.getenv("GC_PROMPT_SOURCE_DIRS", "").strip()
    if registry_env_raw:
        registry_candidate = Path(registry_env_raw)
        if not registry_candidate.is_absolute():
            registry_candidate = project_root_path / registry_candidate
    else:
        registry_candidate = project_root_path / DEFAULT_REGISTRY_SUBDIR

    source_roots = parse_source_env(project_root_path, source_env_raw)
    try:
        ensure_prompt_registry(
            project_root_path,
            registry_dir=registry_candidate,
            source_dirs=source_roots,
            clean=os.getenv("GC_PROMPT_REGISTRY_REFRESH", "").strip().lower() in {"1", "true", "yes", "force"},
        )
    except Exception:
        registry_candidate = None

    instruction_prompts: List[Tuple[str, List[str]]] = []

    story_row = cur.execute(
        'SELECT story_id, story_title, epic_key, epic_title, sequence FROM stories WHERE story_slug = ?',
        (STORY_SLUG,)
    ).fetchone()
    if story_row is None:
        raise SystemExit(f"Story slug not found: {STORY_SLUG}")

    task_rows = cur.execute(
        'SELECT id, task_id, title, description, story_points, assignees_json, tags_json, acceptance_json, dependencies_json, '
        'tags_text, story_points, dependencies_text, assignee_text, document_reference, idempotency, rate_limits, rbac, '
        'messaging_workflows, performance_targets, observability, acceptance_text, endpoints, sample_create_request, '
        'sample_create_response, user_story_ref_id, epic_ref_id, status, last_progress_at, last_progress_run, '
        'last_log_path, last_output_path, last_prompt_path, last_notes_json, last_commands_json, last_apply_status, '
        'last_changes_applied, last_tokens_total, last_duration_seconds, work_branch, work_branch_base '
        'FROM tasks WHERE story_slug = ? ORDER BY position ASC',
        (STORY_SLUG,)
    ).fetchall()
    conn.close()

    if TASK_INDEX < 0 or TASK_INDEX >= len(task_rows):
        raise SystemExit(2)

    task = task_rows[TASK_INDEX]
    task_db_id = task["task_id"]
    existing_task_branch = (task["work_branch"] or "").strip() if "work_branch" in task.keys() else ""
    existing_task_branch_base = (task["work_branch_base"] or "").strip() if "work_branch_base" in task.keys() else ""
    documentation_db_path = os.getenv("GC_DOCUMENTATION_DB_PATH", "").strip()
    doc_catalog_env_raw = os.getenv("GC_DOC_CATALOG_PATH", "").strip()
    doc_catalog_helper = (
        os.getenv("GC_DOC_CATALOG_PY", "").strip()
        or os.getenv("GC_DOC_CATALOG_HELPER", "").strip()
        or os.getenv("doc_catalog", "").strip()
    )
    doc_registry_helper = (
        os.getenv("GC_DOC_REGISTRY_PY", "").strip()
        or os.getenv("GC_DOC_REGISTRY_HELPER", "").strip()
        or os.getenv("doc_registry", "").strip()
    )
    doc_indexer_helper = (
        os.getenv("GC_DOC_INDEXER_PY", "").strip()
        or os.getenv("GC_DOC_INDEXER_HELPER", "").strip()
        or os.getenv("doc_indexer", "").strip()
    )
    has_doc_catalog_helper = bool(doc_catalog_helper)
    has_doc_registry_helper = bool(doc_registry_helper)
    has_doc_indexer_helper = bool(doc_indexer_helper)

    doc_library_candidates: List[Path] = []
    doc_index_candidates: List[Path] = []
    doc_catalog_candidates: List[Path] = []

    fallback_catalog_literal = ".gpt-creator/staging/plan/work/doc-catalog.json"

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
    doc_catalog_pointer = doc_catalog_path_str or fallback_catalog_literal
    doc_library_shim_str = _select_display_path([project_root_path / "docs" / "doc-library.md"])
    doc_index_shim_str = _select_display_path([project_root_path / "docs" / "doc-index.md"])

    documentation_db_display = ""
    documentation_db_available = False
    if documentation_db_path:
        try:
            documentation_db_display = _select_display_path([Path(documentation_db_path)]) or ""
            documentation_db_available = Path(documentation_db_path).is_file()
        except Exception:
            documentation_db_available = False

    vector_index_path = None
    vector_index_path_str = ""
    vector_index_env_raw = os.getenv("GC_DOC_VECTOR_INDEX_PATH", "").strip()
    vector_index_candidates: List[Path] = []
    if vector_index_env_raw:
        try:
            vector_index_candidates.append(Path(vector_index_env_raw))
        except Exception:
            pass
    if documentation_db_path:
        db_path_obj = Path(documentation_db_path)
        resolved_db = _resolve_display_path(db_path_obj)
        vector_index_candidates.append(resolved_db.parent / "documentation-vector-index.sqlite")
        vector_index_candidates.append(db_path_obj.parent / "documentation-vector-index.sqlite")
    if vector_index_candidates:
        vector_index_path = _first_existing_path(vector_index_candidates)
        vector_index_path_str = _select_display_path(vector_index_candidates)

    catalog_reference_docs: List[str] = []
    for filename in ("document-catalog-indexing.md", "document-catalog-metadata.md", "document-catalog-pipeline.md"):
        doc_candidate = project_root_path / "docs" / filename
        doc_candidate_str = _select_display_path([doc_candidate])
        if doc_candidate_str:
            catalog_reference_docs.append(f"`{doc_candidate_str}`")

    documentation_asset_lines: List[str] = []
    if doc_library_path_str:
        library_line = (
            f"- Library overview: `{doc_library_path_str}` — use the documentation catalog search/show helpers "
            "to inspect specific entries instead of opening the file directly."
        )
        if doc_library_shim_str and doc_library_shim_str != doc_library_path_str:
            library_line += f" Shim fallback lives at `{doc_library_shim_str}`."
        documentation_asset_lines.append(library_line)
    elif doc_library_shim_str:
        documentation_asset_lines.append(
            f"- Library overview (shim): `{doc_library_shim_str}` — rely on the documentation catalog search/show helpers rather than reading the file directly."
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
        documentation_asset_lines.append(
            "- Path is also exported as `$GC_DOC_CATALOG_PATH`; quick listing: `python3 tools/scripts/python/doc_catalog_query.py list --limit 10` (falls back to repo scan when the SQLite DB is missing)."
        )
    else:
        documentation_asset_lines.append(
            f"- JSON catalog (doc/snippet map) at `{doc_catalog_pointer}` keeps scripted lookups fast while prompts stay lean."
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


    CLI_ROOT = Path(__file__).resolve().parents[2]
    BUILTIN_WORK_PROMPT_PATH = CLI_ROOT / "assets" / "templates" / "prompts" / "work_on_tasks_default.prompt.md"
    BUILTIN_WORK_PROMPT_LABEL = "builtin/work_on_tasks.prompt.md"
    _BUILTIN_WORK_PROMPT_FALLBACK_LINES: List[str] = [
        "## work-on-tasks Prompt",
        "- Load the task details and acceptance criteria from the context section.",
            "- Consult the documentation catalog (`python3 tools/scripts/python/doc_catalog_query.py search|show …`) before modifying files.",
        "- Outline a concise plan (<=3 bullets focused on actions), execute the required edits, and capture final status notes with clear pass/fail decisions.",
        "- Never create files named `PLAN.md` (or any case variant); summarize plans inline instead of emitting that artifact.",
        "- Apply changes by editing files directly via shell commands (no diff/patch output).",
        "- Every time you run a command that edits files, writes content, stages changes, or runs tests/tools, list that exact command under the `Commands` heading; if you truly ran nothing, state `- (none)` explicitly.",
        "- Record follow-up actions when blockers remain.",
    ]

    def _load_builtin_work_prompt_lines() -> List[str]:
        try:
            text = BUILTIN_WORK_PROMPT_PATH.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return list(_BUILTIN_WORK_PROMPT_FALLBACK_LINES)
        stripped = text.strip()
        if not stripped:
            return list(_BUILTIN_WORK_PROMPT_FALLBACK_LINES)
        return stripped.splitlines()

    def clamp_text(text: str, limit: int) -> str:
        if limit <= 0 or not text:
            return text
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"


    def _instruction_prompt_is_excluded(path_obj: Path, plan_dir: Optional[Path], project_root: Optional[Path]) -> bool:
        try:
            resolved = path_obj.resolve()
        except OSError:
            resolved = path_obj
        candidate_str = str(resolved).replace("\\", "/")
        if "/prompts/" not in candidate_str:
            return False
        if INSTRUCTION_PROMPT_RUN_MARKER in candidate_str and "/runs/" in candidate_str:
            return True
        if INSTRUCTION_PROMPT_CREATE_SDS_MARKER in candidate_str:
            return True
        if INSTRUCTION_PROMPT_CREATE_JIRA_TASKS_MARKER in candidate_str:
            return True
        if INSTRUCTION_PROMPT_BINDER_MARKER in candidate_str:
            return True
        if PROMPT_SNAPSHOT_MARKER in candidate_str:
            return True
        if plan_dir:
            try:
                rel_plan = resolved.relative_to(plan_dir.resolve())
                rel_parts = [part.lower() for part in rel_plan.parts]
                if "runs" in rel_parts and "prompts" in rel_parts:
                    return True
            except Exception:
                pass
        if project_root:
            try:
                rel_project = resolved.relative_to(project_root.resolve())
                rel_parts = [part.lower() for part in rel_project.parts]
                if rel_parts[:3] == [".gpt-creator", "cache", "task-binder"]:
                    return True
            except Exception:
                pass
        return False


    def collect_instruction_prompts(
        plan_dir: Optional[Path],
        project_root: Optional[Path],
        registry_dir: Optional[Path],
    ) -> List[Tuple[str, List[str]]]:
        prompts: List[Tuple[str, List[str]]] = []
        search_roots: List[Path] = []
        if registry_dir and registry_dir.exists():
            search_roots.append(registry_dir)
        if plan_dir and plan_dir.exists():
            search_roots.append(plan_dir)
        if not search_roots and project_root:
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
                if _instruction_prompt_is_excluded(candidate, plan_dir, project_root):
                    continue
                name_lower = candidate.name.lower()
                if not any(prefix in name_lower for prefix in WORK_PROMPT_ALLOWED_PREFIXES):
                    continue
                try:
                    size_bytes = candidate.stat().st_size
                except OSError:
                    size_bytes = 0
                if PROMPT_SOURCE_MAX_BYTES and size_bytes > PROMPT_SOURCE_MAX_BYTES:
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

    instruction_prompts = collect_instruction_prompts(plan_instruction_dir, project_root_path, registry_candidate)

    default_prompt_lines = _load_builtin_work_prompt_lines()

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
            instruction_prompts = [(BUILTIN_WORK_PROMPT_LABEL, default_prompt_lines)]
    else:
        if not any(label == BUILTIN_WORK_PROMPT_LABEL for label, _ in instruction_prompts):
            instruction_prompts.append((BUILTIN_WORK_PROMPT_LABEL, default_prompt_lines))

    debug_prompt_flag = os.getenv("GC_DEBUG_PROMPTS", "").strip().lower()
    if debug_prompt_flag in {"1", "true", "yes"}:
        summary_labels = ", ".join(label for label, _ in instruction_prompts)
        sys.stderr.write(f"gpt-creator: instruction prompts → {summary_labels or '(none)'}\n")

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

    def row_get(row: sqlite3.Row, key: str):
        try:
            return row[key]
        except (KeyError, IndexError):
            return None


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

    tags_text = clean(task['tags_text'])
    story_points = clean(row_get(task, 'estimate')) or clean(row_get(task, 'story_points'))
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
    task_row_id = None
    try:
        task_row_id = int(task['id'])
    except Exception:
        task_row_id = None

    def fetch_recent_comments(limit: int = 6) -> List[sqlite3.Row]:
        """Load latest review/QA comments for this task."""
        if tasks_db_path is None:
            return []
        try:
            with sqlite3.connect(str(tasks_db_path)) as cconn:
                cconn.row_factory = sqlite3.Row
                ccur = cconn.cursor()
                exists = ccur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='task_comments'"
                ).fetchone()
                if not exists:
                    return []
                task_ref_value = task_db_id or f"{STORY_SLUG}:{TASK_INDEX + 1}"
                where_clauses: List[str] = []
                params: List[object] = []
                if task_row_id is not None:
                    where_clauses.append("task_row_id = ?")
                    params.append(task_row_id)
                where_clauses.append("(story_slug = ? AND task_ref = ?)")
                params.extend([STORY_SLUG, task_ref_value])
                where = " OR ".join(where_clauses)
                params.append(limit)
                return list(
                    ccur.execute(
                        f"""
                        SELECT commenter, details, status_from, status_to, severity, component, suggested_fix, blocking, artifact_path, agent_run_id, created_at
                          FROM task_comments
                         WHERE {where}
                         ORDER BY created_at DESC
                         LIMIT ?
                        """,
                        params,
                    ).fetchall()
                )
        except Exception:
            return []

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

    agent_header_lines: List[str] = []
    agent_header_path = os.getenv("GC_ACTIVE_AGENT_FILE", "").strip()
    if agent_header_path:
        try:
            with open(agent_header_path, "r", encoding="utf-8") as agent_file:
                agent_payload = json.load(agent_file)
                prompt_section = agent_payload.get("prompt") or {}
                header_text = (prompt_section.get("header") or "").strip()
                if header_text:
                    agent_header_lines = header_text.splitlines()
        except Exception:
            agent_header_lines = []

    lines: List[str] = []
    instruction_section_lines: List[str] = []

    def append_instruction_lines(new_lines: List[str]) -> None:
        if not new_lines:
            return
        if instruction_section_lines and instruction_section_lines[-1] != "":
            instruction_section_lines.append("")
        instruction_section_lines.extend(new_lines)

    if agent_header_lines:
        lines.extend(agent_header_lines)
        if agent_header_lines[-1].strip():
            lines.append("")
    else:
        lines.append(f"# You are Codex (model: {MODEL_NAME})")
        lines.append("")
    lines.append(f"You are assisting the {project_display} delivery team. Implement the task precisely using the repository at: {repo_path}")
    lines.append("")
    doc_helpers_available = bool(
        documentation_db_available
        and has_doc_catalog_helper
        and has_doc_registry_helper
        and has_doc_indexer_helper
    )
    if doc_helpers_available:
        lines.append("## Documentation Assets (local helpers)")
        lines.append("")
        catalog_line = "- Catalog DB: $GC_DOCUMENTATION_DB_PATH"
        if documentation_db_display:
            catalog_line += f" → `{documentation_db_display}`"
        lines.append(catalog_line)
        vector_line = "- Vector/semantic index: $GC_DOC_VECTOR_INDEX_PATH"
        if vector_index_path_str:
            vector_line += f" → `{vector_index_path_str}`"
        else:
            vector_line += " (generate via documentation scan when semantic lookup is required)"
        lines.append(vector_line)
        lines.append("")
        lines.append("## Documentation Catalog and Commands")
        lines.append("We maintain a docdex-backed documentation catalog (with SQLite/vector fallbacks) so you can pull focused snippets without reopening large files. Prefer querying the catalog instead of searching files directly.")
        lines.append("Catalog structure and key tables:")
        lines.append(f"- Example query: sqlite3 \"$GC_DOCUMENTATION_DB_PATH\" \\")
        lines.append('  "SELECT doc_id,surface FROM documentation_search WHERE documentation_search MATCH \'lockout\' LIMIT 5;"')
        lines.append("- `documentation`: one row per document with metadata (doc_type, rel_path, title, tags_json, metadata_json, status, change_count).")
        lines.append("- `documentation_changes`: append-only audit history keyed by doc_id (change_type, sha256, description, context, recorded_at).")
        lines.append("- `documentation_sections`: hierarchical structure per document (section_id, parent_section_id, order_index, anchor, byte/token spans, summary).")
        lines.append("- `documentation_excerpts`: curated snippets for prompts (content, justification, token_length, optional embedding_id).")
        lines.append("- `documentation_summaries`: cached short/long summaries (summary_short/long, key_points_json, keywords_json, embedding_id).")
        lines.append("- `documentation_index_state`: surfaces pending semantic rebuild (status, indexed_at, usage_score, metadata_json).")
        lines.append("- `documentation_search` (FTS5): searchable text (surface, content) with doc_id/section_id; use MATCH with snippet() or ORDER BY bm25().")
        lines.append('- Schema quick look: sqlite3 "$GC_DOCUMENTATION_DB_PATH" ".tables" or ".schema documentation"')
        lines.append("- Vector DB ($GC_DOCUMENTATION_INDEX_PATH) table `vectors`: embeddings per surface (embedding_id PK, doc_id, section_id, vector_json, dims, metadata_json, updated_at).")
        lines.append("Common catalog commands (wrap inner commands in single quotes so the environment variables remain quoted):")
        lines.append('- List recent docs: python3 tools/scripts/python/doc_catalog_query.py list --limit 10')
        lines.append('- Full-text search: python3 tools/scripts/python/doc_catalog_query.py search --query "lockout" --limit 15')
        lines.append('- Show document by id: python3 tools/scripts/python/doc_catalog_query.py show DOC-1234ABCD --start 500 --end 540')
        lines.append("- Docdex-powered search/snippets: the doc catalog helper automatically talks to the running docdex daemon—use the commands above instead of `rg`/`cat` when you need to locate docs or quote a snippet.")
        lines.append('- Rebuild semantic index: bash -lc \'python3 "$GC_DOC_INDEXER_PY" rebuild --db "$GC_DOCUMENTATION_DB_PATH" --out "$GC_DOC_VECTOR_INDEX_PATH"\'')
        lines.append('- Register or sync discovery TSV: bash -lc \'python3 "$GC_DOC_REGISTRY_PY" register --db "$GC_DOCUMENTATION_DB_PATH" --tsv ".gpt-creator/manifests/<latest>.tsv"\'')
        lines.append("- SQL samples (helpful when Python helpers are unavailable):")
        lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" ".tables"')
        lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" "SELECT doc_id, surface FROM documentation_search WHERE documentation_search MATCH \'lockout\' LIMIT 5;"')
        lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" "SELECT doc_id, path, changed_at FROM documentation_changes ORDER BY changed_at DESC LIMIT 10;"')

    else:
        lines.append("## Documentation Assets (docdex/SQLite fallback)")
        lines.append("")
        catalog_line = "- Catalog DB: $GC_DOCUMENTATION_DB_PATH"
        if documentation_db_display:
            if documentation_db_available:
                catalog_line += f" → `{documentation_db_display}`"
            else:
                catalog_line += (
                    f" (missing at `{documentation_db_display}`; run `gpt-creator scan` to rebuild the doc catalog before issuing catalog commands)"
                )
        else:
            catalog_line += " (run `gpt-creator scan` if the catalog needs to be regenerated)"
        lines.append(catalog_line)
        vector_line = "- Vector/semantic index: $GC_DOC_VECTOR_INDEX_PATH"
        if vector_index_path_str:
            vector_line += f" → `{vector_index_path_str}`"
        lines.append(vector_line)
        lines.append("- FTS example:")
        lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \\')
        lines.append('    "SELECT doc_id, surface FROM documentation_search WHERE documentation_search MATCH \'lockout\' LIMIT 15;"')
        lines.append("- Latest changes:")
        lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \\')
        lines.append('    "SELECT doc_id, path, changed_at FROM documentation_changes ORDER BY changed_at DESC LIMIT 10;"')
        lines.append("- Schema quick look:")
        lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" ".tables"')
        lines.append("- When docdex is available, `python3 tools/scripts/python/doc_catalog_query.py search|show ...` still routes through it automatically; otherwise it falls back to the SQLite/vector index (or CLI JSON query). Use that helper instead of ad-hoc `rg`/`cat` when you need doc snippets.")
        if not documentation_db_available:
            lines.append("- (Documentation catalog helpers unavailable without the SQLite database; regenerate with `gpt-creator scan` before running catalog commands.)")
        else:
            missing_helpers: List[str] = []
            if not has_doc_catalog_helper:
                missing_helpers.append('doc_catalog_refresh.py or GC_DOC_CATALOG_HELPER')
            if not has_doc_registry_helper:
                missing_helpers.append("$GC_DOC_REGISTRY_PY")
            if not has_doc_indexer_helper:
                missing_helpers.append("$GC_DOC_INDEXER_PY")
            if missing_helpers:
                joined = ", ".join(missing_helpers)
                lines.append(f"- (Documentation helpers missing: {joined}. Re-run `gpt-creator install` or `gpt-creator scan` to refresh shims before invoking catalog commands.)")

    instruction_insert_index = len(lines)

    lines.append("")

    if documentation_asset_lines:
        lines.extend(documentation_asset_lines)
    else:
        lines.append("- (No documentation assets detected; ensure doc-library and doc-index are generated before editing.)")
    lines.append("- For focused file searches, run `python3 \"$GC_TARGETED_SEARCH_PY\" --pattern <needle> --paths <dir>` or `python3 \"$GC_REPO_OUTLINE_PY\"` instead of ad-hoc `rg`/`ls` loops; these helpers keep transcripts lean and deterministic.")

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
    story_points = clean(row_get(task, 'estimate')) or clean(row_get(task, 'story_points'))

    if compact_mode:
        task_label = task_id or f"Task {TASK_INDEX + 1}"
        summary = f"- {task_label}"
        if task_title:
            summary += f" — {task_title}"
        lines.append(summary)
        meta_bits = []
    if story_points:
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
    if story_points:
        lines.append(f"- Story points: {story_points}")
        if assignees:
            lines.append("- Assignees: " + ", ".join(assignees))
        elif assignee_text:
            lines.append(f"- Assignee: {assignee_text}")
        if tags:
            lines.append("- Tags: " + ", ".join(tags))
        elif tags_text:
            lines.append(f"- Tags: {tags_text}")
    # Story points already emitted above if present
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
    else:
        lines.append("(No additional description provided.)")

    if acceptance:
        lines.append("")
        lines.append("### Acceptance Criteria")
        for item in acceptance:
            lines.append(f"- {item}")
    elif acceptance_text_extra:
        lines.append("")
        lines.append("### Acceptance Criteria")
        lines.extend(acceptance_text_extra.splitlines())

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

        recent_comments = fetch_recent_comments()
        if recent_comments:
            lines.append("- Review/QA comments (latest):")
            for comment in recent_comments[:4]:
                commenter = clean(comment['commenter'])
                created_at = clean(comment['created_at'])
                status_from = clean(comment['status_from'])
                status_to = clean(comment['status_to'])
                severity = clean(comment['severity'])
                component = clean(comment['component'])
                suggested_fix = clean(comment['suggested_fix'])
                blocking = (str(comment['blocking']).strip() == "1")
                detail_text = clamp_text(clean(comment['details']), 220)
                meta_bits = []
                if status_from or status_to:
                    transition = f"{status_from or '?'}→{status_to or '?'}"
                    meta_bits.append(transition)
                if severity:
                    meta_bits.append(severity)
                if component:
                    meta_bits.append(component)
                if blocking:
                    meta_bits.append("BLOCKING")
                meta_prefix = ""
                if created_at or meta_bits:
                    meta_prefix = " ".join(part for part in [created_at, "[" + " | ".join(meta_bits) + "]" if meta_bits else ""] if part)
                if meta_prefix:
                    lines.append(f"  - {commenter or 'agent'} {meta_prefix}: {detail_text}")
                else:
                    lines.append(f"  - {commenter or 'agent'}: {detail_text}")
                if suggested_fix:
                    lines.append(f"    Suggested fix: {clamp_text(suggested_fix, 180)}")

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

    def _docdex_available() -> bool:
        return _load_docdex_client()

    def _docdex_repo_root() -> Path:
        base = project_root_path or Path.cwd()
        try:
            return base.resolve()
        except Exception:
            return base

    def _run_docdex_search(terms: Sequence[str], limit: int) -> List[Dict[str, object]]:
        if not _docdex_available() or not terms or limit <= 0:
            print("[work_on_tasks] docdex search skipped (unavailable or no terms)", file=sys.stderr)
            return []
        query_text = " ".join(terms[:12]).strip()
        if not query_text:
            return []
        repo_root = _docdex_repo_root()
        try:
            print(f"[work_on_tasks] running docdex search '{query_text}' limit={limit}", file=sys.stderr)
            payload = docdex_client.search_docs(query_text, limit=limit, repo_root=repo_root)  # type: ignore[attr-defined]
        except Exception:
            print("[work_on_tasks] docdex search failed; returning no hits", file=sys.stderr)
            return []
        hits: List[Dict[str, object]] = []
        for hit in payload.get("hits", []):
            doc_id = (hit.get("doc_id") or "").strip()
            if not doc_id:
                continue
            snippet_text = _normalise_space(hit.get("snippet") or hit.get("summary") or "")
            rel_path = (hit.get("rel_path") or doc_id).strip()
            hits.append(
                {
                    "doc_id": doc_id,
                    "method": "docdex",
                    "rel_path": rel_path,
                    "snippet": snippet_text[:500],
                }
            )
        return hits

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


    def _relative_path_for_prompt(path_obj: Path) -> str:
        for base in filter(None, [project_root_path, staging_root]):
            if not base:
                continue
            try:
                return str(path_obj.relative_to(base))
            except ValueError:
                continue
        return str(path_obj)

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
    docdex_ready = _docdex_available()
    print(f"[work_on_tasks] docdex_ready={docdex_ready} (search terms present? {bool(search_terms)})", file=sys.stderr)
    if search_terms:
        seen_doc_ids: Set[str] = {
            entry.get("doc_id", "").strip()
            for entry in doc_catalog_entries
            if entry.get("doc_id")
        }
        seen_doc_ids.discard("")
        if docdex_ready:
            docdex_hits = _run_docdex_search(search_terms, 12)
            for hit in docdex_hits:
                doc_id = (hit.get("doc_id") or "").strip()
                if not doc_id or doc_id in seen_doc_ids:
                    continue
                doc_search_hits.append(hit)
                seen_doc_ids.add(doc_id)
        else:
            print("[work_on_tasks] docdex unavailable; falling back to FTS/vector retrieval", file=sys.stderr)
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

    search_summary_payload: List[Dict[str, object]] = []
    if doc_search_hits:
        lines.append("")
        lines.append("## Documentation Search Hits")
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
        task_ref = task_id or f"{STORY_SLUG}:{TASK_INDEX + 1}"
        if task_ref:
            search_map = doc_catalog_data.setdefault("search_hits", {})
            search_map[task_ref] = search_summary_payload
            doc_catalog_changed["value"] = True

    example_doc_id = ""
    for catalog_entry in doc_catalog_entries:
        candidate_doc_id = (catalog_entry.get("doc_id") or "").strip()
        if candidate_doc_id:
            example_doc_id = candidate_doc_id
            break
    if not example_doc_id:
        for hit in doc_search_hits:
            candidate_doc_id = (hit.get("doc_id") or "").strip()
            if candidate_doc_id:
                example_doc_id = candidate_doc_id
                break

    if doc_catalog_entries and doc_helpers_available:
        lines.append("")
        lines.append("## Documentation Catalog")
        doc_id_token = "<ID>"
        if example_doc_id:
            doc_id_token = shlex.quote(example_doc_id)
        lines.append(
            "Use the catalog below to pick a section, then run "
            f"`python3 tools/scripts/python/doc_catalog_query.py show {doc_id_token} --start 1 --end 200` for a narrow excerpt. "
            "Avoid reading the raw documentation files directly."
        )
        for entry in doc_catalog_entries[:6]:
            rel_path = entry['rel_path']
            lines.append(f"- {entry['doc_id']} — {rel_path}")
            headings_preview = entry.get("headings") or []
            if headings_preview:
                lines.append("  Sections:")
                for heading in headings_preview[:6]:
                    lines.append(f"    • {heading}")
            else:
                lines.append(
                    "  (No headings detected; use the documentation catalog search/show helpers to locate the relevant section instead of opening the file directly.)"
                )
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
                lines.append(
                    f"  -> If a compiled artifact is required for `{rel_path}`, rely on the designated build tool or artifact viewer; otherwise focus on the source file."
                )

    if file_entries:
        lines.append("")
        lines.append("## Cached File Excerpts")
        lines.append(
            "Reuse the snippets below instead of repeating cat/sed on the same file; refresh only if the file changed. "
            "When you need another slice, query the documentation catalog or open just the specific code file segment you plan to modify."
        )
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
                        command_hint = f"sed -n '{start_line},{end_line}p' {rel_path}"
                if not command_hint:
                    command_hint = f"sed -n '1,120p' {rel_path}"
            if command_hint:
                lines.append(f"  -> Reopen via `{command_hint}`")

    if guard_entries:
        block_lines = [
            "## Command Guard Alerts",
            "Resolve these issues before rerunning commands that have already failed; focus on remediation instead of immediate retries.",
        ]
        for entry in guard_entries[:4]:
            command_label = (entry.get("command") or "pnpm").strip() or "pnpm"
            issues = entry.get("issues") or []
            summary = "; ".join(issues) if issues else "Pre-check violation detected."
            block_lines.append(f"- {command_label} — {summary}")
        append_instruction_lines(block_lines)

    append_instruction_lines(
        [
            "## Helper Checklist (before exploring code or docs)",
            "- Map the repo once via `python3 \"$GC_REPO_OUTLINE_PY\" --max-depth 1 --focus apps/api` (helper is auto-cloned under .gpt-creator/shims/python/) instead of issuing repetitive `ls` commands.",
            "- When you need to inspect code, run `python3 \"$GC_TARGETED_SEARCH_PY\" --pattern \"<needle>\" --paths <dirs>` first; only fall back to `sed`/`cat` for the exact ranges you discover there.",
            "- For SDS/PDR context or migrations, run `python3 tools/scripts/python/doc_catalog_query.py search --query \"<term>\" --limit 5` instead of opening doc files or grepping blindly.",
            "- Validate REST endpoints via manifests and `python3 \"$GC_REST_CHECK_RUNNER_PY\" manifest.yaml` instead of crafting ad-hoc HTTP scripts.",
            "- Preview file ranges safely using `python3 \"$GC_SAFE_SHOW_FILE_PY\" <path> --suggest` before `sed`/`cat`, so you avoid missing-file retries.",
            "- Need a quick view of specific lines? Run `python3 tools/scripts/python/show_file_excerpt.py <path> --start 1 --end 200` instead of `nl|sed` pipelines.",
            "- Need a quick Python helper? Create /tmp/snippet.py and run `python3 \"$GC_RUN_SNIPPET_PY\" /tmp/snippet.py`; the script refuses placeholder-only heredocs and keeps commands deterministic.",
            '- Building command entries? Run `python3 tools/scripts/python/command_scaffold.py "label" \'cd apps/api\' \'pnpm test\'` to emit a ready-to-paste "bash -lc ..." block without ellipses.',
            "- Monitoring guardrail hits? Run `python3 tools/scripts/python/guardrails_report.py --json` (or `--fail-on-placeholder N`) to summarize events or fail CI when placeholders persist.",
        ]
    )

    guidance_lines = [
        "## Instructions",
        "### Response Format",
        "- Organize your reply with the headings `Plan`, `Focus`, `Commands`, and `Notes` (in that order).",
        "- Keep notes in Action/Result form; when narration is unavoidable, pipe it through `python3 tools/scripts/python/summarize_note.py \"label\"` and paste the emitted summary pointer.",
        "- Write each heading exactly as shown (e.g., `Plan` on its own line) with no surrounding Markdown styling or punctuation.",
        "- Keep each section to short bullet items or terse sentences; skip JSON, code fences, and closing summaries.",
        "- Do not include source code, config snippets, or test case bodies; describe changes and evidence at a high level only.",
        "- Make repository edits by listing the exact shell commands you will run under `Commands` (use `bash` to write files when needed).",
        '  Example: `bash -lc "python3 tools/scripts/python/summarize_note.py "label" <<\'EOF\' ... EOF"`',
        "- Ensure the `Commands` section lists actionable shell commands; if none are required, include a single bullet `- (none)` beneath the heading.",
            "- Placeholders (`...`, `…`, `cat <<'EOF'` without a closing `EOF`, etc.) immediately trigger the commands-fill-placeholders guard—fully expand every command before submitting.",
        "- Do not generate diffs or patches; apply edits directly through those shell commands.",
        "- Primary objective: ship the code required by the task acceptance criteria; avoid documentation rewrites or reorganizing prompts.",
        "- If an acceptance criterion demands heavy setup or environments the agent cannot access, acknowledge the gap and continue focusing on the core code changes.",
        "- In `Focus`, call out the files or symbols you are touching so reviewers understand the blast radius.",
        "- When you are satisfied with the changes, stage and commit them yourself (e.g., `git add …` then `git commit -m \"<task summary>\"`) and list those commands under `Commands`.",
        "- Push your work once committed (e.g., `git push origin <branch>`), and include that command under `Commands` as well.",
        "- Capture blockers or follow-ups in `Notes`.",
        "- Review `Known Command Failures` and `Command Guard Alerts` before retrying a command; prefer remediation steps over blind reruns.",
        "- Use `python3 tools/scripts/python/doc_catalog_query.py search --query \"<term>\" --limit 5` (or `show DOC-ID --start 500 --end 520`) for SDS/PDR context instead of opening doc files directly.",
        "- Need a repo overview? Run `python3 \"$GC_REPO_OUTLINE_PY\" --max-depth 1 --focus <path>` (see `assets/templates/help/repo_outline_usage.txt`).",
        "- Searching for symbols? Run `python3 \"$GC_TARGETED_SEARCH_PY\" --pattern <needle> --paths <dirs> [--ext .ts]` instead of repo-wide `rg`/`python os.walk` loops (`assets/templates/help/targeted_search_usage.txt`).",
        "- Validating REST endpoints? Define a manifest and run `python3 \"$GC_REST_CHECK_RUNNER_PY\" <manifest.yaml>` (`assets/templates/help/rest_check_runner_usage.txt`).",
        "- Unsure about a file path? Run `python3 \"$GC_SAFE_SHOW_FILE_PY\" <path-or-name> --suggest` before `sed`/`cat` to avoid missing-file retries (`assets/templates/help/safe_show_file_usage.txt`).",
        "- Need a quick Python helper? Create `/tmp/snippet.py` via heredoc and run `python3 \"$GC_RUN_SNIPPET_PY\" /tmp/snippet.py` to avoid placeholder heredocs (`assets/templates/help/run_snippet_usage.txt`).",
        "- End the `Notes` section with `STATUS: completed`, `STATUS: needs-retry`, or `STATUS: failed` so automation can classify the run.",
    ]

    if compact_mode:
        guidance_lines.extend(
            [
                "- Prefer pnpm for scripts; mention commands that cannot run because of network limits.",
                '- When you need documentation context, query the catalog (search/show) with precise section names like `"SDS 7.3"`; do not read doc files from the repo.',
                "- Avoid repo-wide listings/searches; open only the code files you intend to edit and keep `sed`/`cat` ranges tight.",
                "- Track file views; if you begin paging sequential ranges, pause and confirm the slice truly supports the active step.",
            ]
        )
    else:
        guidance_lines.extend(
            [
                "- Prefer pnpm for scripts; note commands that cannot run because of network limits.",
                "- Route all documentation lookups through the catalog search/show helpers; never crawl SDS/PDR files directly.",
                "- Avoid broad repo sweeps; open only the code files tied to your current plan steps and keep the slices minimal.",
            ]
        )

    append_instruction_lines(guidance_lines)

    append_instruction_lines(
        [
            "## Guardrails",
            "- Stay within this task's scope; avoid spinning up unrelated plans or subprojects.",
            "- Consult only the referenced docs or clearly relevant files; skip broad repo sweeps.",
            "- Keep command usage lean and focused on assets needed for the acceptance criteria.",
            "- Do not run directory-wide listings/searches outside the declared `focus`; revise the plan + focus first.",
            "- Never copy, rename, or vend manual backups of dependency caches (node_modules, vendor, Pods, venv/.venv, dist/build/target, pkg/mod, third_party); treat third-party modules as read-only and rely on the package manager instead.",
            "- Tackle documentation edits only after the related code changes land, and only when the documentation would be inaccurate without the update.",
            "- Wrap up once deliverables are met; record blockers or follow-ups succinctly in `notes`.",
        ]
    )

    if instruction_prompts:
        for prompt_label, prompt_lines in instruction_prompts:
            if not prompt_lines:
                continue
            append_instruction_lines(prompt_lines)

    if instruction_section_lines:
        while instruction_section_lines and instruction_section_lines[-1] == "":
            instruction_section_lines.pop()
        while instruction_section_lines and instruction_section_lines[0] == "":
            instruction_section_lines.pop(0)
        if instruction_section_lines:
            instruction_section_lines.append("")
            lines[instruction_insert_index:instruction_insert_index] = instruction_section_lines

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

    section_pairs = _lines_to_sections(lines)
    section_pairs = emit_preamble_once(section_pairs)
    section_pairs = dedupe_and_coalesce(section_pairs)
    formatted_sections = format_sections(section_pairs)
    lines = formatted_sections.rstrip("\n").split("\n") if formatted_sections.strip() else []

    final_prompt_text = "\n".join(lines) + "\n"
    final_prompt_text = slim_prompt_markdown(final_prompt_text)
    prompt_path = Path(PROMPT_PATH)
    meta_path = Path(str(prompt_path) + ".meta.json")
    input_digest = _compute_input_digest(
        STORY_SLUG,
        TASK_INDEX,
        task_id,
        MODEL_NAME,
        final_prompt_text,
    )
    prompt_sha = hashlib.sha256(final_prompt_text.encode("utf-8", "ignore")).hexdigest()
    existing_digest = _read_existing_input_digest(meta_path)
    meta_same = prompt_path.exists() and meta_path.exists() and _meta_same_as(meta_path, prompt_sha)
    if not (prompt_path.exists() and existing_digest == input_digest and meta_same):
        _atomic_write_text(prompt_path, final_prompt_text)
        meta_payload = {
            "story_slug": STORY_SLUG,
            "task_id": task_id,
            "task_title": task_title,
            "task_index": TASK_INDEX,
            "model": MODEL_NAME,
            "bytes": len(final_prompt_text),
            "input_digest": input_digest,
            "prompt_path": str(prompt_path),
            "sha256": prompt_sha,
            "written_at": int(time.time()),
        }
        _atomic_write_text(meta_path, json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n")

    publish_disabled = os.getenv("GC_PROMPT_PUBLISH_DISABLE", "").strip().lower()
    guard_path = os.getenv("GC_WORK_PROMPT_SYNC_RUN_GUARD", "").strip()
    guard_blocking = False
    guard_file: Optional[Path] = None
    if guard_path:
        guard_file = Path(guard_path)
        if guard_file.exists():
            guard_blocking = True
    if publish_disabled not in {"1", "true", "yes"} and not guard_blocking:
        try:
            publish_prompt(prompt_path, meta_path, project_root_path)
            if guard_file is not None:
                guard_file.parent.mkdir(parents=True, exist_ok=True)
                guard_file.write_text(f"{int(time.time())}\n", encoding="utf-8")
        except Exception:
            pass

    story_points_meta = story_points or ""
    print(f"{task_id}\t{task_title}\t{story_points_meta}")
