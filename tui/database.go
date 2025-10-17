package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type databaseDumpFile struct {
	Kind    string
	Path    string
	RelPath string
	ModTime time.Time
	Size    int64
}

type databaseDumpInfo struct {
	Found      bool
	Dir        string
	DirRel     string
	Files      []databaseDumpFile
	Latest     time.Time
	DirPresent bool
}

func gatherDatabaseDumpInfo(root string) databaseDumpInfo {
	info := databaseDumpInfo{}
	root = strings.TrimSpace(root)
	if root == "" {
		return info
	}

	candidates := []string{
		filepath.Join(".gpt-creator", "staging", "db-dump"),
		filepath.Join(".gpt-creator", "staging", "db_dump"),
		filepath.Join(".gpt-creator", "staging", "plan", "create-db-dump", "sql"),
		filepath.Join(".gpt-creator", "staging", "db"),
		"db",
	}

	bestScore := time.Time{}
	for _, relDir := range candidates {
		absDir := filepath.Join(root, relDir)
		files := collectDumpFiles(absDir, relDir)
		if len(files) == 0 {
			if info.Dir == "" {
				if stat, err := os.Stat(absDir); err == nil && stat.IsDir() {
					info.Dir = absDir
					info.DirRel = filepath.ToSlash(relDir)
					info.DirPresent = true
				}
			}
			continue
		}
		latest := latestModTime(files)
		if !info.Found || latest.After(bestScore) {
			bestScore = latest
			info = databaseDumpInfo{
				Found:      true,
				Dir:        absDir,
				DirRel:     filepath.ToSlash(relDir),
				Files:      sortDumpFiles(files),
				Latest:     latest,
				DirPresent: true,
			}
		}
	}

	return info
}

func collectDumpFiles(absDir, relDir string) []databaseDumpFile {
	names := map[string][]string{
		"schema": {"schema.sql"},
		"seed":   {"seed.sql"},
	}
	var files []databaseDumpFile

	for kind, candidates := range names {
		for _, name := range candidates {
			full := filepath.Join(absDir, name)
			stat, err := os.Stat(full)
			if err != nil || stat.IsDir() {
				continue
			}
			files = append(files, databaseDumpFile{
				Kind:    kind,
				Path:    full,
				RelPath: filepath.ToSlash(filepath.Join(relDir, name)),
				ModTime: stat.ModTime(),
				Size:    stat.Size(),
			})
			break
		}
	}
	return files
}

func sortDumpFiles(files []databaseDumpFile) []databaseDumpFile {
	out := append([]databaseDumpFile(nil), files...)
	order := map[string]int{
		"schema": 0,
		"seed":   1,
	}
	sort.Slice(out, func(i, j int) bool {
		left, right := order[out[i].Kind], order[out[j].Kind]
		if left != right {
			return left < right
		}
		if !out[i].ModTime.Equal(out[j].ModTime) {
			return out[i].ModTime.After(out[j].ModTime)
		}
		return out[i].RelPath < out[j].RelPath
	})
	return out
}

func latestModTime(files []databaseDumpFile) time.Time {
	var latest time.Time
	for _, file := range files {
		if file.ModTime.After(latest) {
			latest = file.ModTime
		}
	}
	return latest
}

func renderDatabaseDumpPreview(project *discoveredProject, item featureItemDefinition) string {
	if project == nil {
		return ""
	}

	info := gatherDatabaseDumpInfo(project.Path)
	if !info.Found {
		if info.DirPresent && strings.TrimSpace(info.DirRel) != "" {
			return fmt.Sprintf("No schema.sql or seed.sql found under %s.\nRun `create-db-dump` to generate the database export.\n", trimDumpRel(info.DirRel))
		}
		return "No database dump detected.\nRun `create-db-dump` to generate schema.sql and seed.sql under staging/db-dump/.\n"
	}

	var b strings.Builder
	dirLabel := trimDumpRel(info.DirRel)
	if dirLabel != "" {
		b.WriteString(fmt.Sprintf("Directory: %s\n", dirLabel))
	}
	b.WriteString(fmt.Sprintf("Last update: %s (%s ago)\n", info.Latest.Format(time.RFC822), formatRelativeTime(info.Latest)))

	for _, file := range info.Files {
		b.WriteString("\n")
		b.WriteString(renderDumpFilePreview(file))
	}

	if len(info.Files) > 0 {
		hasSchema := false
		hasSeed := false
		for _, file := range info.Files {
			switch file.Kind {
			case "schema":
				hasSchema = true
			case "seed":
				hasSeed = true
			}
		}
		b.WriteString("\n")
		switch {
		case hasSchema && hasSeed:
			b.WriteString("Press o to open schema.sql • Shift+O to open seed.sql.\n")
		case hasSchema:
			b.WriteString("Press o to open schema.sql in your editor.\n")
		case hasSeed:
			b.WriteString("Press o to open seed.sql in your editor.\n")
		}
	}

	return b.String()
}

func renderDumpFilePreview(file databaseDumpFile) string {
	name := strings.TrimPrefix(filepath.Base(file.RelPath), "/")
	header := fmt.Sprintf("%s\nUpdated: %s (%s ago)\nSize: %s\nPath: %s\n",
		name,
		file.ModTime.Format(time.RFC822),
		formatRelativeTime(file.ModTime),
		formatByteSize(file.Size),
		trimDumpRel(file.RelPath),
	)

	content := readFileLimited(file.Path, maxPreviewBytes, maxPreviewLines)
	if strings.TrimSpace(content) == "" {
		return header + "\n<empty file>\n"
	}
	return header + "\n" + content
}

func trimDumpRel(rel string) string {
	trimmed := strings.TrimPrefix(rel, ".gpt-creator/")
	trimmed = strings.TrimPrefix(trimmed, "./")
	return filepath.ToSlash(trimmed)
}
