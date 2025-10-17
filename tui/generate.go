package main

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	generateDiffSourceGit      = "git"
	generateDiffSourceSnapshot = "snapshot"
)

type generateTargetDefinition struct {
	Key         string
	Title       string
	Command     []string
	Directories []string
	Files       []string
}

var generateTargetDefinitions = []generateTargetDefinition{
	{
		Key:         "api",
		Title:       "API",
		Command:     []string{"generate", "api"},
		Directories: []string{"apps/api"},
	},
	{
		Key:         "web",
		Title:       "Web",
		Command:     []string{"generate", "web"},
		Directories: []string{"apps/web"},
	},
	{
		Key:         "admin",
		Title:       "Admin",
		Command:     []string{"generate", "admin"},
		Directories: []string{"apps/admin"},
	},
	{
		Key:         "db",
		Title:       "DB",
		Command:     []string{"generate", "db"},
		Directories: []string{"apps/db", "db"},
	},
	{
		Key:         "docker",
		Title:       "Docker",
		Command:     []string{"generate", "docker"},
		Directories: []string{"docker"},
		Files:       []string{"docker-compose.yml"},
	},
}

func generateTargetByKey(key string) (generateTargetDefinition, bool) {
	for _, def := range generateTargetDefinitions {
		if def.Key == key {
			return def, true
		}
	}
	return generateTargetDefinition{}, false
}

type generateFileChange struct {
	Path        string
	OldPath     string
	Status      string
	StatusLabel string
	TargetKey   string
	DiffSource  string
	SnapshotOld string
}

type changeCounts struct {
	Added    int
	Modified int
	Deleted  int
	Renamed  int
}

func (c changeCounts) Total() int {
	return c.Added + c.Modified + c.Deleted + c.Renamed
}

func (c changeCounts) Summary() string {
	var parts []string
	if c.Added > 0 {
		parts = append(parts, fmt.Sprintf("%d added", c.Added))
	}
	if c.Modified > 0 {
		parts = append(parts, fmt.Sprintf("%d modified", c.Modified))
	}
	if c.Renamed > 0 {
		parts = append(parts, fmt.Sprintf("%d renamed", c.Renamed))
	}
	if c.Deleted > 0 {
		parts = append(parts, fmt.Sprintf("%d deleted", c.Deleted))
	}
	if len(parts) == 0 {
		return "No pending changes"
	}
	return strings.Join(parts, ", ")
}

type generateTargetChanges struct {
	Definition generateTargetDefinition
	Files      []generateFileChange
	Counts     changeCounts
}

type generateChangeSet struct {
	Source        string
	Targets       map[string]generateTargetChanges
	Keys          []string
	Warning       string
	SnapshotRoot  string
	SnapshotStamp time.Time
}

func gatherGenerateChanges(projectPath string) (generateChangeSet, error) {
	projectPath = filepath.Clean(projectPath)
	if projectPath == "" {
		return generateChangeSet{}, errors.New("project path required")
	}

	changes, ok, err := collectGitChanges(projectPath)
	if err != nil {
		return generateChangeSet{}, err
	}
	if ok {
		return buildChangeSetFromGit(projectPath, changes), nil
	}
	return collectSnapshotChanges(projectPath)
}

type gitChange struct {
	XY      string
	Path    string
	OldPath string
}

func collectGitChanges(projectPath string) ([]gitChange, bool, error) {
	if _, err := exec.LookPath("git"); err != nil {
		return nil, false, nil
	}

	cmd := exec.Command("git", "-C", projectPath, "status", "--porcelain=v1", "-z")
	out, err := cmd.CombinedOutput()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			stderr := string(exitErr.Stderr)
			if strings.Contains(stderr, "Not a git repository") || strings.Contains(stderr, "not a git repository") {
				return nil, false, nil
			}
		}
		return nil, false, err
	}
	if len(out) == 0 {
		return nil, true, nil
	}

	entries := bytes.Split(out, []byte{0})
	var results []gitChange
	for i := 0; i < len(entries); i++ {
		entry := entries[i]
		if len(entry) == 0 {
			continue
		}
		if len(entry) < 3 {
			continue
		}
		status := string(entry[:2])
		path := string(bytes.TrimSpace(entry[3:]))
		path = unescapeGitPath(path)
		if len(status) > 0 && (status[0] == 'R' || status[0] == 'C') {
			i++
			if i < len(entries) {
				newPath := string(entries[i])
				newPath = unescapeGitPath(strings.TrimSpace(newPath))
				results = append(results, gitChange{
					XY:      status,
					Path:    newPath,
					OldPath: path,
				})
			}
			continue
		}
		results = append(results, gitChange{
			XY:   status,
			Path: path,
		})
	}
	return results, true, nil
}

func projectHasGitRepo(projectPath string) bool {
	if _, err := exec.LookPath("git"); err != nil {
		return false
	}
	cmd := exec.Command("git", "-C", projectPath, "rev-parse", "--is-inside-work-tree")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) == "true"
}

func unescapeGitPath(path string) string {
	path = strings.Trim(path, "\"")
	path = strings.ReplaceAll(path, "\\\\", "\\")
	path = strings.ReplaceAll(path, "\\\"", "\"")
	path = strings.ReplaceAll(path, "\\t", "\t")
	path = strings.ReplaceAll(path, "\\n", "\n")
	return path
}

func buildChangeSetFromGit(projectPath string, changes []gitChange) generateChangeSet {
	targetMap := make(map[string]generateTargetChanges)
	for _, def := range generateTargetDefinitions {
		targetMap[def.Key] = generateTargetChanges{Definition: def}
	}

	for _, change := range changes {
		kind := interpretGitStatus(change.XY)
		if kind == "" {
			continue
		}
		path := filepath.ToSlash(change.Path)
		targetKey := matchGenerateTarget(path)
		if targetKey == "" {
			continue
		}
		entry := targetMap[targetKey]
		fileChange := generateFileChange{
			Path:        path,
			OldPath:     filepath.ToSlash(change.OldPath),
			Status:      kind,
			StatusLabel: gitStatusLabel(kind, change.XY),
			TargetKey:   targetKey,
			DiffSource:  generateDiffSourceGit,
		}
		switch kind {
		case "added":
			entry.Counts.Added++
		case "deleted":
			entry.Counts.Deleted++
		case "renamed":
			entry.Counts.Renamed++
		default:
			entry.Counts.Modified++
		}
		entry.Files = append(entry.Files, fileChange)
		targetMap[targetKey] = entry
	}

	var keys []string
	for _, def := range generateTargetDefinitions {
		keys = append(keys, def.Key)
		entry := targetMap[def.Key]
		sort.Slice(entry.Files, func(i, j int) bool {
			return entry.Files[i].Path < entry.Files[j].Path
		})
		targetMap[def.Key] = entry
	}

	return generateChangeSet{
		Source:  generateDiffSourceGit,
		Targets: targetMap,
		Keys:    keys,
	}
}

func interpretGitStatus(xy string) string {
	if len(xy) < 2 {
		return ""
	}
	status := xy[0]
	if status == ' ' {
		status = xy[1]
	}
	switch status {
	case 'M', 'T', 'U':
		return "modified"
	case 'A':
		return "added"
	case 'D':
		return "deleted"
	case 'R', 'C':
		return "renamed"
	case '?':
		return "added"
	}
	return ""
}

func gitStatusLabel(kind, xy string) string {
	prefix := strings.TrimSpace(xy)
	if prefix == "" {
		prefix = kind
	}
	return strings.ToUpper(prefix)
}

func matchGenerateTarget(path string) string {
	path = strings.TrimPrefix(path, "./")
	for _, def := range generateTargetDefinitions {
		if def.matches(path) {
			return def.Key
		}
	}
	return ""
}

func (d generateTargetDefinition) matches(path string) bool {
	path = strings.TrimPrefix(path, "./")
	for _, dir := range d.Directories {
		dir = filepath.ToSlash(strings.TrimSuffix(dir, "/"))
		if dir == "" {
			continue
		}
		if path == dir || strings.HasPrefix(path, dir+"/") {
			return true
		}
	}
	for _, file := range d.Files {
		file = filepath.ToSlash(strings.TrimPrefix(file, "./"))
		if file == "" {
			continue
		}
		if path == file {
			return true
		}
	}
	return false
}

type snapshotRegistry struct {
	mu      sync.Mutex
	records map[string]snapshotRecord
}

type snapshotRecord struct {
	Root       string
	Created    time.Time
	TargetDirs map[string]string
}

var globalSnapshotRegistry snapshotRegistry

func prepareGenerateSnapshots(projectPath string, targetKeys []string) (snapshotRecord, error) {
	projectPath = filepath.Clean(projectPath)
	root := filepath.Join(projectPath, ".gpt-creator", "tmp", "generate-snapshots")
	if err := os.MkdirAll(root, 0o755); err != nil {
		return snapshotRecord{}, err
	}
	timestamp := time.Now().UTC().Format("20060102-150405")
	destRoot := filepath.Join(root, timestamp)
	if err := os.MkdirAll(destRoot, 0o755); err != nil {
		return snapshotRecord{}, err
	}

	record := snapshotRecord{
		Root:       destRoot,
		Created:    time.Now().UTC(),
		TargetDirs: make(map[string]string),
	}

	for _, key := range targetKeys {
		def, ok := generateTargetByKey(key)
		if !ok {
			continue
		}
		targetRoot := filepath.Join(destRoot, key)
		if err := copyTargetBaseline(projectPath, targetRoot, def); err != nil {
			return snapshotRecord{}, err
		}
		record.TargetDirs[key] = targetRoot
	}

	globalSnapshotRegistry.mu.Lock()
	defer globalSnapshotRegistry.mu.Unlock()
	if globalSnapshotRegistry.records == nil {
		globalSnapshotRegistry.records = make(map[string]snapshotRecord)
	}
	previous, ok := globalSnapshotRegistry.records[projectPath]
	if ok && previous.Root != "" && previous.Root != destRoot {
		_ = os.RemoveAll(previous.Root)
	}
	globalSnapshotRegistry.records[projectPath] = record
	return record, nil
}

func snapshotForProject(projectPath string) (snapshotRecord, bool) {
	globalSnapshotRegistry.mu.Lock()
	defer globalSnapshotRegistry.mu.Unlock()
	if globalSnapshotRegistry.records == nil {
		return snapshotRecord{}, false
	}
	record, ok := globalSnapshotRegistry.records[projectPath]
	return record, ok
}

func copyTargetBaseline(projectPath, destRoot string, def generateTargetDefinition) error {
	for _, rel := range def.Directories {
		rel = filepath.Clean(rel)
		if rel == "." {
			continue
		}
		src := filepath.Join(projectPath, rel)
		if info, err := os.Stat(src); err == nil && info.IsDir() {
			if err := copyDir(src, filepath.Join(destRoot, rel)); err != nil {
				return err
			}
		}
	}
	for _, rel := range def.Files {
		rel = filepath.Clean(rel)
		src := filepath.Join(projectPath, rel)
		if info, err := os.Stat(src); err == nil && !info.IsDir() {
			if err := copyFileExact(src, filepath.Join(destRoot, rel)); err != nil {
				return err
			}
		}
	}
	return nil
}

func copyDir(src, dest string) error {
	return filepath.WalkDir(src, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dest, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		if d.Type()&os.ModeSymlink != 0 {
			return copySymlink(path, target)
		}
		return copyFileExact(path, target)
	})
}

func copyFileExact(src, dest string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	mode := fs.FileMode(0o644)
	if info, err := os.Stat(src); err == nil {
		mode = info.Mode()
	}
	return os.WriteFile(dest, data, mode)
}

func copySymlink(src, dest string) error {
	target, err := os.Readlink(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	return os.Symlink(target, dest)
}

func collectSnapshotChanges(projectPath string) (generateChangeSet, error) {
	projectPath = filepath.Clean(projectPath)
	record, ok := snapshotForProject(projectPath)
	targetMap := make(map[string]generateTargetChanges)
	for _, def := range generateTargetDefinitions {
		targetMap[def.Key] = generateTargetChanges{Definition: def}
	}

	if !ok || record.Root == "" {
		return generateChangeSet{
			Source:  generateDiffSourceSnapshot,
			Targets: targetMap,
			Keys:    collectGenerateTargetKeys(),
			Warning: "Git repository not detected. Using temporary snapshots; diffs may be limited until you refresh snapshots.",
		}, nil
	}

	for _, def := range generateTargetDefinitions {
		entry := targetMap[def.Key]
		files, counts := compareSnapshotTarget(projectPath, record, def)
		entry.Files = files
		entry.Counts = counts
		sort.Slice(entry.Files, func(i, j int) bool {
			return entry.Files[i].Path < entry.Files[j].Path
		})
		targetMap[def.Key] = entry
	}

	return generateChangeSet{
		Source:        generateDiffSourceSnapshot,
		Targets:       targetMap,
		Keys:          collectGenerateTargetKeys(),
		Warning:       "Git repository not detected. Showing diffs from temporary snapshots; accuracy may be limited.",
		SnapshotRoot:  record.Root,
		SnapshotStamp: record.Created,
	}, nil
}

func collectGenerateTargetKeys() []string {
	keys := make([]string, 0, len(generateTargetDefinitions))
	for _, def := range generateTargetDefinitions {
		keys = append(keys, def.Key)
	}
	return keys
}

func compareSnapshotTarget(projectPath string, record snapshotRecord, def generateTargetDefinition) ([]generateFileChange, changeCounts) {
	var files []generateFileChange
	var counts changeCounts

	snapshotRoot := filepath.Join(record.Root, def.Key)
	state := newDirState()
	for _, rel := range def.Directories {
		rel = filepath.Clean(rel)
		if rel == "." {
			continue
		}
		cur := filepath.Join(projectPath, rel)
		base := filepath.Join(snapshotRoot, rel)
		state.collect(base, rel, true)
		state.collect(cur, rel, false)
	}
	for _, rel := range def.Files {
		rel = filepath.Clean(rel)
		cur := filepath.Join(projectPath, rel)
		base := filepath.Join(snapshotRoot, rel)
		state.collectFile(base, rel, true)
		state.collectFile(cur, rel, false)
	}

	for rel, info := range state.entries {
		change := determineSnapshotChange(rel, info)
		if change == nil {
			continue
		}
		change.TargetKey = def.Key
		change.DiffSource = generateDiffSourceSnapshot
		switch change.Status {
		case "added":
			counts.Added++
		case "deleted":
			counts.Deleted++
		case "renamed":
			counts.Renamed++
		default:
			counts.Modified++
		}
		files = append(files, *change)
	}

	return files, counts
}

type dirEntryState struct {
	mu      sync.Mutex
	entries map[string]*snapshotEntryState
}

type snapshotEntryState struct {
	SnapshotExists bool
	CurrentExists  bool
	SnapshotPath   string
	CurrentPath    string
	Same           bool
	HashSnapshot   []byte
	HashCurrent    []byte
}

func newDirState() *dirEntryState {
	return &dirEntryState{
		entries: make(map[string]*snapshotEntryState),
	}
}

func (s *dirEntryState) collect(root, rel string, snapshot bool) {
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return
	}
	filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			return nil
		}
		relPath, err := filepath.Rel(root, path)
		if err != nil {
			return nil
		}
		entryRel := relPath
		if strings.Trim(rel, ".") != "" {
			entryRel = filepath.Join(rel, relPath)
		}
		entryRel = filepath.ToSlash(entryRel)
		s.collectFile(path, entryRel, snapshot)
		return nil
	})
}

func (s *dirEntryState) collectFile(path, rel string, snapshot bool) {
	if rel == "" {
		return
	}
	rel = filepath.ToSlash(rel)
	state := s.ensure(rel)
	if snapshot {
		state.SnapshotExists = fileExists(path)
		state.SnapshotPath = path
		if state.SnapshotExists {
			state.HashSnapshot = fileHash(path)
		}
	} else {
		state.CurrentExists = fileExists(path)
		state.CurrentPath = path
		if state.CurrentExists {
			state.HashCurrent = fileHash(path)
		}
	}
	state.Same = bytes.Equal(state.HashSnapshot, state.HashCurrent)
}

func (s *dirEntryState) ensure(rel string) *snapshotEntryState {
	s.mu.Lock()
	defer s.mu.Unlock()
	state, ok := s.entries[rel]
	if !ok {
		state = &snapshotEntryState{}
		s.entries[rel] = state
	}
	return state
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func fileHash(path string) []byte {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	sum := sha256.Sum256(data)
	return sum[:]
}

func determineSnapshotChange(rel string, state *snapshotEntryState) *generateFileChange {
	switch {
	case state.SnapshotExists && !state.CurrentExists:
		return &generateFileChange{
			Path:        filepath.ToSlash(rel),
			Status:      "deleted",
			StatusLabel: "DELETED",
			SnapshotOld: state.SnapshotPath,
		}
	case !state.SnapshotExists && state.CurrentExists:
		return &generateFileChange{
			Path:        filepath.ToSlash(rel),
			Status:      "added",
			StatusLabel: "ADDED",
		}
	case state.SnapshotExists && state.CurrentExists && !state.Same:
		return &generateFileChange{
			Path:        filepath.ToSlash(rel),
			Status:      "modified",
			StatusLabel: "MODIFIED",
			SnapshotOld: state.SnapshotPath,
		}
	default:
		return nil
	}
}

func readFileForDiff(path string) string {
	if path == "" {
		return ""
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(data)
}

func currentFileFor(projectPath string, rel string) string {
	if rel == "" {
		return ""
	}
	rel = filepath.FromSlash(rel)
	return filepath.Join(projectPath, rel)
}
