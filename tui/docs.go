package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
)

type docFile struct {
	DocType   string
	RelPath   string
	Source    string
	ModTime   time.Time
	Size      int64
	Name      string
	IsInitial bool
}

func docHistoryItems(project *discoveredProject) []featureItemDefinition {
	if project == nil {
		return nil
	}
	filesByType := gatherDocFiles(project.Path)
	if len(filesByType) == 0 {
		return nil
	}

	var items []featureItemDefinition
	docOrder := []string{"pdr", "sds", "rfp"}
	for _, docType := range docOrder {
		files := filesByType[docType]
		if len(files) == 0 {
			continue
		}
		sort.Slice(files, func(i, j int) bool {
			if files[i].ModTime.Equal(files[j].ModTime) {
				return files[i].RelPath < files[j].RelPath
			}
			return files[i].ModTime.After(files[j].ModTime)
		})
		for _, file := range files {
			title := buildDocTitle(docType, file)
			desc := buildDocDescription(file)
			meta := map[string]string{
				"docType":    docType,
				"docRelPath": file.RelPath,
				"docSource":  file.Source,
				"docModTime": file.ModTime.UTC().Format(time.RFC3339),
				"docSize":    fmt.Sprintf("%d", file.Size),
			}
			if file.IsInitial {
				meta["docInitial"] = "1"
			}
			items = append(items, featureItemDefinition{
				Key:             fmt.Sprintf("doc-%s-%s", docType, sanitizeDocKey(file.RelPath)),
				Title:           title,
				Desc:            desc,
				PreviewKey:      "docfile:" + file.RelPath,
				Meta:            meta,
				ProjectRequired: true,
			})
		}
		if diff := buildDocDiffItem(docType, files); diff.Key != "" {
			items = append(items, diff)
		}
	}
	return items
}

func gatherDocFiles(root string) map[string][]docFile {
	result := make(map[string][]docFile)
	if strings.TrimSpace(root) == "" {
		return result
	}
	configs := []struct {
		docType string
		dirs    []string
		match   string
	}{
		{
			docType: "pdr",
			dirs: []string{
				filepath.Join(".gpt-creator", "staging", "docs"),
				filepath.Join(".gpt-creator", "staging", "plan", "pdr"),
			},
			match: "pdr",
		},
		{
			docType: "sds",
			dirs: []string{
				filepath.Join(".gpt-creator", "staging", "docs"),
				filepath.Join(".gpt-creator", "staging", "plan", "sds"),
			},
			match: "sds",
		},
		{
			docType: "rfp",
			dirs: []string{
				filepath.Join(".gpt-creator", "staging", "inputs"),
				filepath.Join(".gpt-creator", "staging", "docs"),
			},
			match: "rfp",
		},
	}

	seen := make(map[string]struct{})
	for _, cfg := range configs {
		for _, relDir := range cfg.dirs {
			absDir := filepath.Join(root, relDir)
			entries, err := os.ReadDir(absDir)
			if err != nil {
				continue
			}
			for _, entry := range entries {
				if entry.IsDir() {
					continue
				}
				nameLower := strings.ToLower(entry.Name())
				if !strings.Contains(nameLower, cfg.match) {
					continue
				}
				ext := strings.ToLower(filepath.Ext(nameLower))
				if ext != ".md" && ext != ".markdown" && ext != ".txt" {
					continue
				}
				info, err := entry.Info()
				if err != nil {
					continue
				}
				relPath := filepath.ToSlash(filepath.Join(relDir, entry.Name()))
				if _, ok := seen[relPath]; ok {
					continue
				}
				seen[relPath] = struct{}{}
				result[cfg.docType] = append(result[cfg.docType], docFile{
					DocType:   cfg.docType,
					RelPath:   relPath,
					Source:    filepath.ToSlash(relDir),
					ModTime:   info.ModTime(),
					Size:      info.Size(),
					Name:      entry.Name(),
					IsInitial: strings.Contains(nameLower, "initial"),
				})
			}
		}
	}
	return result
}

func buildDocTitle(docType string, file docFile) string {
	label := strings.ToUpper(docType)
	if file.IsInitial {
		label += " (baseline)"
	}
	return fmt.Sprintf("%s • %s", label, trimDocRel(file.RelPath))
}

func buildDocDescription(file docFile) string {
	rel := trimDocRel(file.RelPath)
	return fmt.Sprintf("%s • %s • %s", rel, formatRelativeTime(file.ModTime), formatByteSize(file.Size))
}

func sanitizeDocKey(relPath string) string {
	trimmed := strings.Trim(relPath, "./")
	if trimmed == "" {
		return "doc"
	}
	var builder strings.Builder
	for _, r := range trimmed {
		switch {
		case unicode.IsLetter(r), unicode.IsDigit(r):
			builder.WriteRune(unicode.ToLower(r))
		default:
			builder.WriteByte('-')
		}
	}
	key := strings.Trim(builder.String(), "-")
	if key == "" {
		return "doc"
	}
	return key
}

func trimDocRel(rel string) string {
	trimmed := strings.TrimPrefix(rel, ".gpt-creator/")
	trimmed = strings.TrimPrefix(trimmed, "./")
	return trimmed
}

func formatByteSize(size int64) string {
	const (
		kb = 1024
		mb = kb * 1024
		gb = mb * 1024
	)
	switch {
	case size >= gb:
		return fmt.Sprintf("%.1f GB", float64(size)/float64(1024*1024*1024))
	case size >= mb:
		return fmt.Sprintf("%.1f MB", float64(size)/float64(1024*1024))
	case size >= kb:
		return fmt.Sprintf("%.1f KB", float64(size)/float64(1024))
	default:
		return fmt.Sprintf("%d B", size)
	}
}

func docPriority(path string) int {
	path = strings.ReplaceAll(path, "\\", "/")
	switch {
	case strings.Contains(path, "staging/docs"):
		return 0
	case strings.Contains(path, "staging/plan"):
		return 1
	case strings.Contains(path, "staging/inputs"):
		return 2
	default:
		return 3
	}
}

func betterHead(candidate, current docFile, hasCurrent bool) bool {
	if !hasCurrent {
		return true
	}
	cp := docPriority(candidate.RelPath)
	curp := docPriority(current.RelPath)
	if cp != curp {
		return cp < curp
	}
	if !candidate.ModTime.Equal(current.ModTime) {
		return candidate.ModTime.After(current.ModTime)
	}
	return candidate.RelPath < current.RelPath
}

func betterBaseline(candidate, current docFile, hasCurrent bool) bool {
	if !hasCurrent {
		return true
	}
	cp := docPriority(candidate.RelPath)
	curp := docPriority(current.RelPath)
	if cp != curp {
		return cp < curp
	}
	if !candidate.ModTime.Equal(current.ModTime) {
		return candidate.ModTime.Before(current.ModTime)
	}
	return candidate.RelPath < current.RelPath
}

func docDiffPair(files []docFile) (docFile, docFile, bool) {
	var head docFile
	var base docFile
	headOk := false
	baseOk := false
	for _, file := range files {
		if file.IsInitial {
			if betterBaseline(file, base, baseOk) {
				base = file
				baseOk = true
			}
			continue
		}
		if betterHead(file, head, headOk) {
			head = file
			headOk = true
		}
	}
	if !headOk || !baseOk {
		return docFile{}, docFile{}, false
	}
	return head, base, true
}

func buildDocDiffItem(docType string, files []docFile) featureItemDefinition {
	if docType == "rfp" {
		return featureItemDefinition{}
	}
	head, base, ok := docDiffPair(files)
	if !ok {
		return featureItemDefinition{}
	}
	meta := map[string]string{
		"docType":        docType,
		"docDiffHead":    head.RelPath,
		"docDiffBase":    base.RelPath,
		"docRelPath":     head.RelPath,
		"docSource":      head.Source,
		"docModTime":     head.ModTime.UTC().Format(time.RFC3339),
		"docSize":        fmt.Sprintf("%d", head.Size),
		"docDiffLabel":   trimDocRel(head.RelPath),
		"docBaseline":    trimDocRel(base.RelPath),
		"docBaselineRel": base.RelPath,
	}
	title := fmt.Sprintf("%s Δ vs baseline", strings.ToUpper(docType))
	desc := fmt.Sprintf("%s ↔ %s", trimDocRel(head.RelPath), trimDocRel(base.RelPath))
	return featureItemDefinition{
		Key:             fmt.Sprintf("doc-diff-%s-%s", docType, sanitizeDocKey(head.RelPath)),
		Title:           title,
		Desc:            desc,
		PreviewKey:      "docdiff:" + docType,
		Meta:            meta,
		ProjectRequired: true,
	}
}

func primaryDocPath(project *discoveredProject, docType string) string {
	if project == nil {
		return ""
	}
	files := gatherDocFiles(project.Path)[docType]
	var selected docFile
	ok := false
	for _, file := range files {
		if file.IsInitial {
			continue
		}
		if betterHead(file, selected, ok) {
			selected = file
			ok = true
		}
	}
	if ok {
		return selected.RelPath
	}
	if len(files) > 0 {
		return files[0].RelPath
	}
	return ""
}

func baselineDocPath(project *discoveredProject, docType string) string {
	if project == nil {
		return ""
	}
	files := gatherDocFiles(project.Path)[docType]
	var selected docFile
	ok := false
	for _, file := range files {
		if !file.IsInitial {
			continue
		}
		if betterBaseline(file, selected, ok) {
			selected = file
			ok = true
		}
	}
	if ok {
		return selected.RelPath
	}
	return ""
}

func renderDocsPreview(project *discoveredProject, item featureItemDefinition) string {
	if item.Meta == nil {
		return "Generate documentation artifacts (PDR/SDS) using Codex context.\n"
	}
	if action := item.Meta["docsAction"]; action == "attach-rfp" {
		return "Attach an external RFP into .gpt-creator/staging/inputs/ so `create-pdr` can synthesize a Product Requirements Document.\nPress Enter to choose a file path; the TUI copies it into staging.\n"
	}
	var builder strings.Builder
	if rel := item.Meta["docRelPath"]; rel != "" {
		builder.WriteString("Preview staged documentation artifacts.\n")
		builder.WriteString(fmt.Sprintf("Path: %s\n", trimDocRel(rel)))
		if modStr := item.Meta["docModTime"]; modStr != "" {
			if ts, err := time.Parse(time.RFC3339, modStr); err == nil {
				builder.WriteString(fmt.Sprintf("Updated: %s (%s ago)\n", ts.Format(time.RFC822), formatRelativeTime(ts)))
			}
		}
		if sizeStr := item.Meta["docSize"]; sizeStr != "" {
			if sz, err := strconv.ParseInt(sizeStr, 10, 64); err == nil {
				builder.WriteString(fmt.Sprintf("Size: %s\n", formatByteSize(sz)))
			}
		}
		builder.WriteString("Press `o` to open in your editor, or Enter to focus the glamour preview.\n")
		return builder.String()
	}
	if head := item.Meta["docDiffHead"]; head != "" {
		builder.WriteString("Compare the current document against its baseline snapshot.\n")
		builder.WriteString(fmt.Sprintf("Current: %s\n", trimDocRel(head)))
		if base := item.Meta["docDiffBase"]; base != "" {
			builder.WriteString(fmt.Sprintf("Baseline: %s\n", trimDocRel(base)))
		}
		builder.WriteString("Preview shows a unified diff with additions and removals highlighted.\nPress `o` to edit the current document in your editor.\n")
		return builder.String()
	}
	return "Generate documentation artifacts (PDR/SDS) using Codex context.\n"
}
