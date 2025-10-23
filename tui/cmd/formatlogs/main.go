package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type rawEvent struct {
	line      int
	timestamp string
	rawHeader string
	channel   string
	message   string
	body      []string
}

type attribute struct {
	label string
	value []string
}

type formattedEvent struct {
	title      string
	category   string
	attributes []attribute
}

var headerPattern = regexp.MustCompile(`^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\]\s*(.*)$`)

func main() {
	var inputPath string
	var outputPath string
	var artifactDirFlag string
	flag.StringVar(&inputPath, "in", "", "input log file path (required)")
	flag.StringVar(&outputPath, "out", "", "output file path (optional, defaults to stdout)")
	flag.StringVar(&artifactDirFlag, "artifacts", "", "directory for extracted artifacts (defaults near output)")
	flag.Parse()

	if inputPath == "" {
		exitWithError(errors.New("missing --in path"))
	}

	events, err := parseLogFile(inputPath)
	if err != nil {
		exitWithError(fmt.Errorf("parse log: %w", err))
	}

	artifactDir, err := resolveArtifactDir(inputPath, outputPath, artifactDirFlag)
	if err != nil {
		exitWithError(err)
	}

	store, err := newArtifactStore(artifactDir)
	if err != nil {
		exitWithError(fmt.Errorf("setup artifact store: %w", err))
	}

	rendered, err := renderEvents(events, inputPath, store)
	if err != nil {
		exitWithError(fmt.Errorf("render events: %w", err))
	}

	if outputPath == "" {
		fmt.Println(rendered)
		return
	}
	if err := os.WriteFile(outputPath, []byte(rendered+"\n"), 0o644); err != nil {
		exitWithError(fmt.Errorf("write output: %w", err))
	}
}

func exitWithError(err error) {
	fmt.Fprintf(os.Stderr, "formatlogs: %v\n", err)
	os.Exit(1)
}

func parseLogFile(path string) ([]rawEvent, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return parseLog(path, bufio.NewScanner(file))
}

func parseLog(path string, scanner *bufio.Scanner) ([]rawEvent, error) {
	lineNo := 0
	var preamble []string
	var events []rawEvent
	var current *rawEvent

	for scanner.Scan() {
		lineNo++
		line := scanner.Text()
		m := headerPattern.FindStringSubmatch(line)
		if m != nil {
			if current != nil {
				events = append(events, *current)
			} else if len(preamble) > 0 {
				events = append(events, rawEvent{
					line:      1,
					timestamp: "",
					rawHeader: "preface",
					channel:   "",
					message:   "",
					body:      append([]string{}, preamble...),
				})
				preamble = nil
			}
			timestamp := strings.TrimSpace(m[1])
			rest := strings.TrimSpace(m[2])
			channel, message := splitChannel(rest)
			current = &rawEvent{
				line:      lineNo,
				timestamp: timestamp,
				rawHeader: rest,
				channel:   channel,
				message:   message,
			}
			continue
		}

		if current == nil {
			preamble = append(preamble, line)
			continue
		}
		current.body = append(current.body, line)
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	if current != nil {
		events = append(events, *current)
	}

	return events, nil
}

func splitChannel(rest string) (string, string) {
	if rest == "" {
		return "", ""
	}
	parts := strings.Fields(rest)
	if len(parts) == 0 {
		return "", rest
	}
	first := parts[0]
	if isChannelToken(first) {
		msg := strings.TrimSpace(rest[len(first):])
		return first, msg
	}
	return "", rest
}

func isChannelToken(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r >= 'A' && r <= 'Z' {
			return false
		}
		if !(r == '-' || r == '_' || (r >= 'a' && r <= 'z')) {
			return false
		}
	}
	return true
}

func renderEvents(events []rawEvent, sourcePath string, store *artifactStore) (string, error) {
	var out []string
	for _, evt := range events {
		formatted := formatEvent(evt)
		lines, err := renderEvent(formatted, sourcePath, evt.line, store)
		if err != nil {
			return "", err
		}
		out = append(out, lines...)
		out = append(out, "")
	}
	if len(out) > 0 {
		out = out[:len(out)-1]
	}
	return strings.Join(out, "\n"), nil
}

func formatEvent(evt rawEvent) formattedEvent {
	switch {
	case evt.timestamp == "" && len(evt.body) > 0:
		return formattedEvent{
			title:    "Preface",
			category: "context.metadata",
			attributes: []attribute{
				{label: "lines", value: trimEmpty(evt.body)},
			},
		}
	case strings.Contains(evt.rawHeader, "OpenAI Codex"):
		return formatContextInit(evt)
	case strings.HasSuffix(evt.rawHeader, "User instructions:"):
		return formatUserInstructions(evt)
	case strings.Contains(strings.ToLower(evt.rawHeader), "shared context"):
		return formatContextManifest(evt)
	case evt.channel == "thinking":
		return formatThinking(evt)
	case evt.channel == "codex":
		return formatCodexStage(evt)
	case evt.channel == "exec":
		return formatExec(evt)
	case evt.channel == "bash":
		return formatBash(evt)
	case evt.channel == "tokens":
		return formatTokens(evt)
	case strings.HasPrefix(evt.channel, "apply_patch"):
		return formatApplyPatch(evt)
	case evt.channel == "turn" && strings.HasPrefix(strings.TrimSpace(evt.message), "diff"):
		return formatDiff(evt)
	default:
		return formatDefault(evt)
	}
}

func formatContextInit(evt rawEvent) formattedEvent {
	attrs := []attribute{
		{label: "timestamp", value: []string{evt.timestamp}},
		{label: "agent_version", value: []string{evt.rawHeader}},
	}
	for _, line := range evt.body {
		line = strings.TrimSpace(line)
		if line == "" || line == "--------" {
			continue
		}
		if kv := strings.SplitN(line, ":", 2); len(kv) == 2 {
			key := strings.TrimSpace(strings.ReplaceAll(kv[0], " ", "_"))
			value := strings.TrimSpace(kv[1])
			attrs = append(attrs, attribute{label: key, value: []string{value}})
		}
	}
	return formattedEvent{
		title:      "Run Context",
		category:   "context.init",
		attributes: attrs,
	}
}

func formatUserInstructions(evt rawEvent) formattedEvent {
	body := trimEmpty(evt.body)
	return formattedEvent{
		title:    "User Brief",
		category: "context.instructions",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "instructions", value: body},
		},
	}
}

func formatContextManifest(evt rawEvent) formattedEvent {
	var artifacts []string
	var notes []string
	for _, line := range evt.body {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "### ") {
			artifacts = append(artifacts, line[4:])
			continue
		}
		if strings.Contains(line, ":") {
			notes = append(notes, line)
			continue
		}
		notes = append(notes, line)
	}
	attrs := []attribute{
		{label: "timestamp", value: []string{evt.timestamp}},
	}
	if len(artifacts) > 0 {
		attrs = append(attrs, attribute{label: "artifacts", value: artifacts})
	}
	if len(notes) > 0 {
		attrs = append(attrs, attribute{label: "notes", value: notes})
	}
	return formattedEvent{
		title:      "Shared Context",
		category:   "context.manifest",
		attributes: attrs,
	}
}

func formatThinking(evt rawEvent) formattedEvent {
	heading := ""
	var narrative []string
	for _, line := range evt.body {
		trim := strings.TrimSpace(line)
		if trim == "" {
			continue
		}
		if strings.HasPrefix(trim, "**") && strings.HasSuffix(trim, "**") && len(trim) > 4 {
			heading = strings.Trim(trim, "*")
			continue
		}
		narrative = append(narrative, trim)
	}
	if heading == "" {
		heading = "Agent Thinking"
	}
	return formattedEvent{
		title:    heading,
		category: "cognition.start",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "notes", value: narrative},
		},
	}
}

func formatCodexStage(evt rawEvent) formattedEvent {
	body := trimEmpty(evt.body)
	return formattedEvent{
		title:    "Execution Stage",
		category: "cognition.stage",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "detail", value: body},
		},
	}
}

func formatExec(evt rawEvent) formattedEvent {
	command := strings.TrimSpace(evt.message)
	cwd := ""
	if idx := strings.LastIndex(command, " in "); idx != -1 {
		cwd = strings.TrimSpace(command[idx+4:])
		command = strings.TrimSpace(command[:idx])
	}
	return formattedEvent{
		title:    "Shell Invocation",
		category: "tool.exec_request",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "command", value: []string{command}},
			{label: "cwd", value: []string{cwd}},
		},
	}
}

func formatBash(evt rawEvent) formattedEvent {
	status := "unknown"
	duration := ""
	message := strings.TrimSpace(evt.message)
	if strings.Contains(message, " succeeded") {
		status = "success"
	} else if strings.Contains(message, " failed") {
		status = "failed"
	}
	if idx := strings.LastIndex(message, "in "); idx != -1 {
		duration = strings.Trim(strings.TrimSuffix(message[idx+3:], ":"), " ")
		message = strings.TrimSpace(message[:idx])
	}
	if strings.HasSuffix(message, " succeeded") {
		message = strings.TrimSpace(strings.TrimSuffix(message, " succeeded"))
	} else if strings.HasSuffix(message, " failed") {
		message = strings.TrimSpace(strings.TrimSuffix(message, " failed"))
	}
	attrs := []attribute{
		{label: "timestamp", value: []string{evt.timestamp}},
		{label: "status", value: []string{status}},
	}
	if duration != "" {
		attrs = append(attrs, attribute{label: "duration", value: []string{duration}})
	}
	if message != "" {
		attrs = append(attrs, attribute{label: "command", value: []string{message}})
	}
	stdout := trimTrailingEmpty(evt.body)
	if len(stdout) > 0 {
		attrs = append(attrs, attribute{label: "output", value: stdout})
	}
	return formattedEvent{
		title:      "Command Result",
		category:   "tool.exec_result",
		attributes: attrs,
	}
}

func formatTokens(evt rawEvent) formattedEvent {
	value := strings.TrimSpace(evt.message)
	if strings.HasPrefix(value, "used:") {
		value = strings.TrimSpace(strings.TrimPrefix(value, "used:"))
	}
	return formattedEvent{
		title:    "Token Snapshot",
		category: "telemetry.tokens",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "tokens_used", value: []string{value}},
		},
	}
}

func formatApplyPatch(evt rawEvent) formattedEvent {
	message := strings.TrimSpace(evt.rawHeader)
	details := trimEmpty(evt.body)
	return formattedEvent{
		title:    "Patch Application",
		category: "tool.patch_result",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "summary", value: []string{message}},
			{label: "details", value: details},
		},
	}
}

func formatDiff(evt rawEvent) formattedEvent {
	diffLines := trimTrailingEmpty(evt.body)
	return formattedEvent{
		title:    "Diff Artifact",
		category: "output.diff_body",
		attributes: []attribute{
			{label: "timestamp", value: []string{evt.timestamp}},
			{label: "diff", value: diffLines},
		},
	}
}

func formatDefault(evt rawEvent) formattedEvent {
	body := trimEmpty(evt.body)
	label := "message"
	if evt.channel != "" {
		label = evt.channel
	}
	attrs := []attribute{
		{label: "timestamp", value: []string{evt.timestamp}},
	}
	if evt.message != "" {
		attrs = append(attrs, attribute{label: "summary", value: []string{evt.message}})
	}
	if len(body) > 0 {
		attrs = append(attrs, attribute{label: label, value: body})
	}
	return formattedEvent{
		title:      "Log Entry",
		category:   "log.raw",
		attributes: attrs,
	}
}

func renderEvent(evt formattedEvent, sourcePath string, line int, store *artifactStore) ([]string, error) {
	var out []string
	out = append(out, "------------------")

	location := sourcePath
	if rel, err := filepath.Rel(".", sourcePath); err == nil {
		location = rel
	}
	title := evt.title
	if title == "" {
		title = "Log Entry"
	}
	category := evt.category
	if category == "" {
		category = "log.raw"
	}
	out = append(out, fmt.Sprintf("%s · %s (%s:%d)", title, category, location, line))
	out = append(out, "------------------")
	for _, attr := range evt.attributes {
		if len(attr.value) == 0 {
			continue
		}
		if store != nil {
			var err error
			attr, err = store.maybeExternalize(evt, line, attr)
			if err != nil {
				return nil, err
			}
		}
		if len(attr.value) == 1 && attr.value[0] != "" && !strings.Contains(attr.value[0], "\n") {
			out = append(out, fmt.Sprintf("%s: %s", attr.label, attr.value[0]))
			continue
		}
		out = append(out, fmt.Sprintf("%s:", attr.label))
		for _, v := range attr.value {
			if v == "" {
				out = append(out, "  ")
			} else {
				out = append(out, "  "+v)
			}
		}
	}
	out = append(out, "------------------")
	return out, nil
}

func trimEmpty(lines []string) []string {
	var out []string
	for _, line := range lines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		out = append(out, strings.TrimRightFunc(line, func(r rune) bool {
			return r == ' ' || r == '\t'
		}))
	}
	return out
}

func trimTrailingEmpty(lines []string) []string {
	end := len(lines)
	for end > 0 {
		if strings.TrimSpace(lines[end-1]) != "" {
			break
		}
		end--
	}
	lines = lines[:end]
	for i := range lines {
		lines[i] = strings.TrimRight(lines[i], " \t")
	}
	return lines
}

type artifactStore struct {
	dir     string
	counter int
}

const (
	maxInlineLines = 40
	maxInlineChars = 4000
)

func resolveArtifactDir(inputPath, outputPath, flagValue string) (string, error) {
	if flagValue != "" {
		return flagValue, nil
	}
	baseDir := filepath.Dir(inputPath)
	baseName := strings.TrimSuffix(filepath.Base(inputPath), filepath.Ext(inputPath))
	if outputPath != "" {
		baseDir = filepath.Dir(outputPath)
		baseName = strings.TrimSuffix(filepath.Base(outputPath), filepath.Ext(outputPath))
	}
	return filepath.Join(baseDir, baseName+".artifacts"), nil
}

func newArtifactStore(dir string) (*artifactStore, error) {
	if dir == "" {
		return nil, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	return &artifactStore{dir: dir}, nil
}

func (s *artifactStore) maybeExternalize(evt formattedEvent, line int, attr attribute) (attribute, error) {
	if s == nil || len(attr.value) == 0 {
		return attr, nil
	}
	if !shouldExternalize(evt, attr) {
		return attr, nil
	}
	path, checksum, err := s.saveArtifact(evt, line, attr)
	if err != nil {
		return attr, err
	}
	lines := len(attr.value)
	attr.value = []string{fmt.Sprintf("[artifact] %s (lines:%d, sha256:%s)", path, lines, checksum)}
	return attr, nil
}

func shouldExternalize(evt formattedEvent, attr attribute) bool {
	label := strings.ToLower(attr.label)
	if label == "instructions" {
		return false
	}
	if evt.category == "output.diff_body" {
		if strings.Contains(label, "diff") {
			return true
		}
		return false
	}
	if strings.Contains(label, "diff") {
		return true
	}
	if label == "output" || label == "stdout" || label == "stderr" {
		return exceedsThreshold(attr.value)
	}
	return exceedsThreshold(attr.value)
}

func exceedsThreshold(values []string) bool {
	lineCount := 0
	charCount := 0
	for _, v := range values {
		lineCount++
		charCount += len(v)
	}
	return lineCount > maxInlineLines || charCount > maxInlineChars
}

func (s *artifactStore) saveArtifact(evt formattedEvent, line int, attr attribute) (string, string, error) {
	s.counter++
	content := strings.Join(attr.value, "\n")
	if !strings.HasSuffix(content, "\n") {
		content += "\n"
	}
	baseName := fmt.Sprintf("%04d_%s_%s_%d.txt", s.counter, sanitizeForName(evt.category), sanitizeForName(attr.label), line)
	fullPath := filepath.Join(s.dir, baseName)
	if err := os.WriteFile(fullPath, []byte(content), 0o644); err != nil {
		return "", "", err
	}
	sum := sha256.Sum256([]byte(content))
	checksum := hex.EncodeToString(sum[:])
	relPath, err := filepath.Rel(".", fullPath)
	if err != nil {
		relPath = fullPath
	}
	return filepath.ToSlash(relPath), checksum, nil
}

func sanitizeForName(input string) string {
	if input == "" {
		return "artifact"
	}
	var b strings.Builder
	for _, r := range input {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
		case r >= 'A' && r <= 'Z':
			b.WriteRune(r)
		case r >= '0' && r <= '9':
			b.WriteRune(r)
		case r == '-' || r == '_':
			b.WriteRune(r)
		default:
			b.WriteRune('-')
		}
	}
	result := strings.Trim(b.String(), "-_")
	if result == "" {
		return "artifact"
	}
	return result
}
