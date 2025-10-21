package main

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

type workspaceStore struct {
	db   *sql.DB
	path string
}

func openWorkspaceStore() (*workspaceStore, error) {
	dir := resolveConfigDir()
	if err := ensureDir(dir); err != nil {
		return nil, err
	}
	sqlitePath := filepath.Join(dir, "workspaces.sqlite")
	db, err := sql.Open("sqlite", sqlitePath)
	if err != nil {
		return nil, err
	}
	if err := migrateWorkspaceStore(db); err != nil {
		_ = db.Close()
		return nil, err
	}
	return &workspaceStore{db: db, path: sqlitePath}, nil
}

func migrateWorkspaceStore(db *sql.DB) error {
	statements := []string{
		`PRAGMA journal_mode=WAL;`,
		`CREATE TABLE IF NOT EXISTS workspaces (
			path TEXT PRIMARY KEY,
			label TEXT NOT NULL DEFAULT '',
			added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
		);`,
	}
	for _, stmt := range statements {
		if _, err := db.Exec(stmt); err != nil {
			return fmt.Errorf("workspace store migration failed: %w", err)
		}
	}
	return nil
}

func (s *workspaceStore) Close() error {
	if s == nil || s.db == nil {
		return nil
	}
	return s.db.Close()
}

func (s *workspaceStore) List() ([]workspaceRoot, error) {
	if s == nil || s.db == nil {
		return nil, nil
	}
	rows, err := s.db.Query(`SELECT path, COALESCE(NULLIF(label, ''), path) FROM workspaces ORDER BY path ASC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var roots []workspaceRoot
	for rows.Next() {
		var (
			path  string
			label string
		)
		if err := rows.Scan(&path, &label); err != nil {
			return nil, err
		}
		clean := filepath.Clean(path)
		if clean == "" {
			continue
		}
		root := workspaceRoot{
			Label: labelForPath(clean),
			Path:  clean,
		}
		roots = append(roots, root)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return roots, nil
}

func (s *workspaceStore) Add(path string) error {
	if s == nil || s.db == nil {
		return nil
	}
	clean := filepath.Clean(strings.TrimSpace(path))
	if clean == "" {
		return nil
	}
	label := labelForPath(clean)
	_, err := s.db.Exec(`INSERT INTO workspaces (path, label) VALUES (?, ?)
		ON CONFLICT(path) DO UPDATE SET label = excluded.label`, clean, label)
	return err
}

func (s *workspaceStore) Remove(path string) error {
	if s == nil || s.db == nil {
		return nil
	}
	clean := filepath.Clean(strings.TrimSpace(path))
	if clean == "" {
		return nil
	}
	_, err := s.db.Exec(`DELETE FROM workspaces WHERE path = ?`, clean)
	return err
}

func (s *workspaceStore) RemoveAll(paths []string) error {
	if s == nil || s.db == nil {
		return nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	stmt, err := tx.Prepare(`DELETE FROM workspaces WHERE path = ?`)
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	defer stmt.Close()
	for _, path := range paths {
		clean := filepath.Clean(strings.TrimSpace(path))
		if clean == "" {
			continue
		}
		if _, err := stmt.Exec(clean); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

func ensureDir(path string) error {
	return os.MkdirAll(path, 0o755)
}
