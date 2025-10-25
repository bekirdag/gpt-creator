# Documentation Catalog Validation & Monitoring Plan

This plan keeps derived assets (summaries, excerpts, sections, indexes, embeddings) aligned with their source documents. It combines automated validation, scheduled monitoring, and alerting hooks so regressions are caught before they impact agent retrieval.

## Objectives

- Detect when catalog metadata or derived artifacts become stale or inconsistent with source content.  
- Surface issues with latency, hallucinations, or indexing gaps before they affect users.  
- Provide actionable dashboards and alerts so operators can remediate quickly.  
- Integrate with existing catalog build and indexing pipelines without significant overhead.

## Validation Checks

| Category | Check | Description | Trigger |
|----------|-------|-------------|---------|
| Freshness | `documentation.updated_at` vs `documentation_summaries.last_generated_at` | Fails whenever the summary is older than 1 hour relative to source update. | Nightly job & on-demand |
| ToC Sync | Section coverage | Compare `documentation_sections` byte/token spans against actual document length; flag gaps or overlaps. | Nightly |
| Excerpt Integrity | Token length accuracy | Re-tokenise sample excerpts and ensure stored `token_length` differs by ≤10%. | Nightly |
| Summary Quality | Faithfulness QA | Run hallucination probes (LLM-based fact checks) on a rotating 20% sample; fail if score < 0.85. | Nightly |
| Keyword Drift | Keyword taxonomy match | Compare generated keywords against controlled vocabulary; alert if match rate < 0.7. | Nightly |
| Index Freshness | `documentation_index_state.indexed_at` | Flag any document where `indexed_at` lags `updated_at` by > 1 hour for `fts` or `vector`. | After indexing run |
| Embedding Cohesion | Embedding hash mismatch | Ensure vector store metadata `text_hash` equals current summary/excerpt hash; warn if mismatch. | After indexing run |
| Retrieval Budget | Token plan overrun | Run `DocumentRetriever.plan` on hot documents and confirm default budget (2,000 tokens) satisfies ≥ 95% of cases. | Nightly |

## Monitoring Metrics

Record metrics in `documentation_quality` (future table) or an external time-series store:

- `summaries_stale_count`, `sections_stale_count`, `index_vector_stale_count`, `index_fts_stale_count`.  
- `summary_faithfulness_score`, `keyword_match_rate`, `excerpt_token_delta_pct`.  
- `retrieval_budget_satisfaction` (percentage).  
- Latency timers: `summary_regen_latency_ms`, `index_rebuild_latency_ms`.  
- `pipeline_failures_total` with labels (`stage`, `doc_type`).

## Pipeline Integration

1. **Catalog build (`doc_catalog.py`)**  
   - Emit `documentation.updated_at` and `documentation.sha256`.  
   - Queue validation job for documents touched in the run.
2. **Summarisation pipeline (`doc_pipeline.py`, future)**  
   - After summaries/excerpts regenerate, mark the relevant validation entries as pending QA.  
   - Publish check results (faithfulness, keyword match) to `documentation_quality`.
3. **Indexer (`DocIndexer`)**  
   - Update `documentation_index_state` for `fts` and `vector`.  
   - If index lag exceeds threshold, raise alert immediately.
4. **Retriever smoke tests**  
   - Nightly job runs `DocumentRetriever.plan` for top N documents (by `usage_score`) and persists token usage stats.

## Alerting Rules

- **Critical**  
  - `summaries_stale_count > 0` for `sensitivity=restricted` documents.  
  - `index_vector_stale_count > 10` across catalog.  
  - `pipeline_failures_total` increases for two consecutive runs.
- **Warning**  
  - `retrieval_budget_satisfaction < 0.95`.  
  - `summary_faithfulness_score < 0.9` (rolling average).  
  - `excerpt_token_delta_pct > 0.1`.
- Alerts are dispatched via the platform’s incident channel (PagerDuty/Webhook) and mirrored in chat for visibility.

## Dashboards

Create a “Documentation Catalog Health” dashboard with:

- Freshness heatmap (documents vs surfaces).  
- Trend lines for faithfulness, keyword match, retrieval satisfaction.  
- Recent pipeline latencies and failure counts.  
- Table of top offending documents with links to regeneration commands.

## Remediation Playbook

1. **Stale summaries/indexes**  
   - Run `scripts/run-doc-pipeline.sh --doc DOC-ID`.  
   - Re-run `DocIndexer` for affected doc IDs.  
   - Confirm `documentation_index_state` updates successfully.
2. **Quality failures (faithfulness/keywords)**  
   - Trigger manual review workflow; edit summary or keywords as needed.  
   - Re-ingest using pipeline with `generator_source="human"` override.  
   - Mark validation entry as resolved once checks pass.
3. **Budget overrun**  
   - Inspect `DocumentRetriever.plan` output to identify oversized excerpts.  
   - Either reduce `max_excerpts`, trim excerpts, or raise default budget following approval.

## Implementation Notes

- Validation scripts live under `scripts/validate-documentation/` (to be created).  
- Tests should run in CI on a subset of sample docs to prevent regressions.  
- Store validation results as JSON artifacts in `logs/document-validation/` for audit purposes.  
- Integrate with the existing `work-on-tasks` logging schema using `phase="validation"` events and `category="doc.validation.*"`.
