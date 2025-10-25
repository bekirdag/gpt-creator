# Documentation Catalog Indexing

This reference explains how the documentation catalog now exposes both full-text and semantic indexing surfaces, along with the token-aware retrieval path that keeps downstream agents efficient.

## Components

| Layer | Purpose | Implementation |
|-------|---------|----------------|
| Full-text index | Keyword search over summaries, metadata, and curated excerpts | SQLite FTS5 table `documentation_search` managed via `DocRegistry.replace_search_entries` |
| Vector index | Semantic similarity search for summaries and excerpts | Local SQLite store handled by `LocalVectorIndex` in `src/lib/doc_indexer.py` |
| Retrieval planner | Budgeted fetch that serves summaries/excerpts before full text | `DocumentRetriever` in `src/lib/doc_retriever.py` |

## Full-Text Indexing

- `DocIndexer.rebuild_full_text` queries `documentation`, `documentation_summaries`, and `documentation_excerpts`.  
- Each document contributes:
  - A `document` surface combining title, path, tags, summaries, keywords, and raw metadata JSON.
  - An `excerpt` surface per curated snippet (content + optional justification).  
- Entries are written through `DocRegistry.replace_search_entries`, which clears prior rows per document and inserts fresh data.  
- `documentation_index_state` is updated with `surface="fts"` and metadata describing how many entries were indexed.

## Vector Indexing

- `DocIndexer.rebuild_vector_index` assembles summary and excerpt texts into `VectorTask` objects.  
- The hashing provider (`HashEmbeddingProvider`) produces deterministic embeddings for offline development; swap in a real provider by implementing `EmbeddingProvider`.  
- `LocalVectorIndex` stores vectors as JSON inside `documentation-vector-index.sqlite`, including metadata (`text_hash`, `token_estimate`, `source_version`) to skip redundant recomputation.  
- Embedding IDs are persisted back onto `documentation_summaries` and `documentation_excerpts`, ensuring future runs reuse cached vectors.  
- Index freshness is tracked via `documentation_index_state` entries with `surface="vector"`.

## Token-Aware Retrieval

- `DocumentRetriever.plan` orchestrates a staged fetch with a `TokenBudget`.  
  1. Short summary → long summary → key points (if they fit).  
  2. Up to `max_excerpts` curated snippets, using `token_length` when available.  
  3. Optional full document text only when remaining budget allows.  
- Budgets default to 2,000 tokens but can be overridden per request.  
- Results are returned as ordered `DocumentChunk` objects containing content, section references, and token costs.  
- LRU caches (`maxsize=256`) guard summary/excerpt lookups so repeated calls avoid extra SQLite queries.

## Operational Usage

1. **Run `gpt-creator scan`** – the CLI now orchestrates catalog build, heuristic summaries, and both index rebuilds automatically.  
2. **(Optional) Rebuild indexes manually** by invoking `DocIndexer`:
   ```python
   from pathlib import Path
   from src.lib.doc_indexer import DocIndexer

   indexer = DocIndexer(Path(".gpt-creator/staging/plan/tasks/tasks.db"))
   indexer.rebuild_full_text()
   indexer.rebuild_vector_index()
   ```
3. **Retrieve content** under a budget:
   ```python
   from pathlib import Path
   from src.lib.doc_retriever import DocumentRetriever, TokenBudget

   retriever = DocumentRetriever(Path(".gpt-creator/staging/plan/tasks/tasks.db"))
   plan = retriever.plan("DOC-ABC12345", budget=TokenBudget(limit=1500), include_full_text=False)
   ```
4. Monitor `documentation_index_state` to confirm both `fts` and `vector` surfaces show fresh timestamps after each run.

Swap out the hashing embedding provider for a production-ready service by supplying a custom `EmbeddingProvider` implementation when constructing `DocIndexer`.
