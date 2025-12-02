package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type verifyCheckDefinition struct {
	Name           string
	Label          string
	Command        []string
	RequiresDocker bool
}

var verifyCheckDefinitions = []verifyCheckDefinition{
	{
		Name:           "acceptance",
		Label:          "Acceptance",
		Command:        []string{"verify", "acceptance"},
		RequiresDocker: true,
	},
	{
		Name:           "openapi",
		Label:          "OpenAPI",
		Command:        []string{"verify", "openapi"},
		RequiresDocker: false,
	},
	{
		Name:           "lighthouse",
		Label:          "Lighthouse",
		Command:        []string{"verify", "lighthouse"},
		RequiresDocker: true,
	},
	{
		Name:           "a11y",
		Label:          "Accessibility",
		Command:        []string{"verify", "a11y"},
		RequiresDocker: true,
	},
	{
		Name:           "consent",
		Label:          "Consent",
		Command:        []string{"verify", "consent"},
		RequiresDocker: false,
	},
	{
		Name:           "program-filters",
		Label:          "Program Filters",
		Command:        []string{"verify", "program-filters"},
		RequiresDocker: false,
	},
}

func verifyDefinitionByName(name string) (verifyCheckDefinition, bool) {
	for _, def := range verifyCheckDefinitions {
		if def.Name == name {
			return def, true
		}
	}
	return verifyCheckDefinition{}, false
}

func verifyCheckOrder() []string {
	order := make([]string, 0, len(verifyCheckDefinitions))
	for _, def := range verifyCheckDefinitions {
		order = append(order, def.Name)
	}
	return order
}

type verifyStats struct {
	Passed  int `json:"passed"`
	Failed  int `json:"failed"`
	Skipped int `json:"skipped"`
	Total   int `json:"total"`
}

type verifyCheck struct {
	Name            string
	Label           string
	Status          string
	Message         string
	Log             string
	Report          string
	Score           *float64
	Updated         time.Time
	RunKind         string
	DurationSeconds float64
}

type verifySummary struct {
	Checks      map[string]verifyCheck
	Order       []string
	Stats       verifyStats
	LastRunKind string
	LastUpdated time.Time
}

func (s *verifySummary) recomputeStats() {
	stats := verifyStats{}
	for _, check := range s.Checks {
		stats.Total++
		switch normalizeVerifyStatus(check.Status) {
		case "pass":
			stats.Passed++
		case "skip":
			stats.Skipped++
		case "fail":
			stats.Failed++
		default:
			// pending/unknown counted toward total only
		}
	}
	s.Stats = stats
}

func normalizeVerifyStatus(status string) string {
	trimmed := strings.TrimSpace(strings.ToLower(status))
	switch trimmed {
	case "pass", "passed", "ok", "success":
		return "pass"
	case "skip", "skipped":
		return "skip"
	case "fail", "failed", "error":
		return "fail"
	case "", "pending", "unknown":
		return "pending"
	default:
		return trimmed
	}
}

func verifyStatusIcon(status string) string {
	switch normalizeVerifyStatus(status) {
	case "pass":
		return "✓"
	case "skip":
		return "●"
	case "fail":
		return "✗"
	default:
		return "…"
	}
}

func verifyStatusLabel(status string) string {
	switch normalizeVerifyStatus(status) {
	case "pass":
		return "Pass"
	case "skip":
		return "Skipped"
	case "fail":
		return "Fail"
	default:
		return "Pending"
	}
}

func overallVerifyStatus(summary verifySummary) string {
	if summary.Stats.Total == 0 {
		return "pending"
	}
	if summary.Stats.Failed > 0 {
		return "fail"
	}
	if summary.Stats.Passed >= summary.Stats.Total {
		return "pass"
	}
	if summary.Stats.Passed+summary.Stats.Skipped >= summary.Stats.Total {
		return "skip"
	}
	return "pending"
}

type verifySummaryFile struct {
	Checks      map[string]verifyCheckFile `json:"checks"`
	Stats       verifyStats                `json:"stats"`
	Order       []string                   `json:"order"`
	LastRunKind string                     `json:"last_run_kind"`
	LastUpdated string                     `json:"last_updated"`
}

type verifyCheckFile struct {
	Name            string   `json:"name"`
	Label           string   `json:"label"`
	Status          string   `json:"status"`
	Message         string   `json:"message"`
	Log             string   `json:"log"`
	Report          string   `json:"report"`
	Score           *float64 `json:"score"`
	Updated         string   `json:"updated"`
	RunKind         string   `json:"run_kind"`
	DurationSeconds float64  `json:"duration_seconds"`
}

func loadVerifySummary(projectPath string) verifySummary {
	summary := verifySummary{
		Checks: make(map[string]verifyCheck),
		Order:  verifyCheckOrder(),
	}

	for _, def := range verifyCheckDefinitions {
		summary.Checks[def.Name] = verifyCheck{
			Name:    def.Name,
			Label:   def.Label,
			Status:  "pending",
			Message: "Not run yet.",
		}
	}

	file := filepath.Join(projectPath, ".gpt-creator", "staging", "verify", "summary.json")
	data, err := os.ReadFile(file)
	if err != nil {
		summary.recomputeStats()
		return summary
	}

	var payload verifySummaryFile
	if err := json.Unmarshal(data, &payload); err != nil {
		summary.recomputeStats()
		return summary
	}

	if len(payload.Order) > 0 {
		order := make([]string, 0, len(payload.Order))
		seen := make(map[string]bool)
		for _, name := range payload.Order {
			name = strings.TrimSpace(name)
			if name == "" || seen[name] {
				continue
			}
			order = append(order, name)
			seen[name] = true
		}
		for _, def := range verifyCheckDefinitions {
			if !seen[def.Name] {
				order = append(order, def.Name)
			}
		}
		summary.Order = order
	}

	for name, entry := range payload.Checks {
		def, ok := verifyDefinitionByName(name)
		if !ok {
			def = verifyCheckDefinition{
				Name:    name,
				Label:   entry.Label,
				Command: []string{"verify", name},
			}
			if def.Label == "" {
				def.Label = strings.Title(strings.ReplaceAll(name, "-", " "))
			}
		}
		parsed := verifyCheck{
			Name:            def.Name,
			Label:           chooseNonEmpty(entry.Label, def.Label),
			Status:          normalizeVerifyStatus(entry.Status),
			Message:         strings.TrimSpace(entry.Message),
			Log:             strings.TrimSpace(entry.Log),
			Report:          strings.TrimSpace(entry.Report),
			Score:           entry.Score,
			RunKind:         strings.TrimSpace(entry.RunKind),
			DurationSeconds: entry.DurationSeconds,
		}
		if ts := strings.TrimSpace(entry.Updated); ts != "" {
			if parsedTime, err := time.Parse(time.RFC3339, ts); err == nil {
				parsed.Updated = parsedTime
			}
		}
		summary.Checks[def.Name] = parsed
	}

	if payload.LastRunKind != "" {
		summary.LastRunKind = payload.LastRunKind
	}
	if ts := strings.TrimSpace(payload.LastUpdated); ts != "" {
		if parsed, err := time.Parse(time.RFC3339, ts); err == nil {
			summary.LastUpdated = parsed
		}
	}

	if payload.Stats.Total > 0 {
		summary.Stats = payload.Stats
	} else {
		summary.recomputeStats()
	}
	if summary.Stats.Total == 0 {
		summary.recomputeStats()
	}
	return summary
}

func chooseNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func verifySummaryForProject(project *discoveredProject) verifySummary {
	if project == nil {
		return verifySummary{
			Checks: make(map[string]verifyCheck),
			Order:  verifyCheckOrder(),
		}
	}
	return loadVerifySummary(project.Path)
}

func formatVerifyDuration(seconds float64) string {
	if seconds <= 0 {
		return ""
	}
	if seconds < 60 {
		return fmt.Sprintf("%.0fs", seconds)
	}
	minutes := seconds / 60
	if minutes < 60 {
		return fmt.Sprintf("%.1fm", minutes)
	}
	hours := minutes / 60
	return fmt.Sprintf("%.1fh", hours)
}

func sortedVerifyChecks(summary verifySummary) []verifyCheck {
	list := make([]verifyCheck, 0, len(summary.Checks))
	for _, name := range summary.Order {
		if check, ok := summary.Checks[name]; ok {
			list = append(list, check)
		}
	}
	if len(list) != len(summary.Checks) {
		extras := make([]verifyCheck, 0)
		for name, check := range summary.Checks {
			found := false
			for _, existing := range summary.Order {
				if existing == name {
					found = true
					break
				}
			}
			if !found {
				extras = append(extras, check)
			}
		}
		sort.Slice(extras, func(i, j int) bool {
			return extras[i].Name < extras[j].Name
		})
		list = append(list, extras...)
	}
	return list
}
