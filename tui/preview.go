package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	maxPreviewBytes     = 8192
	maxPreviewLines     = 200
	maxDocPreviewBytes  = 65536
	maxDocPreviewLines  = 400
	maxDiffPreviewLines = 400
)

const (
	ansiReset = "\x1b[0m"
	ansiRed   = "\x1b[31m"
	ansiGreen = "\x1b[32m"
	ansiDim   = "\x1b[2m"
)

func renderDetailedPreview(project *discoveredProject, featureKey string, item featureItemDefinition) string {
	if featureKey == "generate" {
		if detail := renderGenerateDetail(project, item); detail != "" {
			return detail
		}
	}
	key := item.PreviewKey
	if key == "" {
		return renderServicePreview(item.Meta)
	}
	switch {
	case strings.HasPrefix(key, "generate:"):
		return renderGenerateDetail(project, item)
	case strings.HasPrefix(key, "doc:"):
		name := strings.TrimPrefix(key, "doc:")
		return previewNamedDoc(project, name)
	case strings.HasPrefix(key, "docfile:"):
		rel := strings.TrimPrefix(key, "docfile:")
		return previewDocFile(project, rel)
	case strings.HasPrefix(key, "docdiff:"):
		docType := strings.TrimPrefix(key, "docdiff:")
		return previewDocDiff(project, docType, item.Meta)
	case key == "dbdump" || strings.HasPrefix(key, "dbdump:"):
		return renderDatabaseDumpPreview(project, item)
	case strings.HasPrefix(key, "path:"):
		path := strings.TrimPrefix(key, "path:")
		return previewPath(project, path)
	case key == "env:project":
		return previewEnvFile(filepath.Join(project.Path, ".env"))
	case key == "env:apps":
		return previewAppsEnv(project)
	case strings.HasPrefix(key, "verify:check:"):
		return renderVerifyCheckDetail(project, item)
	case strings.HasPrefix(key, "service:"):
		return renderServicePreview(item.Meta)
	case strings.HasPrefix(key, "tasks:"):
		return previewTasks(project)
	default:
		return ""
	}
}

func renderGenerateDetail(project *discoveredProject, item featureItemDefinition) string {
	if project == nil {
		return ""
	}
	kind := ""
	if item.Meta != nil {
		kind = strings.TrimSpace(item.Meta["generateKind"])
	}
	switch kind {
	case "file":
		return renderGenerateDiff(project, item)
	case "target":
		return renderGenerateTargetDetail(project, item)
	case "command":
		return renderGenerateCommandDetail(project, item)
	case "warning":
		return strings.TrimSpace(item.Meta["generateWarning"]) + "\n"
	default:
		return ""
	}
}

func renderGenerateCommandDetail(project *discoveredProject, item featureItemDefinition) string {
	changeSet, err := gatherGenerateChanges(project.Path)
	if err != nil {
		return fmt.Sprintf("Failed to refresh generate status: %v\n", err)
	}
	total := aggregateGenerateCounts(changeSet)
	var b strings.Builder
	b.WriteString("Generate all targets\n")
	b.WriteString(strings.Repeat("═", len("Generate all targets")))
	b.WriteString("\n")
	b.WriteString(fmt.Sprintf("Source: %s\n", strings.ToUpper(changeSet.Source)))
	if total.Total() == 0 {
		b.WriteString("No pending changes detected across targets.\n")
		if changeSet.Warning != "" {
			b.WriteString("\n" + changeSet.Warning + "\n")
		}
		return b.String()
	}
	b.WriteString(fmt.Sprintf("Files changed: %d (%s)\n\n", total.Total(), total.Summary()))
	for _, key := range changeSet.Keys {
		entry := changeSet.Targets[key]
		if entry.Counts.Total() == 0 {
			continue
		}
		title := entry.Definition.Title
		if title == "" {
			title = strings.ToUpper(key)
		}
		b.WriteString(fmt.Sprintf("%s (%d)\n", title, entry.Counts.Total()))
		for _, change := range entry.Files {
			status := change.StatusLabel
			if strings.TrimSpace(status) == "" {
				status = strings.ToUpper(change.Status)
			}
			label := status
			if change.Status == "renamed" && strings.TrimSpace(change.OldPath) != "" {
				label += " → " + change.OldPath
			}
			b.WriteString(fmt.Sprintf("  %s • %s\n", label, change.Path))
		}
		b.WriteString("\n")
	}
	if changeSet.Warning != "" {
		b.WriteString(changeSet.Warning + "\n")
	}
	return b.String()
}

func renderGenerateTargetDetail(project *discoveredProject, item featureItemDefinition) string {
	target := strings.TrimSpace(item.Meta["generateTarget"])
	if target == "" {
		return ""
	}
	changeSet, err := gatherGenerateChanges(project.Path)
	if err != nil {
		return fmt.Sprintf("Failed to refresh target changes: %v\n", err)
	}
	entry, ok := changeSet.Targets[target]
	if !ok {
		return fmt.Sprintf("No changes recorded for %s.\n", strings.ToUpper(target))
	}
	title := entry.Definition.Title
	if title == "" {
		title = strings.ToUpper(target)
	}
	var b strings.Builder
	b.WriteString(fmt.Sprintf("%s target\n", title))
	b.WriteString(strings.Repeat("═", len(title)+7))
	b.WriteString("\n")
	b.WriteString(fmt.Sprintf("Source: %s\n", strings.ToUpper(changeSet.Source)))
	counts := entry.Counts
	if counts.Total() == 0 {
		b.WriteString("No pending changes detected.\n")
		if changeSet.Warning != "" {
			b.WriteString("\n" + changeSet.Warning + "\n")
		}
		return b.String()
	}
	b.WriteString(fmt.Sprintf("Files changed: %d (%s)\n\n", counts.Total(), counts.Summary()))
	for _, change := range entry.Files {
		status := change.StatusLabel
		if strings.TrimSpace(status) == "" {
			status = strings.ToUpper(change.Status)
		}
		label := status
		if change.Status == "renamed" && strings.TrimSpace(change.OldPath) != "" {
			label += " → " + change.OldPath
		}
		b.WriteString(fmt.Sprintf("%s • %s\n", label, change.Path))
	}
	if changeSet.Warning != "" {
		b.WriteString("\n" + changeSet.Warning + "\n")
	}
	return b.String()
}

func renderGenerateDiff(project *discoveredProject, item featureItemDefinition) string {
	source := strings.TrimSpace(item.Meta["generateDiffSource"])
	switch source {
	case generateDiffSourceGit:
		return renderGenerateGitDiff(project, item)
	case generateDiffSourceSnapshot:
		return renderGenerateSnapshotDiff(project, item)
	default:
		return "Diff source unavailable.\n"
	}
}

func renderGenerateGitDiff(project *discoveredProject, item featureItemDefinition) string {
	rel := strings.TrimSpace(item.Meta["generatePath"])
	if rel == "" {
		return "Diff unavailable.\n"
	}
	status := strings.TrimSpace(item.Meta["generateStatus"])
	oldPath := strings.TrimSpace(item.Meta["generateOldPath"])
	diff, err := gitDiffForFile(project.Path, rel, oldPath, status)
	if err != nil && strings.TrimSpace(diff) == "" {
		return fmt.Sprintf("%s\nStatus: %s\nSource: Git\n\nDiff unavailable (%v).\n", filepath.Join(project.Path, filepath.FromSlash(rel)), strings.ToUpper(status), err)
	}
	if strings.TrimSpace(diff) == "" {
		return fmt.Sprintf("%s\nStatus: %s\nSource: Git\n\nNo differences detected.\n", filepath.Join(project.Path, filepath.FromSlash(rel)), strings.ToUpper(status))
	}
	header := fmt.Sprintf("%s\nStatus: %s\nSource: Git\n", filepath.Join(project.Path, filepath.FromSlash(rel)), strings.ToUpper(status))
	return header + "\n" + limitLines(strings.TrimSpace(diff), maxDiffPreviewLines)
}

func gitDiffForFile(projectPath, relPath, oldPath, status string) (string, error) {
	relPath = filepath.ToSlash(relPath)
	status = strings.ToLower(strings.TrimSpace(status))
	oldPath = filepath.ToSlash(strings.TrimSpace(oldPath))
	if status == "added" && oldPath == "" {
		abs := filepath.Join(projectPath, filepath.FromSlash(relPath))
		cmd := exec.Command("git", "--no-pager", "diff", "--color=never", "--no-index", "/dev/null", abs)
		cmd.Dir = projectPath
		out, err := cmd.CombinedOutput()
		return string(out), err
	}
	args := []string{"-C", projectPath, "--no-pager", "diff", "--color=never"}
	if status == "renamed" && oldPath != "" {
		args = append(args, "--", oldPath, relPath)
	} else {
		args = append(args, "--", relPath)
	}
	cmd := exec.Command("git", args...)
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func renderGenerateSnapshotDiff(project *discoveredProject, item featureItemDefinition) string {
	rel := strings.TrimSpace(item.Meta["generatePath"])
	if rel == "" {
		return "Diff unavailable.\n"
	}
	status := strings.TrimSpace(item.Meta["generateStatus"])
	basePath := strings.TrimSpace(item.Meta["generateSnapshotOld"])
	baseContent := readFileForDiff(basePath)
	headContent := ""
	if status != "deleted" {
		headContent = readFileForDiff(currentFileFor(project.Path, rel))
	}
	baseLines := strings.Split(baseContent, "\n")
	headLines := strings.Split(headContent, "\n")
	chunks := diffLines(baseLines, headLines)
	diffText := renderDiffChunks(chunks)
	diffText = limitLines(diffText, maxDiffPreviewLines)
	if strings.TrimSpace(diffText) == "" {
		return fmt.Sprintf("%s\nStatus: %s\nSource: Snapshot\n\nNo differences detected.\n", filepath.Join(project.Path, filepath.FromSlash(rel)), strings.ToUpper(status))
	}
	header := fmt.Sprintf("%s\nStatus: %s\nSource: Snapshot\n", filepath.Join(project.Path, filepath.FromSlash(rel)), strings.ToUpper(status))
	return header + "\n" + diffText
}

func previewNamedDoc(project *discoveredProject, name string) string {
	if project == nil {
		return ""
	}
	docType := strings.ToLower(strings.TrimSpace(name))
	switch docType {
	case "pdr", "doc:pdr":
		docType = "pdr"
	case "sds", "doc:sds":
		docType = "sds"
	default:
		docType = strings.TrimPrefix(docType, "doc:")
	}
	if docType == "" {
		return ""
	}
	rel := primaryDocPath(project, docType)
	if rel == "" {
		return ""
	}
	return previewDocFile(project, rel)
}

func previewDocFile(project *discoveredProject, rel string) string {
	if project == nil {
		return ""
	}
	rel = strings.TrimSpace(rel)
	if rel == "" {
		return ""
	}
	abs := filepath.Join(project.Path, rel)
	info, err := os.Stat(abs)
	if err != nil || info.IsDir() {
		return fmt.Sprintf("%s\n\nDocument not found.\n", abs)
	}
	content := readFileLimited(abs, maxDocPreviewBytes, maxDocPreviewLines)
	if strings.TrimSpace(content) == "" {
		return fmt.Sprintf("%s\n\n(empty document)\n", abs)
	}
	rendered := RenderMarkdown(content)
	rendered = limitLines(rendered, maxDocPreviewLines)
	header := fmt.Sprintf("%s\nUpdated: %s (%s ago)\nSize: %s\n", abs, info.ModTime().Format(time.RFC822), formatRelativeTime(info.ModTime()), formatByteSize(info.Size()))
	return header + "\n" + rendered
}

func previewDocDiff(project *discoveredProject, docType string, meta map[string]string) string {
	if project == nil {
		return ""
	}
	docType = strings.ToLower(strings.TrimSpace(docType))
	if docType == "" {
		return ""
	}
	filesByType := gatherDocFiles(project.Path)
	files := filesByType[docType]

	headRel := ""
	baseRel := ""
	if meta != nil {
		headRel = meta["docDiffHead"]
		baseRel = meta["docDiffBase"]
	}
	if (headRel == "" || baseRel == "") && len(files) > 0 {
		if head, base, ok := docDiffPair(files); ok {
			if headRel == "" {
				headRel = head.RelPath
			}
			if baseRel == "" {
				baseRel = base.RelPath
			}
		}
	}
	if headRel == "" {
		headRel = primaryDocPath(project, docType)
	}
	if baseRel == "" {
		baseRel = baselineDocPath(project, docType)
	}
	if headRel == "" || baseRel == "" {
		return "Diff unavailable for this document.\n"
	}
	headAbs := filepath.Join(project.Path, headRel)
	baseAbs := filepath.Join(project.Path, baseRel)
	headContent := readFileLimited(headAbs, maxDocPreviewBytes, maxDocPreviewLines)
	baseContent := readFileLimited(baseAbs, maxDocPreviewBytes, maxDocPreviewLines)
	headLines := strings.Split(headContent, "\n")
	baseLines := strings.Split(baseContent, "\n")
	chunks := diffLines(baseLines, headLines)
	diffText := renderDiffChunks(chunks)
	diffText = limitLines(diffText, maxDiffPreviewLines)
	header := fmt.Sprintf("Diff • new: %s\nBaseline: %s\n", headAbs, baseAbs)
	return header + "\n" + diffText
}

func renderVerifyCheckDetail(project *discoveredProject, item featureItemDefinition) string {
	if project == nil {
		return "Select a project to inspect verification results.\n"
	}
	name := strings.TrimSpace(item.Meta["verifyName"])
	label := strings.TrimSpace(item.Meta["verifyLabel"])
	if label == "" {
		label = strings.ReplaceAll(strings.Title(strings.ReplaceAll(name, "-", " ")), "  ", " ")
	}
	status := strings.TrimSpace(item.Meta["verifyStatus"])
	if status == "" {
		status = "pending"
	}
	icon := verifyStatusIcon(status)
	var b strings.Builder
	header := fmt.Sprintf("%s %s", icon, label)
	b.WriteString(header + "\n")
	b.WriteString(strings.Repeat("═", len(header)))
	b.WriteString("\n")
	b.WriteString("Status: " + verifyStatusLabel(status) + "\n")
	if msg := strings.TrimSpace(item.Meta["verifyMessage"]); msg != "" {
		b.WriteString("Message: " + msg + "\n")
	}
	if score := strings.TrimSpace(item.Meta["verifyScore"]); score != "" {
		b.WriteString("Score: " + score + "\n")
	}
	if dur := strings.TrimSpace(item.Meta["verifyDuration"]); dur != "" {
		if seconds, err := strconv.ParseFloat(dur, 64); err == nil && seconds > 0 {
			b.WriteString("Duration: " + formatVerifyDuration(seconds) + "\n")
		}
	}
	if updated := strings.TrimSpace(item.Meta["verifyUpdated"]); updated != "" {
		if ts, err := time.Parse(time.RFC3339, updated); err == nil {
			b.WriteString("Updated: " + ts.Format(time.RFC822) + " (" + formatRelativeTime(ts) + " ago)\n")
		} else {
			b.WriteString("Updated: " + updated + "\n")
		}
	}
	if runKind := strings.TrimSpace(item.Meta["verifyRunKind"]); runKind != "" {
		b.WriteString("Triggered by: verify " + runKind + "\n")
	}
	logRel := strings.TrimSpace(item.Meta["verifyLog"])
	if logRel != "" {
		logAbs := filepath.Join(project.Path, filepath.FromSlash(logRel))
		b.WriteString("\nLog: " + logAbs + "\n")
		if snippet := readFileSnippet(logAbs); snippet != "" {
			b.WriteString(limitLines(snippet, maxPreviewLines))
			if !strings.HasSuffix(snippet, "\n") {
				b.WriteString("\n")
			}
		} else {
			b.WriteString("(log unavailable)\n")
		}
	}
	if reportRel := strings.TrimSpace(item.Meta["verifyReport"]); reportRel != "" {
		reportAbs := filepath.Join(project.Path, filepath.FromSlash(reportRel))
		b.WriteString("\nReport: " + reportAbs + "\n")
	}
	return b.String()
}

func previewPath(project *discoveredProject, rel string) string {
	if project == nil {
		return ""
	}
	abspath := filepath.Join(project.Path, rel)
	info, err := os.Stat(abspath)
	if err != nil {
		return ""
	}
	if info.IsDir() {
		if readme := firstExisting(abspath, "README.md", "README", "readme.md", "readme.txt"); readme != "" {
			if content := readFileSnippet(readme); content != "" {
				return fmt.Sprintf("%s\n\n%s", readme, content)
			}
		}
		entries, _ := os.ReadDir(abspath)
		limit := len(entries)
		if limit > 12 {
			limit = 12
		}
		var lines []string
		for i := 0; i < limit; i++ {
			entry := entries[i]
			marker := ""
			if entry.IsDir() {
				marker = "/"
			}
			lines = append(lines, entry.Name()+marker)
		}
		return fmt.Sprintf("%s/\n%s", abspath, strings.Join(lines, "\n"))
	}
	content := readFileSnippet(abspath)
	if content == "" {
		return ""
	}
	return fmt.Sprintf("%s\n\n%s", abspath, content)
}

func previewEnvFile(path string) string {
	content := readFileSnippet(path)
	if content == "" {
		return ""
	}
	return fmt.Sprintf("%s\n\n%s", path, content)
}

func previewAppsEnv(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	appsDir := filepath.Join(project.Path, "apps")
	entries, err := os.ReadDir(appsDir)
	if err != nil {
		return ""
	}
	var lines []string
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		path := filepath.Join(appsDir, entry.Name(), ".env")
		if _, err := os.Stat(path); err == nil {
			lines = append(lines, entry.Name()+"/.env")
		}
	}
	if len(lines) == 0 {
		return ""
	}
	return "Application env files:\n" + strings.Join(lines, "\n")
}

func renderServicePreview(meta map[string]string) string {
	if len(meta) == 0 {
		return ""
	}
	if meta["serviceRow"] != "1" {
		order := []string{"service", "container", "state", "health", "status", "ports", "endpoint", "latency"}
		var lines []string
		for _, key := range order {
			val := meta[key]
			if strings.TrimSpace(val) == "" {
				continue
			}
			label := strings.ToUpper(key[:1]) + key[1:]
			lines = append(lines, fmt.Sprintf("%s: %s", label, val))
		}
		return strings.Join(lines, "\n")
	}

	var b strings.Builder
	service := strings.TrimSpace(meta["service"])
	state := strings.TrimSpace(meta["state"])
	health := strings.TrimSpace(meta["health"])
	if health == "" {
		health = "n/a"
	}
	header := service
	if header == "" {
		header = "Service"
	}
	if state != "" {
		header = fmt.Sprintf("%s — %s", header, state)
	}
	if health != "" {
		header = fmt.Sprintf("%s (%s)", header, health)
	}
	b.WriteString(header)
	b.WriteByte('\n')
	b.WriteString(strings.Repeat("─", len(header)))
	b.WriteByte('\n')

	container := strings.TrimSpace(meta["container"])
	if container != "" {
		fmt.Fprintf(&b, "Container: %s\n", container)
	}
	status := strings.TrimSpace(meta["status"])
	if status != "" {
		fmt.Fprintf(&b, "Status: %s\n", status)
	}
	restarts := strings.TrimSpace(meta["restarts"])
	if restarts != "" {
		fmt.Fprintf(&b, "Restarts: %s\n", restarts)
	}
	ports := strings.TrimSpace(meta["ports"])
	if ports != "" {
		fmt.Fprintf(&b, "Ports: %s\n", ports)
	}
	endpoint := strings.TrimSpace(meta["endpoint"])
	latency := strings.TrimSpace(meta["latency"])
	if endpoint != "" {
		if latency == "" {
			latency = "n/a"
		}
		fmt.Fprintf(&b, "Primary endpoint: %s (%s)\n", endpoint, latency)
	}

	endpoints := decodeServiceEndpoints(meta["endpoints"])
	if len(endpoints) > 0 {
		b.WriteByte('\n')
		b.WriteString("Endpoints\n")
		b.WriteString("---------\n")
		for idx, ep := range endpoints {
			label := fmt.Sprintf("[%d]", idx+1)
			statusLabel := "ok"
			if !ep.Healthy {
				if strings.TrimSpace(ep.Error) != "" {
					statusLabel = strings.TrimSpace(ep.Error)
				} else if ep.StatusCode > 0 {
					statusLabel = fmt.Sprintf("HTTP %d", ep.StatusCode)
				} else {
					statusLabel = "unreachable"
				}
			}
			lat := "n/a"
			if ep.LatencyMS > 0 {
				lat = fmt.Sprintf("%dms", ep.LatencyMS)
			}
			url := ep.URL
			if url == "" {
				url = fmt.Sprintf("http://%s:%s%s", ep.Host, ep.Port, ep.Path)
			}
			fmt.Fprintf(&b, "  %s %s — %s • %s\n", label, url, statusLabel, lat)
		}
		b.WriteString("\nPress `o` to open the preferred endpoint, or press 1–9 to open a specific URL in your browser.\n")
	}

	if raw := strings.TrimSpace(meta["healthJSON"]); raw != "" && raw != "null" {
		var pretty bytes.Buffer
		if err := json.Indent(&pretty, []byte(raw), "", "  "); err == nil {
			b.WriteByte('\n')
			b.WriteString("Health (docker inspect)\n")
			b.WriteString("-----------------------\n")
			b.WriteString(pretty.String())
			if !strings.HasSuffix(pretty.String(), "\n") {
				b.WriteByte('\n')
			}
		}
	}

	if logs := strings.TrimSpace(meta["logTail"]); logs != "" {
		lines := strings.Split(logs, "\n")
		b.WriteByte('\n')
		b.WriteString("Recent logs\n")
		b.WriteString("-----------\n")
		for _, line := range lines {
			if strings.TrimSpace(line) == "" {
				continue
			}
			b.WriteString("  ")
			b.WriteString(line)
			b.WriteByte('\n')
		}
	}

	b.WriteByte('\n')
	b.WriteString("Stack shortcuts: u=run up • l=run logs • d=run down • o=open endpoint\n")
	return strings.TrimRight(b.String(), "\n")
}

func decodeServiceEndpoints(raw string) []serviceEndpoint {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	var endpoints []serviceEndpoint
	if err := json.Unmarshal([]byte(raw), &endpoints); err != nil {
		return nil
	}
	return endpoints
}

func previewTasks(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	progressPath := filepath.Join(project.Path, ".gpt-creator", "staging", "plan", "tasks", "progress.json")
	content := readFileSnippet(progressPath)
	if content == "" {
		return ""
	}
	return fmt.Sprintf("%s\n\n%s", progressPath, content)
}

func firstExisting(dir string, names ...string) string {
	for _, name := range names {
		candidate := filepath.Join(dir, name)
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}
	return ""
}

func readFileSnippet(path string) string {
	return readFileLimited(path, maxPreviewBytes, maxPreviewLines)
}

func readFileLimited(path string, maxBytes, maxLines int) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	if maxBytes > 0 && len(data) > maxBytes {
		data = data[:maxBytes]
	}
	text := string(data)
	lines := strings.Split(text, "\n")
	if maxLines > 0 && len(lines) > maxLines {
		lines = lines[:maxLines]
	}
	return strings.Join(lines, "\n")
}

type diffOp int

const (
	diffEqual diffOp = iota
	diffDelete
	diffInsert
)

type diffChunk struct {
	op    diffOp
	lines []string
}

func diffLines(base, head []string) []diffChunk {
	n := len(base)
	m := len(head)
	dp := make([][]int, n+1)
	for i := range dp {
		dp[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if base[i] == head[j] {
				dp[i][j] = dp[i+1][j+1] + 1
			} else if dp[i+1][j] >= dp[i][j+1] {
				dp[i][j] = dp[i+1][j]
			} else {
				dp[i][j] = dp[i][j+1]
			}
		}
	}
	var chunks []diffChunk
	appendLine := func(op diffOp, line string) {
		if len(chunks) == 0 || chunks[len(chunks)-1].op != op {
			chunks = append(chunks, diffChunk{op: op, lines: []string{line}})
			return
		}
		chunks[len(chunks)-1].lines = append(chunks[len(chunks)-1].lines, line)
	}
	i, j := 0, 0
	for i < n && j < m {
		if base[i] == head[j] {
			appendLine(diffEqual, base[i])
			i++
			j++
		} else if dp[i+1][j] >= dp[i][j+1] {
			appendLine(diffDelete, base[i])
			i++
		} else {
			appendLine(diffInsert, head[j])
			j++
		}
	}
	for i < n {
		appendLine(diffDelete, base[i])
		i++
	}
	for j < m {
		appendLine(diffInsert, head[j])
		j++
	}
	return chunks
}

func renderDiffChunks(chunks []diffChunk) string {
	var builder strings.Builder
	for _, chunk := range chunks {
		switch chunk.op {
		case diffEqual:
			for _, line := range chunk.lines {
				builder.WriteString(ansiDim)
				builder.WriteString("  ")
				builder.WriteString(line)
				builder.WriteString(ansiReset)
				builder.WriteByte('\n')
			}
		case diffInsert:
			for _, line := range chunk.lines {
				builder.WriteString(ansiGreen)
				builder.WriteString("+ ")
				builder.WriteString(line)
				builder.WriteString(ansiReset)
				builder.WriteByte('\n')
			}
		case diffDelete:
			for _, line := range chunk.lines {
				builder.WriteString(ansiRed)
				builder.WriteString("- ")
				builder.WriteString(line)
				builder.WriteString(ansiReset)
				builder.WriteByte('\n')
			}
		}
	}
	out := builder.String()
	return strings.TrimSuffix(out, "\n")
}

func limitLines(text string, maxLines int) string {
	if maxLines <= 0 {
		return text
	}
	lines := strings.Split(text, "\n")
	if len(lines) <= maxLines {
		return text
	}
	lines = append(lines[:maxLines], "… (truncated)")
	return strings.Join(lines, "\n")
}
