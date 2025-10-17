package main

import (
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type envLineKind int

const (
	envLineBlank envLineKind = iota
	envLineComment
	envLineEntry
	envLineOther
)

type envLine struct {
	Kind    envLineKind
	Raw     string
	Leading string
	Export  bool
	Key     string
	Value   string
	Quote   rune
	Comment string
}

type envEntry struct {
	Key       string
	Value     string
	Secret    bool
	Source    string
	LineIndex int
}

type envValidationResult struct {
	Missing   []string
	Empty     []string
	Duplicates []string
}

func (r envValidationResult) IsClean() bool {
	return len(r.Missing) == 0 && len(r.Empty) == 0 && len(r.Duplicates) == 0
}

type envFileState struct {
	Path               string
	RelPath            string
	Exists             bool
	Lines              []envLine
	Entries            []envEntry
	Dirty              bool
	HasTrailingNewline bool
	Validation         envValidationResult
	expectedKeys       []string
}

func loadEnvFiles(projectPath string) ([]*envFileState, error) {
	var states []*envFileState

	rootEnv := filepath.Join(projectPath, ".env")
	if state, err := parseEnvFile(rootEnv, projectPath); err == nil {
		states = append(states, state)
	} else if !os.IsNotExist(err) {
		return nil, err
	} else {
		state := newEmptyEnvFile(rootEnv, projectPath)
		states = append(states, state)
	}

	appsDir := filepath.Join(projectPath, "apps")
	entries, err := os.ReadDir(appsDir)
	if err == nil {
		var appNames []string
		for _, entry := range entries {
			if entry.IsDir() {
				appNames = append(appNames, entry.Name())
			}
		}
		sort.Strings(appNames)
		for _, name := range appNames {
			envPath := filepath.Join(appsDir, name, ".env")
			if state, err := parseEnvFile(envPath, projectPath); err == nil {
				states = append(states, state)
			} else if os.IsNotExist(err) {
				state := newEmptyEnvFile(envPath, projectPath)
				states = append(states, state)
			} else {
				return nil, err
			}
		}
	}

	return states, nil
}

func newEmptyEnvFile(path, projectRoot string) *envFileState {
	rel := relPath(projectRoot, path)
	return &envFileState{
		Path:    path,
		RelPath: rel,
		Exists:  false,
	}
}

func parseEnvFile(path, projectRoot string) (*envFileState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	content := string(data)
	hasTrailing := strings.HasSuffix(content, "\n")
	if hasTrailing {
		content = content[:len(content)-1]
	}
	var segments []string
	if content == "" {
		segments = []string{}
	} else {
		segments = strings.Split(content, "\n")
	}
	lines := make([]envLine, 0, len(segments))
	for _, raw := range segments {
		raw = strings.TrimSuffix(raw, "\r")
		lines = append(lines, parseEnvLine(raw))
	}
	state := &envFileState{
		Path:               path,
		RelPath:            relPath(projectRoot, path),
		Exists:             true,
		Lines:              lines,
		HasTrailingNewline: hasTrailing,
	}
	state.rebuildEntries()
	state.expectedKeys = discoverExpectedKeys(path)
	state.Validation = state.validate()
	return state, nil
}

func (f *envFileState) rebuildEntries() {
	var entries []envEntry
	for idx, line := range f.Lines {
		if line.Kind != envLineEntry {
			continue
		}
		entry := envEntry{
			Key:       line.Key,
			Value:     line.Value,
			Secret:    isSecretKey(line.Key),
			Source:    f.RelPath,
			LineIndex: idx,
		}
		entries = append(entries, entry)
	}
	f.Entries = entries
}

func (f *envFileState) validate() envValidationResult {
	result := envValidationResult{}
	keyCount := make(map[string]int)
	for _, entry := range f.Entries {
		keyCount[entry.Key]++
		if strings.TrimSpace(entry.Value) == "" {
			result.Empty = append(result.Empty, entry.Key)
		}
	}
	for key, count := range keyCount {
		if count > 1 {
			result.Duplicates = append(result.Duplicates, key)
		}
	}
	if len(result.Duplicates) > 0 {
		sort.Strings(result.Duplicates)
	}
	if len(result.Empty) > 0 {
		sort.Strings(result.Empty)
	}

	if len(f.expectedKeys) > 0 {
		present := make(map[string]bool)
		for _, entry := range f.Entries {
			if strings.TrimSpace(entry.Value) != "" {
				present[entry.Key] = true
			}
		}
		for _, key := range f.expectedKeys {
			if !present[key] {
				result.Missing = append(result.Missing, key)
			}
		}
		if len(result.Missing) > 0 {
			sort.Strings(result.Missing)
		}
	}

	return result
}

func (f *envFileState) serialize() []byte {
	var builder strings.Builder
	for i, line := range f.Lines {
		if i > 0 {
			builder.WriteByte('\n')
		}
		builder.WriteString(serializeEnvLine(line))
	}
	if f.HasTrailingNewline || len(f.Lines) == 0 {
		builder.WriteByte('\n')
	}
	return []byte(builder.String())
}

func (f *envFileState) setValue(index int, value string) {
	if index < 0 || index >= len(f.Lines) {
		return
	}
	line := f.Lines[index]
	if line.Kind != envLineEntry {
		return
	}
	line.Value = value
	line.Quote = chooseQuote(line.Quote, value)
	f.Lines[index] = line
	f.Dirty = true
	f.rebuildEntries()
	f.Validation = f.validate()
}

func (f *envFileState) addEntry(key, value string) int {
	line := envLine{
		Kind:  envLineEntry,
		Key:   key,
		Value: value,
		Quote: chooseQuote(0, value),
	}
	f.Lines = append(f.Lines, line)
	f.Dirty = true
	f.rebuildEntries()
	f.Validation = f.validate()
	return len(f.Entries) - 1
}

func (f *envFileState) ensureTrailingNewline() {
	f.HasTrailingNewline = true
}

func (f *envFileState) refreshValidation() {
	f.Validation = f.validate()
}

func parseEnvLine(raw string) envLine {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return envLine{Kind: envLineBlank, Raw: ""}
	}
	if strings.HasPrefix(trimmed, "#") {
		return envLine{Kind: envLineComment, Raw: raw}
	}

	leadingLen := len(raw) - len(strings.TrimLeft(raw, " \t"))
	leading := raw[:leadingLen]
	rest := strings.TrimLeft(raw, " \t")

	export := false
	if strings.HasPrefix(rest, "export ") {
		export = true
		rest = strings.TrimLeft(rest[len("export "):], " \t")
	}

	eqIdx := strings.Index(rest, "=")
	if eqIdx < 0 {
		return envLine{Kind: envLineOther, Raw: raw}
	}

	keyPart := strings.TrimSpace(rest[:eqIdx])
	valuePart := rest[eqIdx+1:]
	valuePart, comment := splitValueAndComment(valuePart)
	valuePart = strings.TrimSpace(valuePart)

	value, quote := parseEnvValue(valuePart)

	return envLine{
		Kind:    envLineEntry,
		Leading: leading,
		Export:  export,
		Key:     keyPart,
		Value:   value,
		Quote:   quote,
		Comment: comment,
	}
}

func splitValueAndComment(value string) (string, string) {
	inSingle := false
	inDouble := false
	runes := []rune(value)
	for i, r := range runes {
		switch r {
		case '\'':
			if !inDouble {
				inSingle = !inSingle
			}
		case '"':
			if !inSingle {
				inDouble = !inDouble
			}
		case '#':
			if inSingle || inDouble {
				continue
			}
			if i == 0 {
				return "", string(runes[i:])
			}
			if isWhitespaceRune(runes[i-1]) {
				return strings.TrimRight(string(runes[:i]), " \t"), string(runes[i:])
			}
		}
	}
	return strings.TrimRight(value, " \t"), ""
}

func parseEnvValue(raw string) (string, rune) {
	if len(raw) >= 2 {
		if raw[0] == '"' && raw[len(raw)-1] == '"' {
			unquoted, err := strconv.Unquote(raw)
			if err == nil {
				return unquoted, '"'
			}
		} else if raw[0] == '\'' && raw[len(raw)-1] == '\'' {
			return raw[1 : len(raw)-1], '\''
		}
	}
	return raw, 0
}

func serializeEnvLine(line envLine) string {
	switch line.Kind {
	case envLineBlank:
		return ""
	case envLineComment, envLineOther:
		return line.Raw
	case envLineEntry:
		var builder strings.Builder
		builder.WriteString(line.Leading)
		if line.Export {
			builder.WriteString("export ")
		}
		builder.WriteString(line.Key)
		builder.WriteByte('=')
		builder.WriteString(formatEnvValue(line.Value, line.Quote))
		if strings.TrimSpace(line.Comment) != "" {
			builder.WriteString(" ")
			builder.WriteString(strings.TrimSpace(line.Comment))
		}
		return builder.String()
	default:
		return line.Raw
	}
}

func formatEnvValue(value string, quote rune) string {
	switch quote {
	case '\'':
		if strings.ContainsRune(value, '\'') {
			return strconv.Quote(value)
		}
		return "'" + value + "'"
	case '"':
		return strconv.Quote(value)
	default:
		if needsQuoting(value) {
			return strconv.Quote(value)
		}
		return value
	}
}

func chooseQuote(existing rune, value string) rune {
	if existing == '\'' && strings.ContainsRune(value, '\'') {
		existing = '"'
	}
	if existing != 0 {
		return existing
	}
	if needsQuoting(value) {
		return '"'
	}
	return 0
}

func needsQuoting(value string) bool {
	if value == "" {
		return false
	}
	if strings.ContainsAny(value, " \t#\"'`") {
		return true
	}
	if strings.HasPrefix(value, "$") || strings.HasSuffix(value, " ") || strings.HasPrefix(value, " ") {
		return true
	}
	return strings.Contains(value, ":=") || strings.ContainsRune(value, '\t')
}

func isSecretKey(key string) bool {
	up := strings.ToUpper(key)
	keywords := []string{"SECRET", "TOKEN", "PASSWORD", "KEY", "API", "ACCESS", "PRIVATE", "CREDENTIAL"}
	for _, word := range keywords {
		if strings.Contains(up, word) {
			return true
		}
	}
	return false
}

func discoverExpectedKeys(path string) []string {
	dir := filepath.Dir(path)
	base := filepath.Base(path)
	candidates := []string{
		filepath.Join(dir, ".env.example"),
		filepath.Join(dir, ".env.sample"),
		filepath.Join(dir, ".env.template"),
		filepath.Join(dir, base+".example"),
		filepath.Join(dir, base+".sample"),
		filepath.Join(dir, base+".template"),
	}
	keysSet := make(map[string]struct{})
	for _, candidate := range candidates {
		data, err := os.ReadFile(candidate)
		if err != nil {
			continue
		}
		content := string(data)
		if strings.HasSuffix(content, "\n") {
			content = content[:len(content)-1]
		}
		var segments []string
		if content == "" {
			segments = []string{}
		} else {
			segments = strings.Split(content, "\n")
		}
		for _, raw := range segments {
			line := parseEnvLine(strings.TrimSuffix(raw, "\r"))
			if line.Kind == envLineEntry {
				keysSet[line.Key] = struct{}{}
			}
		}
	}
	if len(keysSet) == 0 {
		return nil
}
	var keys []string
	for key := range keysSet {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func relPath(root, target string) string {
	rel, err := filepath.Rel(root, target)
	if err != nil {
		return filepath.ToSlash(target)
	}
	return filepath.ToSlash(rel)
}

func writeEnvFile(state *envFileState) error {
	data := state.serialize()
	dir := filepath.Dir(state.Path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(state.Path, data, 0o600); err != nil {
		return err
	}
	state.Exists = true
	state.Dirty = false
	state.HasTrailingNewline = true
	return nil
}

func isWhitespaceRune(r rune) bool {
	return r == ' ' || r == '\t'
}
