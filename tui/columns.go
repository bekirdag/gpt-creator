package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/list"
	"github.com/charmbracelet/bubbles/table"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type column interface {
	SetSize(width, height int)
	Update(msg tea.Msg) (column, tea.Cmd)
	View(styles styles, focused bool) string
	Title() string
	FocusValue() string
}

type selectableColumn struct {
	title       string
	model       list.Model
	width       int
	height      int
	onSelect    func(entry listEntry) tea.Cmd
	onHighlight func(entry listEntry) tea.Cmd
}

type listEntry struct {
	title   string
	desc    string
	payload any
}

func (e listEntry) Title() string       { return e.title }
func (e listEntry) Description() string { return e.desc }
func (e listEntry) FilterValue() string { return e.title }

func newSelectableColumn(title string, items []list.Item, width int, onSelect func(listEntry) tea.Cmd, s styles) *selectableColumn {
	delegate := list.NewDefaultDelegate()
	delegate.Styles.SelectedTitle = s.listSel
	delegate.Styles.SelectedDesc = s.listSel
	delegate.Styles.NormalTitle = s.listItem
	delegate.Styles.NormalDesc = s.listItem.Foreground(palette.textMuted)

	m := list.New(items, delegate, width, 20)
	m.Title = title
	m.SetShowStatusBar(false)
	m.SetFilteringEnabled(false)
	m.SetShowHelp(false)
	m.SetShowPagination(false)

	return &selectableColumn{
		title:    title,
		model:    m,
		width:    width,
		onSelect: onSelect,
	}
}

func (c *selectableColumn) SetItems(items []list.Item) {
	c.model.SetItems(items)
	if len(items) > 0 {
		c.model.Select(0)
	}
}

func (c *selectableColumn) SetSize(width, height int) {
	c.width = width
	if height < 3 {
		height = 3
	}
	c.height = height
	c.model.SetSize(width, height-2)
}

func (c *selectableColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	prev := c.model.Index()
	switch m := msg.(type) {
	case tea.KeyMsg:
		if m.String() == "enter" && c.onSelect != nil {
			if item, ok := c.model.SelectedItem().(listEntry); ok {
				return c, c.onSelect(item)
			}
		}
	}
	var cmd tea.Cmd
	c.model, cmd = c.model.Update(msg)
	if c.model.Index() != prev && c.onHighlight != nil {
		if item, ok := c.model.SelectedItem().(listEntry); ok {
			if run := c.onHighlight(item); run != nil {
				if cmd != nil {
					return c, tea.Batch(cmd, run)
				}
				return c, run
			}
		}
	}
	return c, cmd
}

func (c *selectableColumn) View(s styles, focused bool) string {
	content := c.model.View()
	body := lipgloss.JoinVertical(lipgloss.Left, s.columnTitle.Render(c.title), content)
	if focused {
		return s.panelFocused.Width(c.width).Render(body)
	}
	return s.panel.Width(c.width).Render(body)
}

func (c *selectableColumn) Title() string {
	return c.title
}

func (c *selectableColumn) FocusValue() string {
	if item, ok := c.model.SelectedItem().(listEntry); ok {
		return item.title
	}
	return ""
}

func (c *selectableColumn) SelectedEntry() (listEntry, bool) {
	if entry, ok := c.model.SelectedItem().(listEntry); ok {
		return entry, true
	}
	return listEntry{}, false
}

func (c *selectableColumn) SetHighlightFunc(fn func(listEntry) tea.Cmd) {
	c.onHighlight = fn
}

type backlogTreeEntry struct {
	title    string
	desc     string
	node     backlogNode
	level    int
	status   string
	selected bool
}

func (e backlogTreeEntry) Title() string {
	prefix := strings.Repeat("  ", e.level)
	marker := "*"
	switch e.node.Type {
	case backlogNodeEpic:
		if e.selected {
			marker = "[x]"
		} else {
			marker = "[ ]"
		}
	case backlogNodeStory:
		marker = "-"
	}
	status := ""
	if trimmed := strings.TrimSpace(e.status); trimmed != "" {
		status = fmt.Sprintf(" [%s]", strings.ToUpper(trimmed))
	}
	return fmt.Sprintf("%s%s %s%s", prefix, marker, e.title, status)
}

func (e backlogTreeEntry) Description() string {
	return e.desc
}

func (e backlogTreeEntry) FilterValue() string {
	return e.title
}

type backlogTreeColumn struct {
	title       string
	model       list.Model
	width       int
	height      int
	onHighlight func(backlogNode) tea.Cmd
	onToggle    func(backlogNode) tea.Cmd
	onActivate  func(backlogNode) tea.Cmd
}

func newBacklogTreeColumn(title string, s styles) *backlogTreeColumn {
	delegate := list.NewDefaultDelegate()
	delegate.Styles.SelectedTitle = s.listSel
	delegate.Styles.SelectedDesc = s.listSel
	delegate.Styles.NormalTitle = s.listItem
	delegate.Styles.NormalDesc = s.listItem.Foreground(palette.textMuted)

	model := list.New([]list.Item{}, delegate, 28, 20)
	model.Title = title
	model.SetShowStatusBar(false)
	model.SetFilteringEnabled(false)
	model.SetShowHelp(false)
	model.SetShowPagination(false)

	return &backlogTreeColumn{
		title: title,
		model: model,
	}
}

func (c *backlogTreeColumn) SetCallbacks(onHighlight, onToggle, onActivate func(backlogNode) tea.Cmd) {
	c.onHighlight = onHighlight
	c.onToggle = onToggle
	c.onActivate = onActivate
}

func (c *backlogTreeColumn) SetItems(items []list.Item) {
	c.model.SetItems(items)
	if len(items) > 0 {
		c.model.Select(0)
	}
}

func (c *backlogTreeColumn) selectedEntry() (backlogTreeEntry, bool) {
	if entry, ok := c.model.SelectedItem().(backlogTreeEntry); ok {
		return entry, true
	}
	return backlogTreeEntry{}, false
}

func (c *backlogTreeColumn) SetSize(width, height int) {
	c.width = width
	if height < 3 {
		height = 3
	}
	c.height = height
	c.model.SetSize(width, height-2)
}

func (c *backlogTreeColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	var cmds []tea.Cmd
	prevIndex := c.model.Index()

	var cmd tea.Cmd
	c.model, cmd = c.model.Update(msg)
	if cmd != nil {
		cmds = append(cmds, cmd)
	}

	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch keyMsg.String() {
		case "enter":
			if entry, ok := c.selectedEntry(); ok && c.onActivate != nil {
				cmds = append(cmds, c.onActivate(entry.node))
			}
		case "space":
			if entry, ok := c.selectedEntry(); ok && c.onToggle != nil {
				cmds = append(cmds, c.onToggle(entry.node))
			}
		}
	}

	if c.model.Index() != prevIndex {
		if entry, ok := c.selectedEntry(); ok && c.onHighlight != nil {
			cmds = append(cmds, c.onHighlight(entry.node))
		}
	}

	return c, tea.Batch(cmds...)
}

func (c *backlogTreeColumn) View(s styles, focused bool) string {
	body := lipgloss.JoinVertical(lipgloss.Left, s.columnTitle.Render(c.title), c.model.View())
	if focused {
		return s.panelFocused.Width(c.width).Render(body)
	}
	return s.panel.Width(c.width).Render(body)
}

func (c *backlogTreeColumn) Title() string {
	return c.title
}

func (c *backlogTreeColumn) FocusValue() string {
	if entry, ok := c.selectedEntry(); ok {
		return entry.title
	}
	return ""
}

func (c *backlogTreeColumn) SelectNode(node backlogNode) {
	if len(c.model.Items()) == 0 {
		return
	}
	if node.IsZero() {
		c.model.Select(0)
		return
	}
	for idx, item := range c.model.Items() {
		if entry, ok := item.(backlogTreeEntry); ok && entry.node.Equals(node) {
			c.model.Select(idx)
			return
		}
	}
	c.model.Select(0)
}

type backlogTableColumn struct {
	title       string
	table       table.Model
	width       int
	height      int
	rows        []backlogRow
	onHighlight func(backlogRow) tea.Cmd
	onToggle    func(backlogRow) tea.Cmd
}

func newBacklogTableColumn(title string, s styles) *backlogTableColumn {
	columns := []table.Column{
		{Title: "Key", Width: 10},
		{Title: "Title", Width: 32},
		{Title: "Type", Width: 8},
		{Title: "Status", Width: 8},
		{Title: "Assignee", Width: 12},
		{Title: "Updated", Width: 10},
	}
	model := table.New(
		table.WithColumns(columns),
		table.WithFocused(true),
		table.WithHeight(10),
	)
	tStyles := table.DefaultStyles()
	tStyles.Header = lipgloss.NewStyle().
		Bold(true).
		Foreground(palette.textMuted).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(palette.border).
		Padding(0, 1)
	tStyles.Cell = lipgloss.NewStyle().
		Padding(0, 1)
	tStyles.Selected = lipgloss.NewStyle().
		Foreground(palette.text).
		Background(palette.selection).
		Padding(0, 1)
	model.SetStyles(tStyles)

	return &backlogTableColumn{
		title: title,
		table: model,
	}
}

func (c *backlogTableColumn) SetCallbacks(onHighlight, onToggle func(backlogRow) tea.Cmd) {
	c.onHighlight = onHighlight
	c.onToggle = onToggle
}

func (c *backlogTableColumn) SetRows(rows []backlogRow) {
	c.rows = rows
	tableRows := make([]table.Row, len(rows))
	for i, row := range rows {
		typeLabel := ""
		switch row.Type {
		case backlogNodeEpic:
			typeLabel = "Epic"
		case backlogNodeStory:
			typeLabel = "Story"
		case backlogNodeTask:
			typeLabel = "Task"
		default:
			typeLabel = "?"
		}
		title := row.Title
		if row.Depth > 0 {
			title = strings.Repeat("  ", row.Depth) + title
		}
		updated := ""
		if !row.UpdatedAt.IsZero() {
			updated = formatRelativeTime(row.UpdatedAt)
		}
		tableRows[i] = table.Row{
			row.Key,
			title,
			typeLabel,
			strings.ToUpper(row.Status),
			row.Assignee,
			updated,
		}
	}
	c.table.SetRows(tableRows)
	if len(tableRows) > 0 {
		c.table.SetCursor(0)
	}
}

func (c *backlogTableColumn) SetSize(width, height int) {
	if width < 30 {
		width = 30
	}
	if height < 6 {
		height = 6
	}
	c.width = width
	c.height = height

	colWidths := []int{12, width - 48, 8, 8, 14, 12}
	if len(colWidths) >= 2 {
		if colWidths[1] < 20 {
			colWidths[1] = 20
		}
	}
	c.table.SetColumns([]table.Column{
		{Title: "Key", Width: colWidths[0]},
		{Title: "Title", Width: colWidths[1]},
		{Title: "Type", Width: colWidths[2]},
		{Title: "Status", Width: colWidths[3]},
		{Title: "Assignee", Width: colWidths[4]},
		{Title: "Updated", Width: colWidths[5]},
	})
	c.table.SetHeight(height - 3)
}

func (c *backlogTableColumn) selectedRow() (backlogRow, bool) {
	if len(c.rows) == 0 {
		return backlogRow{}, false
	}
	idx := c.table.Cursor()
	if idx < 0 || idx >= len(c.rows) {
		return backlogRow{}, false
	}
	return c.rows[idx], true
}

func (c *backlogTableColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	var cmds []tea.Cmd
	prev := c.table.Cursor()

	var cmd tea.Cmd
	c.table, cmd = c.table.Update(msg)
	if cmd != nil {
		cmds = append(cmds, cmd)
	}

	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch keyMsg.String() {
		case "space":
			if row, ok := c.selectedRow(); ok && c.onToggle != nil {
				cmds = append(cmds, c.onToggle(row))
			}
		case "enter":
			if row, ok := c.selectedRow(); ok && c.onHighlight != nil {
				cmds = append(cmds, c.onHighlight(row))
			}
		}
	}

	if c.table.Cursor() != prev {
		if row, ok := c.selectedRow(); ok && c.onHighlight != nil {
			cmds = append(cmds, c.onHighlight(row))
		}
	}

	return c, tea.Batch(cmds...)
}

func (c *backlogTableColumn) View(s styles, focused bool) string {
	body := lipgloss.JoinVertical(lipgloss.Left, s.columnTitle.Render(c.title), c.table.View())
	if focused {
		return s.panelFocused.Width(c.width).Render(body)
	}
	return s.panel.Width(c.width).Render(body)
}

func (c *backlogTableColumn) Title() string {
	return c.title
}

func (c *backlogTableColumn) FocusValue() string {
	if row, ok := c.selectedRow(); ok {
		return row.Title
	}
	return ""
}

func (c *backlogTableColumn) SelectNode(node backlogNode) {
	if len(c.rows) == 0 {
		return
	}
	for idx, row := range c.rows {
		if row.Node.Equals(node) {
			c.table.SetCursor(idx)
			return
		}
	}
	c.table.SetCursor(0)
}

type artifactTreeEntry struct {
	node artifactNode
}

func (e artifactTreeEntry) Title() string {
	icon := "•"
	if e.node.IsDir {
		if e.node.Expanded {
			icon = "▾"
		} else if e.node.HasChildren {
			icon = "▸"
		} else {
			icon = "▹"
		}
	}
	prefix := strings.Repeat("  ", e.node.Level)
	return fmt.Sprintf("%s%s %s", prefix, icon, e.node.Name)
}

func (e artifactTreeEntry) Description() string {
	if e.node.IsDir {
		return e.node.Rel
	}
	parts := []string{}
	if e.node.Size > 0 {
		parts = append(parts, formatByteSize(e.node.Size))
	}
	if !e.node.ModTime.IsZero() {
		parts = append(parts, formatRelativeTime(e.node.ModTime))
	}
	if len(parts) == 0 {
		return e.node.Rel
	}
	return strings.Join(parts, " • ")
}

func (e artifactTreeEntry) FilterValue() string {
	return e.node.Rel
}

type artifactTreeColumn struct {
	title       string
	model       list.Model
	width       int
	height      int
	onHighlight func(artifactNode) tea.Cmd
	onToggle    func(artifactNode) tea.Cmd
	onActivate  func(artifactNode) tea.Cmd
}

func newArtifactTreeColumn(title string, s styles) *artifactTreeColumn {
	delegate := list.NewDefaultDelegate()
	delegate.Styles.SelectedTitle = s.listSel
	delegate.Styles.SelectedDesc = s.listSel
	delegate.Styles.NormalTitle = s.listItem
	delegate.Styles.NormalDesc = s.listItem.Foreground(palette.textMuted)

	model := list.New([]list.Item{}, delegate, 36, 20)
	model.Title = title
	model.SetShowStatusBar(false)
	model.SetFilteringEnabled(false)
	model.SetShowHelp(false)
	model.SetShowPagination(false)

	return &artifactTreeColumn{
		title: title,
		model: model,
	}
}

func (c *artifactTreeColumn) SetCallbacks(onHighlight, onToggle, onActivate func(artifactNode) tea.Cmd) {
	c.onHighlight = onHighlight
	c.onToggle = onToggle
	c.onActivate = onActivate
}

func (c *artifactTreeColumn) SetNodes(nodes []artifactNode) {
	items := make([]list.Item, len(nodes))
	for i, node := range nodes {
		items[i] = artifactTreeEntry{node: node}
	}
	c.model.SetItems(items)
	if len(items) > 0 {
		c.model.Select(0)
	}
}

func (c *artifactTreeColumn) selectedEntry() (artifactTreeEntry, bool) {
	if entry, ok := c.model.SelectedItem().(artifactTreeEntry); ok {
		return entry, true
	}
	return artifactTreeEntry{}, false
}

func (c *artifactTreeColumn) SelectedNode() (artifactNode, bool) {
	if entry, ok := c.selectedEntry(); ok {
		return entry.node, true
	}
	return artifactNode{}, false
}

func (c *artifactTreeColumn) SelectRel(rel string) {
	normalized := normalizeRel(rel)
	items := c.model.Items()
	for idx, item := range items {
		entry, ok := item.(artifactTreeEntry)
		if !ok {
			continue
		}
		if normalizeRel(entry.node.Rel) == normalized {
			c.model.Select(idx)
			return
		}
	}
}

func (c *artifactTreeColumn) SetSize(width, height int) {
	c.width = maxInt(width, 24)
	if height < 3 {
		height = 3
	}
	c.height = height
	c.model.SetSize(c.width, height-2)
}

func (c *artifactTreeColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	prev := c.model.Index()
	var cmds []tea.Cmd

	var cmd tea.Cmd
	c.model, cmd = c.model.Update(msg)
	if cmd != nil {
		cmds = append(cmds, cmd)
	}

	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch keyMsg.String() {
		case "enter":
			if entry, ok := c.selectedEntry(); ok {
				if entry.node.IsDir {
					if c.onToggle != nil {
						cmds = append(cmds, c.onToggle(entry.node))
					}
				} else if c.onActivate != nil {
					cmds = append(cmds, c.onActivate(entry.node))
				}
			}
		case "space":
			if entry, ok := c.selectedEntry(); ok && entry.node.IsDir {
				if c.onToggle != nil {
					cmds = append(cmds, c.onToggle(entry.node))
				}
			}
		case "right", "l":
			if entry, ok := c.selectedEntry(); ok && entry.node.IsDir && !entry.node.Expanded {
				if c.onToggle != nil {
					cmds = append(cmds, c.onToggle(entry.node))
				}
			}
		case "left", "h":
			if entry, ok := c.selectedEntry(); ok {
				if entry.node.IsDir && entry.node.Expanded {
					if c.onToggle != nil {
						cmds = append(cmds, c.onToggle(entry.node))
					}
				} else if entry.node.Parent != "" {
					parentRel := entry.node.Parent
					c.SelectRel(parentRel)
					if c.onHighlight != nil {
						if node, ok := c.SelectedNode(); ok {
							cmds = append(cmds, c.onHighlight(node))
						}
					}
				}
			}
		}
	}

	if c.model.Index() != prev {
		if c.onHighlight != nil {
			if entry, ok := c.selectedEntry(); ok {
				if run := c.onHighlight(entry.node); run != nil {
					cmds = append(cmds, run)
				}
			}
		}
	}

	if len(cmds) == 0 {
		return c, nil
	}
	return c, tea.Batch(cmds...)
}

func (c *artifactTreeColumn) View(s styles, focused bool) string {
	body := lipgloss.JoinVertical(lipgloss.Left, s.columnTitle.Render(c.title), c.model.View())
	if focused {
		return s.panelFocused.Width(c.width).Render(body)
	}
	return s.panel.Width(c.width).Render(body)
}

func (c *artifactTreeColumn) Title() string {
	return c.title
}

func (c *artifactTreeColumn) FocusValue() string {
	if node, ok := c.SelectedNode(); ok {
		return node.Rel
	}
	return ""
}

type actionColumn struct {
	title       string
	table       table.Model
	width       int
	height      int
	items       []featureItemDefinition
	onHighlight func(featureItemDefinition, bool) tea.Cmd
}

func newActionColumn(title string, s styles) *actionColumn {
	columns := []table.Column{
		{Title: "Action", Width: 18},
		{Title: "Details", Width: 42},
	}
	t := table.New(
		table.WithColumns(columns),
		table.WithFocused(true),
		table.WithHeight(8),
	)
	tStyles := table.DefaultStyles()
	tStyles.Header = lipgloss.NewStyle().
		Bold(true).
		Foreground(palette.textMuted).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(palette.border).
		Padding(0, 1)
	tStyles.Cell = lipgloss.NewStyle().Padding(0, 1)
	tStyles.Selected = lipgloss.NewStyle().
		Foreground(palette.text).
		Background(palette.selection).
		Padding(0, 1)
	t.SetStyles(tStyles)

	return &actionColumn{
		title: title,
		table: t,
	}
}

func (c *actionColumn) SetHighlightFunc(fn func(featureItemDefinition, bool) tea.Cmd) {
	c.onHighlight = fn
}

func (c *actionColumn) SetItems(items []featureItemDefinition) {
	c.items = items
	rows := make([]table.Row, len(items))
	for i, item := range items {
		label := item.Title
		desc := item.Desc
		if item.Disabled {
			label = "! " + label
			if strings.TrimSpace(item.DisabledReason) != "" {
				desc = item.DisabledReason
			} else if strings.TrimSpace(desc) == "" {
				desc = "Temporarily unavailable"
			}
		}
		rows[i] = table.Row{label, desc}
	}
	c.table.SetRows(rows)
	if len(rows) > 0 {
		c.table.SetCursor(0)
	}
}

func (c *actionColumn) SetTitle(title string) {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return
	}
	c.title = trimmed
}

func (c *actionColumn) SelectKey(key string) {
	if key == "" {
		return
	}
	for idx, item := range c.items {
		if item.Key == key {
			c.table.SetCursor(idx)
			return
		}
	}
}

func (c *actionColumn) SelectedItem() (featureItemDefinition, bool) {
	if len(c.items) == 0 {
		return featureItemDefinition{}, false
	}
	cursor := c.table.Cursor()
	if cursor < 0 || cursor >= len(c.items) {
		return featureItemDefinition{}, false
	}
	return c.items[cursor], true
}

func (c *actionColumn) SetSize(width, height int) {
	if width < 20 {
		width = 20
	}
	if height < 5 {
		height = 5
	}
	c.width = width
	c.height = height

	actionWidth := maxInt(18, width/3)
	detailsWidth := maxInt(width-actionWidth-4, 24)
	c.table.SetColumns([]table.Column{
		{Title: "Action", Width: actionWidth},
		{Title: "Details", Width: detailsWidth},
	})
	c.table.SetHeight(height - 3)
}

func (c *actionColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	prev := c.table.Cursor()
	var cmds []tea.Cmd

	var cmd tea.Cmd
	c.table, cmd = c.table.Update(msg)
	if cmd != nil {
		cmds = append(cmds, cmd)
	}

	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		if keyMsg.String() == "enter" {
			if c.onHighlight != nil {
				if item, ok := c.SelectedItem(); ok {
					if run := c.onHighlight(item, true); run != nil {
						cmds = append(cmds, run)
					}
				}
			}
		}
	}

	if c.table.Cursor() != prev {
		if c.onHighlight != nil {
			if item, ok := c.SelectedItem(); ok {
				if run := c.onHighlight(item, false); run != nil {
					cmds = append(cmds, run)
				}
			}
		}
	}

	return c, tea.Batch(cmds...)
}

func (c *actionColumn) View(s styles, focused bool) string {
	title := s.columnTitle.Render(c.title)
	var body string
	if len(c.items) == 0 {
		body = s.listItem.Foreground(palette.textMuted).Render("No actions available")
	} else {
		body = c.table.View()
	}
	inner := lipgloss.JoinVertical(lipgloss.Left, title, body)
	if focused {
		return s.panelFocused.Width(c.width).Render(inner)
	}
	return s.panel.Width(c.width).Render(inner)
}

func (c *actionColumn) Title() string {
	return c.title
}

func (c *actionColumn) FocusValue() string {
	if item, ok := c.SelectedItem(); ok {
		return item.Title
	}
	return ""
}

type envTableColumn struct {
	title    string
	table    table.Model
	width    int
	height   int
	entries  []envEntry
	reveal   map[string]bool
	onEdit   func(envEntry) tea.Cmd
	onToggle func(envEntry) tea.Cmd
	onCopy   func(envEntry) tea.Cmd
}

func newEnvTableColumn(title string, s styles) *envTableColumn {
	columns := []table.Column{
		{Title: "Key", Width: 24},
		{Title: "Value", Width: 44},
		{Title: "Secret?", Width: 9},
		{Title: "Source", Width: 24},
	}
	t := table.New(
		table.WithColumns(columns),
		table.WithFocused(true),
		table.WithHeight(8),
	)
	tStyles := table.DefaultStyles()
	tStyles.Header = lipgloss.NewStyle().
		Bold(true).
		Foreground(palette.textMuted).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(palette.border).
		Padding(0, 1)
	tStyles.Cell = lipgloss.NewStyle().Padding(0, 1)
	tStyles.Selected = lipgloss.NewStyle().
		Foreground(palette.text).
		Background(palette.selection).
		Padding(0, 1)
	t.SetStyles(tStyles)

	return &envTableColumn{
		title:  title,
		table:  t,
		reveal: make(map[string]bool),
	}
}

func (c *envTableColumn) SetOnEdit(fn func(envEntry) tea.Cmd) {
	c.onEdit = fn
}

func (c *envTableColumn) SetOnToggle(fn func(envEntry) tea.Cmd) {
	c.onToggle = fn
}

func (c *envTableColumn) SetOnCopy(fn func(envEntry) tea.Cmd) {
	c.onCopy = fn
}

func (c *envTableColumn) SelectedEntry() (envEntry, bool) {
	cursor := c.table.Cursor()
	if cursor < 0 || cursor >= len(c.entries) {
		return envEntry{}, false
	}
	return c.entries[cursor], true
}

func (c *envTableColumn) SetEntries(entries []envEntry, reveal map[string]bool) {
	selectedID := ""
	if entry, ok := c.SelectedEntry(); ok {
		selectedID = envEntryIdentifier(entry)
	}
	c.entries = append([]envEntry(nil), entries...)
	if reveal == nil {
		reveal = make(map[string]bool)
	}
	c.reveal = make(map[string]bool, len(reveal))
	for k, v := range reveal {
		c.reveal[k] = v
	}
	rows := make([]table.Row, len(entries))
	for i, entry := range entries {
		rows[i] = c.buildRow(entry)
	}
	c.table.SetRows(rows)
	if len(rows) == 0 {
		return
	}
	target := 0
	if selectedID != "" {
		for idx, entry := range c.entries {
			if envEntryIdentifier(entry) == selectedID {
				target = idx
				break
			}
		}
	}
	if target < 0 {
		target = 0
	}
	if target >= len(rows) {
		target = len(rows) - 1
	}
	c.table.SetCursor(target)
}

func (c *envTableColumn) buildRow(entry envEntry) table.Row {
	value := entry.Value
	id := envEntryIdentifier(entry)
	revealed := c.reveal[id]
	if entry.Secret && !revealed {
		if strings.TrimSpace(value) == "" {
			value = "[hidden empty]"
		} else {
			value = maskedSecret(value)
		}
	} else if strings.TrimSpace(value) == "" {
		value = "(empty)"
	}
	secretLabel := ""
	if entry.Secret {
		if revealed {
			secretLabel = "yes (shown)"
		} else {
			secretLabel = "yes"
		}
	}
	source := entry.Source
	if strings.TrimSpace(source) == "" {
		source = "(unknown)"
	}
	return table.Row{
		entry.Key,
		value,
		secretLabel,
		source,
	}
}

func (c *envTableColumn) SetSize(width, height int) {
	if width < 20 {
		width = 20
	}
	if height < 5 {
		height = 5
	}
	c.width = width
	c.height = height

	keyWidth := maxInt(16, width/4)
	valueWidth := maxInt(width-keyWidth-28, 28)
	if valueWidth > 64 {
		valueWidth = 64
	}
	secretWidth := 9
	sourceWidth := maxInt(width-keyWidth-valueWidth-secretWidth-4, 18)

	c.table.SetColumns([]table.Column{
		{Title: "Key", Width: keyWidth},
		{Title: "Value", Width: valueWidth},
		{Title: "Secret?", Width: secretWidth},
		{Title: "Source", Width: sourceWidth},
	})
	c.table.SetHeight(height - 3)
}

func (c *envTableColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	var cmds []tea.Cmd

	var cmd tea.Cmd
	c.table, cmd = c.table.Update(msg)
	if cmd != nil {
		cmds = append(cmds, cmd)
	}

	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		key := strings.ToLower(keyMsg.String())
		switch key {
		case "enter":
			if c.onEdit != nil {
				if entry, ok := c.SelectedEntry(); ok {
					if run := c.onEdit(entry); run != nil {
						cmds = append(cmds, run)
					}
				}
			}
		case "r":
			if c.onToggle != nil {
				if entry, ok := c.SelectedEntry(); ok {
					if run := c.onToggle(entry); run != nil {
						cmds = append(cmds, run)
					}
				}
			}
		case "y":
			if c.onCopy != nil {
				if entry, ok := c.SelectedEntry(); ok {
					if run := c.onCopy(entry); run != nil {
						cmds = append(cmds, run)
					}
				}
			}
		}
	}

	if len(cmds) == 0 {
		return c, nil
	}
	return c, tea.Batch(cmds...)
}

func (c *envTableColumn) View(s styles, focused bool) string {
	title := s.columnTitle.Render(c.title)
	var body string
	if len(c.entries) == 0 {
		body = s.listItem.Foreground(palette.textMuted).Render("No variables detected")
	} else {
		body = c.table.View()
	}
	content := lipgloss.JoinVertical(lipgloss.Left, title, body)
	if focused {
		return s.panelFocused.Width(c.width).Render(content)
	}
	return s.panel.Width(c.width).Render(content)
}

func (c *envTableColumn) Title() string {
	return c.title
}

func (c *envTableColumn) FocusValue() string {
	if entry, ok := c.SelectedEntry(); ok {
		return entry.Key
	}
	return ""
}

func envEntryIdentifier(entry envEntry) string {
	return fmt.Sprintf("%s::%s::%d", entry.Source, entry.Key, entry.LineIndex)
}

func maskedSecret(value string) string {
	length := len(value)
	if length <= 0 {
		return "[hidden]"
	}
	if length > 16 {
		length = 16
	}
	return strings.Repeat("*", length)
}

type servicesTableColumn struct {
	title       string
	table       table.Model
	width       int
	height      int
	items       []featureItemDefinition
	onHighlight func(featureItemDefinition, bool) tea.Cmd
}

func newServicesTableColumn(title string, s styles) *servicesTableColumn {
	columns := []table.Column{
		{Title: "Service", Width: 16},
		{Title: "Container", Width: 28},
		{Title: "State", Width: 10},
		{Title: "Health", Width: 12},
		{Title: "Ports", Width: 24},
		{Title: "Restarts", Width: 9},
	}
	t := table.New(
		table.WithColumns(columns),
		table.WithFocused(true),
		table.WithHeight(10),
	)
	tStyles := table.DefaultStyles()
	tStyles.Header = lipgloss.NewStyle().
		Bold(true).
		Foreground(palette.textMuted).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(palette.border).
		Padding(0, 1)
	tStyles.Cell = lipgloss.NewStyle().Padding(0, 1)
	tStyles.Selected = lipgloss.NewStyle().
		Foreground(palette.text).
		Background(palette.selection).
		Padding(0, 1)
	t.SetStyles(tStyles)

	return &servicesTableColumn{
		title: title,
		table: t,
	}
}

func (c *servicesTableColumn) SetHighlightFunc(fn func(featureItemDefinition, bool) tea.Cmd) {
	c.onHighlight = fn
}

func (c *servicesTableColumn) SetItems(items []featureItemDefinition) {
	c.items = items
	rows := make([]table.Row, len(items))
	for i, item := range items {
		if item.Meta != nil && item.Meta["serviceRow"] == "1" {
			rows[i] = table.Row{
				item.Meta["service"],
				item.Meta["container"],
				item.Meta["state"],
				item.Meta["health"],
				item.Meta["ports"],
				item.Meta["restarts"],
			}
		} else {
			label := item.Title
			if strings.TrimSpace(label) == "" {
				label = item.Desc
			}
			rows[i] = table.Row{
				label,
				item.Desc,
				"",
				"",
				"",
				"",
			}
		}
	}
	c.table.SetRows(rows)
	if len(rows) > 0 {
		c.table.SetCursor(0)
	}
}

func (c *servicesTableColumn) SelectKey(key string) {
	if key == "" {
		return
	}
	for idx, item := range c.items {
		if item.Key == key {
			c.table.SetCursor(idx)
			return
		}
	}
}

func (c *servicesTableColumn) SelectedItem() (featureItemDefinition, bool) {
	if len(c.items) == 0 {
		return featureItemDefinition{}, false
	}
	cursor := c.table.Cursor()
	if cursor < 0 || cursor >= len(c.items) {
		return featureItemDefinition{}, false
	}
	return c.items[cursor], true
}

func (c *servicesTableColumn) SetSize(width, height int) {
	if width < 36 {
		width = 36
	}
	if height < 6 {
		height = 6
	}
	c.width = width
	c.height = height

	serviceWidth := maxInt(14, width/6+6)
	containerWidth := maxInt(24, width/3)
	stateWidth := 10
	healthWidth := 12
	restartsWidth := 9
	portsWidth := width - serviceWidth - containerWidth - stateWidth - healthWidth - restartsWidth - 6
	if portsWidth < 16 {
		portsWidth = 16
	}

	c.table.SetColumns([]table.Column{
		{Title: "Service", Width: serviceWidth},
		{Title: "Container", Width: containerWidth},
		{Title: "State", Width: stateWidth},
		{Title: "Health", Width: healthWidth},
		{Title: "Ports", Width: portsWidth},
		{Title: "Restarts", Width: restartsWidth},
	})
	c.table.SetHeight(height - 3)
}

func (c *servicesTableColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	prev := c.table.Cursor()
	var cmds []tea.Cmd

	var cmd tea.Cmd
	c.table, cmd = c.table.Update(msg)
	if cmd != nil {
		cmds = append(cmds, cmd)
	}

	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		if keyMsg.String() == "enter" && c.onHighlight != nil {
			if item, ok := c.SelectedItem(); ok {
				if run := c.onHighlight(item, true); run != nil {
					cmds = append(cmds, run)
				}
			}
		}
	}

	if c.table.Cursor() != prev && c.onHighlight != nil {
		if item, ok := c.SelectedItem(); ok {
			if run := c.onHighlight(item, false); run != nil {
				cmds = append(cmds, run)
			}
		}
	}

	return c, tea.Batch(cmds...)
}

func (c *servicesTableColumn) View(s styles, focused bool) string {
	title := s.columnTitle.Render(c.title)
	var body string
	if len(c.items) == 0 {
		body = s.listItem.Foreground(palette.textMuted).Render("No services detected")
	} else {
		body = c.table.View()
	}
	content := lipgloss.JoinVertical(lipgloss.Left, title, body)
	if focused {
		return s.panelFocused.Width(c.width).Render(content)
	}
	return s.panel.Width(c.width).Render(content)
}

func (c *servicesTableColumn) Title() string {
	return c.title
}

func (c *servicesTableColumn) FocusValue() string {
	if item, ok := c.SelectedItem(); ok {
		if item.Meta != nil && item.Meta["service"] != "" {
			return item.Meta["service"]
		}
		return item.Title
	}
	return ""
}

type previewColumn struct {
	title   string
	width   int
	height  int
	content string
	view    viewport.Model
}

func newPreviewColumn(width int) *previewColumn {
	vp := viewport.New(width, 20)
	return &previewColumn{
		title: "Preview",
		view:  vp,
	}
}

func (p *previewColumn) SetSize(width, height int) {
	p.width = width
	if height < 3 {
		height = 3
	}
	p.height = height
	p.view.Width = width - 2
	p.view.Height = height - 3
}

func (p *previewColumn) SetContent(content string) {
	p.content = content
	p.view.SetContent(content)
}

func (p *previewColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	var cmd tea.Cmd
	p.view, cmd = p.view.Update(msg)
	return p, cmd
}

func (p *previewColumn) View(s styles, focused bool) string {
	header := s.columnTitle.Render(p.title)
	body := header + "\n" + p.view.View()
	if focused {
		return s.panelFocused.Width(p.width).Render(body)
	}
	return s.panel.Width(p.width).Render(body)
}

func (p *previewColumn) Title() string {
	return p.title
}

func (p *previewColumn) FocusValue() string {
	return ""
}

// helpers to build column items

type featureDefinition struct {
	Key   string
	Title string
	Desc  string
}

type featureItemDefinition struct {
	Key             string
	Title           string
	Desc            string
	Command         []string
	ProjectFlag     string
	ProjectRequired bool
	PreviewKey      string
	Meta            map[string]string
	Disabled        bool
	DisabledReason  string
	Artifacts       []pipelineArtifact
	PipelineState   pipelineState
	PipelineIndex   int
	LastUpdated     time.Time
}

var featureDefinitions = []featureDefinition{
	{Key: "overview", Title: "Overview", Desc: "Pipeline & health"},
	{Key: "tasks", Title: "Epics/Stories/Tasks", Desc: "Backlog hierarchy"},
	{Key: "docs", Title: "Docs", Desc: "Generated documentation"},
	{Key: "generate", Title: "Generate", Desc: "Code generation"},
	{Key: "artifacts", Title: "Artifacts", Desc: "Browse staging outputs & apps"},
	{Key: "database", Title: "Database", Desc: "Provision/seed/dump"},
	{Key: "services", Title: "Run/Services", Desc: "Docker services"},
	{Key: "verify", Title: "Verify", Desc: "Acceptance & NFR checks"},
	{Key: "tokens", Title: "Tokens", Desc: "Usage summaries"},
	{Key: "reports", Title: "Reports", Desc: "Automation reports"},
	{Key: "env", Title: "Env Editor", Desc: "Environment variables"},
}

var featureItemsByKey = map[string][]featureItemDefinition{
	"overview": {
		{Key: "pipeline", Title: "Pipeline Status", Desc: "scan → verify"},
		{Key: "activity", Title: "Recent Activity", Desc: "Latest runs & timestamps"},
	},
	"tasks": {
		{Key: "create-jira-tasks", Title: "create-jira-tasks", Desc: "Generate backlog from staged docs", Command: []string{"create-jira-tasks"}, ProjectRequired: true},
		{Key: "migrate-tasks", Title: "migrate-tasks", Desc: "Rebuild tasks.db from JSON artifacts", Command: []string{"migrate-tasks"}, ProjectRequired: true},
		{Key: "refine-tasks", Title: "refine-tasks", Desc: "Refine existing backlog entries", Command: []string{"refine-tasks"}, ProjectRequired: true},
		{Key: "create-tasks", Title: "create-tasks", Desc: "Import Jira markdown into backlog DB", Command: []string{"create-tasks"}, ProjectRequired: true},
		{Key: "work-on-tasks", Title: "work-on-tasks", Desc: "Execute backlog automation loop", Command: []string{"work-on-tasks"}, ProjectRequired: true},
		{Key: "backlog-progress", Title: "backlog --progress", Desc: "Summarise backlog progress", Command: []string{"backlog", "--progress"}, ProjectRequired: true},
	},
	"docs": {
		{Key: "create-pdr", Title: "create-pdr", Desc: "Generate Product Design Record", Command: []string{"create-pdr"}, ProjectRequired: true, PreviewKey: "doc:pdr"},
		{Key: "create-sds", Title: "create-sds", Desc: "Generate System Design Spec", Command: []string{"create-sds"}, ProjectRequired: true, PreviewKey: "doc:sds"},
		{Key: "docs-attach-rfp", Title: "attach-rfp", Desc: "Copy external RFP into staging/inputs/", ProjectRequired: true, Meta: map[string]string{"docsAction": "attach-rfp"}},
	},
	"generate": {
		{Key: "generate-all", Title: "generate all", Desc: "Regenerate all targets", Command: []string{"generate", "all"}, ProjectRequired: true},
		{Key: "generate-api", Title: "generate api", Desc: "Regenerate API sources", Command: []string{"generate", "api"}, ProjectRequired: true, PreviewKey: "path:apps/api"},
		{Key: "generate-web", Title: "generate web", Desc: "Regenerate web app", Command: []string{"generate", "web"}, ProjectRequired: true, PreviewKey: "path:apps/web"},
		{Key: "generate-admin", Title: "generate admin", Desc: "Regenerate admin app", Command: []string{"generate", "admin"}, ProjectRequired: true, PreviewKey: "path:apps/admin"},
		{Key: "generate-db", Title: "generate db", Desc: "Regenerate database artifacts", Command: []string{"generate", "db"}, ProjectRequired: true, PreviewKey: "path:apps/db"},
		{Key: "generate-docker", Title: "generate docker", Desc: "Regenerate Docker assets", Command: []string{"generate", "docker"}, ProjectRequired: true, PreviewKey: "path:docker"},
	},
	"database": {
		{Key: "db-provision", Title: "db provision", Desc: "Provision database containers", Command: []string{"db", "provision"}, ProjectRequired: true},
		{Key: "db-import", Title: "db import", Desc: "Import database snapshot", Command: []string{"db", "import"}, ProjectRequired: true},
		{Key: "db-seed", Title: "db seed", Desc: "Seed development data", Command: []string{"db", "seed"}, ProjectRequired: true},
		{Key: "create-db-dump", Title: "create-db-dump", Desc: "Export schema and seed SQL", Command: []string{"create-db-dump"}, ProjectRequired: true, PreviewKey: "dbdump"},
	},
	"services": {
		{Key: "run-up", Title: "run up", Desc: "Start docker-compose stack", Command: []string{"run", "up"}, ProjectRequired: true, Meta: map[string]string{"requiresDocker": "1"}},
		{Key: "run-logs", Title: "run logs", Desc: "Tail compose logs", Command: []string{"run", "logs"}, ProjectRequired: true, Meta: map[string]string{"requiresDocker": "1"}},
		{Key: "run-open", Title: "run open", Desc: "Open web/admin endpoints", Command: []string{"run", "open"}, ProjectRequired: true, Meta: map[string]string{"requiresDocker": "1"}},
		{Key: "run-down", Title: "run down", Desc: "Tear down stack", Command: []string{"run", "down"}, ProjectRequired: true, Meta: map[string]string{"requiresDocker": "1"}},
	},
	"verify": {
		{Key: "verify-acceptance", Title: "verify acceptance", Desc: "Run functional acceptance suite", Command: []string{"verify", "acceptance"}, ProjectRequired: true, PreviewKey: "path:.gpt-creator/staging/verify", Meta: map[string]string{"requiresDocker": "1"}},
		{Key: "verify-all", Title: "verify all", Desc: "Run full verification suite", Command: []string{"verify", "all"}, ProjectRequired: true, PreviewKey: "path:.gpt-creator/staging/verify", Meta: map[string]string{"requiresDocker": "1"}},
	},
	"tokens": {
		{Key: "tokens-details", Title: "tokens --details", Desc: "Summarise token usage with details", Command: []string{"tokens", "--details"}, ProjectRequired: true, PreviewKey: "path:.gpt-creator/logs/codex-usage.ndjson"},
	},
	"reports": {
		{Key: "reports-list", Title: "reports list", Desc: "List generated automation reports", Command: []string{"reports", "list"}, ProjectRequired: true, PreviewKey: "path:reports"},
		{Key: "reports-backlog", Title: "reports backlog", Desc: "Show pending issue backlog", Command: []string{"reports", "backlog"}, ProjectRequired: true},
	},
	"env": {
		{Key: "project-env", Title: "Project .env", Desc: "Review project .env contents", PreviewKey: "env:project"},
		{Key: "apps-env", Title: "Applications .env", Desc: "Review apps/*/.env entries", PreviewKey: "env:apps"},
	},
}

func featureItemsForKey(key string) []featureItemDefinition {
	defs, ok := featureItemsByKey[key]
	if !ok {
		return nil
	}
	items := make([]featureItemDefinition, len(defs))
	for i, def := range defs {
		clone := def
		if def.Meta != nil {
			clone.Meta = map[string]string{}
			for k, v := range def.Meta {
				clone.Meta[k] = v
			}
		}
		clone.Disabled = def.Disabled
		clone.DisabledReason = def.DisabledReason
		clone.Artifacts = append([]pipelineArtifact(nil), def.Artifacts...)
		clone.PipelineState = def.PipelineState
		clone.PipelineIndex = def.PipelineIndex
		clone.LastUpdated = def.LastUpdated
		items[i] = clone
	}
	return items
}

func featureItemEntries(project *discoveredProject, featureKey string, dockerAvailable bool) []featureItemDefinition {
	var items []featureItemDefinition
	appendDefaults := true
	var docHistory []featureItemDefinition

	switch featureKey {
	case "overview":
		appendDefaults = false
		items = append(items, buildOverviewItems(project)...)
	case "tasks":
		if project != nil && project.Stats.TasksTotal > 0 {
			items = append(items, featureItemDefinition{
				Key:        "tasks-progress",
				Title:      "Backlog progress",
				Desc:       fmt.Sprintf("%d/%d tasks complete", project.Stats.TasksDone, project.Stats.TasksTotal),
				PreviewKey: "tasks:progress",
			})
		}
	case "docs":
		if summary := docsSummary(project); summary != "" {
			items = append(items, featureItemDefinition{
				Key:   "docs-summary",
				Title: "Documentation",
				Desc:  summary,
			})
		}
		docHistory = docHistoryItems(project)
	case "generate":
		items = append(items, buildGenerateItems(project)...)
		appendDefaults = false
	case "database":
		var dumpInfo databaseDumpInfo
		if project != nil {
			dumpInfo = gatherDatabaseDumpInfo(project.Path)
		}
		if summary := databaseSummaryFromInfo(project, dumpInfo); summary != "" {
			items = append(items, featureItemDefinition{
				Key:   "db-summary",
				Title: "Database status",
				Desc:  summary,
			})
		}
		items = decorateDatabaseItems(project, items, dumpInfo)
	case "services":
		appendDefaults = false
		if !dockerAvailable {
			items = append(items, featureItemDefinition{
				Key:        "services-docker-missing",
				Title:      "Docker required",
				Desc:       "Install Docker Desktop / CLI to inspect services.",
				PreviewKey: "",
			})
			break
		}
		if svcItems, err := gatherServiceItems(project, dockerAvailable); err == nil && len(svcItems) > 0 {
			items = append(items, svcItems...)
		} else if err != nil {
			items = append(items, featureItemDefinition{
				Key:   "services-error",
				Title: "Docker status unavailable",
				Desc:  err.Error(),
			})
		} else if summary := servicesSummary(project); summary != "" {
			items = append(items, featureItemDefinition{
				Key:   "services-summary",
				Title: "Service snapshot",
				Desc:  summary,
			})
		}
	case "verify":
		appendDefaults = false
		if project == nil {
			items = append(items, featureItemsForKey("verify")...)
			break
		}
		summary := verifySummaryForProject(project)
		overall := overallVerifyStatus(summary)
		descParts := []string{fmt.Sprintf("%d/%d passing", summary.Stats.Passed, summary.Stats.Total)}
		if summary.Stats.Failed > 0 {
			descParts = append(descParts, fmt.Sprintf("%d failing", summary.Stats.Failed))
		}
		if summary.Stats.Skipped > 0 {
			descParts = append(descParts, fmt.Sprintf("%d skipped", summary.Stats.Skipped))
		}
		if summary.LastUpdated.IsZero() {
			descParts = append(descParts, "No runs yet")
		} else {
			descParts = append(descParts, "Updated "+formatRelativeTime(summary.LastUpdated))
		}
		items = append(items, featureItemDefinition{
			Key:   "verify-summary",
			Title: fmt.Sprintf("%s Overall", verifyStatusIcon(overall)),
			Desc:  strings.Join(descParts, " • "),
			Meta: map[string]string{
				"verifyOverallStatus": overall,
				"verifyPassed":        strconv.Itoa(summary.Stats.Passed),
				"verifyFailed":        strconv.Itoa(summary.Stats.Failed),
				"verifySkipped":       strconv.Itoa(summary.Stats.Skipped),
				"verifyTotal":         strconv.Itoa(summary.Stats.Total),
			},
		})
		for _, check := range sortedVerifyChecks(summary) {
			def, _ := verifyDefinitionByName(check.Name)
			title := fmt.Sprintf("%s %s", verifyStatusIcon(check.Status), check.Label)
			descParts := []string{}
			if check.Score != nil {
				descParts = append(descParts, "Score "+strconv.FormatFloat(*check.Score, 'f', 1, 64))
			}
			if statusLabel := verifyStatusLabel(check.Status); statusLabel != "" {
				descParts = append(descParts, statusLabel)
			}
			if check.Message != "" {
				descParts = append(descParts, check.Message)
			}
			if !check.Updated.IsZero() {
				descParts = append(descParts, "Updated "+formatRelativeTime(check.Updated))
			}
			if len(descParts) == 0 {
				descParts = append(descParts, "Select to view details")
			}
			meta := map[string]string{
				"verifyName":   check.Name,
				"verifyLabel":  check.Label,
				"verifyStatus": normalizeVerifyStatus(check.Status),
			}
			if check.Message != "" {
				meta["verifyMessage"] = check.Message
			}
			if check.Log != "" {
				meta["verifyLog"] = check.Log
			}
			if check.Report != "" {
				meta["verifyReport"] = check.Report
			}
			if !check.Updated.IsZero() {
				meta["verifyUpdated"] = check.Updated.Format(time.RFC3339)
			}
			if check.RunKind != "" {
				meta["verifyRunKind"] = check.RunKind
			}
			if check.DurationSeconds > 0 {
				meta["verifyDuration"] = strconv.FormatFloat(check.DurationSeconds, 'f', 1, 64)
			}
			if check.Score != nil {
				meta["verifyScore"] = strconv.FormatFloat(*check.Score, 'f', 1, 64)
			}
			if def.RequiresDocker {
				meta["requiresDocker"] = "1"
			}
			key := strings.ReplaceAll(check.Name, "/", "-")
			items = append(items, featureItemDefinition{
				Key:             "verify-check-" + key,
				Title:           title,
				Desc:            strings.Join(descParts, " • "),
				Command:         append([]string{}, def.Command...),
				ProjectRequired: true,
				PreviewKey:      "verify:check:" + check.Name,
				Meta:            meta,
			})
		}
		defaults := featureItemsForKey("verify")
		for _, def := range defaults {
			item := def
			switch item.Key {
			case "verify-acceptance":
				if check, ok := summary.Checks["acceptance"]; ok {
					actionParts := []string{}
					actionParts = append(actionParts, verifyStatusLabel(check.Status))
					if !check.Updated.IsZero() {
						actionParts = append(actionParts, "Updated "+formatRelativeTime(check.Updated))
					}
					if len(actionParts) > 0 {
						item.Desc = strings.Join(actionParts, " • ")
					}
				}
			case "verify-all":
				if summary.LastUpdated.IsZero() {
					item.Desc = "Run full verification suite"
				} else {
					item.Desc = fmt.Sprintf("%d/%d passing • Updated %s", summary.Stats.Passed, summary.Stats.Total, formatRelativeTime(summary.LastUpdated))
				}
			}
			items = append(items, item)
		}
	case "tokens":
		if summary := tokensSummary(project); summary != "" {
			items = append(items, featureItemDefinition{
				Key:   "tokens-summary",
				Title: "Token usage",
				Desc:  summary,
			})
		}
	case "reports":
		if summary := reportsSummary(project); summary != "" {
			items = append(items, featureItemDefinition{
				Key:   "reports-summary",
				Title: "Reports",
				Desc:  summary,
			})
		}
	case "env":
		if summary := envPreview(project); summary != "" {
			items = append(items, featureItemDefinition{
				Key:   "env-preview",
				Title: ".env keys",
				Desc:  summary,
			})
		}
	}

	if appendDefaults {
		defs := featureItemsForKey(featureKey)
		for _, def := range defs {
			items = append(items, def)
		}
	}
	if featureKey == "docs" && len(docHistory) > 0 {
		items = append(items, docHistory...)
	}
	if !dockerAvailable {
		for i := range items {
			if itemRequiresDocker(items[i]) {
				items[i].Disabled = true
				if strings.TrimSpace(items[i].DisabledReason) == "" {
					items[i].DisabledReason = "Requires Docker Desktop / CLI"
				}
			}
		}
	}
	return items
}

func decorateDatabaseItems(project *discoveredProject, items []featureItemDefinition, info databaseDumpInfo) []featureItemDefinition {
	for idx := range items {
		if items[idx].Key != "create-db-dump" {
			continue
		}
		item := &items[idx]
		if item.Meta == nil {
			item.Meta = make(map[string]string)
		}
		if info.DirRel != "" {
			item.Meta["dbDumpDirRel"] = info.DirRel
		}
		if info.Found {
			item.LastUpdated = info.Latest
			item.Desc = buildDatabaseActionDescription(info)
			for _, file := range info.Files {
				switch file.Kind {
				case "schema":
					item.Meta["dbSchemaRel"] = file.RelPath
					item.Meta["dbSchemaMod"] = file.ModTime.UTC().Format(time.RFC3339)
					item.Meta["dbSchemaSize"] = fmt.Sprintf("%d", file.Size)
				case "seed":
					item.Meta["dbSeedRel"] = file.RelPath
					item.Meta["dbSeedMod"] = file.ModTime.UTC().Format(time.RFC3339)
					item.Meta["dbSeedSize"] = fmt.Sprintf("%d", file.Size)
				}
			}
		} else if info.DirPresent && strings.TrimSpace(info.DirRel) != "" {
			placeholder := fmt.Sprintf("Awaiting schema.sql/seed.sql under %s", trimDumpRel(info.DirRel))
			if strings.TrimSpace(item.Desc) == "" || strings.Contains(strings.ToLower(item.Desc), "export schema") {
				item.Desc = placeholder
			}
		}
	}
	return items
}

func buildDatabaseActionDescription(info databaseDumpInfo) string {
	if !info.Found {
		return ""
	}
	var parts []string
	for _, file := range info.Files {
		name := filepath.Base(file.RelPath)
		piece := fmt.Sprintf("%s %s ago", name, formatRelativeTime(file.ModTime))
		if file.Size > 0 {
			piece += fmt.Sprintf(" • %s", formatByteSize(file.Size))
		}
		parts = append(parts, piece)
	}
	if info.DirRel != "" {
		parts = append(parts, trimDumpRel(info.DirRel))
	}
	return strings.Join(parts, " • ")
}

func buildOverviewItems(project *discoveredProject) []featureItemDefinition {
	if project == nil {
		return nil
	}
	stats := project.Stats
	if len(stats.Pipeline) == 0 {
		return []featureItemDefinition{{
			Key:   "overview-empty",
			Title: "Pipeline unavailable",
			Desc:  "No pipeline data yet – run create-project to bootstrap.",
			Meta:  map[string]string{"overview": "empty"},
		}}
	}

	var items []featureItemDefinition
	for idx, step := range stats.Pipeline {
		icon := pipelineStateGlyph(step.State)
		desc := pipelineStepSummary(step)
		meta := map[string]string{
			"overview":      "pipeline",
			"pipelineStep":  step.Label,
			"pipelineState": string(step.State),
		}
		items = append(items, featureItemDefinition{
			Key:           fmt.Sprintf("pipeline-step-%d", idx),
			Title:         fmt.Sprintf("%s %s", icon, step.Label),
			Desc:          desc,
			Artifacts:     append([]pipelineArtifact(nil), step.Artifacts...),
			PipelineState: step.State,
			PipelineIndex: idx,
			LastUpdated:   step.LastUpdated,
			Meta:          meta,
		})
	}

	if stats.TasksTotal > 0 {
		percent := percentOf(stats.TasksDone, stats.TasksTotal)
		items = append(items, featureItemDefinition{
			Key:   "overview-tasks",
			Title: fmt.Sprintf("Tasks %d%%", percent),
			Desc:  fmt.Sprintf("%d/%d complete", stats.TasksDone, stats.TasksTotal),
			Meta:  map[string]string{"overview": "tasks"},
		})
	}
	if stats.VerifyTotal > 0 {
		percent := percentOf(stats.VerifyPass, stats.VerifyTotal)
		items = append(items, featureItemDefinition{
			Key:   "overview-verify",
			Title: fmt.Sprintf("Verify %d%%", percent),
			Desc:  fmt.Sprintf("%d/%d passing", stats.VerifyPass, stats.VerifyTotal),
			Meta:  map[string]string{"overview": "verify"},
		})
	}

	items = append(items, featureItemDefinition{
		Key:     "overview-run-create-project",
		Title:   "Run create-project",
		Desc:    "Idempotent pipeline bootstrap (scan → verify).",
		Command: []string{"create-project", project.Path},
		Meta: map[string]string{
			"overview": "action",
			"action":   "create-project",
		},
	})
	items = append(items, featureItemDefinition{
		Key:             "overview-run-verify-all",
		Title:           "Run verify all",
		Desc:            "Re-run verification only; skips generation.",
		Command:         []string{"verify", "all"},
		ProjectRequired: true,
		Meta: map[string]string{
			"overview": "action",
			"action":   "verify-all",
		},
	})

	return items
}

func pipelineStateGlyph(state pipelineState) string {
	switch state {
	case pipelineStateDone:
		return "✓"
	case pipelineStateActive:
		return "●"
	default:
		return "…"
	}
}

func pipelineStateLabel(state pipelineState) string {
	switch state {
	case pipelineStateDone:
		return "done"
	case pipelineStateActive:
		return "in-progress"
	default:
		return "pending"
	}
}

func pipelineStepSummary(step pipelineStepStatus) string {
	switch step.State {
	case pipelineStateDone:
		if step.LastUpdated.IsZero() {
			return "Completed"
		}
		return fmt.Sprintf("Completed %s ago", formatRelativeTime(step.LastUpdated))
	case pipelineStateActive:
		return "In progress - ready to run"
	default:
		return "Pending - waiting on previous steps"
	}
}

func percentOf(value, total int) int {
	if total <= 0 {
		return 0
	}
	return (value*100 + total/2) / total
}

func formatRelativeTime(ts time.Time) string {
	if ts.IsZero() {
		return "N/A"
	}
	delta := time.Since(ts)
	if delta < time.Minute {
		return "just now"
	}
	if delta < time.Hour {
		return fmt.Sprintf("%dm", int(delta.Minutes()))
	}
	if delta < 24*time.Hour {
		return fmt.Sprintf("%dh", int(delta.Hours()))
	}
	if delta < 7*24*time.Hour {
		return fmt.Sprintf("%dd", int(delta.Hours()/24))
	}
	return ts.Format("2006-01-02")
}

func renderOverviewPreview(project *discoveredProject, item featureItemDefinition) string {
	if project == nil {
		return "Select a project to inspect the pipeline.\n"
	}

	var b strings.Builder
	b.WriteString(renderPipeline(project))
	b.WriteString("\n")

	switch item.Meta["overview"] {
	case "pipeline":
		idx := item.PipelineIndex
		if idx >= 0 && idx < len(project.Stats.Pipeline) {
			step := project.Stats.Pipeline[idx]
			b.WriteString(fmt.Sprintf("%s - %s\n", step.Label, capitalizeWord(pipelineStateLabel(step.State))))
			if step.LastUpdated.IsZero() {
				b.WriteString("No artifacts yet.\n")
			} else {
				b.WriteString(fmt.Sprintf("Last updated: %s ago\n", formatRelativeTime(step.LastUpdated)))
			}
			if len(step.Artifacts) == 0 {
				if step.LastUpdated.IsZero() {
					b.WriteString("\nNo artifacts yet.\n")
				} else {
					b.WriteString("\nArtifacts unavailable.\n")
				}
			} else {
				b.WriteString("\nArtifacts:\n")
				for _, art := range step.Artifacts {
					b.WriteString(fmt.Sprintf("• %s (%s ago)\n", art.Path, formatRelativeTime(art.ModTime)))
				}
			}
		}
	case "tasks":
		stats := project.Stats
		percent := percentOf(stats.TasksDone, stats.TasksTotal)
		b.WriteString(fmt.Sprintf("Tasks: %d/%d complete (%d%%).\n", stats.TasksDone, stats.TasksTotal, percent))
		b.WriteString("Use backlog commands to drill into epics/stories.\n")
	case "verify":
		stats := project.Stats
		percent := percentOf(stats.VerifyPass, stats.VerifyTotal)
		b.WriteString(fmt.Sprintf("Verify: %d/%d passing (%d%%).\n", stats.VerifyPass, stats.VerifyTotal, percent))
		b.WriteString("Re-run `verify all` to refresh acceptance and NFR checks.\n")
	case "action":
		switch item.Meta["action"] {
		case "create-project":
			b.WriteString("Re-run the entire pipeline. Safe to run again; generates missing artifacts and refreshes verification.\n")
		case "verify-all":
			b.WriteString("Execute only verification commands. Generation and database steps are skipped.\n")
		}
	default:
		if strings.TrimSpace(item.Desc) != "" {
			b.WriteString(item.Desc + "\n")
		}
	}

	return b.String()
}

func buildGenerateItems(project *discoveredProject) []featureItemDefinition {
	if project == nil {
		return nil
	}

	changeSet, err := gatherGenerateChanges(project.Path)
	if err != nil {
		return []featureItemDefinition{{
			Key:      "generate-error",
			Title:    "Generation status unavailable",
			Desc:     fmt.Sprintf("Failed to inspect project: %v", err),
			Disabled: true,
		}}
	}

	defaults := featureItemsForKey("generate")
	var allItem featureItemDefinition
	targetBase := make(map[string]featureItemDefinition)
	for _, def := range defaults {
		switch {
		case def.Key == "generate-all":
			allItem = def
		case strings.HasPrefix(def.Key, "generate-"):
			target := strings.TrimPrefix(def.Key, "generate-")
			targetBase[target] = def
		}
	}

	var items []featureItemDefinition

	if allItem.Key != "" {
		counts := aggregateGenerateCounts(changeSet)
		meta := ensureMeta(allItem.Meta)
		meta["generateKind"] = "command"
		meta["generateTarget"] = "all"
		meta["generateSource"] = changeSet.Source
		meta["generateSummary"] = counts.Summary()
		meta["generateCount"] = strconv.Itoa(counts.Total())
		if changeSet.Warning != "" {
			meta["generateWarning"] = changeSet.Warning
		}
		allItem.Meta = meta
		if counts.Total() > 0 {
			allItem.Title = fmt.Sprintf("%s (%d)", allItem.Title, counts.Total())
			allItem.Desc = formatGenerateSummary(counts, changeSet.Source)
		} else {
			allItem.Desc = "Regenerate all targets"
		}
		allItem.PreviewKey = "generate:command"
		items = append(items, allItem)
	}

	for _, key := range changeSet.Keys {
		entry := changeSet.Targets[key]
		def := entry.Definition
		if def.Key == "" {
			if candidate, ok := generateTargetByKey(key); ok {
				def = candidate
			}
		}
		baseItem, ok := targetBase[key]
		if !ok {
			baseItem = featureItemDefinition{
				Key:             "generate-" + key,
				Title:           fmt.Sprintf("generate %s", key),
				Desc:            fmt.Sprintf("Regenerate %s assets", strings.ToUpper(key)),
				Command:         []string{"generate", key},
				ProjectRequired: true,
			}
		}
		counts := entry.Counts
		meta := ensureMeta(baseItem.Meta)
		meta["generateKind"] = "target"
		meta["generateTarget"] = key
		meta["generateSource"] = changeSet.Source
		meta["generateSummary"] = counts.Summary()
		meta["generateCount"] = strconv.Itoa(counts.Total())
		if changeSet.Warning != "" {
			meta["generateWarning"] = changeSet.Warning
		}
		if changeSet.Source == generateDiffSourceSnapshot && changeSet.SnapshotRoot != "" {
			meta["generateSnapshotRoot"] = changeSet.SnapshotRoot
			if !changeSet.SnapshotStamp.IsZero() {
				meta["generateSnapshotAt"] = changeSet.SnapshotStamp.Format(time.RFC3339)
			}
		}
		baseItem.Meta = meta

		title := def.Title
		if title == "" {
			title = strings.ToUpper(key)
		}
		if counts.Total() > 0 {
			baseItem.Title = fmt.Sprintf("%s (%d)", title, counts.Total())
			baseItem.Desc = formatGenerateSummary(counts, changeSet.Source)
		} else {
			baseItem.Title = fmt.Sprintf("%s (0)", title)
			baseItem.Desc = "No pending changes detected"
		}
		baseItem.PreviewKey = "generate:target"
		items = append(items, baseItem)

		for _, change := range entry.Files {
			items = append(items, buildGenerateFileItem(changeSet.Source, key, change, changeSet.Warning))
		}
	}

	if changeSet.Warning != "" {
		items = append(items, featureItemDefinition{
			Key:        "generate-warning",
			Title:      "Snapshot mode",
			Desc:       changeSet.Warning,
			PreviewKey: "generate:warning",
			Meta: map[string]string{
				"generateKind":    "warning",
				"generateWarning": changeSet.Warning,
			},
		})
	}

	return items
}

func aggregateGenerateCounts(set generateChangeSet) changeCounts {
	var total changeCounts
	for _, key := range set.Keys {
		entry := set.Targets[key]
		total.Added += entry.Counts.Added
		total.Modified += entry.Counts.Modified
		total.Deleted += entry.Counts.Deleted
		total.Renamed += entry.Counts.Renamed
	}
	return total
}

func ensureMeta(meta map[string]string) map[string]string {
	if meta == nil {
		return map[string]string{}
	}
	clone := make(map[string]string, len(meta))
	for k, v := range meta {
		clone[k] = v
	}
	return clone
}

func formatGenerateSummary(counts changeCounts, source string) string {
	if counts.Total() == 0 {
		return "No pending changes"
	}
	summary := counts.Summary()
	if source != "" {
		return fmt.Sprintf("%s • source: %s", summary, strings.ToUpper(source))
	}
	return summary
}

func buildGenerateFileItem(source, targetKey string, change generateFileChange, warning string) featureItemDefinition {
	status := change.StatusLabel
	if strings.TrimSpace(status) == "" {
		status = strings.ToUpper(change.Status)
	}
	descParts := []string{status}
	if source != "" {
		descParts = append(descParts, strings.ToUpper(source))
	}
	if change.Status == "renamed" && strings.TrimSpace(change.OldPath) != "" {
		descParts = append(descParts, fmt.Sprintf("from %s", change.OldPath))
	}
	desc := strings.Join(descParts, " • ")
	meta := map[string]string{
		"generateKind":        "file",
		"generateTarget":      targetKey,
		"generatePath":        change.Path,
		"generateStatus":      change.Status,
		"generateStatusLabel": status,
		"generateDiffSource":  source,
	}
	if change.OldPath != "" {
		meta["generateOldPath"] = change.OldPath
	}
	if change.SnapshotOld != "" {
		meta["generateSnapshotOld"] = change.SnapshotOld
	}
	if warning != "" {
		meta["generateWarning"] = warning
	}
	return featureItemDefinition{
		Key:        "generate-file-" + targetKey + "-" + sanitizeGenerateKey(change.Path),
		Title:      "  • " + change.Path,
		Desc:       desc,
		Meta:       meta,
		PreviewKey: "generate:diff",
	}
}

func sanitizeGenerateKey(path string) string {
	replacer := strings.NewReplacer(
		" ", "_",
		"/", "_",
		"\\", "_",
		".", "_",
		":", "_",
	)
	key := replacer.Replace(path)
	key = strings.Trim(key, "_")
	if key == "" {
		key = "file"
	}
	return key
}

func renderGeneratePreview(project *discoveredProject, item featureItemDefinition) string {
	if project == nil {
		return "Select a project to inspect generate targets.\n"
	}
	if item.Meta == nil {
		return "Re-run generation for API/Web/Admin/DB/Docker targets and inspect diffs.\n"
	}

	kind := item.Meta["generateKind"]
	switch kind {
	case "command":
		count := item.Meta["generateCount"]
		summary := strings.TrimSpace(item.Meta["generateSummary"])
		source := strings.ToUpper(strings.TrimSpace(item.Meta["generateSource"]))
		var b strings.Builder
		fmt.Fprintf(&b, "Queue generation across all targets.\n")
		if summary != "" && summary != "No pending changes" {
			fmt.Fprintf(&b, "Pending changes: %s\n", summary)
		}
		if count != "" {
			fmt.Fprintf(&b, "Files touched: %s\n", count)
		}
		if source != "" {
			fmt.Fprintf(&b, "Diff source: %s\n", source)
		}
		b.WriteString("\nPress Enter to run `generate all`.\n")
		return b.String()
	case "target":
		var b strings.Builder
		target := item.Meta["generateTarget"]
		count := item.Meta["generateCount"]
		summary := strings.TrimSpace(item.Meta["generateSummary"])
		source := strings.ToUpper(strings.TrimSpace(item.Meta["generateSource"]))
		fmt.Fprintf(&b, "Target: %s\n", strings.ToUpper(target))
		if summary != "" {
			fmt.Fprintf(&b, "Status: %s\n", summary)
		}
		if count != "" {
			fmt.Fprintf(&b, "Files changed: %s\n", count)
		}
		if source != "" {
			fmt.Fprintf(&b, "Diff source: %s\n", source)
		}
		if warning := strings.TrimSpace(item.Meta["generateWarning"]); warning != "" {
			fmt.Fprintf(&b, "\nNotice: %s\n", warning)
		}
		b.WriteString("\nPress Enter to run targeted generation.\n")
		b.WriteString("Highlight a file below to inspect its diff.\n")
		return b.String()
	case "file":
		var b strings.Builder
		path := item.Meta["generatePath"]
		status := item.Meta["generateStatusLabel"]
		if status == "" {
			status = strings.ToUpper(item.Meta["generateStatus"])
		}
		source := strings.ToUpper(strings.TrimSpace(item.Meta["generateDiffSource"]))
		fmt.Fprintf(&b, "File: %s\n", path)
		if status != "" {
			fmt.Fprintf(&b, "Status: %s\n", status)
		}
		if old := strings.TrimSpace(item.Meta["generateOldPath"]); old != "" {
			fmt.Fprintf(&b, "Renamed from: %s\n", old)
		}
		if source != "" {
			fmt.Fprintf(&b, "Diff source: %s\n", source)
		}
		if warning := strings.TrimSpace(item.Meta["generateWarning"]); warning != "" {
			fmt.Fprintf(&b, "\nNotice: %s\n", warning)
		}
		b.WriteString("\nPress Enter to view a unified diff.\n")
		b.WriteString("Press `o` to open the file in your editor.\n")
		return b.String()
	case "warning":
		return item.Meta["generateWarning"] + "\n"
	default:
		return "Re-run generation for API/Web/Admin/DB/Docker targets and inspect diffs.\n"
	}
}

func capitalizeWord(s string) string {
	if s == "" {
		return s
	}
	lower := strings.ToLower(s)
	return strings.ToUpper(lower[:1]) + lower[1:]
}

func itemPreview(project *discoveredProject, featureKey string, item featureItemDefinition) string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s\n", item.Title)
	b.WriteString(strings.Repeat("─", len(item.Title)))
	b.WriteString("\n\n")

	if project != nil {
		stats := project.Stats
		fmt.Fprintf(&b, "Project: %s\nPath: %s\n", project.Name, project.Path)
		if stats.StageTotal > 0 {
			fmt.Fprintf(&b, "Stage: %s (%d/%d)\n", stats.StageLabel, stats.StageIndex, stats.StageTotal)
			if stats.NextStage != "" {
				fmt.Fprintf(&b, "Next: %s\n", stats.NextStage)
			}
		}
		if stats.TasksTotal > 0 {
			fmt.Fprintf(&b, "Tasks: %d/%d complete\n", stats.TasksDone, stats.TasksTotal)
		}
		if stats.VerifyTotal > 0 {
			fmt.Fprintf(&b, "Verify: %d/%d passing\n", stats.VerifyPass, stats.VerifyTotal)
		}
		if !project.Stats.LastRun.IsZero() {
			fmt.Fprintf(&b, "Last activity: %s\n", project.Stats.LastRun.Format(time.RFC822))
		}
		b.WriteString("\n")
		b.WriteString(item.Desc + "\n\n")
	}

	switch featureKey {
	case "overview":
		b.WriteString(renderOverviewPreview(project, item))
	case "tasks":
		b.WriteString("Trigger backlog automation commands directly from here.\n")
	case "docs":
		b.WriteString(renderDocsPreview(project, item))
	case "generate":
		b.WriteString(renderGeneratePreview(project, item))
	case "database":
		b.WriteString("Provision, import, seed, or export the project database.\n")
	case "services":
		b.WriteString("Monitor docker-compose services, container health, and HTTP endpoints.\n")
		b.WriteString("Shortcuts: u=up • l=logs • d=down • o=open endpoint • 1-9 open specific endpoint.\n")
	case "verify":
		b.WriteString("Run acceptance or full verification suites and inspect their reports.\n")
	case "tokens":
		b.WriteString("Track Codex/OpenAI token usage and costs over time.\n")
	case "reports":
		b.WriteString("Browse generated reports and toggle automation defaults.\n")
	case "env":
		b.WriteString("Review and edit .env values across project applications (editing coming soon).\n")
	default:
		if item.Desc == "" {
			b.WriteString("Use this command from the preview panel.\n")
		}
	}

	if item.Disabled {
		reason := strings.TrimSpace(item.DisabledReason)
		if reason == "" {
			reason = "Action disabled."
		}
		b.WriteString("\nStatus: " + reason + "\n")
	} else if len(item.Command) > 0 {
		b.WriteString("\nCommand:\n  gpt-creator ")
		b.WriteString(strings.Join(item.Command, " "))
		if project != nil {
			flag := item.ProjectFlag
			if flag == "" {
				flag = "--project"
			}
			if flag != "" {
				b.WriteString(" ")
				b.WriteString(flag)
				b.WriteString(" \"")
				b.WriteString(project.Path)
				b.WriteString("\"")
			}
		}
		b.WriteString("\nPress Enter while focused on the preview to run this command.\n")
	} else if project == nil {
		b.WriteString("\nSelect or add a project to enable commands.\n")
	}

	return b.String()
}

func docsSummary(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	docsDir := filepath.Join(project.Path, ".gpt-creator", "staging", "docs")
	variations := []string{"PDR.md", "pdr.md", "product-design-record.md", "SDS.md", "sds.md", "system-design-spec.md"}
	for _, name := range variations {
		path := filepath.Join(docsDir, name)
		if info, err := os.Stat(path); err == nil {
			return fmt.Sprintf("%s updated %s", name, info.ModTime().Format(time.RFC822))
		}
	}
	if info, err := os.Stat(docsDir); err == nil {
		return fmt.Sprintf("Docs updated %s", info.ModTime().Format(time.RFC822))
	}
	return ""
}

func generationSummary(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	targets := map[string]string{
		"API":    filepath.Join(project.Path, "apps", "api"),
		"Web":    filepath.Join(project.Path, "apps", "web"),
		"Admin":  filepath.Join(project.Path, "apps", "admin"),
		"DB":     filepath.Join(project.Path, "apps", "db"),
		"Docker": filepath.Join(project.Path, "docker"),
	}
	var available []string
	for label, path := range targets {
		if dirExists(path) {
			available = append(available, label)
		}
	}
	if len(available) == 0 {
		return ""
	}
	return "Available: " + strings.Join(available, ", ")
}

func databaseSummary(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	info := gatherDatabaseDumpInfo(project.Path)
	summary := databaseSummaryFromInfo(project, info)
	if summary != "" {
		return summary
	}
	return ""
}

func databaseSummaryFromInfo(project *discoveredProject, info databaseDumpInfo) string {
	if project == nil {
		return ""
	}
	if info.Found {
		return buildDatabaseActionDescription(info)
	}
	if info.DirPresent && strings.TrimSpace(info.DirRel) != "" {
		return fmt.Sprintf("Awaiting schema.sql/seed.sql under %s", trimDumpRel(info.DirRel))
	}
	dbDir := filepath.Join(project.Path, "db")
	if stat, err := os.Stat(dbDir); err == nil && stat.IsDir() {
		return fmt.Sprintf("db/ updated %s", stat.ModTime().Format(time.RFC822))
	}
	legacyDir := filepath.Join(project.Path, ".gpt-creator", "staging", "db")
	if stat, err := os.Stat(legacyDir); err == nil && stat.IsDir() {
		return fmt.Sprintf("staging/db updated %s", stat.ModTime().Format(time.RFC822))
	}
	return ""
}

func servicesSummary(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	compose := filepath.Join(project.Path, "docker-compose.yml")
	if info, err := os.Stat(compose); err == nil {
		return fmt.Sprintf("docker-compose.yml updated %s", info.ModTime().Format(time.RFC822))
	}
	dockerDir := filepath.Join(project.Path, "docker")
	if dirExists(dockerDir) {
		return "Docker resources ready"
	}
	return ""
}

func tokensSummary(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	logPath := filepath.Join(project.Path, ".gpt-creator", "logs", "codex-usage.ndjson")
	if info, err := os.Stat(logPath); err == nil {
		return fmt.Sprintf("Usage log updated %s", info.ModTime().Format(time.RFC822))
	}
	return ""
}

func reportsSummary(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	reportsDir := filepath.Join(project.Path, "reports")
	entries, err := os.ReadDir(reportsDir)
	if err != nil || len(entries) == 0 {
		return ""
	}
	return fmt.Sprintf("%d reports available", len(entries))
}

func envPreview(project *discoveredProject) string {
	if project == nil {
		return ""
	}
	data, err := os.ReadFile(filepath.Join(project.Path, ".env"))
	if err != nil {
		return ""
	}
	lines := strings.Split(string(data), "\n")
	var keys []string
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if idx := strings.Index(line, "="); idx > 0 {
			keys = append(keys, line[:idx])
		}
		if len(keys) >= 4 {
			break
		}
	}
	if len(keys) == 0 {
		return ""
	}
	return "Keys: " + strings.Join(keys, ", ")
}

func itemRequiresDocker(item featureItemDefinition) bool {
	if item.Meta != nil && item.Meta["requiresDocker"] == "1" {
		return true
	}
	if strings.HasPrefix(item.Key, "run-") || strings.HasPrefix(item.Key, "verify-") {
		return true
	}
	if len(item.Command) == 0 {
		return false
	}
	switch item.Command[0] {
	case "run", "verify":
		return true
	}
	return false
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
