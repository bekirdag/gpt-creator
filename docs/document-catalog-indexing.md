# Document Catalog — Indexing (shim)

> Purpose: Provide a stable reference for agents that expect this file. This is a minimal shim; expand as needed.

## Locations
- Registry DB: `.gpt-creator/staging/plan/tasks/tasks.db` (tables: `documentation`, `documentation_changes`, `documentation_search`)
- Vector index: `.gpt-creator/staging/plan/tasks/documentation-vector-index.sqlite`
- JSON catalog: `.gpt-creator/staging/plan/work/doc-catalog.json`
- Headings index: `.gpt-creator/staging/doc-index.md`
- Library overview: `.gpt-creator/staging/doc-library.md` (fallback: `docs/doc-library.md`)

## Quick commands
```bash
export GC_DOCUMENTATION_DB_PATH=".gpt-creator/staging/plan/tasks/tasks.db"
# Keyword search (FTS)
sqlite3 "$GC_DOCUMENTATION_DB_PATH" \
  "SELECT doc_id,surface FROM documentation_search WHERE documentation_search MATCH 'lockout' LIMIT 10;"
# Vector index refresh (best-effort)
python3 src/lib/doc_indexer.py --runtime-dir .gpt-creator || echo 'indexer not available; skipping'
```

## Notes
- If the registry DB is missing, agents should **skip indexing gracefully** and proceed; this page’s presence prevents hard-fail lookups.
