-- Documentation catalog schema extensions.
-- Mirrors the tables created in src/lib/doc_registry.py::DocRegistry.ensure_schema.

CREATE TABLE IF NOT EXISTS documentation_summaries (
  doc_id TEXT PRIMARY KEY,
  summary_short TEXT,
  summary_long TEXT,
  key_points_json TEXT,
  keywords_json TEXT,
  embedding_id TEXT,
  last_generated_at TEXT,
  generator_source TEXT,
  source_version TEXT,
  FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS documentation_sections (
  section_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  parent_section_id TEXT,
  order_index INTEGER NOT NULL,
  title TEXT NOT NULL,
  anchor TEXT,
  byte_start INTEGER,
  byte_end INTEGER,
  token_start INTEGER,
  token_end INTEGER,
  summary TEXT,
  last_synced_at TEXT,
  source_version TEXT,
  FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE,
  FOREIGN KEY(parent_section_id) REFERENCES documentation_sections(section_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documentation_sections_doc ON documentation_sections(doc_id);
CREATE INDEX IF NOT EXISTS idx_documentation_sections_parent ON documentation_sections(parent_section_id);

CREATE TABLE IF NOT EXISTS documentation_excerpts (
  excerpt_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  section_id TEXT,
  content TEXT NOT NULL,
  justification TEXT,
  token_length INTEGER,
  embedding_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  source_version TEXT,
  FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE,
  FOREIGN KEY(section_id) REFERENCES documentation_sections(section_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_documentation_excerpts_doc ON documentation_excerpts(doc_id);
CREATE INDEX IF NOT EXISTS idx_documentation_excerpts_section ON documentation_excerpts(section_id);

CREATE TABLE IF NOT EXISTS documentation_index_state (
  doc_id TEXT NOT NULL,
  surface TEXT NOT NULL,
  indexed_at TEXT,
  status TEXT,
  usage_score REAL,
  metadata_json TEXT,
  PRIMARY KEY (doc_id, surface),
  FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documentation_index_state_surface ON documentation_index_state(surface);
