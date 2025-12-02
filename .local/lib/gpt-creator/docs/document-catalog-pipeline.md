# Documentation Catalog Summarization Pipeline

This document outlines the end-to-end automation that keeps derived summaries, abstracts, keywords and embeddings fresh for every catalogued document. The goal is to offer deterministic entry points for the AI agent while bounding token usage. The pipeline combines ingestion triggers, deterministic preprocessing, LLM-backed generation and continuous evaluation.

## Objectives

- Populate `documentation_summaries`, `documentation_excerpts` and relevant vector stores without manual effort.  
- Regenerate derived artifacts whenever source documents change or quality signals require correction.  
- Keep processing cost predictable via batching, caching and token budgeting.  
- Provide guardrails so generated summaries stay faithful, concise and useful for retrieval.

## High-Level Flow

1. **Change detection** – Watch the `documentation` table for new rows or updates where `checksum` or `status` changed.  
2. **Preprocessing** – Normalize text (strip boilerplate, dedupe headers), segment into logical sections, and calculate token statistics.  
3. **Summary generation** – Produce short and long summaries plus key points for the full document.  
4. **Keyword extraction** – Generate topic keywords using hybrid (statistical + LLM) approach.  
5. **Excerpt selection** – Curate high-signal snippets per section.  
6. **Embedding + indexing** – Embed summaries/excerpts, update vector store and text-search indexes.  
7. **Evaluation loop** – Score outputs for coverage, faithfulness and freshness; queue manual review when thresholds fail.

## Triggering and Orchestration

- **Scheduler**: run as part of the `gpt-creator` automation suite (cron or managed job) checking for documents with `updated_at > last_generated_at`.  
- **On-demand API**: allow manual re-run per `doc_id` for urgent fixes.  
- **Message queue**: optional enhancement—emit `doc.updated` events from ingestion steps to enqueue pipeline jobs.
- **Default CLI integration**: `gpt-creator scan` now invokes the heuristic pipeline so local workflows always produce summaries/excerpts immediately after discovery.

Implementation can live inside a dedicated module `src/lib/doc_pipeline.py` (not yet created) orchestrated via `scripts/run-doc-pipeline.sh`.

## Tooling and Models

| Stage | Tooling | Notes |
|-------|---------|-------|
| Text extraction | Python (`markdown-it`, `beautifulsoup4` for HTML) | Produce clean text + section hierarchy. |
| Tokenization | `tiktoken` (OpenAI) or `tokenizers` (HuggingFace) | Aligns with downstream embedding model. |
| Summaries & abstracts | OpenAI GPT-4.1-mini (default) with fallbacks to `gpt-4o` or local LLM via vLLM | Prompt tuned for bullet key points & constrained length. |
| Keywords | Hybrid: RAKE/KeyBERT for candidates + LLM validation | Ensures domain terminology coverage. |
| Excerpt scoring | Section-level embeddings using OpenAI `text-embedding-3-large`; rank via Maximal Marginal Relevance | Select diverse snippets. |
| Vector store | SQLite-based AnnLite for dev, upgradeable to Qdrant/Weaviate in production | Store references via `embedding_id`. |
| Indexing | SQLite FTS5 or Postgres `tsvector` depending on deployment | Index `summary_*`, `excerpt` content. |
| Workflow engine | Prefect or Dagster lightweight deployment | Handles retries, logging and metrics. |

### Model Configuration

- **Prompt template** stored in `templates/doc_summarize.prompt` with placeholders for title, section overview, token budget.  
- **Max tokens** per summary: 256 (short) / 600 (long).  
- **Temperature**: 0.2 for deterministic outputs.  
- **Seed** where available to ensure repeatability.  
- Cache prompts + responses keyed by (`doc_id`, `source_version`, `prompt_hash`) to avoid re-generation.

## Data Flow Details

### Preprocessing

- Read source text from `source_path` or `staging_path`.  
- Normalize line endings, remove HTML boilerplate, convert tables to text approximations.  
- Derive section headers (Markdown `#`, HTML `<h*>`, AsciiDoc).  
- Persist sections into `documentation_sections` with `order_index`, `byte_*`, `token_*` ranges (implemented via the `doc_catalog.sync_registry` step, which also injects a root node per document for hierarchy reconstruction).

### Summary Generation

1. Build context: document title, purpose, first-level sections list with token counts.  
2. Invoke summarization model to produce:
   - `summary_short`: ≤ 300 characters, single paragraph.  
   - `summary_long`: multi-paragraph abstract summarizing objectives, key components, dependencies.  
   - `key_points`: 3–5 bullet strings (stored as JSON).  
3. Run guard checks:
   - Validate output length and absence of disallowed phrases (`TODO`, `unknown`).  
   - Ensure key points count within bounds.  
4. Store outputs in `documentation_summaries` with `generator_source="llm"` and `source_version`.

### Keyword Extraction

- Candidate generation via RAKE on cleaned text (top 20 phrases).  
- Validate with LLM prompt: keep domain-relevant terms, return ≤ 12 keywords.  
- Deduplicate, lowercase, store in `keywords_json`.  
- Optionally map to controlled vocabulary if available.

### Excerpt Selection

- Split sections into paragraphs / code blocks.  
- Score using combination of:
  - Section importance (depth, heading keywords).  
  - Embedding similarity to summary vectors.  
  - Heuristics (presence of API definitions, configuration tables).  
- Pick top N (default 5) excerpts, ensure token_length ≤ 200 each.  
- Insert into `documentation_excerpts` with justification notes.  
- Persist embeddings separately; store reference IDs.

### Embedding + Indexing

- Compute embeddings for:
  - Document summary (`summary_long`).  
  - Each key point aggregated text.  
  - Each excerpt.  
- Store embeddings in external vector store keyed by `embedding_id`.  
- Update `documentation_index_state` with `surface` values (`"vector"`, `"fts"`, `"summary"`) and timestamps.  
- Refresh text-search index (SQLite FTS5 or Postgres) covering `summary_short`, `summary_long`, `key_points`, `excerpt.content`.
  The concrete developer-facing workflow for both full-text and vector indexing lives in `docs/document-catalog-indexing.md`.

## Evaluation Criteria

| Dimension | Metric | Threshold | Action if Failed |
|-----------|--------|-----------|------------------|
| Faithfulness | QA pairs via automatic hallucination probe (TruthfulQA-style) | ≥ 0.85 | Flag for human review. |
| Coverage | Section coverage ratio (tokens summarized ÷ total tokens) | ≥ 0.6 | Increase context or re-run with extended prompt. |
| Conciseness | Length checks (short ≤ 300 chars, long ≤ 1200 chars) | Hard limit | Truncate / regenerate. |
| Freshness | `last_generated_at` within 1 hour of `documentation.updated_at` | Hard limit | Re-queue job. |
| Keyword quality | Keyword match rate against taxonomy (if defined) | ≥ 0.7 | Regenerate keywords. |
| Excerpt utility | Click-through / usage_score uplift (rolling) | Monitored | Adjust heuristics if low. |

Automate evaluation via scheduled job writing results to a `documentation_quality` table (future work) and surface alerts on failures.

## Operational Considerations

- **Rate limiting**: use concurrency caps per model provider; exponential backoff on 429 errors.  
- **Secrets management**: load API keys via `config/pipeline.env` consumed by Prefect/Dagster runs.  
- **Observability**: log pipeline events using existing `work-on-tasks` schema (`phase=execution`, categories for `summary.generate`, `keywords.generate`, etc.).  
- **Rollback**: retain previous summaries (versioned in `documentation_summaries_history` table—future enhancement) to revert problematic outputs.  
- **Testing**: include integration tests that run pipeline against sample docs in `examples/` and assert summary shape + keyword counts.

## Next Steps

1. Scaffold `doc_pipeline.py` module encapsulating detection, generation and persistence routines.  
2. Create Prefect/Dagster flow definitions and CLI entrypoint for manual reruns.  
3. Implement evaluation job writing metrics to monitoring dashboard.  
4. Integrate with CI to smoke-test summary generation on representative docs before release.

The detailed validation and monitoring playbook that underpins these steps is documented in `docs/document-catalog-monitoring.md`.
