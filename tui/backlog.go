package main

import (
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

var (
	errBacklogMissing = errors.New("tasks backlog database missing")
)

type backlogNodeType int

const (
	backlogNodeInvalid backlogNodeType = iota
	backlogNodeEpic
	backlogNodeStory
	backlogNodeTask
)

type backlogNode struct {
	Type         backlogNodeType
	EpicKey      string
	StorySlug    string
	TaskPosition int
}

func (n backlogNode) IsZero() bool {
	return n.Type == backlogNodeInvalid
}

func (n backlogNode) Equals(other backlogNode) bool {
	return n.Type == other.Type &&
		n.EpicKey == other.EpicKey &&
		n.StorySlug == other.StorySlug &&
		n.TaskPosition == other.TaskPosition
}

type backlogTypeFilter int

const (
	backlogTypeFilterAll backlogTypeFilter = iota
	backlogTypeFilterEpics
	backlogTypeFilterStories
	backlogTypeFilterTasks
)

func (f backlogTypeFilter) String() string {
	switch f {
	case backlogTypeFilterEpics:
		return "Epics"
	case backlogTypeFilterStories:
		return "Stories"
	case backlogTypeFilterTasks:
		return "Tasks"
	default:
		return "All"
	}
}

func (f backlogTypeFilter) Next() backlogTypeFilter {
	switch f {
	case backlogTypeFilterAll:
		return backlogTypeFilterEpics
	case backlogTypeFilterEpics:
		return backlogTypeFilterStories
	case backlogTypeFilterStories:
		return backlogTypeFilterTasks
	default:
		return backlogTypeFilterAll
	}
}

type backlogStatusFilter int

const (
	backlogStatusFilterAll backlogStatusFilter = iota
	backlogStatusFilterTodo
	backlogStatusFilterDoing
	backlogStatusFilterDone
	backlogStatusFilterBlocked
)

func (f backlogStatusFilter) String() string {
	switch f {
	case backlogStatusFilterTodo:
		return "Todo"
	case backlogStatusFilterDoing:
		return "Doing"
	case backlogStatusFilterDone:
		return "Done"
	case backlogStatusFilterBlocked:
		return "Blocked"
	default:
		return "All"
	}
}

func (f backlogStatusFilter) Next() backlogStatusFilter {
	switch f {
	case backlogStatusFilterAll:
		return backlogStatusFilterTodo
	case backlogStatusFilterTodo:
		return backlogStatusFilterDoing
	case backlogStatusFilterDoing:
		return backlogStatusFilterDone
	case backlogStatusFilterDone:
		return backlogStatusFilterBlocked
	default:
		return backlogStatusFilterAll
	}
}

type backlogData struct {
	ProjectPath string
	DBPath      string
	Epics       []*backlogEpic
	Stories     []*backlogStory
	Tasks       []*backlogTask
	Rows        []backlogRow
	Bundles     map[string]string
	Summary     backlogSummary
	LoadedAt    time.Time
}

type backlogSummary struct {
	Epics         int
	Stories       int
	Tasks         int
	DoneTasks     int
	DoingTasks    int
	TodoTasks     int
	BlockedTasks  int
	LastUpdatedAt time.Time
}

type backlogEpic struct {
	Key        string
	Title      string
	Slug       string
	UpdatedAt  time.Time
	StoryCount int
	TaskCount  int
	Status     string
}

type backlogStory struct {
	Slug         string
	Key          string
	Title        string
	EpicKey      string
	EpicTitle    string
	Status       string
	UpdatedAt    time.Time
	Completed    int
	Total        int
	LastRun      string
	AssigneeHint string
}

type backlogTask struct {
	StorySlug   string
	Position    int
	ID          string
	Title       string
	Description string
	Status      string
	Estimate    string
	Assignee    string
	Acceptance  string
	UpdatedAt   time.Time
	LastRun     string
	Endpoints   string
}

type backlogRow struct {
	Node      backlogNode
	Depth     int
	Key       string
	Title     string
	Type      backlogNodeType
	Status    string
	Assignee  string
	UpdatedAt time.Time
}

func backlogDBPath(projectPath string) string {
	return filepath.Join(projectPath, ".gpt-creator", "staging", "plan", "tasks", "tasks.db")
}

func loadBacklogData(projectPath string) (*backlogData, error) {
	dbPath := backlogDBPath(projectPath)
	if _, err := os.Stat(dbPath); err != nil {
		if os.IsNotExist(err) {
			return nil, errBacklogMissing
		}
		return nil, err
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	db.SetMaxOpenConns(1)

	data := &backlogData{
		ProjectPath: projectPath,
		DBPath:      dbPath,
		Bundles:     make(map[string]string),
		LoadedAt:    time.Now(),
	}

	epicIndex := make(map[string]*backlogEpic)
	rows, err := db.Query(`
		SELECT epic_key, COALESCE(title, ''), COALESCE(slug, ''), 
		       COALESCE(updated_at, created_at) 
		  FROM epics
		 ORDER BY created_at, epic_key
	`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var key, title, slug, ts string
		if err := rows.Scan(&key, &title, &slug, &ts); err != nil {
			rows.Close()
			return nil, err
		}
		epic := &backlogEpic{
			Key:       strings.TrimSpace(key),
			Title:     strings.TrimSpace(title),
			Slug:      strings.TrimSpace(slug),
			UpdatedAt: parseBacklogTime(ts),
		}
		epicIndex[epic.Key] = epic
		data.Epics = append(data.Epics, epic)
	}
	rows.Close()

	storyIndex := make(map[string]*backlogStory)
	rows, err = db.Query(`
		SELECT story_slug,
		       COALESCE(story_key, ''),
		       COALESCE(story_title, ''),
		       COALESCE(epic_key, ''),
		       COALESCE(epic_title, ''),
		       COALESCE(status, ''),
		       COALESCE(updated_at, created_at),
		       COALESCE(completed_tasks, 0),
		       COALESCE(total_tasks, 0),
		       COALESCE(last_run, '')
		  FROM stories
		 ORDER BY epic_key, sequence, story_slug
	`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var slug, storyKey, title, epicKey, epicTitle, status, ts, lastRun string
		var completed, total int
		if err := rows.Scan(&slug, &storyKey, &title, &epicKey, &epicTitle, &status, &ts, &completed, &total, &lastRun); err != nil {
			rows.Close()
			return nil, err
		}
		story := &backlogStory{
			Slug:         strings.TrimSpace(slug),
			Key:          strings.TrimSpace(storyKey),
			Title:        strings.TrimSpace(title),
			EpicKey:      strings.TrimSpace(epicKey),
			EpicTitle:    strings.TrimSpace(epicTitle),
			Status:       normalizeBacklogStatus(status),
			UpdatedAt:    parseBacklogTime(ts),
			Completed:    completed,
			Total:        total,
			LastRun:      strings.TrimSpace(lastRun),
			AssigneeHint: "",
		}
		storyIndex[story.Slug] = story
		data.Stories = append(data.Stories, story)
		if epic := epicIndex[story.EpicKey]; epic != nil {
			epic.StoryCount++
			if story.Total > 0 {
				epic.TaskCount += story.Total
			}
			if story.Status != "" {
				epic.Status = aggregateStatus(epic.Status, story.Status)
			}
			if story.UpdatedAt.After(epic.UpdatedAt) {
				epic.UpdatedAt = story.UpdatedAt
			}
		}
	}
	rows.Close()

	rows, err = db.Query(`
		SELECT story_slug,
		       position,
		       COALESCE(task_id, ''),
		       COALESCE(title, ''),
		       COALESCE(description, ''),
		       COALESCE(status, ''),
		       COALESCE(assignee_text, ''),
		       COALESCE(estimate, ''),
		       COALESCE(acceptance_text, ''),
		       COALESCE(updated_at, created_at),
		       COALESCE(last_run, ''),
		       COALESCE(endpoints, '')
		  FROM tasks
		 ORDER BY story_slug, position
	`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var slug, taskID, title, desc, status, assignee, estimate, acceptance, ts, lastRun, endpoints string
		var position int
		if err := rows.Scan(&slug, &position, &taskID, &title, &desc, &status, &assignee, &estimate, &acceptance, &ts, &lastRun, &endpoints); err != nil {
			rows.Close()
			return nil, err
		}
		task := &backlogTask{
			StorySlug:   strings.TrimSpace(slug),
			Position:    position,
			ID:          strings.TrimSpace(taskID),
			Title:       strings.TrimSpace(title),
			Description: strings.TrimSpace(desc),
			Status:      normalizeBacklogStatus(status),
			Estimate:    strings.TrimSpace(estimate),
			Assignee:    strings.TrimSpace(assignee),
			Acceptance:  strings.TrimSpace(acceptance),
			UpdatedAt:   parseBacklogTime(ts),
			LastRun:     strings.TrimSpace(lastRun),
			Endpoints:   strings.TrimSpace(endpoints),
		}
		data.Tasks = append(data.Tasks, task)
		if story := storyIndex[task.StorySlug]; story != nil {
			story.Total++
			if task.Status == "done" {
				story.Completed++
			}
			if task.Assignee != "" {
				story.AssigneeHint = task.Assignee
			}
			if task.UpdatedAt.After(story.UpdatedAt) {
				story.UpdatedAt = task.UpdatedAt
			}
			if task.LastRun != "" {
				story.LastRun = task.LastRun
			}
			story.Status = aggregateStatus(story.Status, task.Status)
			if epic := epicIndex[story.EpicKey]; epic != nil {
				epic.TaskCount++
				epic.Status = aggregateStatus(epic.Status, task.Status)
				if task.UpdatedAt.After(epic.UpdatedAt) {
					epic.UpdatedAt = task.UpdatedAt
				}
			}
		}
		data.Summary.Tasks++
		switch task.Status {
		case "done":
			data.Summary.DoneTasks++
		case "doing":
			data.Summary.DoingTasks++
		case "blocked":
			data.Summary.BlockedTasks++
		default:
			data.Summary.TodoTasks++
		}
		if !task.UpdatedAt.IsZero() && task.UpdatedAt.After(data.Summary.LastUpdatedAt) {
			data.Summary.LastUpdatedAt = task.UpdatedAt
		}
	}
	rows.Close()

	data.Summary.Epics = len(data.Epics)
	data.Summary.Stories = len(data.Stories)

	sort.Slice(data.Epics, func(i, j int) bool {
		return data.Epics[i].Key < data.Epics[j].Key
	})
	sort.Slice(data.Stories, func(i, j int) bool {
		if data.Stories[i].EpicKey == data.Stories[j].EpicKey {
			return data.Stories[i].Slug < data.Stories[j].Slug
		}
		return data.Stories[i].EpicKey < data.Stories[j].EpicKey
	})
	sort.Slice(data.Tasks, func(i, j int) bool {
		if data.Tasks[i].StorySlug == data.Tasks[j].StorySlug {
			return data.Tasks[i].Position < data.Tasks[j].Position
		}
		return data.Tasks[i].StorySlug < data.Tasks[j].StorySlug
	})

	data.Rows = buildBacklogRows(data)
	data.Bundles = loadTaskBundles(projectPath)

	return data, nil
}

func buildBacklogRows(data *backlogData) []backlogRow {
	if data == nil {
		return nil
	}
	var rows []backlogRow
	storiesByEpic := make(map[string][]*backlogStory)
	for _, story := range data.Stories {
		storiesByEpic[story.EpicKey] = append(storiesByEpic[story.EpicKey], story)
	}
	tasksByStory := make(map[string][]*backlogTask)
	for _, task := range data.Tasks {
		tasksByStory[task.StorySlug] = append(tasksByStory[task.StorySlug], task)
	}

	for _, epic := range data.Epics {
		row := backlogRow{
			Node: backlogNode{
				Type:    backlogNodeEpic,
				EpicKey: epic.Key,
			},
			Depth:     0,
			Key:       canonicalEpicKey(epic),
			Title:     safeTitle(epic.Title),
			Type:      backlogNodeEpic,
			Status:    displayStatus(epic.Status),
			Assignee:  "",
			UpdatedAt: epic.UpdatedAt,
		}
		rows = append(rows, row)

		stories := storiesByEpic[epic.Key]
		sort.Slice(stories, func(i, j int) bool {
			return stories[i].Slug < stories[j].Slug
		})
		for _, story := range stories {
			storyRow := backlogRow{
				Node: backlogNode{
					Type:      backlogNodeStory,
					EpicKey:   epic.Key,
					StorySlug: story.Slug,
				},
				Depth:     1,
				Key:       canonicalStoryKey(story),
				Title:     safeTitle(story.Title),
				Type:      backlogNodeStory,
				Status:    displayStatus(story.Status),
				Assignee:  story.AssigneeHint,
				UpdatedAt: story.UpdatedAt,
			}
			rows = append(rows, storyRow)

			tasks := tasksByStory[story.Slug]
			sort.Slice(tasks, func(i, j int) bool {
				return tasks[i].Position < tasks[j].Position
			})
			for _, task := range tasks {
				taskRow := backlogRow{
					Node: backlogNode{
						Type:         backlogNodeTask,
						EpicKey:      epic.Key,
						StorySlug:    story.Slug,
						TaskPosition: task.Position,
					},
					Depth:     2,
					Key:       canonicalTaskKey(task),
					Title:     safeTitle(task.Title),
					Type:      backlogNodeTask,
					Status:    displayStatus(task.Status),
					Assignee:  task.Assignee,
					UpdatedAt: task.UpdatedAt,
				}
				rows = append(rows, taskRow)
			}
		}
	}
	return rows
}

func canonicalEpicKey(epic *backlogEpic) string {
	if epic == nil {
		return ""
	}
	if epic.Key != "" {
		return epic.Key
	}
	if epic.Slug != "" {
		return epic.Slug
	}
	return "-"
}

func canonicalStoryKey(story *backlogStory) string {
	if story == nil {
		return ""
	}
	if story.Key != "" {
		return story.Key
	}
	if story.Slug != "" {
		return story.Slug
	}
	return "-"
}

func canonicalTaskKey(task *backlogTask) string {
	if task == nil {
		return ""
	}
	if task.ID != "" {
		return task.ID
	}
	return fmt.Sprintf("#%d", task.Position)
}

func safeTitle(title string) string {
	if strings.TrimSpace(title) == "" {
		return "(untitled)"
	}
	return title
}

func parseBacklogTime(value string) time.Time {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}
	}
	formats := []string{
		time.RFC3339,
		"2006-01-02 15:04:05",
		"2006-01-02T15:04:05",
	}
	for _, layout := range formats {
		if ts, err := time.Parse(layout, value); err == nil {
			return ts
		}
	}
	return time.Time{}
}

func normalizeBacklogStatus(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "complete", "completed", "done":
		return "done"
	case "in-progress", "in progress", "doing":
		return "doing"
	case "blocked":
		return "blocked"
	case "todo":
		return "todo"
	case "pending", "":
		return "todo"
	default:
		return strings.ToLower(strings.TrimSpace(status))
	}
}

func displayStatus(status string) string {
	norm := normalizeBacklogStatus(status)
	switch norm {
	case "doing":
		return "doing"
	case "done":
		return "done"
	case "blocked":
		return "blocked"
	default:
		return "todo"
	}
}

func aggregateStatus(existing, incoming string) string {
	current := normalizeBacklogStatus(existing)
	next := normalizeBacklogStatus(incoming)
	if current == "" || current == "todo" {
		return next
	}
	if next == "blocked" {
		return "blocked"
	}
	if current == "blocked" {
		return "blocked"
	}
	if next == "doing" {
		if current == "done" {
			return "doing"
		}
		return "doing"
	}
	if next == "done" && current != "blocked" && current != "doing" {
		return "done"
	}
	return current
}

func (data *backlogData) StoryBySlug(slug string) *backlogStory {
	for _, story := range data.Stories {
		if story.Slug == slug {
			return story
		}
	}
	return nil
}

func (data *backlogData) EpicByKey(key string) *backlogEpic {
	for _, epic := range data.Epics {
		if epic.Key == key {
			return epic
		}
	}
	return nil
}

func (data *backlogData) TaskByNode(node backlogNode) *backlogTask {
	if node.Type != backlogNodeTask {
		return nil
	}
	for _, task := range data.Tasks {
		if task.StorySlug == node.StorySlug && task.Position == node.TaskPosition {
			return task
		}
	}
	return nil
}

func (data *backlogData) RowByNode(node backlogNode) (backlogRow, bool) {
	if data == nil {
		return backlogRow{}, false
	}
	for _, row := range data.Rows {
		if row.Node.Equals(node) {
			return row, true
		}
	}
	return backlogRow{}, false
}

func pruneBacklogEpics(dbPath string, keep []string) error {
	if len(keep) == 0 {
		return nil
	}
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return err
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	placeholders := strings.Repeat("?,", len(keep))
	placeholders = strings.TrimSuffix(placeholders, ",")
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback()
		}
	}()
	args := make([]any, len(keep))
	for i, key := range keep {
		args[i] = key
	}
	if _, err = tx.Exec("DELETE FROM tasks WHERE epic_key NOT IN ("+placeholders+")", args...); err != nil {
		return err
	}
	if _, err = tx.Exec("DELETE FROM stories WHERE epic_key NOT IN ("+placeholders+")", args...); err != nil {
		return err
	}
	if _, err = tx.Exec("DELETE FROM epics WHERE epic_key NOT IN ("+placeholders+")", args...); err != nil {
		return err
	}
	return tx.Commit()
}

func (data *backlogData) FilteredRows(typeFilter backlogTypeFilter, statusFilter backlogStatusFilter, scope backlogNode) []backlogRow {
	if data == nil {
		return nil
	}
	var filtered []backlogRow
	for _, row := range data.Rows {
		if !scope.IsZero() {
			switch scope.Type {
			case backlogNodeEpic:
				if row.Node.EpicKey != scope.EpicKey {
					continue
				}
			case backlogNodeStory:
				if row.Node.Type == backlogNodeEpic {
					if row.Node.EpicKey != scope.EpicKey {
						continue
					}
				} else if row.Node.StorySlug != scope.StorySlug {
					continue
				}
			case backlogNodeTask:
				if !row.Node.Equals(scope) {
					continue
				}
			}
		}
		if !typeMatchesFilter(row.Type, typeFilter) {
			continue
		}
		if !statusMatchesFilter(row.Status, statusFilter) {
			continue
		}
		filtered = append(filtered, row)
	}
	return filtered
}

func typeMatchesFilter(t backlogNodeType, filter backlogTypeFilter) bool {
	switch filter {
	case backlogTypeFilterEpics:
		return t == backlogNodeEpic
	case backlogTypeFilterStories:
		return t == backlogNodeStory
	case backlogTypeFilterTasks:
		return t == backlogNodeTask
	default:
		return true
	}
}

func statusMatchesFilter(status string, filter backlogStatusFilter) bool {
	switch filter {
	case backlogStatusFilterTodo:
		return status == "todo"
	case backlogStatusFilterDoing:
		return status == "doing"
	case backlogStatusFilterDone:
		return status == "done"
	case backlogStatusFilterBlocked:
		return status == "blocked"
	default:
		return true
	}
}

func loadTaskBundles(projectPath string) map[string]string {
	candidates := []string{
		filepath.Join(projectPath, ".gpt-creator", "staging", "plan", "tasks", "tasks_generated.json"),
		filepath.Join(projectPath, ".gpt-creator", "staging", "plan", "create-jira-tasks", "json", "tasks_payload.json"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			if payloads := parseTaskBundle(candidate); len(payloads) > 0 {
				return payloads
			}
		}
	}
	return map[string]string{}
}

func parseTaskBundle(path string) map[string]string {
	data, err := os.ReadFile(path)
	if err != nil {
		return map[string]string{}
	}
	var payload struct {
		Tasks []map[string]any `json:"tasks"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return map[string]string{}
	}
	result := make(map[string]string, len(payload.Tasks))
	for _, entry := range payload.Tasks {
		storySlug, _ := entry["story_slug"].(string)
		if storySlug == "" {
			continue
		}
		indented, err := json.MarshalIndent(entry, "", "  ")
		if err != nil {
			continue
		}
		result[storySlug] = string(indented)
	}
	return result
}

func exportBacklogCSV(path string, rows []backlogRow) error {
	if len(rows) == 0 {
		return errors.New("no backlog rows to export")
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	writer := csv.NewWriter(f)
	defer writer.Flush()

	header := []string{"Key", "Title", "Type", "Status", "Assignee", "Updated"}
	if err := writer.Write(header); err != nil {
		return err
	}

	for _, row := range rows {
		typeLabel := ""
		switch row.Type {
		case backlogNodeEpic:
			typeLabel = "Epic"
		case backlogNodeStory:
			typeLabel = "Story"
		case backlogNodeTask:
			typeLabel = "Task"
		default:
			typeLabel = "Unknown"
		}
		updated := ""
		if !row.UpdatedAt.IsZero() {
			updated = row.UpdatedAt.UTC().Format(time.RFC3339)
		}
		record := []string{
			row.Key,
			row.Title,
			typeLabel,
			row.Status,
			row.Assignee,
			updated,
		}
		if err := writer.Write(record); err != nil {
			return err
		}
	}
	return writer.Error()
}

func updateTaskStatus(dbPath string, node backlogNode, newStatus string) error {
	if node.Type != backlogNodeTask {
		return errors.New("status updates only supported for tasks")
	}
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return err
	}
	defer db.Close()
	db.SetMaxOpenConns(1)

	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback()
		}
	}()

	var startedAt, completedAt sql.NullString
	var prevStatus string
	err = tx.QueryRow(`
		SELECT status, started_at, completed_at
		  FROM tasks
		 WHERE story_slug = ? AND position = ?
	`, node.StorySlug, node.TaskPosition).Scan(&prevStatus, &startedAt, &completedAt)
	if err != nil {
		return err
	}

	rawStatus := mapDisplayStatusToDB(newStatus)
	if rawStatus == "" {
		return fmt.Errorf("unsupported status %q", newStatus)
	}
	now := time.Now().UTC().Format(time.RFC3339)
	var startedValue, completedValue any
	switch rawStatus {
	case "in-progress":
		if startedAt.Valid && startedAt.String != "" {
			startedValue = startedAt.String
		} else {
			startedValue = now
		}
		if completedAt.Valid {
			completedValue = completedAt.String
		} else {
			completedValue = nil
		}
	case "complete":
		if startedAt.Valid && startedAt.String != "" {
			startedValue = startedAt.String
		} else {
			startedValue = now
		}
		completedValue = now
	case "pending":
		startedValue = nil
		completedValue = nil
	case "blocked":
		if startedAt.Valid && startedAt.String != "" {
			startedValue = startedAt.String
		} else {
			startedValue = now
		}
		if completedAt.Valid {
			completedValue = completedAt.String
		} else {
			completedValue = nil
		}
	default:
		startedValue = startedAt
		completedValue = completedAt
	}

	_, err = tx.Exec(`
		UPDATE tasks
		   SET status = ?,
		       updated_at = ?,
		       last_run = ?,
		       started_at = ?,
		       completed_at = ?
		 WHERE story_slug = ? AND position = ?
	`, rawStatus, now, "tui", startedValue, completedValue, node.StorySlug, node.TaskPosition)
	if err != nil {
		return err
	}

	return tx.Commit()
}

func mapDisplayStatusToDB(status string) string {
	switch strings.ToLower(status) {
	case "todo":
		return "pending"
	case "doing":
		return "in-progress"
	case "done":
		return "complete"
	case "blocked":
		return "blocked"
	default:
		return ""
	}
}
