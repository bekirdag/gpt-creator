package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/atotto/clipboard"
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/list"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type focusArea int

const (
	focusWorkspace focusArea = iota
	focusProjects
	focusFeatures
	focusItems
	focusPreview
)

type workspaceItemKind int

const (
	workspaceKindRoot workspaceItemKind = iota
	workspaceKindNewProject
	workspaceKindAddRoot
)

type inputMode int

const (
	inputNone inputMode = iota
	inputAddRoot
	inputNewProjectPath
	inputNewProjectTemplate
	inputNewProjectConfirm
	inputAttachRFP
	inputCommandPalette
)

type workspaceRoot struct {
	Label  string
	Path   string
	Pinned bool
}

type workspaceItem struct {
	kind   workspaceItemKind
	path   string
	pinned bool
}

type projectItem struct {
	project *discoveredProject
}

type paletteEntry struct {
	label           string
	command         []string
	description     string
	requiresProject bool
	meta            map[string]string
}

type jobMsg interface {
	isJob()
}

type jobStartedMsg struct {
	Title string
}

func (jobStartedMsg) isJob() {}

type jobLogMsg struct {
	Title string
	Line  string
}

func (jobLogMsg) isJob() {}

type jobFinishedMsg struct {
	Title string
	Err   error
}

func (jobFinishedMsg) isJob() {}

type jobChannelClosedMsg struct{}

func (jobChannelClosedMsg) isJob() {}

type workspaceSelectedMsg struct {
	item workspaceItem
}

type projectSelectedMsg struct {
	project *discoveredProject
}

type featureSelectedMsg struct {
	project *discoveredProject
	feature featureDefinition
}

type itemSelectedMsg struct {
	project  *discoveredProject
	feature  featureDefinition
	item     featureItemDefinition
	activate bool
}

type artifactCategorySelectedMsg struct {
	category artifactCategory
}

type artifactNodeHighlightedMsg struct {
	node artifactNode
}

type artifactNodeToggleMsg struct {
	node artifactNode
}

type artifactNodeActivatedMsg struct {
	node artifactNode
}

type backlogLoadedMsg struct {
	data *backlogData
	err  error
}

type artifactSplitState struct {
	Enabled   bool
	PlanRel   string
	TargetRel string
}

type backlogNodeHighlightedMsg struct {
	node backlogNode
}

type backlogNodeToggleMsg struct {
	node backlogNode
}

type backlogRowHighlightedMsg struct {
	row backlogRow
}

type backlogToggleRequest struct {
	row backlogRow
}

type backlogStatusUpdatedMsg struct {
	node   backlogNode
	status string
	err    error
}

type servicesLoadedMsg struct {
	items []featureItemDefinition
}

type servicesPollMsg struct{}

const servicesPollInterval = 2 * time.Second

type keyMap struct {
	quit        key.Binding
	nextFocus   key.Binding
	prevFocus   key.Binding
	toggleLogs  key.Binding
	openPalette key.Binding
	closePal    key.Binding
	runPal      key.Binding
	openEditor  key.Binding
	togglePin   key.Binding
	copyPath    key.Binding
	copySnippet key.Binding
	toggleSplit key.Binding
}

func newKeyMap() keyMap {
	return keyMap{
		quit:        key.NewBinding(key.WithKeys("q", "ctrl+c")),
		nextFocus:   key.NewBinding(key.WithKeys("tab")),
		prevFocus:   key.NewBinding(key.WithKeys("shift+tab")),
		toggleLogs:  key.NewBinding(key.WithKeys("f6")),
		openPalette: key.NewBinding(key.WithKeys(":")),
		closePal:    key.NewBinding(key.WithKeys("esc")),
		runPal:      key.NewBinding(key.WithKeys("enter")),
		openEditor:  key.NewBinding(key.WithKeys("o")),
		togglePin:   key.NewBinding(key.WithKeys("p")),
		copyPath:    key.NewBinding(key.WithKeys("y")),
		copySnippet: key.NewBinding(key.WithKeys("Y")),
		toggleSplit: key.NewBinding(key.WithKeys("s")),
	}
}

type model struct {
	width  int
	height int

	styles styles
	keys   keyMap

	workspaceRoots []workspaceRoot
	currentRoot    *workspaceRoot
	projects       []discoveredProject
	currentProject *discoveredProject
	currentFeature string
	currentItem    featureItemDefinition

	workspaceCol         *selectableColumn
	projectsCol          *selectableColumn
	featureCol           *selectableColumn
	itemsCol             *actionColumn
	servicesCol          *servicesTableColumn
	artifactsCol         *selectableColumn
	artifactTreeCol      *artifactTreeColumn
	previewCol           *previewColumn
	columns              []column
	defaultColumns       []column
	usingTasksLayout     bool
	usingServicesLayout  bool
	usingArtifactsLayout bool
	backlogCol           *backlogTreeColumn
	backlogTable         *backlogTableColumn

	focus int

	showLogs   bool
	logsHeight int
	logs       viewport.Model
	logLines   []string

	inputActive bool
	inputMode   inputMode
	inputPrompt string
	inputField  textinput.Model

	jobRunner *jobManager

	commandEntries []paletteEntry
	paletteMatches []paletteEntry
	paletteIndex   int

	pinnedPaths        map[string]bool
	uiConfig           *uiConfig
	uiConfigPath       string
	telemetry          *telemetryLogger
	serviceHealth      map[string]string
	servicesPolling    bool
	dockerAvailable    bool
	seenProjects       map[string]bool
	createProjectJobs  map[string]string
	lastProjectRefresh map[string]time.Time
	jobProjectPaths    map[string]string

	toastMessage string
	toastExpires time.Time

	pendingNewProjectPath     string
	pendingNewProjectTemplate string

	currentDocRelPath       string
	currentDocDiffBase      string
	currentDocType          string
	lastDocTelemetryKey     string
	currentVerifyCheck      string
	lastVerifyPreviewKey    string
	currentGenerateTarget   string
	currentGenerateFile     string
	lastGenerateDiffKey     string
	currentDBSchemaPath     string
	currentDBSeedPath       string
	currentServiceEndpoints []serviceEndpoint
	artifactCategories      []artifactCategory
	artifactExplorers       map[string]*artifactExplorer
	currentArtifactCategory string
	currentArtifactKey      string
	currentArtifactRel      string
	artifactSplit           artifactSplitState

	suppressPipelineTelemetry bool

	backlog              *backlogData
	backlogLoading       bool
	backlogError         error
	backlogFilterType    backlogTypeFilter
	backlogStatusFilter  backlogStatusFilter
	backlogScope         backlogNode
	backlogActive        backlogNode
	selectedEpics        map[string]bool
	pendingBacklogReason string
	credentialHint       string
}

func initialModel() *model {
	s := newStyles()
	m := &model{
		styles:     s,
		keys:       newKeyMap(),
		logsHeight: 8,
		logLines: []string{
			"[INFO] Select a workspace root or add a project path to begin.",
			"[TIP] Use Tab/Shift+Tab or h/l to move focus across columns.",
			"[TIP] Press Enter to drill into a column; Backspace to step back.",
		},
	}

	m.inputField = textinput.New()
	m.inputField.Prompt = "> "
	m.inputField.CharLimit = 256
	m.jobRunner = newJobManager()
	m.seenProjects = make(map[string]bool)
	m.pinnedPaths = make(map[string]bool)
	m.createProjectJobs = make(map[string]string)
	m.lastProjectRefresh = make(map[string]time.Time)
	m.jobProjectPaths = make(map[string]string)
	m.selectedEpics = make(map[string]bool)
	m.artifactExplorers = make(map[string]*artifactExplorer)
	m.backlogFilterType = backlogTypeFilterAll
	m.backlogStatusFilter = backlogStatusFilterAll
	if cfg, cfgPath := loadUIConfig(); cfg != nil {
		for _, path := range cfg.Pinned {
			clean := filepath.Clean(path)
			if clean != "" {
				m.pinnedPaths[clean] = true
			}
		}
		m.uiConfig = cfg
		m.uiConfigPath = cfgPath
	}
	m.dockerAvailable = dockerCLIAvailable()
	m.telemetry = newTelemetryLogger(filepath.Join(resolveConfigDir(), "ui-events.ndjson"))
	m.serviceHealth = make(map[string]string)

	m.workspaceRoots = defaultWorkspaceRoots()
	m.ensurePinnedRoots()

	m.workspaceCol = newSelectableColumn("Workspace", nil, 22, func(entry listEntry) tea.Cmd {
		if item, ok := entry.payload.(workspaceItem); ok {
			return func() tea.Msg { return workspaceSelectedMsg{item: item} }
		}
		return nil
	}, s)

	m.projectsCol = newSelectableColumn("Projects", nil, 26, func(entry listEntry) tea.Cmd {
		if payload, ok := entry.payload.(projectItem); ok && payload.project != nil {
			return func() tea.Msg { return projectSelectedMsg{project: payload.project} }
		}
		return nil
	}, s)

	m.featureCol = newSelectableColumn("Feature", nil, 26, func(entry listEntry) tea.Cmd {
		if def, ok := entry.payload.(featureDefinition); ok {
			return func() tea.Msg {
				return featureSelectedMsg{project: m.currentProject, feature: def}
			}
		}
		return nil
	}, s)

	m.artifactsCol = newSelectableColumn("Artifacts", nil, 26, func(entry listEntry) tea.Cmd {
		if cat, ok := entry.payload.(artifactCategory); ok {
			return func() tea.Msg { return artifactCategorySelectedMsg{category: cat} }
		}
		return nil
	}, s)
	m.artifactsCol.SetHighlightFunc(func(entry listEntry) tea.Cmd {
		if cat, ok := entry.payload.(artifactCategory); ok {
			return func() tea.Msg { return artifactCategorySelectedMsg{category: cat} }
		}
		return nil
	})

	m.itemsCol = newActionColumn("Actions", s)
	m.itemsCol.SetHighlightFunc(func(item featureItemDefinition, activate bool) tea.Cmd {
		if m.currentProject == nil {
			return nil
		}
		feature := findFeatureDefinition(m.currentFeature)
		return func() tea.Msg {
			return itemSelectedMsg{
				project:  m.currentProject,
				feature:  feature,
				item:     item,
				activate: activate,
			}
		}
	})

	m.servicesCol = newServicesTableColumn("Services", s)
	m.servicesCol.SetHighlightFunc(func(item featureItemDefinition, activate bool) tea.Cmd {
		if m.currentProject == nil {
			return nil
		}
		feature := findFeatureDefinition("services")
		return func() tea.Msg {
			return itemSelectedMsg{
				project:  m.currentProject,
				feature:  feature,
				item:     item,
				activate: activate,
			}
		}
	})

	m.backlogCol = newBacklogTreeColumn("Epics/Stories/Tasks", s)
	m.backlogCol.SetCallbacks(
		m.backlogHighlightCmd,
		m.backlogToggleCmd,
		m.backlogActivateCmd,
	)
	m.backlogTable = newBacklogTableColumn("Backlog", s)
	m.backlogTable.SetCallbacks(
		m.backlogRowHighlightCmd,
		m.backlogRowToggleCmd,
	)

	m.artifactTreeCol = newArtifactTreeColumn("Files", s)
	m.artifactTreeCol.SetCallbacks(
		func(node artifactNode) tea.Cmd {
			return func() tea.Msg { return artifactNodeHighlightedMsg{node: node} }
		},
		func(node artifactNode) tea.Cmd {
			return func() tea.Msg { return artifactNodeToggleMsg{node: node} }
		},
		func(node artifactNode) tea.Cmd {
			return func() tea.Msg { return artifactNodeActivatedMsg{node: node} }
		},
	)

	m.previewCol = newPreviewColumn(32)
	m.previewCol.SetContent("Select an item to preview details.\n")

	m.columns = []column{
		m.workspaceCol,
		m.projectsCol,
		m.featureCol,
		m.itemsCol,
		m.previewCol,
	}
	m.defaultColumns = append([]column(nil), m.columns...)

	m.logs = viewport.New(80, m.logsHeight)
	m.refreshLogs()

	m.refreshWorkspaceColumn()
	if len(m.workspaceRoots) > 0 {
		m.currentRoot = &m.workspaceRoots[0]
		m.focus = int(focusWorkspace)
		m.refreshProjectsForCurrentRoot()
	}

	m.refreshCommandCatalog()

	return m
}

func (m *model) Init() tea.Cmd {
	return nil
}

func (m *model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	if m.inputActive {
		if paletteActive := m.inputMode == inputCommandPalette; paletteActive {
			if keyMsg, ok := msg.(tea.KeyMsg); ok {
				switch keyMsg.String() {
				case "up", "ctrl+p":
					m.movePaletteSelection(-1)
					return m, nil
				case "down", "ctrl+n":
					m.movePaletteSelection(1)
					return m, nil
				case "tab":
					m.movePaletteSelection(1)
					return m, nil
				case "shift+tab":
					m.movePaletteSelection(-1)
					return m, nil
				}
			}
		}

		switch keyMsg := msg.(type) {
		case tea.KeyMsg:
			switch keyMsg.String() {
			case "esc":
				m.closeInput()
				return m, nil
			case "enter":
				value := strings.TrimSpace(m.inputField.Value())
				cmd, keepOpen := m.handleInputSubmit(value)
				if !keepOpen {
					m.closeInput()
				}
				if cmd != nil {
					cmds = append(cmds, cmd)
				}
				return m, tea.Batch(cmds...)
			}
		}
		var cmd tea.Cmd
		m.inputField, cmd = m.inputField.Update(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
		if m.inputMode == inputCommandPalette {
			m.updatePaletteMatches(m.inputField.Value())
		}
		return m, tea.Batch(cmds...)
	}

	switch message := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = message.Width, message.Height
		m.applyLayout()
		return m, nil

	case tea.KeyMsg:
		if handled, cmd := m.handleGlobalKey(message); handled {
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
			return m, tea.Batch(cmds...)
		}
	}

	if m.focus >= 0 && m.focus < len(m.columns) {
		col := m.columns[m.focus]
		var cmd tea.Cmd
		m.columns[m.focus], cmd = col.Update(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	switch message := msg.(type) {
	case workspaceSelectedMsg:
		m.handleWorkspaceSelected(message.item)
	case projectSelectedMsg:
		if cmd := m.handleProjectSelected(message.project); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case featureSelectedMsg:
		if cmd := m.handleFeatureSelected(message.feature); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case itemSelectedMsg:
		m.handleItemSelected(message)
	case artifactCategorySelectedMsg:
		if cmd := m.handleArtifactCategorySelected(message.category); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case artifactNodeHighlightedMsg:
		m.handleArtifactNodeHighlighted(message.node)
	case artifactNodeToggleMsg:
		if cmd := m.handleArtifactNodeToggle(message.node); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case artifactNodeActivatedMsg:
		if cmd := m.handleArtifactNodeActivated(message.node); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case jobMsg:
		if cmd := m.handleJobMessage(message); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case servicesLoadedMsg:
		m.handleServicesLoaded(message.items)
	case servicesPollMsg:
		if m.servicesPolling && m.currentFeature == "services" {
			if cmd := m.loadServicesCmd(); cmd != nil {
				cmds = append(cmds, cmd)
			}
			if cmd := m.scheduleServicePoll(); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
	case backlogLoadedMsg:
		m.handleBacklogLoaded(message)
	case backlogNodeHighlightedMsg:
		m.handleBacklogNodeHighlighted(message.node)
	case backlogNodeToggleMsg:
		m.handleBacklogToggle(message.node)
	case backlogRowHighlightedMsg:
		m.handleBacklogRowHighlighted(message.row)
	case backlogToggleRequest:
		if cmd := m.handleBacklogToggleRequest(message.row); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case backlogStatusUpdatedMsg:
		if cmd := m.handleBacklogStatusUpdated(message); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	m.applyLayout()
	return m, tea.Batch(cmds...)
}

func (m *model) View() string {
	var builder strings.Builder

	title := "gpt-creator • Miller Columns TUI"
	if m.currentRoot != nil {
		title += " • " + abbreviatePath(m.currentRoot.Path)
	}
	if m.currentProject != nil {
		title += " • " + m.currentProject.Name
	}
	builder.WriteString(m.styles.topBar.Width(m.width).Render(title))
	builder.WriteRune('\n')

	var colViews []string
	for i, col := range m.columns {
		colViews = append(colViews, col.View(m.styles, i == m.focus))
	}
	row := lipgloss.JoinHorizontal(lipgloss.Top, colViews...)
	builder.WriteString(row)
	builder.WriteRune('\n')

	if m.showLogs {
		logTitle := m.styles.columnTitle.Render("Job / Logs / Status")
		logBody := m.styles.panel.Width(m.width).Render(logTitle + "\n" + m.logs.View())
		builder.WriteString(logBody)
		builder.WriteRune('\n')
	}

	status := m.renderStatus()
	builder.WriteString(status)

	if m.inputActive {
		overlayWidth := min(64, m.width-4)
		if overlayWidth < 24 {
			overlayWidth = m.width - 4
		}
		if overlayWidth < 24 {
			overlayWidth = 24
		}
		content := m.styles.cmdPrompt.Render(m.inputPrompt) + "\n" + m.inputField.View()
		if m.inputMode == inputCommandPalette && len(m.paletteMatches) > 0 {
			content += "\n\n" + m.renderPaletteMatches(overlayWidth)
		}
		overlay := m.styles.cmdOverlay.Width(overlayWidth).Render(content)
		builder.WriteString("\n")
		builder.WriteString(lipgloss.Place(m.width, m.height/2, lipgloss.Center, lipgloss.Center, overlay))
	}

	return m.styles.app.Render(builder.String())
}

func (m *model) handleGlobalKey(msg tea.KeyMsg) (bool, tea.Cmd) {
	if m.currentFeature == "services" {
		switch focusArea(m.focus) {
		case focusItems, focusPreview:
			switch msg.String() {
			case "u":
				return true, m.runServiceCommand("run-up")
			case "d":
				return true, m.runServiceCommand("run-down")
			case "l":
				return true, m.runServiceCommand("run-logs")
			case "o", "O":
				m.openSelectedServiceEndpoint(-1)
				return true, nil
			default:
				if idx := parseServiceEndpointIndex(msg.String()); idx >= 0 {
					m.openSelectedServiceEndpoint(idx)
					return true, nil
				}
			}
		}
	}
	switch {
	case key.Matches(msg, m.keys.quit):
		return true, tea.Quit
	case key.Matches(msg, m.keys.nextFocus):
		m.focus = (m.focus + 1) % len(m.columns)
		return true, nil
	case key.Matches(msg, m.keys.prevFocus):
		m.focus = (m.focus - 1 + len(m.columns)) % len(m.columns)
		return true, nil
	case key.Matches(msg, m.keys.toggleLogs):
		m.showLogs = !m.showLogs
		m.applyLayout()
		return true, nil
	case key.Matches(msg, m.keys.openPalette):
		if !m.inputActive {
			m.openCommandPalette()
			return true, nil
		}
		return true, nil
	case key.Matches(msg, m.keys.openEditor):
		switch focusArea(m.focus) {
		case focusProjects:
			m.openProjectInEditor()
		case focusItems, focusPreview:
			switch m.currentFeature {
			case "docs":
				m.openCurrentDocInEditor()
			case "generate":
				m.openCurrentGenerateFileInEditor()
			case "database":
				m.openDatabaseDumpInEditor("schema")
			case "artifacts":
				m.openCurrentArtifactInEditor()
			}
		}
		return true, nil
	case key.Matches(msg, m.keys.togglePin):
		if focusArea(m.focus) == focusWorkspace {
			m.toggleSelectedWorkspacePin()
		}
		return true, nil
	case key.Matches(msg, m.keys.copyPath):
		if m.currentFeature == "artifacts" {
			m.copyCurrentArtifactPath()
			return true, nil
		}
	case key.Matches(msg, m.keys.copySnippet):
		if m.currentFeature == "artifacts" {
			m.copyCurrentArtifactSnippet()
			return true, nil
		}
	case key.Matches(msg, m.keys.toggleSplit):
		if m.currentFeature == "artifacts" {
			m.toggleArtifactSplit()
			return true, nil
		}
	}

	switch msg.String() {
	case "O":
		if (focusArea(m.focus) == focusPreview || focusArea(m.focus) == focusItems) && m.currentFeature == "database" {
			m.openDatabaseDumpInEditor("seed")
			return true, nil
		}
	case "enter":
		if focusArea(m.focus) == focusPreview {
			if len(m.currentItem.Command) > 0 {
				return true, m.runCurrentItemCommand()
			}
			if m.currentFeature == "docs" && m.handleDocsPreviewEnter() {
				return true, nil
			}
			return true, nil
		}
		return false, nil
	case "h", "left":
		if m.focus > 0 {
			m.focus--
		}
		return true, nil
	case "l", "right":
		if m.focus < len(m.columns)-1 {
			m.focus++
		}
		return true, nil
	case "backspace":
		m.stepBack()
		return true, nil
	}

	if m.currentFeature == "tasks" {
		switch msg.String() {
		case "f":
			m.backlogFilterType = m.backlogFilterType.Next()
			m.applyBacklogFilters()
			return true, nil
		case "s":
			m.backlogStatusFilter = m.backlogStatusFilter.Next()
			m.applyBacklogFilters()
			return true, nil
		case "ctrl+e", "E":
			m.runBacklogExport()
			return true, nil
		case "g":
			return true, m.queueTasksCommand([]string{"create-jira-tasks"})
		case "m":
			return true, m.queueTasksCommand([]string{"migrate-tasks"})
		case "r":
			return true, m.queueTasksCommand([]string{"refine-tasks"})
		case "c":
			return true, m.queueTasksCommand([]string{"create-tasks"})
		case "w":
			return true, m.queueTasksCommand([]string{"work-on-tasks"})
		}
	}

	return false, nil
}

func (m *model) stepBack() {
	switch focusArea(m.focus) {
	case focusPreview:
		m.focus = int(focusItems)
		m.currentItem = featureItemDefinition{}
		if m.currentFeature == "docs" {
			m.resetDocSelection()
		}
	case focusItems:
		if m.currentFeature == "docs" {
			m.resetDocSelection()
		}
		m.currentFeature = ""
		m.itemsCol.SetItems(nil)
		m.previewCol.SetContent("Select an item to preview details.\n")
		m.currentItem = featureItemDefinition{}
		m.focus = int(focusFeatures)
	case focusFeatures:
		if m.currentFeature == "docs" {
			m.resetDocSelection()
		}
		m.currentProject = nil
		m.featureCol.SetItems(nil)
		m.itemsCol.SetItems(nil)
		m.itemsCol.SetTitle("Actions")
		m.previewCol.SetContent("Select an item to preview details.\n")
		m.currentItem = featureItemDefinition{}
		m.focus = int(focusProjects)
	case focusProjects:
		m.focus = int(focusWorkspace)
	}
}

func (m *model) handleWorkspaceSelected(item workspaceItem) {
	switch item.kind {
	case workspaceKindRoot:
		root := m.findRoot(item.path)
		if root == nil {
			label := labelForPath(item.path)
			root = &workspaceRoot{Label: label, Path: item.path, Pinned: m.pinnedPaths[filepath.Clean(item.path)]}
			m.workspaceRoots = append(m.workspaceRoots, *root)
			m.ensurePinnedRoots()
			root = &m.workspaceRoots[len(m.workspaceRoots)-1]
		}
		m.currentRoot = root
		m.refreshProjectsForCurrentRoot()
		m.focus = int(focusProjects)
		cleanPath := filepath.Clean(root.Path)
		m.appendLog(fmt.Sprintf("Workspace selected: %s", abbreviatePath(root.Path)))
		fields := map[string]string{"path": cleanPath}
		if root.Pinned {
			fields["pinned"] = "true"
		}
		m.emitTelemetry("workspace_opened", fields)
		m.previewCol.SetContent(previewPath(&discoveredProject{Path: root.Path}, "."))
	case workspaceKindNewProject:
		defaultPath := ""
		if m.currentRoot != nil {
			defaultPath = filepath.Join(m.currentRoot.Path, "new-project")
		}
		m.startNewProjectFlow(defaultPath)
	case workspaceKindAddRoot:
		m.openInput("Add workspace path", "", inputAddRoot)
	}
}

func (m *model) handleProjectSelected(project *discoveredProject) tea.Cmd {
	if project == nil {
		return nil
	}
	prevFeature := m.currentFeature
	m.currentProject = project
	m.currentFeature = ""
	m.currentItem = featureItemDefinition{}
	m.resetDocSelection()
	m.currentGenerateTarget = ""
	m.currentGenerateFile = ""
	m.lastGenerateDiffKey = ""
	m.featureCol.SetItems(featureListEntries())
	m.itemsCol.SetTitle("Actions")
	m.itemsCol.SetItems(nil)
	m.previewCol.SetContent(previewPath(project, "."))
	m.focus = int(focusFeatures)
	m.appendLog(fmt.Sprintf("Project loaded: %s", project.Name))
	m.emitTelemetry("project_opened", map[string]string{"path": filepath.Clean(project.Path)})
	if prevFeature == "tasks" {
		if def := findFeatureDefinition("tasks"); def.Key != "" {
			return m.handleFeatureSelected(def)
		}
	} else if prevFeature == "services" {
		if def := findFeatureDefinition("services"); def.Key != "" {
			return m.handleFeatureSelected(def)
		}
	} else if prevFeature == "artifacts" {
		if def := findFeatureDefinition("artifacts"); def.Key != "" {
			return m.handleFeatureSelected(def)
		}
	}
	return nil
}

func (m *model) handleFeatureSelected(feature featureDefinition) tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	m.currentFeature = feature.Key
	m.currentItem = featureItemDefinition{}
	m.resetDocSelection()
	if feature.Key != "generate" {
		m.currentGenerateTarget = ""
		m.currentGenerateFile = ""
	}
	m.currentVerifyCheck = ""
	m.stopServicePolling()
	m.currentServiceEndpoints = nil
	if feature.Key == "tasks" {
		m.useTasksLayout(true)
		m.backlogScope = backlogNode{}
		m.previewCol.SetContent("Loading backlog…\n")
		m.updateCredentialHint()
		m.focus = int(focusFeatures)
		m.backlogLoading = true
		return m.loadBacklogCmd()
	}
	m.useTasksLayout(false)
	if feature.Key == "artifacts" {
		m.useServicesLayout(false)
		m.useArtifactsLayout(true)
		cmd := m.prepareArtifactsView()
		m.focus = int(focusFeatures)
		return cmd
	}
	if feature.Key == "services" {
		m.useServicesLayout(true)
		m.servicesCol.SetItems(nil)
		m.previewCol.SetContent("Gathering docker-compose services…\n")
		cmds := []tea.Cmd{}
		if cmd := m.loadServicesCmd(); cmd != nil {
			cmds = append(cmds, cmd)
		}
		if cmd := m.startServicePolling(); cmd != nil {
			cmds = append(cmds, cmd)
		}
		m.focus = int(focusItems)
		return tea.Batch(cmds...)
	}
	m.useServicesLayout(false)
	m.useArtifactsLayout(false)
	if feature.Key == "overview" {
		m.emitTelemetry("overview_opened", map[string]string{"path": filepath.Clean(m.currentProject.Path)})
		m.itemsCol.SetTitle("Overview")
	} else if feature.Key == "docs" {
		m.itemsCol.SetTitle("Docs")
	} else if feature.Key == "generate" {
		m.itemsCol.SetTitle("Targets")
	} else {
		m.itemsCol.SetTitle("Actions")
	}
	m.itemsCol.SetItems(featureItemEntries(m.currentProject, feature.Key, m.dockerAvailable))
	if item, ok := m.itemsCol.SelectedItem(); ok {
		if feature.Key == "overview" {
			m.suppressPipelineTelemetry = true
		}
		m.applyItemSelection(m.currentProject, feature.Key, item, false)
	} else {
		m.previewCol.SetContent("Select an item to preview details.\n")
	}
	m.focus = int(focusItems)
	return nil
}

func (m *model) handleItemSelected(msg itemSelectedMsg) {
	targetProject := msg.project
	if targetProject == nil {
		targetProject = m.currentProject
	}
	if targetProject == nil {
		return
	}
	featureKey := msg.feature.Key
	if featureKey == "" {
		featureKey = m.currentFeature
	}
	m.applyItemSelection(targetProject, featureKey, msg.item, msg.activate)
	if msg.activate {
		m.focus = int(focusPreview)
	}
}

func (m *model) applyItemSelection(project *discoveredProject, featureKey string, item featureItemDefinition, activate bool) {
	if project == nil {
		return
	}
	m.currentItem = item
	m.currentFeature = featureKey
	m.currentProject = project
	if featureKey == "docs" {
		m.handleDocItemSelection(item, activate)
	}
	if featureKey == "verify" {
		m.handleVerifyItemSelection(item)
	}
	if featureKey == "generate" {
		m.handleGenerateItemSelection(item, activate)
	}
	if featureKey == "database" {
		m.handleDatabaseItemSelection(item)
	}
	if featureKey == "services" {
		m.handleServiceItemSelection(item)
	} else {
		m.currentServiceEndpoints = nil
	}
	content := itemPreview(project, featureKey, item)
	if extra := renderDetailedPreview(project, featureKey, item); extra != "" {
		content += "\n\n" + extra
	}
	m.previewCol.SetContent(content)
	if featureKey == "overview" && !activate {
		if m.suppressPipelineTelemetry {
			m.suppressPipelineTelemetry = false
		} else if item.Meta != nil && item.Meta["overview"] == "pipeline" {
			stepLabel := item.Meta["pipelineStep"]
			if item.PipelineIndex >= 0 && item.PipelineIndex < len(project.Stats.Pipeline) {
				stepLabel = project.Stats.Pipeline[item.PipelineIndex].Label
			}
			fields := map[string]string{
				"path":  filepath.Clean(project.Path),
				"step":  stepLabel,
				"state": string(item.PipelineState),
			}
			if !item.LastUpdated.IsZero() {
				fields["last_updated"] = item.LastUpdated.UTC().Format(time.RFC3339)
			}
			m.emitTelemetry("pipeline_step_opened", fields)
		}
	}
	if activate {
		m.appendLog(fmt.Sprintf("Selected action: %s", item.Title))
	}
}

func (m *model) prepareArtifactsView() tea.Cmd {
	if m.currentProject == nil {
		m.artifactCategories = nil
		m.artifactExplorers = make(map[string]*artifactExplorer)
		m.artifactsCol.SetItems(nil)
		m.artifactTreeCol.SetNodes(nil)
		m.previewCol.SetContent("Select a project to browse artifacts.\n")
		return nil
	}
	m.artifactCategories = buildArtifactCategories(m.currentProject.Path)
	m.artifactExplorers = make(map[string]*artifactExplorer)
	items := make([]list.Item, 0, len(m.artifactCategories))
	for _, cat := range m.artifactCategories {
		items = append(items, listEntry{
			title:   cat.Title,
			desc:    cat.Description,
			payload: cat,
		})
	}
	m.artifactsCol.SetItems(items)
	m.artifactTreeCol.SetNodes(nil)
	m.currentArtifactCategory = ""
	m.currentArtifactKey = ""
	m.currentArtifactRel = ""
	m.clearArtifactSplit()
	if len(m.artifactCategories) == 0 {
		m.previewCol.SetContent("No artifact directories detected.\n")
		return nil
	}
	selected := m.artifactCategories[0]
	if entry, ok := m.artifactsCol.SelectedEntry(); ok {
		if cat, ok := entry.payload.(artifactCategory); ok {
			selected = cat
		}
	}
	return func() tea.Msg { return artifactCategorySelectedMsg{category: selected} }
}

func (m *model) handleArtifactCategorySelected(cat artifactCategory) tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	m.currentArtifactCategory = cat.Key
	explorer := m.ensureArtifactExplorer(cat)
	if explorer == nil {
		m.artifactTreeCol.SetNodes(nil)
		m.previewCol.SetContent("Unable to load artifacts for this category.\n")
		return nil
	}
	nodes := explorer.VisibleNodes()
	m.artifactTreeCol.SetNodes(nodes)
	if m.currentArtifactRel != "" {
		m.artifactTreeCol.SelectRel(m.currentArtifactRel)
	}

	if node, ok := m.artifactTreeCol.SelectedNode(); ok {
		m.currentArtifactKey = node.Key
		m.currentArtifactRel = node.Rel
		return func() tea.Msg { return artifactNodeHighlightedMsg{node: node} }
	}
	if len(nodes) > 0 {
		node := nodes[0]
		m.artifactTreeCol.SelectRel(node.Rel)
		m.currentArtifactKey = node.Key
		m.currentArtifactRel = node.Rel
		return func() tea.Msg { return artifactNodeHighlightedMsg{node: node} }
	}
	m.previewCol.SetContent("No files detected in this category.\n")
	return nil
}

func (m *model) ensureArtifactExplorer(cat artifactCategory) *artifactExplorer {
	if m.currentProject == nil {
		return nil
	}
	if m.artifactExplorers == nil {
		m.artifactExplorers = make(map[string]*artifactExplorer)
	}
	if explorer, ok := m.artifactExplorers[cat.Key]; ok && explorer != nil {
		return explorer
	}
	explorer := newArtifactExplorer(m.currentProject.Path, cat.Key, cat.Paths)
	for _, rootKey := range explorer.RootKeys() {
		_ = explorer.Expand(rootKey)
	}
	m.artifactExplorers[cat.Key] = explorer
	return explorer
}

func (m *model) artifactExplorerForCurrent() *artifactExplorer {
	if m.artifactExplorers == nil || m.currentArtifactCategory == "" {
		return nil
	}
	return m.artifactExplorers[m.currentArtifactCategory]
}

func (m *model) handleArtifactNodeHighlighted(node artifactNode) {
	if m.currentProject == nil {
		return
	}
	m.currentArtifactKey = node.Key
	m.currentArtifactRel = node.Rel
	if node.IsDir {
		m.clearArtifactSplit()
		m.previewCol.SetContent(m.renderArtifactPreview(node))
		return
	}
	if m.artifactSplit.Enabled {
		if content, ok := m.refreshArtifactSplit(node); ok {
			m.previewCol.SetContent(content)
			return
		}
		m.clearArtifactSplit()
	}
	m.previewCol.SetContent(m.renderArtifactPreview(node))
}

func (m *model) handleArtifactNodeToggle(node artifactNode) tea.Cmd {
	explorer := m.artifactExplorerForCurrent()
	if explorer == nil {
		return nil
	}
	target := explorer.Node(node.Key)
	if target == nil {
		return nil
	}
	prevExpanded := target.Expanded
	if err := explorer.Toggle(node.Key); err != nil {
		m.appendLog(fmt.Sprintf("Failed to read %s: %v", node.Rel, err))
		m.setToast("Unable to read directory", 4*time.Second)
	}
	nodes := explorer.VisibleNodes()
	m.artifactTreeCol.SetNodes(nodes)
	m.artifactTreeCol.SelectRel(target.Rel)
	updated := explorer.Node(node.Key)
	if updated != nil {
		if updated.Expanded && !prevExpanded && m.currentProject != nil {
			fields := map[string]string{
				"path":   filepath.Clean(m.currentProject.Path),
				"folder": updated.Rel,
			}
			m.emitTelemetry("folder_expanded", fields)
		}
		return func() tea.Msg { return artifactNodeHighlightedMsg{node: *updated} }
	}
	return nil
}

func (m *model) handleArtifactNodeActivated(node artifactNode) tea.Cmd {
	if node.IsDir {
		return nil
	}
	m.currentArtifactKey = node.Key
	m.currentArtifactRel = node.Rel
	m.openCurrentArtifactInEditor()
	return nil
}

func (m *model) renderArtifactPreview(node artifactNode) string {
	if m.currentProject == nil {
		return "Select a project to browse artifacts.\n"
	}
	rel := node.Rel
	if rel == "" {
		rel = "."
	}
	snippet := previewPath(m.currentProject, filepath.FromSlash(rel))
	if strings.TrimSpace(snippet) == "" {
		header := m.artifactAbsolutePath(rel)
		if node.IsDir {
			snippet = fmt.Sprintf("%s\nFolder preview unavailable.\n", header)
		} else {
			snippet = fmt.Sprintf("%s\nNo textual preview available.\n", header)
		}
	}
	snippet = strings.TrimRight(snippet, "\n")
	actions := []string{"o open in editor", "y copy path"}
	if !node.IsDir {
		actions = append(actions, "Y copy snippet", "s split diff")
	}
	return fmt.Sprintf("%s\n\nActions: %s\n", snippet, strings.Join(actions, " • "))
}

func (m *model) artifactAbsolutePath(rel string) string {
	if m.currentProject == nil {
		return filepath.FromSlash(rel)
	}
	return filepath.Join(m.currentProject.Path, filepath.FromSlash(rel))
}

func (m *model) clearArtifactSplit() {
	m.artifactSplit = artifactSplitState{}
}

func (m *model) refreshArtifactSplit(node artifactNode) (string, bool) {
	planRel, targetRel, ok := m.findArtifactCounterpart(node.Rel)
	if !ok {
		return "", false
	}
	view := m.renderArtifactSplitPreview(planRel, targetRel)
	if strings.TrimSpace(view) == "" {
		return "", false
	}
	m.artifactSplit = artifactSplitState{
		Enabled:   true,
		PlanRel:   planRel,
		TargetRel: targetRel,
	}
	return view, true
}

func (m *model) renderArtifactSplitPreview(planRel, targetRel string) string {
	leftPath := m.artifactAbsolutePath(planRel)
	rightPath := m.artifactAbsolutePath(targetRel)
	leftContent := readFileLimited(leftPath, maxDocPreviewBytes, maxDiffPreviewLines)
	rightContent := readFileLimited(rightPath, maxDocPreviewBytes, maxDiffPreviewLines)
	leftLines := strings.Split(leftContent, "\n")
	rightLines := strings.Split(rightContent, "\n")
	view := renderSideBySideDiff(planRel, targetRel, leftLines, rightLines)
	if strings.TrimSpace(view) == "" {
		return fmt.Sprintf("No diff available between %s and %s.\n", planRel, targetRel)
	}
	return fmt.Sprintf("%s\n\nPress `s` to exit split mode.\n", view)
}

const artifactSplitColumnWidth = 48

func renderSideBySideDiff(leftLabel, rightLabel string, leftLines, rightLines []string) string {
	width := artifactSplitColumnWidth
	var builder strings.Builder
	header := fmt.Sprintf("%-*s │ %-*s\n", width, leftLabel, width, rightLabel)
	divider := strings.Repeat("─", width) + "─┼─" + strings.Repeat("─", width) + "\n"
	builder.WriteString(header)
	builder.WriteString(divider)

	lines := 0
	chunks := diffLines(leftLines, rightLines)
	for _, chunk := range chunks {
		switch chunk.op {
		case diffEqual:
			for _, line := range chunk.lines {
				builder.WriteString(formatSplitRow("  "+line, "  "+line, width))
				lines++
				if lines >= maxDiffPreviewLines {
					builder.WriteString("… truncated\n")
					return strings.TrimRight(builder.String(), "\n")
				}
			}
		case diffDelete:
			for _, line := range chunk.lines {
				builder.WriteString(formatSplitRow("- "+line, "", width))
				lines++
				if lines >= maxDiffPreviewLines {
					builder.WriteString("… truncated\n")
					return strings.TrimRight(builder.String(), "\n")
				}
			}
		case diffInsert:
			for _, line := range chunk.lines {
				builder.WriteString(formatSplitRow("", "+ "+line, width))
				lines++
				if lines >= maxDiffPreviewLines {
					builder.WriteString("… truncated\n")
					return strings.TrimRight(builder.String(), "\n")
				}
			}
		}
	}
	return strings.TrimRight(builder.String(), "\n")
}

func formatSplitRow(left, right string, width int) string {
	return fmt.Sprintf("%s │ %s\n", padOrTrim(left, width), padOrTrim(right, width))
}

func padOrTrim(s string, width int) string {
	if width <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) > width {
		if width <= 1 {
			return string(runes[:width])
		}
		return string(runes[:width-1]) + "…"
	}
	if len(runes) < width {
		return s + strings.Repeat(" ", width-len(runes))
	}
	return s
}

func (m *model) findArtifactCounterpart(rel string) (string, string, bool) {
	if m.currentProject == nil {
		return "", "", false
	}
	clean := normalizeRel(rel)
	planPrefix := ".gpt-creator/staging/plan/"
	if strings.HasPrefix(clean, planPrefix) {
		tail := strings.TrimPrefix(clean, planPrefix)
		if strings.HasPrefix(tail, "apps/") {
			target := normalizeRel(tail)
			if _, err := os.Stat(m.artifactAbsolutePath(target)); err == nil {
				return clean, target, true
			}
		}
		return "", "", false
	}
	if strings.HasPrefix(clean, "apps/") {
		plan := normalizeRel(planPrefix + clean)
		if _, err := os.Stat(m.artifactAbsolutePath(plan)); err == nil {
			return plan, clean, true
		}
	}
	return "", "", false
}

func (m *model) currentArtifactNode() *artifactNode {
	explorer := m.artifactExplorerForCurrent()
	if explorer == nil {
		return nil
	}
	return explorer.Node(m.currentArtifactKey)
}

func (m *model) toggleArtifactSplit() {
	node := m.currentArtifactNode()
	if node == nil {
		m.setToast("Select a file first", 4*time.Second)
		return
	}
	if node.IsDir {
		m.setToast("Split view requires a file selection", 4*time.Second)
		return
	}
	if !m.artifactSplit.Enabled {
		if content, ok := m.refreshArtifactSplit(*node); ok {
			m.previewCol.SetContent(content)
			m.setToast("Split diff enabled", 4*time.Second)
			return
		}
		m.setToast("No generated counterpart found", 4*time.Second)
		return
	}
	m.clearArtifactSplit()
	m.previewCol.SetContent(m.renderArtifactPreview(*node))
	m.setToast("Split diff disabled", 3*time.Second)
}

func (m *model) openCurrentArtifactInEditor() {
	if m.currentProject == nil {
		m.appendLog("Select a project before opening files.")
		return
	}
	node := m.currentArtifactNode()
	if node == nil || node.IsDir {
		m.appendLog("Select a file to open in the editor.")
		m.setToast("Select a file first", 4*time.Second)
		return
	}
	abs := m.artifactAbsolutePath(node.Rel)
	if _, err := os.Stat(abs); err != nil {
		m.appendLog(fmt.Sprintf("Artifact not found: %s", abs))
		m.setToast("File not found", 5*time.Second)
		return
	}
	commandLine, err := launchEditor(abs)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to open artifact: %v", err))
		m.setToast("Failed to open file", 5*time.Second)
		return
	}
	m.appendLog("Opening artifact: " + commandLine)
	m.setToast("Opening artifact in editor", 4*time.Second)
	fields := map[string]string{
		"path": filepath.Clean(m.currentProject.Path),
		"file": node.Rel,
	}
	m.emitTelemetry("artifact_opened", fields)
}

func (m *model) copyCurrentArtifactPath() {
	node := m.currentArtifactNode()
	if node == nil {
		m.setToast("Select a file or folder first", 4*time.Second)
		return
	}
	path := node.Rel
	if path == "" {
		path = "."
	}
	if err := clipboard.WriteAll(path); err != nil {
		m.appendLog(fmt.Sprintf("Failed to copy path: %v", err))
		m.setToast("Clipboard unavailable", 4*time.Second)
		return
	}
	m.setToast("Artifact path copied", 3*time.Second)
}

func (m *model) copyCurrentArtifactSnippet() {
	if m.currentProject == nil {
		m.setToast("Select a project first", 4*time.Second)
		return
	}
	node := m.currentArtifactNode()
	if node == nil || node.IsDir {
		m.setToast("Select a file to copy its contents", 4*time.Second)
		return
	}
	abs := m.artifactAbsolutePath(node.Rel)
	content := readFileLimited(abs, maxDocPreviewBytes, maxDocPreviewLines)
	if strings.TrimSpace(content) == "" {
		m.setToast("No content available to copy", 4*time.Second)
		return
	}
	if err := clipboard.WriteAll(content); err != nil {
		m.appendLog(fmt.Sprintf("Failed to copy snippet: %v", err))
		m.setToast("Clipboard unavailable", 4*time.Second)
		return
	}
	m.setToast("Snippet copied to clipboard", 3*time.Second)
}

func (m *model) handleJobMessage(msg jobMsg) tea.Cmd {
	var followCmd tea.Cmd
	var reason string
	switch message := msg.(type) {
	case jobStartedMsg:
		m.appendLog(fmt.Sprintf("[job] %s started", message.Title))
		m.refreshCreateProjectProgress(message.Title)
	case jobLogMsg:
		if strings.HasPrefix(message.Line, "::verify::") {
			payload, err := parseVerifyEventMessage(strings.TrimPrefix(message.Line, "::verify::"))
			if err == nil {
				m.handleVerifyJobEvent(message.Title, payload)
			}
		}
		m.appendLog(message.Line)
		m.refreshCreateProjectProgress(message.Title)
	case jobFinishedMsg:
		if message.Err != nil {
			m.appendLog(fmt.Sprintf("[job] %s failed: %v", message.Title, message.Err))
		} else {
			m.appendLog(fmt.Sprintf("[job] %s completed successfully", message.Title))
			lower := strings.ToLower(message.Title)
			switch {
			case strings.Contains(lower, "create-jira-tasks"):
				reason = "create-jira-tasks"
			case strings.Contains(lower, "migrate-tasks"):
				reason = "migrate-tasks"
			case strings.Contains(lower, "refine-tasks"):
				reason = "refine-tasks"
			case strings.Contains(lower, "create-tasks"):
				reason = "create-tasks"
			case strings.Contains(lower, "work-on-tasks"):
				reason = "work-on-tasks"
			}
			if reason != "" && m.currentFeature == "tasks" {
				if reason == "create-jira-tasks" && len(m.selectedEpics) > 0 && m.currentProject != nil {
					if err := pruneBacklogEpics(backlogDBPath(m.currentProject.Path), sortedEpicKeys(m.selectedEpics)); err != nil {
						m.appendLog(fmt.Sprintf("Failed to prune backlog epics: %v", err))
					}
				}
				event := ""
				switch reason {
				case "create-jira-tasks":
					event = "tasks_generated"
				case "migrate-tasks":
					event = "tasks_migrated"
				case "refine-tasks":
					event = "tasks_refined"
				case "create-tasks":
					event = "tasks_imported"
				case "work-on-tasks":
					event = "tasks_worked"
				}
				if event != "" && m.currentProject != nil {
					m.emitTelemetry(event, map[string]string{"project": filepath.Clean(m.currentProject.Path)})
				}
				m.pendingBacklogReason = reason
				m.backlogLoading = true
				followCmd = m.loadBacklogCmd()
			}
		}
		delete(m.jobProjectPaths, message.Title)
		m.refreshCreateProjectProgress(message.Title)
	case jobChannelClosedMsg:
		// silence
	}
	var runnerCmd tea.Cmd
	if m.jobRunner != nil {
		runnerCmd = m.jobRunner.Handle(msg)
	}
	if followCmd != nil && runnerCmd != nil {
		return tea.Batch(runnerCmd, followCmd)
	}
	if followCmd != nil {
		return followCmd
	}
	if runnerCmd != nil {
		return runnerCmd
	}
	return nil
}

type verifyEventMessage struct {
	Name            string      `json:"name"`
	Label           string      `json:"label"`
	Status          string      `json:"status"`
	Message         string      `json:"message"`
	Log             string      `json:"log"`
	Report          string      `json:"report"`
	Score           *float64    `json:"score"`
	Updated         string      `json:"updated"`
	RunKind         string      `json:"run_kind"`
	Stats           verifyStats `json:"stats"`
	DurationSeconds float64     `json:"duration_seconds"`
}

func parseVerifyEventMessage(raw string) (verifyEventMessage, error) {
	var payload verifyEventMessage
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return payload, fmt.Errorf("empty verify payload")
	}
	if err := json.Unmarshal([]byte(trimmed), &payload); err != nil {
		return payload, err
	}
	return payload, nil
}

func (m *model) handleVerifyJobEvent(title string, payload verifyEventMessage) {
	path := ""
	if m.jobProjectPaths != nil {
		path = m.jobProjectPaths[title]
	}
	if path == "" && m.currentProject != nil {
		path = filepath.Clean(m.currentProject.Path)
	}
	if path == "" {
		return
	}
	m.updateProjectStats(path)
	m.refreshCurrentFeatureItemsFor(path)
	if m.currentFeature == "verify" && m.currentProject != nil && filepath.Clean(m.currentProject.Path) == filepath.Clean(path) {
		if item, ok := m.itemsCol.SelectedItem(); ok {
			m.applyItemSelection(m.currentProject, "verify", item, false)
		}
	}
}

func (m *model) updateProjectStats(path string) {
	clean := filepath.Clean(path)
	for i := range m.projects {
		if filepath.Clean(m.projects[i].Path) != clean {
			continue
		}
		stats := collectProjectStats(m.projects[i].Path)
		m.projects[i].Stats = stats
		if m.currentProject != nil && filepath.Clean(m.currentProject.Path) == clean {
			m.currentProject.Stats = stats
		}
		m.refreshProjectsColumn()
		return
	}
}

func (m *model) handleInputSubmit(value string) (tea.Cmd, bool) {
	if value == "" {
		return nil, false
	}

	switch m.inputMode {
	case inputAddRoot:
		path := m.resolvePath(value)
		if !pathExists(path) {
			m.appendLog(fmt.Sprintf("Path not found: %s", path))
			return nil, false
		}
		if !m.hasWorkspaceRoot(path) {
			label := labelForPath(path)
			m.workspaceRoots = append(m.workspaceRoots, workspaceRoot{Label: label, Path: filepath.Clean(path)})
			m.ensurePinnedRoots()
			m.refreshWorkspaceColumn()
			m.appendLog(fmt.Sprintf("Added workspace root: %s", abbreviatePath(path)))
		}
		return nil, false
	case inputNewProjectPath:
		cmd := m.handleNewProjectPathSubmit(value)
		keep := false
		if m.inputMode == inputNewProjectTemplate || m.inputMode == inputNewProjectConfirm {
			keep = true
		} else if cmd == nil {
			keep = true
		}
		return cmd, keep
	case inputNewProjectConfirm:
		if strings.EqualFold(strings.TrimSpace(value), "yes") {
			m.openTemplatePrompt()
			return nil, true
		} else {
			m.appendLog("Create project cancelled.")
			m.setToast("Create project cancelled", 4*time.Second)
			m.pendingNewProjectPath = ""
			m.pendingNewProjectTemplate = ""
		}
		return nil, false
	case inputNewProjectTemplate:
		tpl := strings.TrimSpace(value)
		if tpl == "" {
			tpl = "auto"
		}
		m.pendingNewProjectTemplate = tpl
		path := m.pendingNewProjectPath
		if path == "" {
			m.appendLog("No project path captured; aborting create-project.")
			return nil, false
		}
		cmd := m.launchCreateProject(path, tpl)
		m.pendingNewProjectPath = ""
		m.pendingNewProjectTemplate = ""
		return cmd, false
	case inputAttachRFP:
		keep := m.handleAttachRFPSubmit(value)
		return nil, keep
	case inputCommandPalette:
		return m.executePaletteCommand(value), false
	}
	return nil, false
}

func (m *model) refreshWorkspaceColumn() {
	if m.workspaceCol == nil {
		return
	}
	m.ensurePinnedRoots()
	var items []list.Item
	if len(m.pinnedPaths) > 0 {
		items = append(items, listEntry{title: "Pinned", desc: "", payload: nil})
		sortedPinned := sortedPaths(m.pinnedPaths)
		for _, path := range sortedPinned {
			label := labelForPath(path)
			desc := abbreviatePath(path)
			items = append(items, listEntry{
				title:   "★ " + label,
				desc:    desc,
				payload: workspaceItem{kind: workspaceKindRoot, path: path, pinned: true},
			})
		}
	}
	items = append(items, listEntry{title: "Workspace", desc: "", payload: nil})
	for _, root := range m.workspaceRoots {
		clean := filepath.Clean(root.Path)
		if m.pinnedPaths[clean] {
			continue
		}
		desc := abbreviatePath(root.Path)
		items = append(items, listEntry{
			title:   root.Label,
			desc:    desc,
			payload: workspaceItem{kind: workspaceKindRoot, path: root.Path, pinned: false},
		})
	}
	items = append(items, listEntry{
		title:   "New Project…",
		desc:    "Run create-project for a new workspace",
		payload: workspaceItem{kind: workspaceKindNewProject},
	})
	items = append(items, listEntry{
		title:   "Add Workspace Path…",
		desc:    "Manually add a folder to scan for projects",
		payload: workspaceItem{kind: workspaceKindAddRoot},
	})
	m.workspaceCol.SetItems(items)
}

func (m *model) refreshProjectsForCurrentRoot() {
	if m.currentRoot == nil {
		m.projects = nil
		m.projectsCol.SetItems(nil)
		m.featureCol.SetItems(nil)
		m.itemsCol.SetItems(nil)
		m.previewCol.SetContent("Select an item to preview details.\n")
		m.currentProject = nil
		m.currentFeature = ""
		m.currentItem = featureItemDefinition{}
		return
	}

	projects, err := discoverProjects(m.currentRoot.Path)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to discover projects: %v", err))
		m.projects = nil
	} else {
		m.projects = projects
		for _, proj := range m.projects {
			clean := filepath.Clean(proj.Path)
			if m.seenProjects == nil {
				m.seenProjects = make(map[string]bool)
			}
			if !m.seenProjects[clean] {
				m.seenProjects[clean] = true
				m.emitTelemetry("project_discovered", map[string]string{"path": clean})
			}
		}
	}
	m.refreshProjectsColumn()
	m.featureCol.SetItems(nil)
	m.itemsCol.SetItems(nil)
	m.itemsCol.SetTitle("Actions")
	m.previewCol.SetContent("Select an item to preview details.\n")
}

func (m *model) refreshProjectsColumn() {
	if m.projectsCol == nil {
		return
	}
	selectedPath := ""
	if entry, ok := m.projectsCol.SelectedEntry(); ok {
		if payload, ok := entry.payload.(projectItem); ok && payload.project != nil {
			selectedPath = filepath.Clean(payload.project.Path)
		}
	}
	var items []list.Item
	for i := range m.projects {
		proj := &m.projects[i]
		desc := formatProjectDescription(proj.Stats)
		items = append(items, listEntry{
			title:   proj.Name,
			desc:    desc,
			payload: projectItem{project: proj},
		})
	}
	m.projectsCol.SetItems(items)
	if selectedPath != "" {
		m.selectProjectPath(selectedPath)
	}
}

func (m *model) openInput(prompt, placeholder string, mode inputMode) {
	m.inputMode = mode
	m.inputPrompt = prompt
	m.inputActive = true
	m.inputField.SetValue(placeholder)
	m.inputField.CursorEnd()
	m.inputField.Focus()
}

func (m *model) closeInput() {
	prevMode := m.inputMode
	if prevMode == inputCommandPalette {
		m.paletteMatches = nil
		m.paletteIndex = 0
	}
	m.inputActive = false
	m.inputField.Blur()
	m.inputField.SetValue("")
	m.inputField.Placeholder = ""
	m.inputMode = inputNone
	if prevMode == inputNewProjectPath || prevMode == inputNewProjectTemplate || prevMode == inputNewProjectConfirm {
		m.pendingNewProjectPath = ""
		m.pendingNewProjectTemplate = ""
	}
}

func (m *model) openCommandPalette() {
	m.refreshCommandCatalog()
	m.inputMode = inputCommandPalette
	m.inputPrompt = "Command"
	m.inputActive = true
	m.inputField.Placeholder = "e.g. run up"
	m.inputField.SetValue("")
	m.inputField.Focus()
	m.paletteIndex = 0
	m.updatePaletteMatches("")
}

func (m *model) startNewProjectFlow(defaultPath string) {
	m.pendingNewProjectPath = ""
	m.pendingNewProjectTemplate = ""
	m.openInput("New project path", defaultPath, inputNewProjectPath)
	if defaultPath != "" {
		m.emitTelemetry("create_project_wizard_opened", map[string]string{"default_path": filepath.Clean(defaultPath)})
	} else {
		m.emitTelemetry("create_project_wizard_opened", nil)
	}
}

func (m *model) openTemplatePrompt() {
	m.openInput("Template (auto/skip/<name>)", "auto", inputNewProjectTemplate)
}

func (m *model) launchCreateProject(path string, template string) tea.Cmd {
	resolved := filepath.Clean(path)
	parent := filepath.Dir(resolved)
	if !pathExists(parent) {
		m.appendLog(fmt.Sprintf("Parent directory does not exist: %s", parent))
		m.setToast("Parent directory missing", 5*time.Second)
		return nil
	}

	args := []string{"create-project"}
	trimmedTpl := strings.TrimSpace(template)
	if trimmedTpl != "" && trimmedTpl != "auto" {
		args = append(args, "--template", trimmedTpl)
	}
	args = append(args, resolved)

	title := fmt.Sprintf("create-project %s", filepath.Base(resolved))
	m.appendLog(fmt.Sprintf("Queued %s", title))
	m.appendLog(fmt.Sprintf("Command: gpt-creator %s", strings.Join(args, " ")))
	m.showLogs = true
	m.emitTelemetry("create_project_started", map[string]string{"path": resolved, "template": trimmedTpl})
	if m.createProjectJobs == nil {
		m.createProjectJobs = make(map[string]string)
	}
	m.createProjectJobs[title] = resolved

	return m.enqueueJob(jobRequest{
		title:   title,
		dir:     parent,
		command: "gpt-creator",
		args:    args,
		onStart: func() {
			m.refreshCreateProjectProgress(title)
		},
		onFinish: func(err error) {
			m.refreshCreateProjectProgress(title)
			delete(m.createProjectJobs, title)
			delete(m.lastProjectRefresh, filepath.Clean(resolved))
			if err != nil {
				m.emitTelemetry("create_project_failed", map[string]string{"path": resolved})
				m.appendLog(fmt.Sprintf("create-project failed: %v", err))
				m.setToast("Create project failed", 6*time.Second)
				return
			}
			m.emitTelemetry("create_project_succeeded", map[string]string{"path": resolved})
			m.refreshCreateProjectProgress(title)
			m.refreshProjectsForCurrentRoot()
			if project := m.projectByPath(resolved); project != nil {
				m.handleProjectSelected(project)
				stats := project.Stats
				toast := "Project ready"
				if stats.VerifyTotal > 0 {
					toast = fmt.Sprintf("Project ready • Verify acceptance: %d/%d ✓", stats.VerifyPass, stats.VerifyTotal)
				}
				m.setToast(toast, 8*time.Second)
			}
		},
	})
}

func (m *model) enqueueJob(req jobRequest) tea.Cmd {
	if m.jobRunner == nil {
		m.jobRunner = newJobManager()
	}
	return m.jobRunner.Enqueue(req)
}

func (m *model) refreshCommandCatalog() {
	seen := make(map[string]paletteEntry)
	for _, defs := range featureItemsByKey {
		for _, def := range defs {
			if len(def.Command) == 0 {
				continue
			}
			key := strings.Join(def.Command, " ")
			if _, ok := seen[key]; ok {
				continue
			}
			label := "gpt-creator " + key
			meta := map[string]string{}
			if def.Meta != nil {
				for k, v := range def.Meta {
					meta[k] = v
				}
			}
			entry := paletteEntry{
				label:           label,
				command:         def.Command,
				description:     def.Desc,
				requiresProject: def.ProjectRequired || def.ProjectFlag != "",
				meta:            meta,
			}
			seen[key] = entry
		}
	}
	entries := make([]paletteEntry, 0, len(seen))
	for _, entry := range seen {
		entries = append(entries, entry)
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].label < entries[j].label
	})
	m.commandEntries = entries
	m.updatePaletteMatches(m.inputField.Value())
}

func (m *model) updatePaletteMatches(query string) {
	q := strings.ToLower(strings.TrimSpace(query))
	if len(m.commandEntries) == 0 {
		m.paletteMatches = nil
		m.paletteIndex = 0
		return
	}
	if q == "" {
		m.paletteMatches = append([]paletteEntry(nil), m.commandEntries...)
		if len(m.paletteMatches) > 8 {
			m.paletteMatches = m.paletteMatches[:8]
		}
		m.paletteIndex = 0
		return
	}

	type scored struct {
		entry paletteEntry
		score int
	}
	var scoredMatches []scored
	for _, entry := range m.commandEntries {
		score := paletteScore(entry, q)
		if score >= 0 {
			scoredMatches = append(scoredMatches, scored{entry: entry, score: score})
		}
	}
	sort.Slice(scoredMatches, func(i, j int) bool {
		if scoredMatches[i].score == scoredMatches[j].score {
			return scoredMatches[i].entry.label < scoredMatches[j].entry.label
		}
		return scoredMatches[i].score < scoredMatches[j].score
	})
	m.paletteMatches = nil
	for _, item := range scoredMatches {
		m.paletteMatches = append(m.paletteMatches, item.entry)
		if len(m.paletteMatches) >= 8 {
			break
		}
	}
	if len(m.paletteMatches) == 0 {
		m.paletteIndex = 0
	} else if m.paletteIndex >= len(m.paletteMatches) {
		m.paletteIndex = len(m.paletteMatches) - 1
	}
}

func paletteScore(entry paletteEntry, query string) int {
	label := strings.ToLower(entry.label)
	cmd := strings.ToLower(strings.Join(entry.command, " "))
	desc := strings.ToLower(entry.description)
	if idx := strings.Index(label, query); idx >= 0 {
		return idx
	}
	if idx := strings.Index(cmd, query); idx >= 0 {
		return idx + 50
	}
	if idx := strings.Index(desc, query); idx >= 0 {
		return idx + 100
	}
	return -1
}

func (m *model) movePaletteSelection(delta int) {
	if len(m.paletteMatches) == 0 {
		m.paletteIndex = 0
		return
	}
	count := len(m.paletteMatches)
	m.paletteIndex = (m.paletteIndex + delta + count) % count
}

func (m *model) selectedPaletteEntry() (paletteEntry, bool) {
	if len(m.paletteMatches) == 0 {
		return paletteEntry{}, false
	}
	if m.paletteIndex < 0 || m.paletteIndex >= len(m.paletteMatches) {
		return paletteEntry{}, false
	}
	return m.paletteMatches[m.paletteIndex], true
}

func (m *model) executePaletteCommand(raw string) tea.Cmd {
	entry, ok := m.selectedPaletteEntry()
	if !ok {
		fields := strings.Fields(raw)
		if len(fields) == 0 {
			m.appendLog("No command selected.")
			return nil
		}
		if fields[0] == "gpt-creator" {
			fields = fields[1:]
		}
		if len(fields) == 0 {
			m.appendLog("Provide a command to run.")
			return nil
		}
		entry = paletteEntry{
			label:       "gpt-creator " + strings.Join(fields, " "),
			command:     fields,
			description: "manual command",
		}
	}
	return m.runPaletteEntry(entry)
}

func (m *model) runPaletteEntry(entry paletteEntry) tea.Cmd {
	if entry.requiresProject && m.currentProject == nil {
		m.appendLog("Select a project before running this command.")
		return nil
	}
	requiresDocker := entry.meta != nil && entry.meta["requiresDocker"] == "1"
	if !requiresDocker && len(entry.command) > 0 {
		if entry.command[0] == "run" || entry.command[0] == "verify" {
			requiresDocker = true
		}
	}
	if requiresDocker && !m.dockerAvailable {
		m.appendLog("Docker CLI not available; install Docker Desktop to run this command.")
		m.setToast("Docker required for this command", 5*time.Second)
		return nil
	}
	args := append([]string{}, entry.command...)
	if entry.requiresProject && m.currentProject != nil {
		needsFlag := true
		for _, arg := range args {
			if strings.HasPrefix(arg, "--project") {
				needsFlag = false
				break
			}
		}
		if needsFlag {
			args = append(args, "--project", m.currentProject.Path)
		}
	}

	dir := ""
	if m.currentProject != nil {
		dir = m.currentProject.Path
	}

	m.appendLog(fmt.Sprintf("Queued %s", entry.label))
	if entry.description != "" {
		m.appendLog(entry.description)
	}
	m.appendLog(fmt.Sprintf("Command: gpt-creator %s", strings.Join(args, " ")))
	m.showLogs = true
	fields := map[string]string{"command": strings.Join(entry.command, " ")}
	if m.currentProject != nil {
		fields["project"] = filepath.Clean(m.currentProject.Path)
	}
	m.emitTelemetry("command_queued", fields)

	identifier := strings.Join(entry.command, " ")
	return m.enqueueJob(jobRequest{
		title:   entry.label,
		dir:     dir,
		command: "gpt-creator",
		args:    args,
		onFinish: func(err error) {
			if err == nil && (strings.HasPrefix(identifier, "generate") || strings.HasPrefix(identifier, "verify")) {
				m.refreshProjectsForCurrentRoot()
			}
		},
	})
}

func (m *model) renderPaletteMatches(width int) string {
	if len(m.paletteMatches) == 0 {
		return "No matches"
	}
	limit := len(m.paletteMatches)
	if limit > 8 {
		limit = 8
	}
	if width < 10 {
		width = 10
	}
	header := m.styles.statusHint.Render("↑/↓ select • Enter run • Esc cancel")
	var lines []string
	lines = append(lines, header)
	for i := 0; i < limit; i++ {
		entry := m.paletteMatches[i]
		label := entry.label
		needsProject := entry.requiresProject && m.currentProject == nil
		needsDocker := entry.meta != nil && entry.meta["requiresDocker"] == "1" && !m.dockerAvailable
		if needsProject {
			label += " (project required)"
		}
		if needsDocker {
			label += " (requires Docker)"
		}
		description := entry.description
		line := label
		if description != "" {
			line += " — " + description
		}
		disabled := needsProject || needsDocker
		style := m.styles.listItem
		if i == m.paletteIndex {
			style = m.styles.listSel
		}
		if disabled {
			style = style.Foreground(palette.textMuted)
		}
		lines = append(lines, style.Width(width-4).Render(line))
	}
	return strings.Join(lines, "\n")
}

func (m *model) runCurrentItemCommand() tea.Cmd {
	if m.currentItem.Disabled {
		reason := strings.TrimSpace(m.currentItem.DisabledReason)
		if reason == "" {
			reason = "This action is currently disabled."
		}
		m.appendLog(reason)
		m.setToast(reason, 5*time.Second)
		return nil
	}
	if len(m.currentItem.Command) == 0 {
		return nil
	}
	if m.currentProject == nil {
		m.appendLog("Select a project before running commands.")
		return nil
	}
	requiresDocker := m.currentItem.Meta != nil && m.currentItem.Meta["requiresDocker"] == "1"
	if !requiresDocker {
		if strings.HasPrefix(m.currentItem.Key, "run-") || strings.HasPrefix(m.currentItem.Key, "verify-") {
			requiresDocker = true
		}
	}
	if requiresDocker && !m.dockerAvailable {
		m.appendLog("Docker CLI not available; install Docker Desktop to run this command.")
		m.setToast("Docker required for this command", 5*time.Second)
		return nil
	}

	args := append([]string{}, m.currentItem.Command...)
	flag := m.currentItem.ProjectFlag
	if flag == "" && m.currentItem.ProjectRequired {
		flag = "--project"
	}
	if flag != "" {
		args = append(args, flag, m.currentProject.Path)
	}

	title := fmt.Sprintf("%s • %s", m.currentItem.Title, m.currentProject.Name)
	m.appendLog(fmt.Sprintf("Queued %s", title))
	m.appendLog(fmt.Sprintf("Command: gpt-creator %s", strings.Join(args, " ")))
	m.showLogs = true
	itemKey := m.currentItem.Key
	isVerifyAll := itemKey == "overview-run-verify-all" || itemKey == "verify-all"
	isGenerate := strings.HasPrefix(itemKey, "generate-") || itemKey == "generate-all"
	isCreateDBDump := itemKey == "create-db-dump"
	verifyKind := ""
	if len(args) > 0 && args[0] == "verify" {
		if len(args) > 1 {
			verifyKind = strings.TrimSpace(strings.ToLower(args[1]))
		} else {
			verifyKind = "all"
		}
		if verifyKind == "program_filters" {
			verifyKind = "program-filters"
		}
	}
	runEvent := ""
	switch itemKey {
	case "run-up":
		runEvent = "stack_up"
	case "run-down":
		runEvent = "stack_down"
	case "run-logs":
		runEvent = "stack_logs"
	case "run-open":
		runEvent = "stack_open"
	}
	docEvent := ""
	docType := ""
	switch itemKey {
	case "create-pdr":
		docEvent = "doc_pdr_created"
		docType = "pdr"
	case "create-sds":
		docEvent = "doc_sds_created"
		docType = "sds"
	}
	refreshOnSuccess := itemKey == "generate-all" ||
		strings.HasPrefix(itemKey, "generate-") ||
		strings.HasPrefix(itemKey, "verify-") ||
		isVerifyAll ||
		isCreateDBDump ||
		(len(args) > 0 && args[0] == "create-project")
	if docEvent != "" {
		refreshOnSuccess = true
	}
	targetLabel := ""
	var snapshotTargets []string
	if isGenerate {
		targetLabel = strings.TrimPrefix(itemKey, "generate-")
		if targetLabel == "" {
			targetLabel = "all"
		}
		if targetLabel == "all" {
			for _, def := range generateTargetDefinitions {
				snapshotTargets = append(snapshotTargets, def.Key)
			}
		} else {
			snapshotTargets = append(snapshotTargets, targetLabel)
		}
	}
	path := filepath.Clean(m.currentProject.Path)
	req := jobRequest{
		title:   title,
		dir:     m.currentProject.Path,
		command: "gpt-creator",
		args:    args,
	}
	if m.jobProjectPaths == nil {
		m.jobProjectPaths = make(map[string]string)
	}
	m.jobProjectPaths[title] = path
	if isVerifyAll {
		req.onStart = func() {
			m.emitTelemetry("verify_all_started", map[string]string{"path": path})
		}
	}
	prevFinish := req.onFinish
	req.onFinish = func(err error) {
		if prevFinish != nil {
			prevFinish(err)
		}
		if isVerifyAll {
			event := "verify_all_succeeded"
			fields := map[string]string{"path": path}
			if err != nil {
				event = "verify_all_failed"
				fields["error"] = err.Error()
			}
			m.emitTelemetry(event, fields)
		}
		if verifyKind != "" {
			event := "verify_succeeded"
			fields := map[string]string{"path": path, "kind": verifyKind}
			if err != nil {
				event = "verify_failed"
				fields["error"] = err.Error()
			}
			m.emitTelemetry(event, fields)
		}
		if isCreateDBDump {
			event := "db_dump_succeeded"
			fields := map[string]string{"path": path}
			if err != nil {
				event = "db_dump_failed"
				fields["error"] = err.Error()
			}
			m.emitTelemetry(event, fields)
		}
		if err == nil && refreshOnSuccess {
			if verifyKind != "" {
				m.updateProjectStats(path)
				m.refreshCurrentFeatureItemsFor(path)
			} else {
				m.refreshProjectsForCurrentRoot()
				m.refreshCurrentFeatureItemsFor(path)
			}
			if docEvent != "" {
				fields := map[string]string{"path": path}
				if docType != "" {
					fields["doc_type"] = docType
				}
				m.emitTelemetry(docEvent, fields)
			}
		} else if verifyKind != "" {
			m.updateProjectStats(path)
			m.refreshCurrentFeatureItemsFor(path)
		}
		if isGenerate {
			fields := map[string]string{"path": path, "target": targetLabel}
			event := "generate_succeeded"
			if err != nil {
				event = "generate_failed"
				fields["error"] = err.Error()
			}
			m.emitTelemetry(event, fields)
			if err == nil {
				m.refreshCurrentFeatureItemsFor(path)
			}
		}
	}
	prevStart := req.onStart
	req.onStart = func() {
		if prevStart != nil {
			prevStart()
		}
		if verifyKind != "" {
			fields := map[string]string{"path": path, "kind": verifyKind}
			m.emitTelemetry("verify_started", fields)
		}
		if isCreateDBDump {
			m.emitTelemetry("db_dump_started", map[string]string{"path": path})
		}
		if isGenerate {
			fields := map[string]string{"path": path, "target": targetLabel}
			m.emitTelemetry("generate_started", fields)
			if len(snapshotTargets) > 0 && !projectHasGitRepo(path) {
				if _, err := prepareGenerateSnapshots(path, snapshotTargets); err != nil {
					m.appendLog(fmt.Sprintf("Snapshot unavailable: %v", err))
				} else {
					m.appendLog(fmt.Sprintf("Captured snapshot for %s", strings.Join(snapshotTargets, ", ")))
				}
			}
		}
		if runEvent != "" {
			fields := map[string]string{
				"path":    path,
				"command": strings.Join(args, " "),
			}
			m.emitTelemetry(runEvent, fields)
		}
	}
	return m.enqueueJob(req)
}

func (m *model) handleDocItemSelection(item featureItemDefinition, activate bool) {
	if item.Meta == nil {
		m.resetDocSelection()
		return
	}
	docRel := strings.TrimSpace(item.Meta["docRelPath"])
	if docRel == "" {
		docRel = strings.TrimSpace(item.Meta["docDiffHead"])
	}
	m.currentDocRelPath = docRel
	m.currentDocDiffBase = strings.TrimSpace(item.Meta["docDiffBase"])
	m.currentDocType = strings.TrimSpace(item.Meta["docType"])
	if activate && item.Meta["docsAction"] == "attach-rfp" {
		m.startAttachRFP()
	}
	m.recordDocPreviewTelemetry(item)
}

func (m *model) recordDocPreviewTelemetry(item featureItemDefinition) {
	if m.currentProject == nil || item.Meta == nil {
		return
	}
	docRel := strings.TrimSpace(item.Meta["docRelPath"])
	if docRel == "" {
		docRel = strings.TrimSpace(item.Meta["docDiffHead"])
	}
	if docRel == "" {
		return
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	key := fmt.Sprintf("%s|%s|%s", item.Key, docRel, projectPath)
	if key == m.lastDocTelemetryKey {
		return
	}
	m.lastDocTelemetryKey = key
	fields := map[string]string{
		"path":     projectPath,
		"document": docRel,
		"mode":     "preview",
	}
	if docType := strings.TrimSpace(item.Meta["docType"]); docType != "" {
		fields["doc_type"] = docType
	}
	m.emitTelemetry("doc_opened", fields)
}

func (m *model) handleVerifyItemSelection(item featureItemDefinition) {
	m.currentVerifyCheck = ""
	if m.currentProject == nil || item.Meta == nil {
		return
	}
	check := strings.TrimSpace(item.Meta["verifyName"])
	m.currentVerifyCheck = check
	m.recordVerifyPreviewTelemetry(item)
}

func (m *model) recordVerifyPreviewTelemetry(item featureItemDefinition) {
	if m.currentProject == nil || item.Meta == nil {
		return
	}
	check := strings.TrimSpace(item.Meta["verifyName"])
	if check == "" {
		return
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	key := fmt.Sprintf("%s|%s|%s", item.Key, check, projectPath)
	if key == m.lastVerifyPreviewKey {
		return
	}
	m.lastVerifyPreviewKey = key
	fields := map[string]string{
		"path":  projectPath,
		"check": check,
	}
	if status := strings.TrimSpace(item.Meta["verifyStatus"]); status != "" {
		fields["status"] = status
	}
	if log := strings.TrimSpace(item.Meta["verifyLog"]); log != "" {
		fields["log"] = log
	}
	if report := strings.TrimSpace(item.Meta["verifyReport"]); report != "" {
		fields["report"] = report
	}
	m.emitTelemetry("verify_report_opened", fields)
}

func (m *model) handleGenerateItemSelection(item featureItemDefinition, activate bool) {
	if item.Meta == nil {
		return
	}
	kind := strings.TrimSpace(item.Meta["generateKind"])
	switch kind {
	case "target":
		m.currentGenerateTarget = strings.TrimSpace(item.Meta["generateTarget"])
		m.currentGenerateFile = ""
	case "file":
		m.currentGenerateTarget = strings.TrimSpace(item.Meta["generateTarget"])
		m.currentGenerateFile = strings.TrimSpace(item.Meta["generatePath"])
		m.recordGenerateDiffTelemetry(item)
	case "command":
		m.currentGenerateTarget = "all"
		m.currentGenerateFile = ""
	}
}

func (m *model) handleDatabaseItemSelection(item featureItemDefinition) {
	m.currentDBSchemaPath = ""
	m.currentDBSeedPath = ""
	if m.currentProject == nil {
		return
	}
	info := gatherDatabaseDumpInfo(m.currentProject.Path)
	if info.Found {
		for _, file := range info.Files {
			switch file.Kind {
			case "schema":
				m.currentDBSchemaPath = file.Path
			case "seed":
				m.currentDBSeedPath = file.Path
			}
		}
	}
	if item.Meta != nil {
		if m.currentDBSchemaPath == "" {
			if rel := strings.TrimSpace(item.Meta["dbSchemaRel"]); rel != "" {
				m.currentDBSchemaPath = filepath.Join(m.currentProject.Path, filepath.FromSlash(rel))
			}
		}
		if m.currentDBSeedPath == "" {
			if rel := strings.TrimSpace(item.Meta["dbSeedRel"]); rel != "" {
				m.currentDBSeedPath = filepath.Join(m.currentProject.Path, filepath.FromSlash(rel))
			}
		}
	}
}

func (m *model) handleServiceItemSelection(item featureItemDefinition) {
	m.currentServiceEndpoints = nil
	if item.Meta == nil || item.Meta["serviceRow"] != "1" {
		return
	}
	endpoints := decodeServiceEndpoints(item.Meta["endpoints"])
	if len(endpoints) == 0 {
		url := strings.TrimSpace(item.Meta["primaryEndpoint"])
		if url != "" {
			endpoints = append(endpoints, serviceEndpoint{
				URL:     url,
				Healthy: strings.EqualFold(strings.TrimSpace(item.Meta["health"]), "healthy"),
			})
		}
	}
	m.currentServiceEndpoints = endpoints
}

func parseServiceEndpointIndex(key string) int {
	if len(key) != 1 {
		return -1
	}
	ch := key[0]
	if ch < '1' || ch > '9' {
		return -1
	}
	return int(ch - '1')
}

func (m *model) recordGenerateDiffTelemetry(item featureItemDefinition) {
	if m.currentProject == nil || item.Meta == nil {
		return
	}
	path := strings.TrimSpace(item.Meta["generatePath"])
	if path == "" {
		return
	}
	target := strings.TrimSpace(item.Meta["generateTarget"])
	projectPath := filepath.Clean(m.currentProject.Path)
	key := fmt.Sprintf("%s|%s|%s", projectPath, target, path)
	if key == m.lastGenerateDiffKey {
		return
	}
	m.lastGenerateDiffKey = key
	fields := map[string]string{
		"path":   projectPath,
		"target": target,
		"file":   path,
	}
	if source := strings.TrimSpace(item.Meta["generateDiffSource"]); source != "" {
		fields["source"] = source
	}
	m.emitTelemetry("diff_viewed", fields)
}

func (m *model) runServiceCommand(itemKey string) tea.Cmd {
	defs := featureItemsForKey("services")
	for _, def := range defs {
		if def.Key != itemKey {
			continue
		}
		prevItem := m.currentItem
		prevFeature := m.currentFeature
		m.currentItem = def
		m.currentFeature = "services"
		cmd := m.runCurrentItemCommand()
		m.currentItem = prevItem
		m.currentFeature = prevFeature
		return cmd
	}
	m.appendLog(fmt.Sprintf("Command unavailable: %s", itemKey))
	return nil
}

func (m *model) openSelectedServiceEndpoint(index int) {
	if m.currentFeature != "services" {
		return
	}
	if m.currentProject == nil {
		m.appendLog("Select a project before opening endpoints.")
		m.setToast("Select a project first", 4*time.Second)
		return
	}
	endpoints := append([]serviceEndpoint(nil), m.currentServiceEndpoints...)
	if len(endpoints) == 0 && m.currentItem.Meta != nil {
		if url := strings.TrimSpace(m.currentItem.Meta["primaryEndpoint"]); url != "" {
			endpoints = append(endpoints, serviceEndpoint{URL: url})
		}
	}
	if len(endpoints) == 0 {
		m.appendLog("No endpoints available for this service.")
		m.setToast("No endpoint available", 4*time.Second)
		return
	}
	var chosen serviceEndpoint
	if index >= 0 && index < len(endpoints) {
		chosen = endpoints[index]
	} else {
		for _, ep := range endpoints {
			if strings.TrimSpace(ep.URL) != "" && ep.Healthy {
				chosen = ep
				break
			}
		}
		if strings.TrimSpace(chosen.URL) == "" {
			chosen = endpoints[0]
		}
	}
	url := strings.TrimSpace(chosen.URL)
	if url == "" && strings.TrimSpace(chosen.Port) != "" {
		host := sanitizeHost(chosen.Host)
		path := chosen.Path
		if path == "" {
			path = "/"
		}
		url = fmt.Sprintf("http://%s:%s%s", host, chosen.Port, path)
	}
	if url == "" {
		m.appendLog("No valid endpoint URL for this service.")
		m.setToast("Endpoint unavailable", 4*time.Second)
		return
	}
	commandLine, err := launchBrowser(url)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to open endpoint %s: %v", url, err))
		m.setToast("Failed to open endpoint", 5*time.Second)
		return
	}
	m.appendLog("Opening endpoint: " + url)
	m.appendLog("Browser command: " + commandLine)
	fields := map[string]string{
		"project": filepath.Clean(m.currentProject.Path),
		"url":     url,
	}
	if m.currentItem.Meta != nil {
		fields["service"] = strings.TrimSpace(m.currentItem.Meta["service"])
	}
	m.emitTelemetry("endpoint_opened", fields)
	m.setToast("Opening endpoint", 3*time.Second)
}

func (m *model) startServicePolling() tea.Cmd {
	m.servicesPolling = true
	return m.scheduleServicePoll()
}

func (m *model) stopServicePolling() {
	m.servicesPolling = false
}

func (m *model) scheduleServicePoll() tea.Cmd {
	if !m.servicesPolling {
		return nil
	}
	return tea.Tick(servicesPollInterval, func(time.Time) tea.Msg {
		return servicesPollMsg{}
	})
}

func (m *model) loadServicesCmd() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	projectCopy := *m.currentProject
	dockerAvailable := m.dockerAvailable
	return func() tea.Msg {
		items := featureItemEntries(&projectCopy, "services", dockerAvailable)
		return servicesLoadedMsg{items: items}
	}
}

func (m *model) handleServicesLoaded(items []featureItemDefinition) {
	if m.currentFeature != "services" {
		return
	}
	prevKey := m.currentItem.Key
	if prevKey == "" {
		if item, ok := m.servicesCol.SelectedItem(); ok {
			prevKey = item.Key
		}
	}
	m.servicesCol.SetItems(items)
	if prevKey != "" {
		m.servicesCol.SelectKey(prevKey)
	}
	if item, ok := m.servicesCol.SelectedItem(); ok {
		m.applyItemSelection(m.currentProject, "services", item, false)
	} else {
		if len(items) == 0 {
			m.previewCol.SetContent("No services detected.\n")
		}
		m.currentItem = featureItemDefinition{}
	}
	m.recordServiceHealth(items)
}

func (m *model) recordServiceHealth(items []featureItemDefinition) {
	if m.currentProject == nil {
		return
	}
	if m.serviceHealth == nil {
		m.serviceHealth = make(map[string]string)
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	for _, item := range items {
		if item.Meta == nil || item.Meta["serviceRow"] != "1" {
			continue
		}
		container := strings.TrimSpace(item.Meta["container"])
		if container == "" {
			continue
		}
		health := strings.TrimSpace(item.Meta["health"])
		if health == "" {
			health = "n/a"
		}
		key := projectPath + "|" + container
		prev, ok := m.serviceHealth[key]
		if !ok || prev != health {
			fields := map[string]string{
				"project":   projectPath,
				"service":   strings.TrimSpace(item.Meta["service"]),
				"container": container,
				"health":    health,
				"state":     strings.TrimSpace(item.Meta["state"]),
			}
			m.emitTelemetry("service_health_changed", fields)
		}
		m.serviceHealth[key] = health
	}
}

func (m *model) handleDocsPreviewEnter() bool {
	if m.currentItem.Meta == nil {
		return false
	}
	switch m.currentItem.Meta["docsAction"] {
	case "attach-rfp":
		m.startAttachRFP()
		return true
	}
	return false
}

func (m *model) startAttachRFP() {
	if m.currentProject == nil {
		m.appendLog("Select a project before attaching artifacts.")
		m.setToast("Select a project first", 5*time.Second)
		return
	}
	m.openInput("Attach RFP path", "", inputAttachRFP)
	m.inputField.Placeholder = "~/path/to/rfp.md"
	m.appendLog("Attach RFP: Enter a file path to copy into .gpt-creator/staging/inputs/.")
	m.setToast("Provide RFP file path", 5*time.Second)
}

func (m *model) handleAttachRFPSubmit(raw string) bool {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		m.appendLog("Attach RFP cancelled (empty path).")
		m.setToast("Attach RFP cancelled", 4*time.Second)
		return false
	}
	if m.currentProject == nil {
		m.appendLog("No project selected; cannot attach RFP.")
		m.setToast("Select a project first", 5*time.Second)
		return false
	}
	src := m.resolvePath(trimmed)
	destRel, err := m.attachFileToInputs(src)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to attach RFP: %v", err))
		m.setToast("Attach RFP failed", 6*time.Second)
		return true
	}
	m.appendLog(fmt.Sprintf("Attached RFP → %s", destRel))
	m.setToast("RFP attached to staging/inputs/", 5*time.Second)
	m.refreshCurrentFeatureItemsFor(filepath.Clean(m.currentProject.Path))
	return false
}

func (m *model) attachFileToInputs(src string) (string, error) {
	info, err := os.Stat(src)
	if err != nil {
		return "", err
	}
	if info.IsDir() {
		return "", fmt.Errorf("%s is a directory", src)
	}
	destDir := filepath.Join(m.currentProject.Path, ".gpt-creator", "staging", "inputs")
	if err := os.MkdirAll(destDir, 0o755); err != nil {
		return "", err
	}
	ext := strings.ToLower(filepath.Ext(info.Name()))
	if ext == "" {
		ext = ".md"
	}
	base := "rfp" + ext
	destPath := filepath.Join(destDir, base)
	if _, err := os.Stat(destPath); err == nil {
		timestamp := time.Now().UTC().Format("20060102-150405")
		destPath = filepath.Join(destDir, fmt.Sprintf("rfp-%s%s", timestamp, ext))
	}
	if err := copyFile(src, destPath); err != nil {
		return "", err
	}
	rel, err := filepath.Rel(m.currentProject.Path, destPath)
	if err != nil {
		rel = strings.TrimPrefix(destPath, m.currentProject.Path+string(os.PathSeparator))
	}
	return filepath.ToSlash(rel), nil
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

func (m *model) refreshCurrentFeatureItemsFor(path string) {
	if m.currentProject == nil {
		return
	}
	if filepath.Clean(m.currentProject.Path) != filepath.Clean(path) {
		return
	}
	if m.currentFeature == "" {
		return
	}
	switch m.currentFeature {
	case "docs", "generate", "database", "verify":
		currentKey := m.currentItem.Key
		items := featureItemEntries(m.currentProject, m.currentFeature, m.dockerAvailable)
		m.itemsCol.SetItems(items)
		if currentKey != "" {
			m.itemsCol.SelectKey(currentKey)
		}
		if item, ok := m.itemsCol.SelectedItem(); ok {
			m.applyItemSelection(m.currentProject, m.currentFeature, item, false)
		} else {
			m.previewCol.SetContent("Select an item to preview details.\n")
		}
	default:
		return
	}
}

func (m *model) resetDocSelection() {
	m.currentDocRelPath = ""
	m.currentDocDiffBase = ""
	m.currentDocType = ""
}

func (m *model) selectedWorkspaceItem() (workspaceItem, bool) {
	if m.workspaceCol == nil {
		return workspaceItem{}, false
	}
	entry, ok := m.workspaceCol.SelectedEntry()
	if !ok {
		return workspaceItem{}, false
	}
	item, ok := entry.payload.(workspaceItem)
	return item, ok
}

func (m *model) toggleSelectedWorkspacePin() {
	item, ok := m.selectedWorkspaceItem()
	if !ok || item.kind != workspaceKindRoot || item.path == "" {
		return
	}
	clean := filepath.Clean(item.path)
	currentlyPinned := m.pinnedPaths[clean]
	m.togglePinState(clean, !currentlyPinned)
}

func (m *model) togglePinState(path string, pinned bool) {
	clean := filepath.Clean(path)
	if clean == "" {
		return
	}
	if m.pinnedPaths == nil {
		m.pinnedPaths = make(map[string]bool)
	}
	if pinned {
		m.pinnedPaths[clean] = true
		m.emitTelemetry("workspace_pinned", map[string]string{"path": clean})
	} else {
		delete(m.pinnedPaths, clean)
		m.emitTelemetry("workspace_unpinned", map[string]string{"path": clean})
	}
	m.ensurePinnedRoots()
	m.refreshWorkspaceColumn()
	m.persistPins()
	if pinned {
		m.setToast(fmt.Sprintf("Pinned %s", labelForPath(clean)), 4*time.Second)
	} else {
		m.setToast(fmt.Sprintf("Unpinned %s", labelForPath(clean)), 4*time.Second)
	}
}

func (m *model) persistPins() {
	if m.uiConfig == nil {
		m.uiConfig = &uiConfig{}
	}
	sorted := sortedPaths(m.pinnedPaths)
	m.uiConfig.Pinned = sorted
	if m.uiConfigPath == "" {
		_, m.uiConfigPath = loadUIConfig()
	}
	_ = saveUIConfig(m.uiConfig, m.uiConfigPath)
}

func (m *model) handleNewProjectPathSubmit(raw string) tea.Cmd {
	resolved := m.resolvePath(strings.TrimSpace(raw))
	if resolved == "" {
		m.appendLog("Project path cannot be empty.")
		return nil
	}
	needsConfirm, confirmMessage, err := m.validateNewProjectPath(resolved)
	if err != nil {
		m.appendLog(err.Error())
		m.setToast("Invalid project path", 5*time.Second)
		return nil
	}
	m.pendingNewProjectPath = resolved
	var confirmReasons []string
	if needsConfirm && strings.TrimSpace(confirmMessage) != "" {
		confirmReasons = append(confirmReasons, strings.TrimSpace(confirmMessage))
	}
	if os.Getenv("OPENAI_API_KEY") == "" && os.Getenv("GC_OPENAI_KEY") == "" {
		m.appendLog("Hint: OPENAI_API_KEY not set; update your .env after bootstrap.")
		confirmReasons = append(confirmReasons, "OPENAI_API_KEY missing")
	}
	if len(confirmReasons) > 0 {
		prompt := strings.Join(confirmReasons, " • ")
		m.openInput(prompt+" (type YES to continue)", "", inputNewProjectConfirm)
		return nil
	}
	m.openTemplatePrompt()
	return nil
}

func (m *model) validateNewProjectPath(path string) (bool, string, error) {
	clean := filepath.Clean(path)
	if clean == "" {
		return false, "", fmt.Errorf("empty path")
	}
	parent := filepath.Dir(clean)
	info, err := os.Stat(parent)
	if err != nil {
		return false, "", fmt.Errorf("parent directory does not exist: %s", parent)
	}
	if !info.IsDir() {
		return false, "", fmt.Errorf("parent path is not a directory: %s", parent)
	}
	if err := checkDirWritable(parent); err != nil {
		return false, "", err
	}
	info, err = os.Stat(clean)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return false, "", nil
		}
		return false, "", err
	}
	if !info.IsDir() {
		return false, "", fmt.Errorf("%s exists and is not a directory", clean)
	}
	empty, err := isDirEmpty(clean)
	if err != nil {
		return false, "", err
	}
	if !empty {
		return true, "Directory not empty.", nil
	}
	return false, "", nil
}

func (m *model) appendLog(line string) {
	if line == "" {
		return
	}
	m.logLines = append(m.logLines, line)
	if len(m.logLines) > 400 {
		m.logLines = m.logLines[len(m.logLines)-400:]
	}
	m.refreshLogs()
}

func (m *model) refreshLogs() {
	m.logs.SetContent(strings.Join(m.logLines, "\n"))
}

func (m *model) applyLayout() {
	if m.width == 0 || m.height == 0 {
		return
	}

	topChrome := 1
	bottomChrome := 1
	bodyHeight := m.height - topChrome - bottomChrome
	if bodyHeight < 6 {
		bodyHeight = 6
	}
	availableWidth := m.width

	if m.showLogs {
		bodyHeight -= m.logsHeight
		if bodyHeight < 3 {
			bodyHeight = 3
		}
		m.logs.Width = availableWidth - 2
		if m.logs.Width < 10 {
			m.logs.Width = availableWidth
		}
		m.logs.Height = m.logsHeight - 2
	}

	widths := []int{22, 26, 26, 28}
	if m.usingTasksLayout {
		widths = []int{22, 26, 32, 36}
	} else if m.usingServicesLayout {
		widths = []int{22, 26, 24, 44}
	} else if m.usingArtifactsLayout {
		widths = []int{22, 26, 26, 36}
	}
	remaining := availableWidth
	for i := range widths {
		if widths[i] > remaining {
			widths[i] = max(remaining, 10)
		}
		remaining -= widths[i]
	}
	if remaining < 24 {
		remaining = max(remaining, 24)
	}
	widths = append(widths, remaining)

	for i, col := range m.columns {
		col.SetSize(widths[i], bodyHeight)
		m.columns[i] = col
	}
}

func (m *model) useTasksLayout(enable bool) {
	if enable {
		if m.usingTasksLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.backlogCol,
			m.backlogTable,
			m.previewCol,
		}
		m.usingTasksLayout = true
		if focusArea(m.focus) == focusItems {
			m.focus = int(focusFeatures)
		}
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	} else {
		if !m.usingTasksLayout {
			return
		}
		if len(m.defaultColumns) == len(m.columns) && len(m.defaultColumns) > 0 {
			m.columns = append([]column(nil), m.defaultColumns...)
		} else {
			m.columns = []column{
				m.workspaceCol,
				m.projectsCol,
				m.featureCol,
				m.itemsCol,
				m.previewCol,
			}
		}
		m.usingTasksLayout = false
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	}
	m.applyLayout()
}

func (m *model) useServicesLayout(enable bool) {
	if enable {
		if m.usingServicesLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.featureCol,
			m.servicesCol,
			m.previewCol,
		}
		m.usingServicesLayout = true
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	} else {
		if !m.usingServicesLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.featureCol,
			m.itemsCol,
			m.previewCol,
		}
		m.usingServicesLayout = false
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	}
	m.applyLayout()
}

func (m *model) useArtifactsLayout(enable bool) {
	if enable {
		if m.usingArtifactsLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.artifactsCol,
			m.artifactTreeCol,
			m.previewCol,
		}
		m.usingArtifactsLayout = true
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	} else {
		if !m.usingArtifactsLayout {
			return
		}
		if len(m.defaultColumns) == len(m.columns) && len(m.defaultColumns) > 0 {
			m.columns = append([]column(nil), m.defaultColumns...)
		} else {
			m.columns = []column{
				m.workspaceCol,
				m.projectsCol,
				m.featureCol,
				m.itemsCol,
				m.previewCol,
			}
		}
		m.usingArtifactsLayout = false
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	}
	m.applyLayout()
}

func (m *model) backlogHighlightCmd(node backlogNode) tea.Cmd {
	return func() tea.Msg { return backlogNodeHighlightedMsg{node: node} }
}

func (m *model) backlogToggleCmd(node backlogNode) tea.Cmd {
	return func() tea.Msg { return backlogNodeToggleMsg{node: node} }
}

func (m *model) backlogActivateCmd(node backlogNode) tea.Cmd {
	return func() tea.Msg { return backlogNodeHighlightedMsg{node: node} }
}

func (m *model) backlogRowHighlightCmd(row backlogRow) tea.Cmd {
	return func() tea.Msg { return backlogRowHighlightedMsg{row: row} }
}

func (m *model) backlogRowToggleCmd(row backlogRow) tea.Cmd {
	return func() tea.Msg { return backlogToggleRequest{row: row} }
}

func (m *model) loadBacklogCmd() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	return func() tea.Msg {
		data, err := loadBacklogData(projectPath)
		return backlogLoadedMsg{data: data, err: err}
	}
}

func (m *model) computeCredentialHint() string {
	var missing []string
	if os.Getenv("OPENAI_API_KEY") == "" && os.Getenv("GC_OPENAI_API_KEY") == "" {
		missing = append(missing, "OPENAI_API_KEY")
	}
	if os.Getenv("JIRA_API_TOKEN") == "" && os.Getenv("GC_JIRA_API_TOKEN") == "" {
		missing = append(missing, "JIRA_API_TOKEN")
	}
	if len(missing) == 0 {
		return ""
	}
	return fmt.Sprintf("Missing credentials: %s. Open the Env Editor to configure them.", strings.Join(missing, ", "))
}

func (m *model) updateCredentialHint() {
	m.credentialHint = m.computeCredentialHint()
}

func (m *model) buildBacklogTreeItems() []list.Item {
	if m.backlog == nil {
		return nil
	}
	items := make([]list.Item, 0, len(m.backlog.Rows))
	for _, row := range m.backlog.Rows {
		entry := backlogTreeEntry{
			title:  row.Title,
			desc:   "",
			node:   row.Node,
			level:  row.Depth,
			status: row.Status,
		}
		switch row.Type {
		case backlogNodeEpic:
			if epic := m.backlog.EpicByKey(row.Node.EpicKey); epic != nil {
				entry.desc = fmt.Sprintf("%d stories · %d tasks", epic.StoryCount, epic.TaskCount)
			}
			entry.selected = m.selectedEpics[row.Node.EpicKey]
		case backlogNodeStory:
			if story := m.backlog.StoryBySlug(row.Node.StorySlug); story != nil {
				entry.desc = fmt.Sprintf("%d/%d tasks complete", story.Completed, story.Total)
				if story.AssigneeHint != "" {
					entry.desc += " · " + story.AssigneeHint
				}
			}
		case backlogNodeTask:
			if task := m.backlog.TaskByNode(row.Node); task != nil {
				summary := []string{}
				if task.Assignee != "" {
					summary = append(summary, task.Assignee)
				}
				if task.Estimate != "" {
					summary = append(summary, task.Estimate)
				}
				if task.LastRun != "" {
					summary = append(summary, task.LastRun)
				}
				entry.desc = strings.Join(summary, " · ")
			}
		}
		items = append(items, entry)
	}
	return items
}

func (m *model) refreshBacklogViews() {
	if m.backlogCol == nil || m.backlogTable == nil {
		return
	}
	if m.backlog == nil {
		m.backlogCol.SetItems(nil)
		m.backlogTable.SetRows(nil)
		return
	}
	scope := m.backlogScope
	items := m.buildBacklogTreeItems()
	m.backlogCol.SetItems(items)
	m.backlogCol.SelectNode(scope)
	m.applyBacklogFilters()
}

func (m *model) applyBacklogFilters() {
	if m.backlogTable == nil {
		return
	}
	if m.backlog == nil {
		m.backlogTable.SetRows(nil)
		return
	}
	rows := m.backlog.FilteredRows(m.backlogFilterType, m.backlogStatusFilter, m.backlogScope)
	m.backlogTable.SetRows(rows)
	if !m.backlogActive.IsZero() {
		m.backlogTable.SelectNode(m.backlogActive)
	} else if len(rows) > 0 {
		m.backlogTable.SelectNode(rows[0].Node)
	}
}

func (m *model) handleBacklogLoaded(msg backlogLoadedMsg) {
	m.backlogLoading = false
	if msg.err != nil {
		m.backlog = nil
		m.backlogError = msg.err
		if errors.Is(msg.err, errBacklogMissing) {
			m.previewCol.SetContent("Task database missing. Run `gpt-creator migrate-tasks` to build the backlog.\n")
			m.appendLog("Tasks database missing. Run migrate-tasks first.")
			m.setToast("Run migrate-tasks to create tasks.db", 6*time.Second)
		} else {
			m.previewCol.SetContent(fmt.Sprintf("Failed to load backlog: %v\n", msg.err))
			m.appendLog(fmt.Sprintf("Failed to load backlog: %v", msg.err))
			m.setToast("Backlog load failed", 6*time.Second)
		}
		if m.backlogCol != nil {
			m.backlogCol.SetItems(nil)
		}
		if m.backlogTable != nil {
			m.backlogTable.SetRows(nil)
		}
		return
	}
	m.backlog = msg.data
	m.backlogError = nil
	m.updateCredentialHint()
	m.refreshBacklogViews()
	if !m.backlogActive.IsZero() {
		m.backlogTable.SelectNode(m.backlogActive)
	}
	if m.backlog != nil {
		m.previewCol.SetContent(m.renderBacklogSummary())
	}
	if reason := strings.TrimSpace(m.pendingBacklogReason); reason != "" && m.backlog != nil {
		s := m.backlog.Summary
		m.appendLog(fmt.Sprintf("Backlog refreshed (%s): %d tasks (done %d, doing %d, todo %d, blocked %d).",
			reason, s.Tasks, s.DoneTasks, s.DoingTasks, s.TodoTasks, s.BlockedTasks))
		m.pendingBacklogReason = ""
	}
}

func (m *model) handleBacklogNodeHighlighted(node backlogNode) {
	if m.backlog == nil {
		return
	}
	m.backlogScope = node
	m.backlogActive = node
	m.applyBacklogFilters()
	if m.backlogCol != nil {
		m.backlogCol.SelectNode(node)
	}
	if m.backlogTable != nil {
		m.backlogTable.SelectNode(node)
	}
	if row, ok := m.backlog.RowByNode(node); ok {
		m.previewCol.SetContent(m.renderBacklogPreview(row))
	}
}

func (m *model) handleBacklogRowHighlighted(row backlogRow) {
	m.backlogActive = row.Node
	if row.Node.Type == backlogNodeEpic || row.Node.Type == backlogNodeStory {
		m.backlogScope = row.Node
		if m.backlogCol != nil {
			m.backlogCol.SelectNode(row.Node)
		}
		m.applyBacklogFilters()
	}
	m.previewCol.SetContent(m.renderBacklogPreview(row))
}

func (m *model) handleBacklogToggle(node backlogNode) {
	if node.Type != backlogNodeEpic {
		return
	}
	if m.selectedEpics == nil {
		m.selectedEpics = make(map[string]bool)
	}
	key := strings.TrimSpace(node.EpicKey)
	if key == "" {
		return
	}
	if m.selectedEpics[key] {
		delete(m.selectedEpics, key)
	} else {
		m.selectedEpics[key] = true
	}
	scope := m.backlogScope
	items := m.buildBacklogTreeItems()
	m.backlogCol.SetItems(items)
	m.backlogCol.SelectNode(scope)
	m.applyBacklogFilters()
}

func (m *model) handleBacklogToggleRequest(row backlogRow) tea.Cmd {
	if m.backlog == nil || row.Node.Type != backlogNodeTask {
		return nil
	}
	if m.backlog.DBPath == "" {
		m.appendLog("Task database unavailable; cannot update status.")
		return nil
	}
	m.backlogActive = row.Node
	nextStatus := "done"
	if strings.EqualFold(row.Status, "done") {
		nextStatus = "todo"
	}
	m.appendLog(fmt.Sprintf("Updating task %s → %s", row.Key, nextStatus))
	return func() tea.Msg {
		err := updateTaskStatus(m.backlog.DBPath, row.Node, nextStatus)
		return backlogStatusUpdatedMsg{node: row.Node, status: nextStatus, err: err}
	}
}

func (m *model) handleBacklogStatusUpdated(msg backlogStatusUpdatedMsg) tea.Cmd {
	if msg.err != nil {
		m.appendLog(fmt.Sprintf("Task status update failed: %v", msg.err))
		m.setToast("Task update failed", 6*time.Second)
		return nil
	}
	m.backlogActive = msg.node
	m.pendingBacklogReason = "status change"
	m.backlogLoading = true
	fields := map[string]string{"status": msg.status}
	if m.currentProject != nil {
		fields["project"] = filepath.Clean(m.currentProject.Path)
	}
	if msg.node.StorySlug != "" {
		fields["story_slug"] = msg.node.StorySlug
	}
	if msg.node.TaskPosition > 0 {
		fields["position"] = fmt.Sprintf("%d", msg.node.TaskPosition)
	}
	m.emitTelemetry("task_status_changed", fields)
	return m.loadBacklogCmd()
}

func (m *model) runBacklogExport() {
	if m.currentProject == nil || m.backlog == nil {
		m.appendLog("No backlog available to export.")
		return
	}
	rows := m.backlog.FilteredRows(m.backlogFilterType, m.backlogStatusFilter, m.backlogScope)
	if len(rows) == 0 {
		m.appendLog("No rows match the current backlog filters.")
		return
	}
	path := filepath.Join(m.currentProject.Path, "backlog.csv")
	if err := exportBacklogCSV(path, rows); err != nil {
		m.appendLog(fmt.Sprintf("Failed to export backlog CSV: %v", err))
		m.setToast("Backlog export failed", 6*time.Second)
		return
	}
	m.appendLog(fmt.Sprintf("Backlog exported → %s", abbreviatePath(path)))
	m.setToast("backlog.csv updated", 5*time.Second)
}

func (m *model) renderBacklogSummary() string {
	if m.backlog == nil {
		return "Backlog unavailable.\n"
	}
	s := m.backlog.Summary
	lines := []string{
		fmt.Sprintf("Epics %d • Stories %d • Tasks %d", s.Epics, s.Stories, s.Tasks),
		fmt.Sprintf("Done %d • Doing %d • Todo %d • Blocked %d", s.DoneTasks, s.DoingTasks, s.TodoTasks, s.BlockedTasks),
	}
	if !s.LastUpdatedAt.IsZero() {
		lines = append(lines, fmt.Sprintf("Last update %s ago", formatRelativeTime(s.LastUpdatedAt)))
	}
	if m.credentialHint != "" {
		lines = append(lines, "", m.credentialHint)
	}
	return strings.Join(lines, "\n") + "\n"
}

func (m *model) renderBacklogPreview(row backlogRow) string {
	if m.backlog == nil {
		return "Backlog unavailable.\n"
	}
	var b strings.Builder
	b.WriteString(row.Title)
	b.WriteRune('\n')
	b.WriteString(strings.Repeat("─", len(row.Title)))
	b.WriteRune('\n')
	b.WriteRune('\n')
	switch row.Type {
	case backlogNodeEpic:
		if epic := m.backlog.EpicByKey(row.Node.EpicKey); epic != nil {
			b.WriteString(fmt.Sprintf("Key: %s\n", canonicalEpicKey(epic)))
			b.WriteString(fmt.Sprintf("Stories: %d\nTasks: %d\nStatus: %s\n", epic.StoryCount, epic.TaskCount, strings.ToUpper(displayStatus(epic.Status))))
			if !epic.UpdatedAt.IsZero() {
				b.WriteString(fmt.Sprintf("Updated: %s ago\n", formatRelativeTime(epic.UpdatedAt)))
			}
		}
	case backlogNodeStory:
		if story := m.backlog.StoryBySlug(row.Node.StorySlug); story != nil {
			b.WriteString(fmt.Sprintf("Slug: %s\n", story.Slug))
			if story.Key != "" {
				b.WriteString(fmt.Sprintf("Key: %s\n", story.Key))
			}
			b.WriteString(fmt.Sprintf("Tasks: %d/%d complete\nStatus: %s\n", story.Completed, story.Total, strings.ToUpper(displayStatus(story.Status))))
			if story.LastRun != "" {
				b.WriteString(fmt.Sprintf("Last run: %s\n", story.LastRun))
			}
			if story.AssigneeHint != "" {
				b.WriteString(fmt.Sprintf("Assignee: %s\n", story.AssigneeHint))
			}
			if !story.UpdatedAt.IsZero() {
				b.WriteString(fmt.Sprintf("Updated: %s ago\n", formatRelativeTime(story.UpdatedAt)))
			}
		}
		if bundle := m.backlog.Bundles[row.Node.StorySlug]; bundle != "" {
			b.WriteString("\nBundle JSON:\n")
			b.WriteString(bundle)
		}
	case backlogNodeTask:
		if task := m.backlog.TaskByNode(row.Node); task != nil {
			if task.ID != "" {
				b.WriteString(fmt.Sprintf("ID: %s\n", task.ID))
			}
			b.WriteString(fmt.Sprintf("Status: %s\n", strings.ToUpper(displayStatus(task.Status))))
			if task.Assignee != "" {
				b.WriteString(fmt.Sprintf("Assignee: %s\n", task.Assignee))
			}
			if task.Estimate != "" {
				b.WriteString(fmt.Sprintf("Estimate: %s\n", task.Estimate))
			}
			if !task.UpdatedAt.IsZero() {
				b.WriteString(fmt.Sprintf("Updated: %s ago\n", formatRelativeTime(task.UpdatedAt)))
			}
			if task.Description != "" {
				b.WriteString("\nDescription:\n")
				b.WriteString(trimMultiline(task.Description, 18))
				b.WriteRune('\n')
			}
			if task.Acceptance != "" {
				b.WriteString("\nAcceptance:\n")
				b.WriteString(trimMultiline(task.Acceptance, 12))
				b.WriteRune('\n')
			}
		}
		if story := m.backlog.StoryBySlug(row.Node.StorySlug); story != nil {
			if bundle := m.backlog.Bundles[story.Slug]; bundle != "" {
				b.WriteString("\nBundle JSON:\n")
				b.WriteString(bundle)
			}
		}
	}
	b.WriteRune('\n')
	return b.String()
}

func trimMultiline(input string, limit int) string {
	text := strings.TrimSpace(input)
	if text == "" {
		return ""
	}
	lines := strings.Split(text, "\n")
	if len(lines) > limit {
		lines = append(lines[:limit], "…")
	}
	return strings.Join(lines, "\n")
}

func (m *model) queueTasksCommand(command []string) tea.Cmd {
	if len(command) == 0 {
		return nil
	}
	if m.currentProject == nil {
		m.appendLog("Select a project before running backlog commands.")
		return nil
	}
	args := append([]string{}, command...)
	needsProject := true
	for _, arg := range args {
		if strings.HasPrefix(arg, "--project") {
			needsProject = false
			break
		}
	}
	if needsProject {
		args = append(args, "--project", m.currentProject.Path)
	}
	title := "gpt-creator " + strings.Join(command, " ")
	m.appendLog(fmt.Sprintf("Queued %s", title))
	m.appendLog(fmt.Sprintf("Command: %s", title))
	m.showLogs = true
	fields := map[string]string{"command": strings.Join(command, " ")}
	if m.currentProject != nil {
		fields["project"] = filepath.Clean(m.currentProject.Path)
	}
	m.emitTelemetry("command_queued", fields)

	var env []string
	if command[0] == "create-jira-tasks" && len(m.selectedEpics) > 0 {
		keys := sortedEpicKeys(m.selectedEpics)
		if len(keys) > 0 {
			env = append(env, "CJT_SELECTED_EPICS="+strings.Join(keys, ","))
		}
	}

	return m.enqueueJob(jobRequest{
		title:   title,
		dir:     m.currentProject.Path,
		command: "gpt-creator",
		args:    args,
		env:     env,
	})
}

func sortedEpicKeys(set map[string]bool) []string {
	keys := make([]string, 0, len(set))
	for key, selected := range set {
		if selected {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return keys
}

func (m *model) renderStatus() string {
	focusTitle := m.columns[m.focus].Title()
	focusValue := strings.TrimSpace(m.columns[m.focus].FocusValue())
	if focusValue == "" {
		focusValue = "—"
	}

	segments := []string{
		m.styles.statusSeg.Render(fmt.Sprintf("%s: %s", focusTitle, focusValue)),
	}
	if m.currentRoot != nil {
		segments = append(segments, m.styles.statusSeg.Render("Root: "+abbreviatePath(m.currentRoot.Path)))
	}
	if m.currentProject != nil {
		segments = append(segments, m.styles.statusSeg.Render("Project: "+m.currentProject.Name))
	}
	segments = append(segments, m.styles.statusSeg.Render(fmt.Sprintf("Logs: %s", ternary(m.showLogs, "on", "off"))))
	if m.currentFeature == "tasks" {
		segments = append(segments, m.styles.statusSeg.Render("Type: "+m.backlogFilterType.String()))
		segments = append(segments, m.styles.statusSeg.Render("Status: "+m.backlogStatusFilter.String()))
	}
	if m.toastMessage != "" {
		if time.Now().After(m.toastExpires) {
			m.toastMessage = ""
		} else {
			segments = append(segments, m.styles.statusSeg.Render(m.toastMessage))
		}
	}
	left := strings.Join(segments, lipgloss.NewStyle().Foreground(palette.border).Render("│"))

	timeStr := m.styles.statusHint.Render(time.Now().Format("15:04:05"))
	gap := max(0, m.width-lipgloss.Width(left)-lipgloss.Width(timeStr))
	line := lipgloss.JoinHorizontal(lipgloss.Top,
		left,
		lipgloss.PlaceHorizontal(gap, lipgloss.Right, timeStr),
	)
	return m.styles.statusBar.Width(m.width).Render(line)
}

func (m *model) findRoot(path string) *workspaceRoot {
	clean := filepath.Clean(path)
	for i := range m.workspaceRoots {
		if filepath.Clean(m.workspaceRoots[i].Path) == clean {
			m.workspaceRoots[i].Pinned = m.pinnedPaths[clean]
			return &m.workspaceRoots[i]
		}
	}
	return nil
}

func (m *model) hasWorkspaceRoot(path string) bool {
	for _, root := range m.workspaceRoots {
		if filepath.Clean(root.Path) == filepath.Clean(path) {
			return true
		}
	}
	return false
}

func (m *model) resolvePath(input string) string {
	path := strings.TrimSpace(input)
	if path == "" {
		return ""
	}
	if strings.HasPrefix(path, "~") {
		if home, err := os.UserHomeDir(); err == nil {
			path = filepath.Join(home, strings.TrimPrefix(path, "~"))
		}
	}
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}

	if m.currentRoot != nil {
		return filepath.Clean(filepath.Join(m.currentRoot.Path, path))
	}
	cwd, err := os.Getwd()
	if err != nil {
		return filepath.Clean(path)
	}
	return filepath.Clean(filepath.Join(cwd, path))
}

func defaultWorkspaceRoots() []workspaceRoot {
	var roots []workspaceRoot
	seen := make(map[string]struct{})

	cwd, err := os.Getwd()
	if err == nil {
		addRootIfExists(&roots, seen, cwd)
		workspaceDir := filepath.Join(cwd, "workspace")
		addRootIfExists(&roots, seen, workspaceDir)
	}
	if home, err := os.UserHomeDir(); err == nil {
		addRootIfExists(&roots, seen, filepath.Join(home, "gpt-projects"))
	}

	if len(roots) == 0 && err == nil {
		roots = append(roots, workspaceRoot{Label: labelForPath(cwd), Path: cwd})
	}
	return roots
}

func addRootIfExists(list *[]workspaceRoot, seen map[string]struct{}, path string) {
	if path == "" {
		return
	}
	if _, ok := seen[path]; ok {
		return
	}
	if dirExists(path) {
		*list = append(*list, workspaceRoot{
			Label:  labelForPath(path),
			Path:   filepath.Clean(path),
			Pinned: false,
		})
		seen[path] = struct{}{}
	}
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func sortedPaths(set map[string]bool) []string {
	if len(set) == 0 {
		return nil
	}
	paths := make([]string, 0, len(set))
	for path := range set {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	return paths
}

func checkDirWritable(dir string) error {
	file, err := os.CreateTemp(dir, "gc_writable_*")
	if err != nil {
		return fmt.Errorf("directory not writable: %s", dir)
	}
	name := file.Name()
	file.Close()
	_ = os.Remove(name)
	return nil
}

func isDirEmpty(path string) (bool, error) {
	f, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer f.Close()
	_, err = f.Readdirnames(1)
	if err == io.EOF {
		return true, nil
	}
	if err != nil {
		return false, err
	}
	return false, nil
}

func (m *model) ensurePinnedRoots() {
	for i := range m.workspaceRoots {
		clean := filepath.Clean(m.workspaceRoots[i].Path)
		m.workspaceRoots[i].Pinned = m.pinnedPaths[clean]
	}
	for path := range m.pinnedPaths {
		if !m.hasWorkspaceRoot(path) {
			m.workspaceRoots = append(m.workspaceRoots, workspaceRoot{
				Label:  labelForPath(path),
				Path:   filepath.Clean(path),
				Pinned: true,
			})
		}
	}
}

func (m *model) projectByPath(path string) *discoveredProject {
	clean := filepath.Clean(path)
	for i := range m.projects {
		if filepath.Clean(m.projects[i].Path) == clean {
			return &m.projects[i]
		}
	}
	return nil
}

func (m *model) selectProjectPath(path string) {
	if m.projectsCol == nil {
		return
	}
	clean := filepath.Clean(path)
	items := m.projectsCol.model.Items()
	for i, item := range items {
		entry, ok := item.(listEntry)
		if !ok {
			continue
		}
		payload, ok := entry.payload.(projectItem)
		if !ok || payload.project == nil {
			continue
		}
		if filepath.Clean(payload.project.Path) == clean {
			m.projectsCol.model.Select(i)
			return
		}
	}
}

func (m *model) selectedProjectPath() string {
	if m.projectsCol == nil {
		return ""
	}
	entry, ok := m.projectsCol.SelectedEntry()
	if !ok {
		return ""
	}
	payload, ok := entry.payload.(projectItem)
	if !ok || payload.project == nil {
		return ""
	}
	return filepath.Clean(payload.project.Path)
}

func (m *model) refreshCreateProjectProgress(title string) {
	if m.createProjectJobs == nil {
		return
	}
	path, ok := m.createProjectJobs[title]
	if !ok {
		return
	}
	m.refreshProjectSnapshotThrottled(path)
}

func (m *model) refreshProjectSnapshotThrottled(path string) {
	clean := filepath.Clean(path)
	if clean == "" {
		return
	}
	if !m.shouldRefreshProjectSnapshot(clean) {
		return
	}
	m.refreshProjectSnapshot(clean)
}

func (m *model) shouldRefreshProjectSnapshot(path string) bool {
	if m.lastProjectRefresh == nil {
		m.lastProjectRefresh = make(map[string]time.Time)
	}
	last := m.lastProjectRefresh[path]
	if time.Since(last) < 600*time.Millisecond {
		return false
	}
	m.lastProjectRefresh[path] = time.Now()
	return true
}

func (m *model) refreshProjectSnapshot(path string) {
	clean := filepath.Clean(path)
	if clean == "" {
		return
	}
	if !isProjectDir(clean) {
		return
	}

	updated := buildProject(clean)
	found := false
	for i := range m.projects {
		if filepath.Clean(m.projects[i].Path) == clean {
			m.projects[i].Stats = updated.Stats
			m.projects[i].Name = updated.Name
			found = true
			break
		}
	}
	if !found {
		m.projects = append(m.projects, updated)
		sort.Slice(m.projects, func(i, j int) bool {
			return m.projects[i].Name < m.projects[j].Name
		})
		if m.seenProjects == nil {
			m.seenProjects = make(map[string]bool)
		}
		if !m.seenProjects[clean] {
			m.seenProjects[clean] = true
			m.emitTelemetry("project_discovered", map[string]string{"path": clean})
		}
	}

	currentSelection := m.selectedProjectPath()
	m.refreshProjectsColumn()
	if currentSelection != "" {
		m.selectProjectPath(currentSelection)
	} else if !found {
		m.selectProjectPath(clean)
		if project := m.projectByPath(clean); project != nil {
			m.handleProjectSelected(project)
		}
		return
	}

	if found && m.currentProject != nil && filepath.Clean(m.currentProject.Path) == clean {
		if project := m.projectByPath(clean); project != nil {
			m.currentProject = project
			if m.currentFeature != "" {
				currentKey := m.currentItem.Key
				items := featureItemEntries(m.currentProject, m.currentFeature, m.dockerAvailable)
				m.itemsCol.SetItems(items)
				if currentKey != "" {
					m.itemsCol.SelectKey(currentKey)
					for _, def := range items {
						if def.Key == currentKey {
							m.currentItem = def
							break
						}
					}
					m.applyItemSelection(m.currentProject, m.currentFeature, m.currentItem, false)
				} else {
					m.previewCol.SetContent("Select an item to preview details.\n")
				}
			} else {
				m.previewCol.SetContent(previewPath(m.currentProject, "."))
			}
		}
	}
}

func (m *model) selectedProject() *discoveredProject {
	if m.projectsCol == nil {
		return nil
	}
	entry, ok := m.projectsCol.SelectedEntry()
	if !ok {
		return nil
	}
	payload, ok := entry.payload.(projectItem)
	if !ok || payload.project == nil {
		return nil
	}
	return payload.project
}

func (m *model) openProjectInEditor() {
	project := m.selectedProject()
	if project == nil {
		m.appendLog("Select a project to open in editor.")
		return
	}
	commandLine, err := launchEditor(project.Path)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to launch editor: %v", err))
		m.setToast("Failed to open editor", 5*time.Second)
		return
	}
	m.appendLog("Opening editor: " + commandLine)
	m.setToast("Opening in editor", 4*time.Second)
	fields := map[string]string{
		"path":    filepath.Clean(project.Path),
		"command": commandLine,
	}
	m.emitTelemetry("editor_opened", fields)
}

func (m *model) openCurrentDocInEditor() {
	if m.currentProject == nil {
		m.appendLog("Select a project before opening documentation.")
		return
	}
	rel := strings.TrimSpace(m.currentDocRelPath)
	if rel == "" {
		m.appendLog("No document selected to open.")
		m.setToast("Select a document first", 4*time.Second)
		return
	}
	abs := filepath.Join(m.currentProject.Path, rel)
	if _, err := os.Stat(abs); err != nil {
		m.appendLog(fmt.Sprintf("Document not found: %s", abs))
		m.setToast("Document not found", 5*time.Second)
		return
	}
	commandLine, err := launchEditor(abs)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to launch editor: %v", err))
		m.setToast("Failed to open document", 5*time.Second)
		return
	}
	m.appendLog("Opening document: " + commandLine)
	m.setToast("Opening document in editor", 4*time.Second)
	fields := map[string]string{
		"path":     filepath.Clean(m.currentProject.Path),
		"document": rel,
		"mode":     "editor",
	}
	if m.currentDocType != "" {
		fields["doc_type"] = m.currentDocType
	}
	m.emitTelemetry("doc_opened", fields)
}

func (m *model) openCurrentGenerateFileInEditor() {
	if m.currentProject == nil {
		m.appendLog("Select a project before opening files.")
		return
	}
	rel := strings.TrimSpace(m.currentGenerateFile)
	if rel == "" {
		m.appendLog("Select a generated file first.")
		m.setToast("Select a file first", 4*time.Second)
		return
	}
	status := ""
	if m.currentItem.Meta != nil {
		status = strings.TrimSpace(m.currentItem.Meta["generateStatus"])
	}
	abs := filepath.Join(m.currentProject.Path, filepath.FromSlash(rel))
	if status == "deleted" {
		m.appendLog("File was deleted; cannot open in editor.")
		m.setToast("File removed from workspace", 5*time.Second)
		return
	}
	if _, err := os.Stat(abs); err != nil {
		m.appendLog(fmt.Sprintf("File not found: %s", abs))
		m.setToast("File not found", 5*time.Second)
		return
	}
	commandLine, err := launchEditor(abs)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to launch editor: %v", err))
		m.setToast("Failed to open file", 5*time.Second)
		return
	}
	m.appendLog("Opening file: " + commandLine)
	m.setToast("Opening file in editor", 4*time.Second)
	fields := map[string]string{
		"path":   filepath.Clean(m.currentProject.Path),
		"file":   rel,
		"target": strings.TrimSpace(m.currentGenerateTarget),
	}
	m.emitTelemetry("file_opened", fields)
}

func (m *model) openDatabaseDumpInEditor(kind string) {
	if m.currentProject == nil {
		m.appendLog("Select a project before opening database dumps.")
		return
	}
	var (
		path  string
		label string
	)
	switch kind {
	case "schema":
		path = strings.TrimSpace(m.currentDBSchemaPath)
		label = "schema.sql"
	case "seed":
		path = strings.TrimSpace(m.currentDBSeedPath)
		label = "seed.sql"
	default:
		return
	}
	if path == "" {
		m.appendLog(fmt.Sprintf("No %s available to open.", label))
		m.setToast(fmt.Sprintf("No %s found", label), 4*time.Second)
		return
	}
	if _, err := os.Stat(path); err != nil {
		m.appendLog(fmt.Sprintf("%s not found: %v", label, err))
		m.setToast(fmt.Sprintf("%s missing", label), 5*time.Second)
		return
	}
	commandLine, err := launchEditor(path)
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to open %s: %v", label, err))
		m.setToast(fmt.Sprintf("Failed to open %s", label), 5*time.Second)
		return
	}
	m.appendLog(fmt.Sprintf("Opening %s: %s", label, commandLine))
	m.setToast(fmt.Sprintf("Opening %s", label), 4*time.Second)
	projectPath := filepath.Clean(m.currentProject.Path)
	rel, err := filepath.Rel(projectPath, path)
	if err != nil {
		rel = path
	}
	fields := map[string]string{
		"path": projectPath,
		"file": filepath.ToSlash(rel),
		"kind": kind,
	}
	m.emitTelemetry("db_dump_opened", fields)
}

func launchBrowser(target string) (string, error) {
	target = strings.TrimSpace(target)
	if target == "" {
		return "", fmt.Errorf("empty URL")
	}
	if browser := strings.TrimSpace(os.Getenv("BROWSER")); browser != "" {
		parts := strings.Fields(browser)
		if len(parts) > 0 {
			bin := parts[0]
			args := append(parts[1:], target)
			cmd := exec.Command(bin, args...)
			if err := cmd.Start(); err == nil {
				return strings.Join(append([]string{bin}, args...), " "), nil
			}
		}
	}
	switch runtime.GOOS {
	case "darwin":
		cmd := exec.Command("open", target)
		if err := cmd.Start(); err != nil {
			return "", err
		}
		return "open " + target, nil
	case "windows":
		quoted := fmt.Sprintf("\"%s\"", target)
		cmd := exec.Command("cmd", "/c", "start", "", quoted)
		if err := cmd.Start(); err != nil {
			return "", err
		}
		return "cmd /c start " + quoted, nil
	default:
		cmd := exec.Command("xdg-open", target)
		if err := cmd.Start(); err != nil {
			return "", err
		}
		return "xdg-open " + target, nil
	}
}

func launchEditor(path string) (string, error) {
	candidates := []string{os.Getenv("VISUAL"), os.Getenv("EDITOR")}
	for _, candidate := range candidates {
		candidate = strings.TrimSpace(candidate)
		if candidate == "" {
			continue
		}
		parts := strings.Fields(candidate)
		parts = append(parts, path)
		bin := parts[0]
		args := parts[1:]
		cmd := exec.Command(bin, args...)
		if err := cmd.Start(); err != nil {
			continue
		}
		return strings.Join(append([]string{bin}, args...), " "), nil
	}
	switch runtime.GOOS {
	case "darwin":
		cmd := exec.Command("open", path)
		if err := cmd.Start(); err != nil {
			return "", err
		}
		return "open " + path, nil
	case "windows":
		quoted := fmt.Sprintf("\"%s\"", path)
		cmd := exec.Command("cmd", "/c", "start", "", quoted)
		if err := cmd.Start(); err != nil {
			return "", err
		}
		return "cmd /c start " + quoted, nil
	default:
		cmd := exec.Command("xdg-open", path)
		if err := cmd.Start(); err != nil {
			return "", err
		}
		return "xdg-open " + path, nil
	}
}

func (m *model) emitTelemetry(event string, fields map[string]string) {
	if m.telemetry == nil {
		return
	}
	m.telemetry.Emit(event, fields)
}

func (m *model) setToast(msg string, duration time.Duration) {
	trimmed := strings.TrimSpace(msg)
	if trimmed == "" {
		m.toastMessage = ""
		m.toastExpires = time.Time{}
		return
	}
	if duration <= 0 {
		duration = 5 * time.Second
	}
	m.toastMessage = trimmed
	m.toastExpires = time.Now().Add(duration)
}

func pathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func labelForPath(path string) string {
	clean := filepath.Clean(path)
	if clean == "." || clean == string(filepath.Separator) {
		return clean
	}
	base := filepath.Base(clean)
	if base == "" || base == "." {
		return clean
	}
	return base
}

func abbreviatePath(path string) string {
	if strings.HasPrefix(path, "~") {
		return path
	}
	if home, err := os.UserHomeDir(); err == nil {
		if strings.HasPrefix(path, home) {
			return "~" + strings.TrimPrefix(path, home)
		}
	}
	return path
}

func formatProjectDescription(stats projectStats) string {
	stage := fmt.Sprintf("%s (%d/%d)", stats.StageLabel, stats.StageIndex, stats.StageTotal)
	tasks := "Tasks —"
	if stats.TasksTotal > 0 {
		tasks = fmt.Sprintf("Tasks %d/%d", stats.TasksDone, stats.TasksTotal)
	}
	verify := "Verify —"
	if stats.VerifyTotal > 0 {
		verify = fmt.Sprintf("Verify %d/%d", stats.VerifyPass, stats.VerifyTotal)
	}
	return fmt.Sprintf("%s · %s · %s", stage, tasks, verify)
}

func featureListEntries() []list.Item {
	items := make([]list.Item, 0, len(featureDefinitions))
	for _, def := range featureDefinitions {
		items = append(items, listEntry{
			title:   def.Title,
			desc:    def.Desc,
			payload: def,
		})
	}
	return items
}

func findFeatureDefinition(key string) featureDefinition {
	for _, def := range featureDefinitions {
		if def.Key == key {
			return def
		}
	}
	return featureDefinition{}
}

func renderPipeline(project *discoveredProject) string {
	if project == nil {
		return "Pipeline progress unavailable.\n"
	}
	stats := project.Stats
	if len(stats.Pipeline) == 0 {
		return "Pipeline progress unavailable.\n"
	}

	blocks := make([]string, len(stats.Pipeline))
	for i, step := range stats.Pipeline {
		label := pipelineSteps[i].Label
		style := lipgloss.NewStyle().Foreground(palette.textMuted)
		icon := "…"
		switch step.State {
		case pipelineStateDone:
			style = lipgloss.NewStyle().Foreground(palette.success)
			icon = "✓"
		case pipelineStateActive:
			style = lipgloss.NewStyle().Foreground(palette.info)
			icon = "●"
		default:
			style = lipgloss.NewStyle().Foreground(palette.textMuted)
			icon = "…"
		}
		blocks[i] = style.Render("[" + icon + "] " + label)
	}
	return strings.Join(blocks, "  ") + "\n"
}

func ternary[T any](cond bool, a, b T) T {
	if cond {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
