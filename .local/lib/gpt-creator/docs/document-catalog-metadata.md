# Document Catalog Metadata Requirements

This document establishes the canonical metadata requirements for the documentation catalog. The goal is to give the AI agent targeted entry points into relevant material while keeping token usage predictable. Each catalog entry MUST capture identity, provenance, derived summaries and abstracts, and a structured table of contents so the agent can narrow retrieval before loading full text.

## Metadata Model Overview

The catalog is composed of four complementary layers:

1. **Document record** – single row per source document with canonical identity, provenance and lifecycle flags.  
2. **Derived content** – summaries, abstracts, keywords and excerpt snippets generated from the underlying text.  
3. **Table of contents (ToC)** – hierarchical section records that map logical structure to byte and token ranges.  
4. **Indexing surfaces** – embeddings, search indexes and freshness metadata that let retrieval stay synchronized with source content.

All layers MUST be joinable via stable identifiers (`document_id`, `section_id`).

## Physical Tables

| Layer | Table | Purpose |
|-------|-------|---------|
| Document record | `documentation` | Canonical registry row for each document (existing table). |
| Derived content | `documentation_summaries` | Stores summaries, abstracts, keywords and generator metadata. |
| Derived content | `documentation_excerpts` | Holds curated snippets tied to documents and sections. |
| Table of contents | `documentation_sections` | Represents hierarchical section structure with byte/token ranges. |
| Indexing surfaces | `documentation_index_state` | Tracks per-surface indexing status, timestamps and usage signals. |

The full SQL definition lives in `docs/document-catalog-schema.sql`. The automated pipeline that keeps these tables populated is described in `docs/document-catalog-pipeline.md`, the indexing stack is detailed in `docs/document-catalog-indexing.md`, and the validation/monitoring plan resides in `docs/document-catalog-monitoring.md`.

## Document Record

Each document in the catalog MUST expose the following fields:

| Field | Type | Requirement |
|-------|------|-------------|
| `document_id` | string (UUID) | Primary key used across all dependent tables. |
| `title` | string | Human-readable title as it appears in the source system. |
| `source_type` | enum (`manual`, `spec`, `api_ref`, etc.) | Classifier for routing ingestion and retrieval heuristics. |
| `source_uri` | string | Canonical locator (git path, URL, or knowledge base id). |
| `version` | string | Semantic or git-based revision identifier. |
| `language` | string | BCP-47 language tag. |
| `created_at` / `updated_at` | timestamp | Track provenance and trigger downstream refresh. |
| `status` | enum (`draft`, `active`, `deprecated`) | Drives retrieval eligibility. |
| `tokens_estimate` | integer | Approximate token count for the full document. |
| `checksum` | string | Content hash to detect drift between text and metadata. |

### Optional but Recommended

| Field | Type | Requirement |
|-------|------|-------------|
| `tags` | string[] | Free-form facets (e.g., `["tui", "logging", "architecture"]`). |
| `owners` | string[] | Responsible teams or individuals for escalation. |
| `sensitivity` | enum (`public`, `internal`, `restricted`) | Controls exposure in responses. |
| `retention_policy` | string | Links to archival or purge requirements. |

## Derived Content Requirements

Derived content enables the agent to scope results before loading full text. Store the following per document:

| Field | Type | Requirement |
|-------|------|-------------|
| `summary_short` | string (≤ 300 chars) | Concise synopsis optimized for system prompts. |
| `summary_long` | text | Richer abstract (300–1200 chars) for human-facing previews. |
| `key_points` | string[] | Bulleted highlights emphasising actionable knowledge. |
| `keywords` | string[] | Search tokens generated from taxonomy or NLP pipeline. |
| `embedding_id` | string | Reference into vector store entry representing the summary text. |
| `last_generated_at` | timestamp | Supports freshness checks against source version. |
| `generator_source` | enum (`llm`, `human`, `import`) | Provenance and quality tracking. |

### Excerpts and Snippets

To support targeted retrieval, maintain an excerpt table keyed by `document_id` and `excerpt_id`:

| Field | Type | Requirement |
|-------|------|-------------|
| `excerpt_id` | string (UUID) | Primary key per excerpt. |
| `section_id` | string (nullable) | Links excerpt to a ToC node when applicable. |
| `content` | text | Extracted paragraph or code block. |
| `justification` | string | Why the excerpt is important (e.g., `"defines logging schema"`). |
| `token_length` | integer | Precomputed token count of the excerpt. |
| `embedding_id` | string | Vector reference of the excerpt content. |

## Table of Contents Structure

The ToC is modeled as a separate table (`document_sections`) containing one row per logical section. Requirements:

| Field | Type | Requirement |
|-------|------|-------------|
| `section_id` | string (UUID) | Primary key. |
| `document_id` | string | Foreign key to document record. |
| `parent_section_id` | string (nullable) | Enables hierarchical nesting. |
| `order_index` | integer | Ordering among siblings. |
| `title` | string | Section heading as rendered. |
| `anchor` | string | Slug or anchor ID for deep links. |
| `byte_range` | `[start, end]` integers | Byte offsets within the source text. |
| `token_range` | `[start, end]` integers | Token offsets for precise chunking. |
| `summary` | string (≤ 200 chars) | Optional per-section synopsis. |
| `last_synced_at` | timestamp | Refresh tracking relative to source document hash. |

The ToC MUST cover the entire document without overlapping ranges and SHOULD include `depth` information (implicit via parent chain) so clients can reconstruct the hierarchy.

Each document entry includes a synthetic root section (anchor `root`) that spans the entire document; all top-level headings reference this node as their parent so consumers can rebuild the tree without special cases.

## Indexing and Retrieval Surfaces

To keep search consistent across backends:

- Maintain a text search index (e.g., Postgres `tsvector`) over `title`, `summary_short`, `summary_long`, and excerpt content.  
- Persist vector embeddings for documents, sections and excerpts; refer to them through `embedding_id` rather than inlining base64 blobs.  
- Track `indexed_at` timestamps per surface (text search, vector store) to confirm freshness before serving results.  
- Store `usage_score` (rolling counter updated from analytics) to prioritize high-traffic documents in retrieval heuristics.

## Data Quality and Governance

- Introduce `quality_grade` (`high`, `medium`, `needs_review`) and `reviewed_by` fields to the document record.  
- Each derived artifact MUST include `source_version` so stale summaries can be detected when `version` or `checksum` changes.  
- Validation jobs SHOULD compare `tokens_estimate` with actual token counts periodically to catch drift.  
- Changes to `status` or `sensitivity` MUST trigger downstream processes (e.g., purge vector embeddings for deprecated documents).

## Next Steps

- Finalize table definitions and migration scripts reflecting the required fields.  
- Wire ingestion pipeline to populate derived content and ToC structures.  
- Add monitoring dashboards to track freshness (`last_generated_at`, `last_synced_at`, `indexed_at`) versus source updates.  
- Document governance workflows for regenerating summaries after manual edits or automated imports.
