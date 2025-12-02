# Document Catalog — Indexing

> TL;DR for agents: the documentation registry lives in `.gpt-creator/staging/plan/tasks/tasks.db`. Use `DocRegistry` (Python) or the helper commands below instead of rebuilding context from scratch.

## Key Locations
- Registry DB: `.gpt-creator/staging/plan/tasks/tasks.db`  
  Tables include `documentation`, `documentation_sections`, `documentation_summaries`, `documentation_excerpts`, `documentation_changes`, and the FTS table `documentation_search`.
- Vector index (when enabled): `.gpt-creator/staging/plan/tasks/documentation-vector-index.sqlite`
- JSON catalog snapshot: `.gpt-creator/staging/plan/work/doc-catalog.json`
- Library markdown: `.gpt-creator/staging/doc-library.md` (fallback shim: `docs/doc-library.md`)
- Headings index: `.gpt-creator/staging/doc-index.md`

## Agent Quickstart
- Prefer reading metadata through `DocRegistry` (`src/lib/doc_registry.py`) instead of scanning the filesystem. It already deduplicates documents, tracks change counters, and exposes sections/summaries/excerpts.
- When you need to refresh the catalog after editing docs, rerun the scan pipeline:
  ```bash
  gpt-creator scan --project "$PWD"
  ```
  That command will:
  1. Rebuild the discovery manifest.
  2. Upsert rows via `doc_registry.py sync-scan`.
  3. Regenerate the catalog (`doc_catalog.py`), summaries/excerpts (`doc_pipeline.py`), and vector index (best-effort).
- To search staged content inside the registry, use SQLite FTS:
  ```bash
  export GC_DOCUMENTATION_DB_PATH=".gpt-creator/staging/plan/tasks/tasks.db"
  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \
    "SELECT doc_id, surface FROM documentation_search
     WHERE documentation_search MATCH 'lockout'
     ORDER BY rank LIMIT 10;"
  ```
- To pull the latest summaries or excerpts for grounding answers:
  ```bash
  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \
    "SELECT doc_id, summary_short FROM documentation_summaries ORDER BY last_generated_at DESC LIMIT 5;"
  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \
    "SELECT doc_id, content FROM documentation_excerpts WHERE doc_id='DOC-XXXXXX' LIMIT 5;"
  ```

## Programmatic Registry Access
- Import `DocRegistry` when you need structured rows:
  ```python
  from pathlib import Path
  from src.lib.doc_registry import DocRegistry

  registry = DocRegistry(Path(".gpt-creator/staging/plan/tasks/tasks.db"))
  docs = registry.fetch_all()  # [{doc_id, rel_path, tags, metadata, ...}]
  sections = registry.fetch_sections([doc["doc_id"] for doc in docs])
  ```
- To upsert summaries/excerpts after generating new content, call:
  ```python
  from src.lib.doc_registry import SummaryInput, ExcerptInput

  registry.upsert_summaries([
      SummaryInput(
          doc_id="DOC-1234ABCD",
          summary_short="Concise overview …",
          summary_long="Longer abstract …",
          key_points=["Point A", "Point B"],
          keywords=["keyword-a", "keyword-b"],
          source_version="sha256-of-source",
      ),
  ])

  registry.replace_excerpts_bulk({
      "DOC-1234ABCD": [
          ExcerptInput(
              excerpt_id="uuid-1",
              doc_id="DOC-1234ABCD",
              section_id=None,
              content="High-signal paragraph …",
              token_length=120,
              source_version="sha256-of-source",
          )
      ],
  })
  ```
- The registry automatically records change history in `documentation_changes` and keeps `documentation_search` in sync. No manual SQL is required when you use the helper methods.

## Manual Resyncs & Change Tracking
- Only call `doc_registry.py` directly when you have a fresh discovery manifest and do **not** want to rerun the whole scan pipeline:
  ```bash
  python3 src/lib/doc_registry.py sync-scan \
    --project-root "$PWD" \
    --runtime-dir .gpt-creator \
    --scan-tsv "$(ls -1t .gpt-creator/manifests/discovery_*.tsv | head -n1)"
  ```
- When a document hash (`sha256`) changes, the registry increments `change_count`, inserts a row into `documentation_changes`, and clears dependent embeddings (by nulling `embedding_id`). Downstream jobs (summaries, indexer) repopulate those fields on the next pass.

## Notes
- If the registry DB is genuinely absent, agents should **skip catalog-dependent steps gracefully** and continue with the task.
- All tables use UTF-8 text and are part of the same SQLite file, so local queries are inexpensive compared to streaming entire docs through the model.
