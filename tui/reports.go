package main

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"gopkg.in/yaml.v3"
)

type reportEntry struct {
	Key        string
	Slug       string
	Title      string
	Summary    string
	Type       string
	Priority   string
	Status     string
	Reporter   string
	Timestamp  time.Time
	RelPath    string
	AbsPath    string
	Format     string
	Source     string
	Definition string
	Popularity int
	Likes      int
	Comments   int
	Size       int64
}

func gatherProjectReports(projectPath string) ([]reportEntry, error) {
	var all []reportEntry

	issueDir := filepath.Join(projectPath, ".gpt-creator", "logs", "issue-reports")
	if entries, err := loadIssueReports(issueDir, projectPath); err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
	} else {
		all = append(all, entries...)
	}

	reportDir := filepath.Join(projectPath, "reports")
	if entries, err := collectReportFiles(reportDir, projectPath, "report", reportFileTypeFromPath); err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
	} else {
		all = append(all, entries...)
	}

	verifyDir := filepath.Join(projectPath, ".gpt-creator", "staging", "verify")
	if entries, err := collectReportFiles(verifyDir, projectPath, "verify", verifyReportTypeFromPath); err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
	} else {
		all = append(all, entries...)
	}

	sort.SliceStable(all, func(i, j int) bool {
		it := all[i].Timestamp
		jt := all[j].Timestamp
		switch {
		case it.IsZero() && !jt.IsZero():
			return false
		case !it.IsZero() && jt.IsZero():
			return true
		case !it.Equal(jt):
			return it.After(jt)
		default:
			return all[i].RelPath < all[j].RelPath
		}
	})
	return all, nil
}

func loadIssueReports(dir, projectPath string) ([]reportEntry, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, nil
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	var reports []reportEntry
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		lower := strings.ToLower(name)
		if !strings.HasSuffix(lower, ".yml") && !strings.HasSuffix(lower, ".yaml") {
			continue
		}
		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		report, err := parseIssueReport(projectPath, path, info, data)
		if err != nil {
			continue
		}
		reports = append(reports, report)
	}
	return reports, nil
}

func parseIssueReport(projectPath, path string, info fs.FileInfo, data []byte) (reportEntry, error) {
	var payload map[string]any
	if err := yaml.Unmarshal(data, &payload); err != nil {
		return reportEntry{}, err
	}
	entry := reportEntry{
		AbsPath: path,
		Format:  "YAML",
		Source:  "issue",
		Size:    info.Size(),
	}
	base := filepath.Base(path)
	entry.Slug = strings.TrimSuffix(strings.TrimSuffix(base, ".yaml"), ".yml")
	entry.Key = "issue:" + entry.Slug
	entry.RelPath = relativePath(projectPath, path)

	entry.Title = stringValue(payload["summary"])
	entry.Summary = entry.Title
	entry.Priority = stringValue(payload["priority"])
	entry.Type = stringValue(payload["type"])
	entry.Definition = stringValue(payload["definition"])
	if entry.Title == "" {
		entry.Title = entry.Slug
	}
	entry.Timestamp = parseReportTime(
		stringValue(payload["timestamp"]),
	)
	entry.Reporter = stringValue(payload["reporter"])

	metadata := mapValue(payload["metadata"])
	if entry.Reporter == "" {
		entry.Reporter = stringValue(metadata["reporter"])
	}
	if ts := stringValue(metadata["timestamp"]); !entry.Timestamp.IsZero() {
		// already set
	} else if parsed := parseReportTime(ts); !parsed.IsZero() {
		entry.Timestamp = parsed
	}
	entry.Status = stringValue(metadata["status"])
	entry.Likes = intValue(metadata["likes"])
	entry.Comments = intValue(metadata["comments"])
	entry.Popularity = entry.Likes + entry.Comments

	if entry.Timestamp.IsZero() {
		entry.Timestamp = info.ModTime()
	}
	return entry, nil
}

func collectReportFiles(dir, projectPath, source string, typeResolver func(base, rel string) string) ([]reportEntry, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, nil
	}
	var reports []reportEntry
	allowedExt := map[string]struct{}{
		".yaml":     {},
		".yml":      {},
		".md":       {},
		".markdown": {},
		".html":     {},
		".htm":      {},
	}
	err = filepath.WalkDir(dir, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil
		}
		if d.IsDir() {
			return nil
		}
		ext := strings.ToLower(filepath.Ext(d.Name()))
		if _, ok := allowedExt[ext]; !ok {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		rel := relativePath(projectPath, path)
		entry := reportEntry{
			Key:       source + ":" + rel,
			AbsPath:   path,
			RelPath:   rel,
			Source:    source,
			Format:    strings.ToUpper(strings.TrimPrefix(ext, ".")),
			Size:      info.Size(),
			Timestamp: info.ModTime(),
		}
		entry.Type = typeResolver(dir, rel)
		entry.Title = summariseReportFile(path, ext)
		entry.Summary = entry.Title
		if entry.Type == "" {
			entry.Type = strings.ToUpper(strings.TrimPrefix(ext, "."))
		}
		reports = append(reports, entry)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return reports, nil
}

func reportFileTypeFromPath(base, rel string) string {
	path := filepath.ToSlash(rel)
	path = strings.TrimPrefix(path, "./")
	if strings.Contains(path, "/") {
		head := strings.SplitN(path, "/", 2)[0]
		if head != "" {
			return titleCase(strings.ReplaceAll(head, "-", " "))
		}
	}
	if base != "" {
		return titleCase(strings.ReplaceAll(filepath.Base(base), "-", " "))
	}
	return ""
}

func verifyReportTypeFromPath(base, rel string) string {
	path := filepath.ToSlash(rel)
	path = strings.TrimPrefix(path, ".gpt-creator/staging/verify/")
	path = strings.TrimPrefix(path, "/")
	segments := strings.Split(path, "/")
	for _, seg := range segments {
		trim := strings.TrimSpace(seg)
		if trim == "" {
			continue
		}
		trim = strings.TrimSuffix(trim, filepath.Ext(trim))
		if trim == "" {
			continue
		}
		return titleCase(strings.ReplaceAll(trim, "-", " "))
	}
	return "Verify"
}

func summariseReportFile(path, ext string) string {
	data := readFileLimited(path, 4096, 120)
	if data == "" {
		return filepath.Base(path)
	}
	if ext == ".html" || ext == ".htm" {
		if title := extractHTMLTitle(data); title != "" {
			return title
		}
	}
	lines := strings.Split(data, "\n")
	for _, line := range lines {
		trim := strings.TrimSpace(stripMarkdownHeading(line))
		if trim == "" {
			continue
		}
		return trim
	}
	return filepath.Base(path)
}

func extractHTMLTitle(content string) string {
	lower := strings.ToLower(content)
	start := strings.Index(lower, "<title>")
	end := strings.Index(lower, "</title>")
	if start < 0 || end < 0 || end <= start+7 {
		return ""
	}
	title := content[start+7 : end]
	title = strings.ReplaceAll(title, "\n", " ")
	title = strings.TrimSpace(title)
	return collapseSpaces(stripHTMLTags(title))
}

func stripHTMLTags(input string) string {
	var builder strings.Builder
	inTag := false
	for _, r := range input {
		switch r {
		case '<':
			inTag = true
		case '>':
			inTag = false
		default:
			if !inTag {
				builder.WriteRune(r)
			}
		}
	}
	return builder.String()
}

func collapseSpaces(input string) string {
	fields := strings.Fields(input)
	return strings.Join(fields, " ")
}

func stripMarkdownHeading(line string) string {
	line = strings.TrimSpace(line)
	if strings.HasPrefix(line, "#") {
		return strings.TrimSpace(strings.TrimLeft(line, "#"))
	}
	if strings.HasPrefix(line, "- ") || strings.HasPrefix(line, "* ") {
		return strings.TrimSpace(line[2:])
	}
	return line
}

func parseReportTime(values ...string) time.Time {
	layouts := []string{
		time.RFC3339Nano,
		time.RFC3339,
		time.RFC1123Z,
		time.RFC1123,
		time.RFC822Z,
		time.RFC822,
		"2006-01-02 15:04:05",
		"2006-01-02T15:04:05",
	}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		for _, layout := range layouts {
			if ts, err := time.Parse(layout, value); err == nil {
				return ts
			}
		}
	}
	return time.Time{}
}

func relativePath(projectPath, abs string) string {
	rel, err := filepath.Rel(projectPath, abs)
	if err != nil {
		return filepath.ToSlash(abs)
	}
	return filepath.ToSlash(rel)
}

func stringValue(value any) string {
	switch v := value.(type) {
	case string:
		return strings.TrimSpace(v)
	case fmt.Stringer:
		return strings.TrimSpace(v.String())
	default:
		return strings.TrimSpace(fmt.Sprint(value))
	}
}

func mapValue(value any) map[string]any {
	if value == nil {
		return nil
	}
	if m, ok := value.(map[string]any); ok {
		return m
	}
	if m, ok := value.(map[interface{}]interface{}); ok {
		out := make(map[string]any, len(m))
		for key, val := range m {
			out[fmt.Sprint(key)] = val
		}
		return out
	}
	return nil
}

func intValue(value any) int {
	switch v := value.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case uint64:
		return int(v)
	case float64:
		return int(v)
	case string:
		v = strings.TrimSpace(v)
		if v == "" {
			return 0
		}
		if parsed, err := strconv.Atoi(v); err == nil {
			return parsed
		}
	}
	return 0
}

func titleCase(input string) string {
	if input == "" {
		return ""
	}
	parts := strings.FieldsFunc(input, func(r rune) bool {
		switch r {
		case '-', '_', '/', '\\':
			return true
		default:
			return unicode.IsSpace(r)
		}
	})
	for i, part := range parts {
		runes := []rune(strings.ToLower(part))
		if len(runes) == 0 {
			continue
		}
		runes[0] = unicode.ToUpper(runes[0])
		parts[i] = string(runes)
	}
	return strings.Join(parts, " ")
}
