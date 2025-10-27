PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documentation (
  doc_id         TEXT PRIMARY KEY,
  doc_type       TEXT NOT NULL,
  source_path    TEXT,
  staging_path   TEXT,
  rel_path       TEXT,
  file_name      TEXT,
  file_ext       TEXT,
  size_bytes     INTEGER,
  mtime_ns       INTEGER,
  sha256         TEXT,
  title          TEXT,
  tags_json      TEXT,
  metadata_json  TEXT,
  discovered_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status         TEXT NOT NULL DEFAULT 'active',
  change_count   INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS documentation_doc_id_idx
  ON documentation(doc_id);

CREATE TABLE IF NOT EXISTS documentation_changes (
  change_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id        TEXT NOT NULL,
  change_type   TEXT NOT NULL,
  sha256        TEXT,
  size_bytes    INTEGER,
  mtime_ns      INTEGER,
  description   TEXT,
  context       TEXT,
  recorded_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS documentation_search
USING fts5(doc_id, surface, tokenize = 'unicode61');

INSERT INTO documentation_search(doc_id, surface)
SELECT doc_id, COALESCE(title, rel_path, file_name, source_path, doc_id)
FROM documentation
WHERE NOT EXISTS (SELECT 1 FROM documentation_search LIMIT 1);
