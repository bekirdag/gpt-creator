package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"time"
)

type discoveredProject struct {
	Name  string
	Path  string
	Stats projectStats
}

type projectStats struct {
	StageLabel string
	NextStage  string
	StageIndex int
	StageTotal int
	Pipeline   []pipelineStepStatus

	TasksDone  int
	TasksTotal int

	VerifyPass  int
	VerifyTotal int

	LastRun time.Time
}

type pipelineStep struct {
	Label string
	Paths []string
}

type pipelineState string

const (
	pipelineStateDone    pipelineState = "done"
	pipelineStateActive  pipelineState = "active"
	pipelineStatePending pipelineState = "pending"
)

type pipelineArtifact struct {
	Path    string
	ModTime time.Time
	Size    int64
}

type pipelineStepStatus struct {
	Label       string
	State       pipelineState
	LastUpdated time.Time
	Duration    time.Duration
	Artifacts   []pipelineArtifact
}

var pipelineSteps = []pipelineStep{
	{Label: "Scan", Paths: []string{filepath.Join(".gpt-creator", "staging", "inputs")}},
	{Label: "Normalize", Paths: []string{filepath.Join(".gpt-creator", "staging", "normalize")}},
	{Label: "Plan", Paths: []string{filepath.Join(".gpt-creator", "staging", "plan")}},
	{Label: "Generate", Paths: []string{"apps"}},
	{Label: "DB", Paths: []string{
		"db",
		filepath.Join(".gpt-creator", "staging", "db-dump"),
		filepath.Join(".gpt-creator", "staging", "db_dump"),
		filepath.Join(".gpt-creator", "staging", "plan", "create-db-dump", "sql"),
	}},
	{Label: "Run", Paths: []string{"docker"}},
	{Label: "Verify", Paths: []string{filepath.Join(".gpt-creator", "staging", "verify")}},
}

func discoverProjects(root string) ([]discoveredProject, error) {
	root = filepath.Clean(root)
	info, err := os.Stat(root)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, nil
	}

	var projects []discoveredProject
	seen := make(map[string]struct{})

	if isProjectDir(root) {
		projects = append(projects, buildProject(root))
		seen[root] = struct{}{}
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		return projects, err
	}

	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		path := filepath.Join(root, entry.Name())
		if _, ok := seen[path]; ok {
			continue
		}
		if isProjectDir(path) {
			projects = append(projects, buildProject(path))
		}
	}

	sort.Slice(projects, func(i, j int) bool {
		return projects[i].Name < projects[j].Name
	})
	return projects, nil
}

func buildProject(path string) discoveredProject {
	name := filepath.Base(path)
	stats := collectProjectStats(path)
	return discoveredProject{
		Name:  name,
		Path:  path,
		Stats: stats,
	}
}

func isProjectDir(path string) bool {
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		return false
	}

	if dirInfo, err := os.Stat(filepath.Join(path, ".gpt-creator")); err == nil && dirInfo.IsDir() {
		return true
	}
	if _, err := os.Stat(filepath.Join(path, ".gptcreatorrc")); err == nil {
		return true
	}
	return false
}

func collectProjectStats(path string) projectStats {
	stats := projectStats{
		StageIndex: 0,
		StageTotal: len(pipelineSteps),
		Pipeline:   make([]pipelineStepStatus, 0, len(pipelineSteps)),
	}

	completed := 0
	firstPending := true
	for _, step := range pipelineSteps {
		status := pipelineStepStatus{Label: step.Label}
		artifacts, present := collectStepArtifacts(path, step.Paths)
		status.Artifacts = artifacts
		if present {
			status.State = pipelineStateDone
			if len(artifacts) > 0 {
				status.LastUpdated = artifacts[0].ModTime
			} else {
				status.LastUpdated = detectStepTimestamp(path, step.Paths)
			}
			completed++
		} else {
			if firstPending {
				status.State = pipelineStateActive
				firstPending = false
			} else {
				status.State = pipelineStatePending
			}
		}
		stats.Pipeline = append(stats.Pipeline, status)
	}

	stats.StageIndex = completed
	if completed > 0 {
		stats.StageLabel = pipelineSteps[completed-1].Label
		for i := 0; i < completed && i < len(stats.Pipeline); i++ {
			stats.Pipeline[i].Duration = time.Since(stats.Pipeline[i].LastUpdated)
		}
	}
	if completed == 0 {
		stats.StageLabel = "Not started"
	}
	if completed < len(pipelineSteps) {
		stats.NextStage = pipelineSteps[completed].Label
	}

	stats.TasksDone, stats.TasksTotal = gatherTaskMetrics(path)
	stats.VerifyPass, stats.VerifyTotal = gatherVerifyMetrics(path)
	stats.LastRun = latestProjectModTime(path)
	return stats
}

func gatherTaskMetrics(root string) (done, total int) {
	file := filepath.Join(root, ".gpt-creator", "staging", "plan", "tasks", "progress.json")
	data, err := os.ReadFile(file)
	if err != nil {
		return 0, 0
	}

	var payload struct {
		Done      int `json:"done"`
		Completed int `json:"completed"`
		Total     int `json:"total"`
	}
	if err := json.Unmarshal(data, &payload); err == nil {
		done := payload.Done
		if done == 0 {
			done = payload.Completed
		}
		if payload.Total == 0 && payload.Completed > 0 {
			return done, payload.Completed
		}
		return done, payload.Total
	}

	m := make(map[string]int)
	if err := json.Unmarshal(data, &m); err == nil {
		done := m["done"]
		if done == 0 {
			done = m["completed"]
		}
		total := m["total"]
		if total == 0 {
			total = m["count"]
		}
		return done, total
	}
	return 0, 0
}

func gatherVerifyMetrics(root string) (passed, total int) {
	file := filepath.Join(root, ".gpt-creator", "staging", "verify", "summary.json")
	data, err := os.ReadFile(file)
	if err != nil {
		return 0, 0
	}

	var payload struct {
		Stats  verifyStats `json:"stats"`
		Checks map[string]struct {
			Status string `json:"status"`
		} `json:"checks"`
		Passed int `json:"passed"`
		Total  int `json:"total"`
	}
	if err := json.Unmarshal(data, &payload); err == nil {
		if payload.Stats.Total > 0 {
			return payload.Stats.Passed, payload.Stats.Total
		}
		if payload.Total > 0 && payload.Passed > 0 {
			return payload.Passed, payload.Total
		}
		if len(payload.Checks) > 0 {
			total := len(payload.Checks)
			passed := 0
			for _, check := range payload.Checks {
				if normalizeVerifyStatus(check.Status) == "pass" {
					passed++
				}
			}
			return passed, total
		}
	}

	m := make(map[string]int)
	if err := json.Unmarshal(data, &m); err == nil {
		passed := m["passed"]
		if passed == 0 {
			passed = m["success"]
		}
		total := m["total"]
		if total == 0 {
			total = m["checks"]
		}
		return passed, total
	}

	return 0, 0
}

func latestProjectModTime(root string) time.Time {
	var latest time.Time

	candidates := []string{
		filepath.Join(root, ".gpt-creator"),
		filepath.Join(root, "apps"),
		filepath.Join(root, "db"),
		filepath.Join(root, "docker"),
		filepath.Join(root, ".gpt-creator", "staging", "verify"),
	}

	for _, path := range candidates {
		info, err := os.Stat(path)
		if err != nil {
			continue
		}
		if info.ModTime().After(latest) {
			latest = info.ModTime()
		}
	}
	return latest
}

const maxArtifactsPerStep = 6

func collectStepArtifacts(root string, relative []string) ([]pipelineArtifact, bool) {
	var artifacts []pipelineArtifact
	found := false

	for _, rel := range relative {
		abs := filepath.Join(root, rel)
		info, err := os.Stat(abs)
		if err != nil {
			continue
		}
		found = true
		if info.IsDir() {
			dirArtifacts := collectDirArtifacts(root, abs, info)
			artifacts = append(artifacts, dirArtifacts...)
		} else {
			artifacts = append(artifacts, pipelineArtifact{
				Path:    relativePath(root, abs),
				ModTime: info.ModTime(),
				Size:    info.Size(),
			})
		}
	}

	sort.Slice(artifacts, func(i, j int) bool {
		return artifacts[i].ModTime.After(artifacts[j].ModTime)
	})
	if len(artifacts) > maxArtifactsPerStep {
		artifacts = artifacts[:maxArtifactsPerStep]
	}
	return artifacts, found
}

func collectDirArtifacts(root, dir string, dirInfo os.FileInfo) []pipelineArtifact {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return []pipelineArtifact{{
			Path:    relativePath(root, dir),
			ModTime: dirInfo.ModTime(),
			Size:    dirInfo.Size(),
		}}
	}

	type entryWithInfo struct {
		path string
		info os.FileInfo
	}
	var gathered []entryWithInfo
	for _, entry := range entries {
		full := filepath.Join(dir, entry.Name())
		info, err := os.Stat(full)
		if err != nil {
			continue
		}
		gathered = append(gathered, entryWithInfo{path: full, info: info})
	}

	sort.Slice(gathered, func(i, j int) bool {
		return gathered[i].info.ModTime().After(gathered[j].info.ModTime())
	})

	var artifacts []pipelineArtifact
	for idx, entry := range gathered {
		if idx >= maxArtifactsPerStep {
			break
		}
		artifacts = append(artifacts, pipelineArtifact{
			Path:    relativePath(root, entry.path),
			ModTime: entry.info.ModTime(),
			Size:    entry.info.Size(),
		})
	}

	if len(artifacts) == 0 {
		artifacts = append(artifacts, pipelineArtifact{
			Path:    relativePath(root, dir),
			ModTime: dirInfo.ModTime(),
			Size:    dirInfo.Size(),
		})
	}
	return artifacts
}

func relativePath(root, full string) string {
	if rel, err := filepath.Rel(root, full); err == nil {
		return filepath.ToSlash(rel)
	}
	return filepath.ToSlash(full)
}

func detectStepTimestamp(root string, relative []string) time.Time {
	var latest time.Time
	for _, rel := range relative {
		abs := filepath.Join(root, rel)
		info, err := os.Stat(abs)
		if err != nil {
			continue
		}
		if info.ModTime().After(latest) {
			latest = info.ModTime()
		}
	}
	return latest
}
