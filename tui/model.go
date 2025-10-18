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
	"strconv"
	"strings"
	"time"

	"github.com/atotto/clipboard"
	"github.com/charmbracelet/bubbles/filepicker"
	"github.com/charmbracelet/bubbles/help"
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/list"
	"github.com/charmbracelet/bubbles/paginator"
	"github.com/charmbracelet/bubbles/progress"
	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/stopwatch"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/timer"
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

const horizontalScrollStep = 4

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
	inputEnvEditValue
	inputEnvNewKey
	inputEnvNewValue
	inputSettingsWorkspaceAdd
	inputSettingsWorkspaceRemove
	inputSettingsDockerPath
	inputSettingsConcurrency
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

type envFileItem struct {
	index int
	state *envFileState
}

type paletteEntry struct {
	label           string
	command         []string
	description     string
	requiresProject bool
	meta            map[string]string
}

type envFilesLoadedMsg struct {
	states []*envFileState
	err    error
}

type envFileSelectedMsg struct {
	index    int
	activate bool
}

type jobMsg interface {
	isJob()
	jobID() int
}

type jobStartedMsg struct {
	Title string
	ID    int
}

func (jobStartedMsg) isJob()         {}
func (msg jobStartedMsg) jobID() int { return msg.ID }

type jobLogMsg struct {
	Title string
	Line  string
	ID    int
}

func (jobLogMsg) isJob()         {}
func (msg jobLogMsg) jobID() int { return msg.ID }

type jobFinishedMsg struct {
	Title string
	Err   error
	ID    int
}

func (jobFinishedMsg) isJob()         {}
func (msg jobFinishedMsg) jobID() int { return msg.ID }

type jobChannelClosedMsg struct {
	ID int
}

func (jobChannelClosedMsg) isJob()         {}
func (msg jobChannelClosedMsg) jobID() int { return msg.ID }

type jobCancelledMsg struct {
	ID    int
	Title string
}

func (jobCancelledMsg) isJob()         {}
func (msg jobCancelledMsg) jobID() int { return msg.ID }

type jobStatus struct {
	ID              int
	Title           string
	Status          string
	Started         time.Time
	Ended           time.Time
	Err             string
	CancelRequested bool
}

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

type tokensLoadedMsg struct {
	usage *tokensUsage
	err   error
}

type tokensRowSelectedMsg struct {
	row tokensTableRow
}

type tokensExportedMsg struct {
	path     string
	err      error
	rangeKey string
	group    tokensGroupMode
	records  int
	tokens   int
}

type reportsLoadedMsg struct {
	entries []reportEntry
	err     error
}

type reportsRowSelectedMsg struct {
	entry    reportEntry
	activate bool
}

type servicesLoadedMsg struct {
	items []featureItemDefinition
}

const servicesPollInterval = 2 * time.Second

type keyMap struct {
	quit        key.Binding
	nextFocus   key.Binding
	prevFocus   key.Binding
	nextFeature key.Binding
	prevFeature key.Binding
	toggleLogs  key.Binding
	openPalette key.Binding
	closePal    key.Binding
	runPal      key.Binding
	openEditor  key.Binding
	togglePin   key.Binding
	copyPath    key.Binding
	copySnippet key.Binding
	toggleSplit key.Binding
	cancelJob   key.Binding
	toggleHelp  key.Binding
}

func newKeyMap() keyMap {
	return keyMap{
		quit: key.NewBinding(
			key.WithKeys("q", "ctrl+c"),
			key.WithHelp("q", "quit"),
		),
		nextFocus: key.NewBinding(
			key.WithKeys("tab"),
			key.WithHelp("tab", "next panel"),
		),
		prevFocus: key.NewBinding(
			key.WithKeys("shift+tab"),
			key.WithHelp("shift+tab", "prev panel"),
		),
		nextFeature: key.NewBinding(
			key.WithKeys("]"),
			key.WithHelp("]", "next feature"),
		),
		prevFeature: key.NewBinding(
			key.WithKeys("["),
			key.WithHelp("[", "prev feature"),
		),
		toggleLogs: key.NewBinding(
			key.WithKeys("f6"),
			key.WithHelp("F6", "toggle logs"),
		),
		openPalette: key.NewBinding(
			key.WithKeys(":"),
			key.WithHelp(":", "command palette"),
		),
		closePal: key.NewBinding(
			key.WithKeys("esc"),
			key.WithHelp("esc", "close palette"),
		),
		runPal: key.NewBinding(
			key.WithKeys("enter"),
			key.WithHelp("enter", "run palette entry"),
		),
		openEditor: key.NewBinding(
			key.WithKeys("o"),
			key.WithHelp("o", "open in editor"),
		),
		togglePin: key.NewBinding(
			key.WithKeys("p"),
			key.WithHelp("p", "pin workspace"),
		),
		copyPath: key.NewBinding(
			key.WithKeys("y"),
			key.WithHelp("y", "copy path"),
		),
		copySnippet: key.NewBinding(
			key.WithKeys("Y"),
			key.WithHelp("Y", "copy snippet"),
		),
		toggleSplit: key.NewBinding(
			key.WithKeys("s"),
			key.WithHelp("s", "toggle split"),
		),
		cancelJob: key.NewBinding(
			key.WithKeys("ctrl+k"),
			key.WithHelp("ctrl+k", "cancel job"),
		),
		toggleHelp: key.NewBinding(
			key.WithKeys("?"),
			key.WithHelp("?", "toggle help"),
		),
	}
}

func (k keyMap) ShortHelp() []key.Binding {
	return []key.Binding{
		k.nextFocus,
		k.prevFocus,
		k.nextFeature,
		k.prevFeature,
		k.openPalette,
		k.toggleLogs,
		k.toggleHelp,
		k.quit,
	}
}

func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.nextFocus, k.prevFocus, k.nextFeature, k.prevFeature},
		{k.openPalette, k.runPal, k.closePal},
		{k.openEditor, k.togglePin, k.toggleSplit},
		{k.copyPath, k.copySnippet},
		{k.cancelJob, k.toggleLogs, k.toggleHelp, k.quit},
	}
}

type model struct {
	width  int
	height int

	styles styles
	keys   keyMap
	help   help.Model

	markdownTheme markdownTheme

	workspaceRoots []workspaceRoot
	currentRoot    *workspaceRoot
	projects       []discoveredProject
	currentProject *discoveredProject
	currentFeature string
	currentItem    featureItemDefinition

	workspaceCol            *selectableColumn
	projectsCol             *selectableColumn
	featureCol              *selectableColumn
	itemsCol                *actionColumn
	envTableCol             *envTableColumn
	servicesCol             *servicesTableColumn
	tokensCol               *tokensTableColumn
	reportsCol              *reportsTableColumn
	artifactsCol            *selectableColumn
	artifactTreeCol         *artifactTreeColumn
	previewCol              *previewColumn
	columns                 []column
	defaultColumns          []column
	featureSelectDefault    func(listEntry) tea.Cmd
	featureHighlightDefault func(listEntry) tea.Cmd
	usingTasksLayout        bool
	usingServicesLayout     bool
	usingArtifactsLayout    bool
	usingEnvLayout          bool
	usingTokensLayout       bool
	usingReportsLayout      bool
	backlogCol              *backlogTreeColumn
	backlogTable            *backlogTableColumn

	focus int

	showLogs   bool
	logsHeight int
	logs       viewport.Model
	logLines   []string

	inputActive     bool
	inputMode       inputMode
	inputPrompt     string
	inputField      textinput.Model
	inputArea       textarea.Model
	textAreaEnabled bool
	spinner         spinner.Model
	spinnerActive   bool
	spinnerMessage  string

	filePicker           filepicker.Model
	filePickerEnabled    bool
	filePickerAllowDirs  bool
	filePickerAllowFiles bool

	jobRunner       *jobManager
	jobStatuses     map[int]*jobStatus
	jobOrder        []int
	jobRunningCount int

	commandEntries   []paletteEntry
	paletteMatches   []paletteEntry
	paletteIndex     int
	palettePaginator paginator.Model

	pinnedPaths         map[string]bool
	uiConfig            *uiConfig
	uiConfigPath        string
	telemetry           *telemetryLogger
	serviceHealth       map[string]string
	servicesPolling     bool
	servicesTimer       timer.Model
	servicesTimerActive bool
	dockerAvailable     bool
	seenProjects        map[string]bool
	createProjectJobs   map[string]string
	lastProjectRefresh  map[string]time.Time
	jobProjectPaths     map[string]string

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

	envFiles              []*envFileState
	currentEnvFile        *envFileState
	envSelection          int
	envReveal             map[string]bool
	envEditingFile        *envFileState
	envEditingEntry       envEntry
	pendingEnvKey         string
	envValidationNotified map[string]bool
	envOpenTelemetrySent  bool

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

	tokensUsage         *tokensUsage
	tokensViewData      tokensViewData
	tokensRangeIndex    int
	tokensGroup         tokensGroupMode
	tokensCurrentRow    string
	tokensLoading       bool
	tokensError         error
	tokensTelemetrySent bool

	reportEntries        []reportEntry
	currentReportKey     string
	reportsLoading       bool
	reportsError         error
	reportsTelemetrySent bool
	settingsConcurrency  int
	settingsDockerPath   string
	customWorkspaceRoots []string
	updateStatus         string
	updateLastError      string
	updateLastRun        time.Time

	jobStopwatch    stopwatch.Model
	jobTimingActive bool
	jobTimingTitle  string
	jobLastDuration time.Duration
}

func initialModel() *model {
	s := newStyles()
	m := &model{
		styles:        s,
		keys:          newKeyMap(),
		help:          help.New(),
		markdownTheme: currentMarkdownTheme(),
		showLogs:      true,
		logsHeight:    8,
		logLines: []string{
			"[INFO] Select a workspace root or add a project path to begin.",
			"[TIP] Use Tab/Shift+Tab or h/l to move focus across columns.",
			"[TIP] Press Enter to drill into a column; Backspace to step back.",
		},
	}

	m.help.ShortSeparator = " │ "
	m.help.Styles.ShortKey = m.styles.statusHint.Copy()
	m.help.Styles.ShortDesc = m.styles.statusHint.Copy()
	m.help.Styles.ShortSeparator = m.styles.statusSeg.Copy()
	m.help.Styles.Ellipsis = m.styles.statusSeg.Copy()
	m.help.Styles.FullKey = m.styles.statusHint.Copy()
	m.help.Styles.FullDesc = m.styles.statusHint.Copy()
	m.help.Styles.FullSeparator = m.styles.statusSeg.Copy()

	m.help.ShowAll = true

	m.inputField = textinput.New()
	m.inputField.Prompt = "> "
	m.inputField.CharLimit = 256
	m.inputArea = textarea.New()
	m.inputArea.Prompt = ""
	m.inputArea.CharLimit = 4096
	m.inputArea.ShowLineNumbers = false
	m.inputArea.SetHeight(6)
	m.inputArea.SetWidth(48)
	m.inputArea.Blur()
	m.spinner = spinner.New(spinner.WithSpinner(spinner.Dot))
	m.spinner.Style = m.styles.statusHint.Copy().Bold(true)
	m.palettePaginator = paginator.New()
	m.palettePaginator.Type = paginator.Dots
	m.palettePaginator.PerPage = 6
	m.palettePaginator.TotalPages = 1
	m.jobRunner = newJobManager()
	m.jobStatuses = make(map[int]*jobStatus)
	m.jobOrder = nil
	m.seenProjects = make(map[string]bool)
	m.pinnedPaths = make(map[string]bool)
	m.createProjectJobs = make(map[string]string)
	m.lastProjectRefresh = make(map[string]time.Time)
	m.jobProjectPaths = make(map[string]string)
	m.selectedEpics = make(map[string]bool)
	m.artifactExplorers = make(map[string]*artifactExplorer)
	m.backlogFilterType = backlogTypeFilterAll
	m.backlogStatusFilter = backlogStatusFilterAll
	customRoots := []string{}
	if cfg, cfgPath := loadUIConfig(); cfg != nil {
		for _, path := range cfg.Pinned {
			clean := filepath.Clean(path)
			if clean != "" {
				m.pinnedPaths[clean] = true
			}
		}
		m.uiConfig = cfg
		m.uiConfigPath = cfgPath
		if theme := strings.TrimSpace(cfg.Theme); theme != "" {
			selected := markdownThemeFromString(theme)
			m.markdownTheme = selected
			setMarkdownTheme(selected)
		}
		if cfg.Concurrency > 0 {
			m.settingsConcurrency = cfg.Concurrency
		}
		m.settingsDockerPath = strings.TrimSpace(cfg.DockerPath)
		rootSeen := make(map[string]struct{})
		for _, path := range cfg.WorkspaceRoots {
			clean := filepath.Clean(strings.TrimSpace(path))
			if clean == "" {
				continue
			}
			if _, ok := rootSeen[clean]; ok {
				continue
			}
			rootSeen[clean] = struct{}{}
			customRoots = append(customRoots, clean)
		}
	}
	if m.settingsConcurrency < 1 {
		m.settingsConcurrency = 1
	}
	if m.jobRunner != nil {
		m.jobRunner.maxParallel = m.settingsConcurrency
	}
	if m.updateStatus == "" {
		m.updateStatus = "Idle"
	}
	m.dockerAvailable = dockerCLIAvailableWithPath(m.settingsDockerPath)
	m.telemetry = newTelemetryLogger(filepath.Join(resolveConfigDir(), "ui-events.ndjson"))
	m.serviceHealth = make(map[string]string)
	m.jobStopwatch = stopwatch.NewWithInterval(500 * time.Millisecond)

	m.workspaceRoots = defaultWorkspaceRoots()
	if len(customRoots) > 0 {
		sort.Strings(customRoots)
		for _, path := range customRoots {
			if !m.hasWorkspaceRoot(path) {
				m.workspaceRoots = append(m.workspaceRoots, workspaceRoot{
					Label: labelForPath(path),
					Path:  filepath.Clean(path),
				})
			}
		}
		m.customWorkspaceRoots = append([]string{}, customRoots...)
	}
	m.ensurePinnedRoots()

	m.workspaceCol = newSelectableColumn("Workspace", nil, 22, func(entry listEntry) tea.Cmd {
		if item, ok := entry.payload.(workspaceItem); ok {
			return func() tea.Msg { return workspaceSelectedMsg{item: item} }
		}
		return nil
	})
	m.workspaceCol.ApplyStyles(m.styles)

	m.projectsCol = newSelectableColumn("Projects", nil, 26, func(entry listEntry) tea.Cmd {
		if payload, ok := entry.payload.(projectItem); ok && payload.project != nil {
			return func() tea.Msg { return projectSelectedMsg{project: payload.project} }
		}
		return nil
	})

	m.featureCol = newSelectableColumn("Feature", nil, 26, func(entry listEntry) tea.Cmd {
		switch payload := entry.payload.(type) {
		case featureDefinition:
			return func() tea.Msg {
				return featureSelectedMsg{project: m.currentProject, feature: payload}
			}
		case envFileItem:
			return func() tea.Msg {
				return envFileSelectedMsg{index: payload.index, activate: true}
			}
		default:
			return nil
		}
	})
	m.projectsCol.ApplyStyles(m.styles)
	m.featureCol.ApplyStyles(m.styles)
	m.featureSelectDefault = m.featureCol.onSelect
	m.featureHighlightDefault = nil

	m.artifactsCol = newSelectableColumn("Artifacts", nil, 26, func(entry listEntry) tea.Cmd {
		if cat, ok := entry.payload.(artifactCategory); ok {
			return func() tea.Msg { return artifactCategorySelectedMsg{category: cat} }
		}
		return nil
	})
	m.artifactsCol.SetHighlightFunc(func(entry listEntry) tea.Cmd {
		if cat, ok := entry.payload.(artifactCategory); ok {
			return func() tea.Msg { return artifactCategorySelectedMsg{category: cat} }
		}
		return nil
	})
	m.artifactsCol.ApplyStyles(m.styles)

	m.envTableCol = newEnvTableColumn("Variables")
	m.envTableCol.SetOnEdit(func(entry envEntry) tea.Cmd {
		m.promptEnvValueEdit(entry)
		return nil
	})
	m.envTableCol.SetOnToggle(func(entry envEntry) tea.Cmd {
		m.toggleEnvReveal(entry)
		return nil
	})
	m.envTableCol.SetOnCopy(func(entry envEntry) tea.Cmd {
		m.copyEnvValue(entry)
		return nil
	})
	m.envTableCol.ApplyStyles(m.styles)

	m.itemsCol = newActionColumn("Actions")
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
	m.itemsCol.ApplyStyles(m.styles)

	m.servicesCol = newServicesTableColumn("Services")
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
	m.servicesCol.ApplyStyles(m.styles)

	m.tokensCol = newTokensTableColumn("Tokens")
	m.tokensCol.SetHighlightFunc(func(row tokensTableRow) tea.Cmd {
		return func() tea.Msg { return tokensRowSelectedMsg{row: row} }
	})
	m.tokensCol.ApplyStyles(m.styles)

	m.reportsCol = newReportsTableColumn("Reports")
	m.reportsCol.SetHighlightFunc(func(entry reportEntry, activate bool) tea.Cmd {
		return func() tea.Msg { return reportsRowSelectedMsg{entry: entry, activate: activate} }
	})
	m.reportsCol.ApplyStyles(m.styles)

	m.backlogCol = newBacklogTreeColumn("Epics/Stories/Tasks")
	m.backlogCol.SetCallbacks(
		m.backlogHighlightCmd,
		m.backlogToggleCmd,
		m.backlogActivateCmd,
	)
	m.backlogCol.ApplyStyles(m.styles)
	m.backlogTable = newBacklogTableColumn("Backlog")
	m.backlogTable.SetCallbacks(
		m.backlogRowHighlightCmd,
		m.backlogRowToggleCmd,
	)
	m.backlogTable.ApplyStyles(m.styles)

	m.artifactTreeCol = newArtifactTreeColumn("Files")
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
	m.artifactTreeCol.ApplyStyles(m.styles)

	m.previewCol = newPreviewColumn(32)
	m.previewCol.SetContent("Select an item to preview details.\n")
	m.previewCol.ApplyStyles(m.styles)
	m.applyMarkdownTheme(m.markdownTheme, false)

	m.columns = []column{
		m.workspaceCol,
		m.projectsCol,
		m.featureCol,
		m.itemsCol,
		m.previewCol,
	}
	m.defaultColumns = append([]column(nil), m.columns...)

	m.envReveal = make(map[string]bool)
	m.envValidationNotified = make(map[string]bool)
	m.envSelection = -1

	m.tokensGroup = tokensGroupByDay
	if len(tokensRangeOptions) > 1 {
		m.tokensRangeIndex = 1
	} else if len(tokensRangeOptions) > 0 {
		m.tokensRangeIndex = 0
	}

	m.logs = viewport.New(80, m.logsHeight)
	m.logs.Style = m.styles.body.Copy().Foreground(crushForegroundMuted)
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
	return m.spinner.Tick
}

func (m *model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	if tick, ok := msg.(spinner.TickMsg); ok {
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(tick)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	if swTick, ok := msg.(stopwatch.TickMsg); ok {
		var cmd tea.Cmd
		m.jobStopwatch, cmd = m.jobStopwatch.Update(swTick)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	if swStartStop, ok := msg.(stopwatch.StartStopMsg); ok {
		var cmd tea.Cmd
		m.jobStopwatch, cmd = m.jobStopwatch.Update(swStartStop)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	if swReset, ok := msg.(stopwatch.ResetMsg); ok {
		var cmd tea.Cmd
		m.jobStopwatch, cmd = m.jobStopwatch.Update(swReset)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	if tickMsg, ok := msg.(timer.TickMsg); ok && m.servicesTimerActive {
		var cmd tea.Cmd
		m.servicesTimer, cmd = m.servicesTimer.Update(tickMsg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	if startStopMsg, ok := msg.(timer.StartStopMsg); ok && m.servicesTimerActive {
		var cmd tea.Cmd
		m.servicesTimer, cmd = m.servicesTimer.Update(startStopMsg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	if timeoutMsg, ok := msg.(timer.TimeoutMsg); ok && m.servicesTimerActive && timeoutMsg.ID == m.servicesTimer.ID() {
		m.servicesTimerActive = false
		if cmd := m.loadServicesCmd(); cmd != nil {
			cmds = append(cmds, cmd)
		}
		if m.servicesPolling {
			m.servicesTimer = timer.NewWithInterval(servicesPollInterval, time.Second)
			m.servicesTimerActive = true
			if cmd := m.servicesTimer.Init(); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
	}

	if m.inputActive {
		if m.filePickerEnabled {
			if keyMsg, ok := msg.(tea.KeyMsg); ok {
				switch keyMsg.String() {
				case "esc":
					m.closeInput()
					return m, tea.Batch(cmds...)
				case "ctrl+t":
					if toggleCmd := m.toggleFilePickerMode(); toggleCmd != nil {
						cmds = append(cmds, toggleCmd)
					}
					return m, tea.Batch(cmds...)
				}
			}
			var cmd tea.Cmd
			m.filePicker, cmd = m.filePicker.Update(msg)
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
			if selected, path := m.filePicker.DidSelectFile(msg); selected {
				cmd, keepOpen := m.handleInputSubmit(path)
				if cmd != nil {
					cmds = append(cmds, cmd)
				}
				if !keepOpen {
					m.closeInput()
				}
				return m, tea.Batch(cmds...)
			}
			if disabled, path := m.filePicker.DidSelectDisabledFile(msg); disabled {
				m.setToast(fmt.Sprintf("Selection not allowed: %s", filepath.Base(path)), 4*time.Second)
				return m, tea.Batch(cmds...)
			}
			return m, tea.Batch(cmds...)
		}

		if m.textAreaEnabled {
			if keyMsg, ok := msg.(tea.KeyMsg); ok {
				switch keyMsg.String() {
				case "esc":
					m.closeInput()
					return m, tea.Batch(cmds...)
				case "ctrl+enter", "ctrl+s":
					value := m.inputArea.Value()
					cmd, keepOpen := m.handleInputSubmit(value)
					if cmd != nil {
						cmds = append(cmds, cmd)
					}
					if !keepOpen {
						m.closeInput()
					}
					return m, tea.Batch(cmds...)
				}
			}
			var cmd tea.Cmd
			m.inputArea, cmd = m.inputArea.Update(msg)
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
			return m, tea.Batch(cmds...)
		}

		if m.inputMode == inputCommandPalette {
			m.palettePaginator, _ = m.palettePaginator.Update(msg)
			m.configurePalettePaginator()
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

		if keyMsg, ok := msg.(tea.KeyMsg); ok {
			switch keyMsg.String() {
			case "esc":
				m.closeInput()
				return m, nil
			case "ctrl+t":
				if m.inputMode == inputAddRoot || m.inputMode == inputAttachRFP {
					if toggleCmd := m.toggleFilePickerMode(); toggleCmd != nil {
						cmds = append(cmds, toggleCmd)
					}
					return m, tea.Batch(cmds...)
				}
			case "enter":
				raw := m.inputField.Value()
				value := raw
				switch m.inputMode {
				case inputEnvEditValue, inputEnvNewValue:
					// keep raw value to preserve whitespace
				default:
					value = strings.TrimSpace(raw)
				}
				cmd, keepOpen := m.handleInputSubmit(value)
				if cmd != nil {
					cmds = append(cmds, cmd)
				}
				if !keepOpen {
					m.closeInput()
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
		if cmd := m.handleWorkspaceSelected(message.item); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case projectSelectedMsg:
		if cmd := m.handleProjectSelected(message.project); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case featureSelectedMsg:
		if cmd := m.handleFeatureSelected(message.feature); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case envFilesLoadedMsg:
		if cmd := m.handleEnvFilesLoaded(message); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case envFileSelectedMsg:
		m.handleEnvFileSelected(message)
	case itemSelectedMsg:
		if cmd := m.handleItemSelected(message); cmd != nil {
			cmds = append(cmds, cmd)
		}
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
	case reportsLoadedMsg:
		if cmd := m.handleReportsLoaded(message); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case reportsRowSelectedMsg:
		m.handleReportsRowSelected(message)
	case tokensLoadedMsg:
		if cmd := m.handleTokensLoaded(message); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case tokensRowSelectedMsg:
		m.handleTokensRowSelected(message.row)
	case tokensExportedMsg:
		m.handleTokensExported(message)
	}

	m.applyLayout()
	return m, tea.Batch(cmds...)
}

func (m *model) View() string {
	var builder strings.Builder

	helpWidth := m.width - 4
	if helpWidth < 0 {
		helpWidth = 0
	}
	m.help.Width = helpWidth

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

	if helpView := m.help.View(m.keys); helpView != "" {
		builder.WriteString(helpView)
		if !strings.HasSuffix(helpView, "\n") {
			builder.WriteRune('\n')
		}
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
		var contentBuilder strings.Builder
		contentBuilder.WriteString(m.styles.cmdPrompt.Render(m.inputPrompt))
		contentBuilder.WriteRune('\n')
		if m.filePickerEnabled {
			pickerView := m.filePicker.View()
			if pickerView != "" {
				contentBuilder.WriteString(pickerView)
				if !strings.HasSuffix(pickerView, "\n") {
					contentBuilder.WriteRune('\n')
				}
			}
			selected := strings.TrimSpace(m.filePicker.Path)
			if selected == "" {
				selected = strings.TrimSpace(m.filePicker.CurrentDirectory)
			}
			if trimmed := strings.TrimSpace(selected); trimmed != "" {
				contentBuilder.WriteString(m.styles.cmdHint.Render(abbreviatePath(trimmed)))
				contentBuilder.WriteRune('\n')
			}
			hintParts := []string{"enter select", "ctrl+t manual entry", "esc cancel"}
			contentBuilder.WriteString(m.styles.cmdHint.Render(strings.Join(hintParts, " • ")))
		} else if m.textAreaEnabled {
			areaWidth := overlayWidth - 4
			if areaWidth < 24 {
				areaWidth = overlayWidth - 2
			}
			if areaWidth < 24 {
				areaWidth = 24
			}
			m.inputArea.SetWidth(areaWidth)
			lineCount := strings.Count(m.inputArea.Value(), "\n") + 1
			areaHeight := lineCount + 1
			if areaHeight < 4 {
				areaHeight = 4
			}
			if areaHeight > 12 {
				areaHeight = 12
			}
			m.inputArea.SetHeight(areaHeight)
			contentBuilder.WriteString(m.inputArea.View())
			contentBuilder.WriteRune('\n')
			contentBuilder.WriteString(m.styles.cmdHint.Render("ctrl+enter save • esc cancel"))
		} else {
			contentBuilder.WriteString(m.inputField.View())
			if m.inputMode == inputCommandPalette && len(m.paletteMatches) > 0 {
				contentBuilder.WriteString("\n\n")
				contentBuilder.WriteString(m.renderPaletteMatches(overlayWidth))
			}
			var hintParts []string
			switch m.inputMode {
			case inputCommandPalette:
				hintParts = []string{"tab cycle", "enter run", "esc close", "←/→ page"}
			default:
				if m.inputMode == inputAddRoot || m.inputMode == inputAttachRFP {
					hintParts = append(hintParts, "ctrl+t file picker")
				}
				hintParts = append(hintParts, "enter confirm", "esc cancel")
			}
			contentBuilder.WriteRune('\n')
			contentBuilder.WriteString(m.styles.cmdHint.Render(strings.Join(hintParts, " • ")))
		}
		overlayContent := strings.TrimRight(contentBuilder.String(), "\n")
		overlay := m.styles.cmdOverlay.Width(overlayWidth).Render(overlayContent)
		builder.WriteString("\n")
		builder.WriteString(lipgloss.Place(m.width, m.height/2, lipgloss.Center, lipgloss.Center, overlay))
	}

	return m.styles.app.Render(builder.String())
}

func (m *model) handleGlobalKey(msg tea.KeyMsg) (bool, tea.Cmd) {
	if m.currentFeature == "settings" {
		if handled, cmd := m.handleSettingsKey(msg); handled {
			return true, cmd
		}
	}
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
	if m.currentFeature == "tokens" {
		switch msg.String() {
		case "-", "_":
			if cmd := m.adjustTokensRange(-1); cmd != nil {
				return true, cmd
			}
			return true, nil
		case "=", "+":
			if cmd := m.adjustTokensRange(1); cmd != nil {
				return true, cmd
			}
			return true, nil
		case "g", "G":
			if cmd := m.toggleTokensGroup(); cmd != nil {
				return true, cmd
			}
			return true, nil
		case "e", "E":
			if cmd := m.exportTokensCSV(); cmd != nil {
				return true, cmd
			}
			return true, nil
		}
	}
	if m.currentFeature == "reports" {
		switch msg.String() {
		case "o", "O":
			m.openSelectedReport()
			return true, nil
		case "e", "E":
			if cmd := m.exportSelectedReport(); cmd != nil {
				return true, cmd
			}
			return true, nil
		case "y":
			m.copySelectedReportPath()
			return true, nil
		case "Y":
			m.copySelectedReportSnippet()
			return true, nil
		}
	}
	switch {
	case msg.String() == "H":
		if m.scrollFocusedColumn(-horizontalScrollStep) {
			return true, nil
		}
	case msg.String() == "L":
		if m.scrollFocusedColumn(horizontalScrollStep) {
			return true, nil
		}
	case key.Matches(msg, m.keys.quit):
		return true, tea.Quit
	case key.Matches(msg, m.keys.nextFocus):
		m.focus = (m.focus + 1) % len(m.columns)
		return true, nil
	case key.Matches(msg, m.keys.prevFocus):
		m.focus = (m.focus - 1 + len(m.columns)) % len(m.columns)
		return true, nil
	case key.Matches(msg, m.keys.nextFeature):
		if cmd := m.cycleFeature(1); cmd != nil {
			return true, cmd
		}
		return true, nil
	case key.Matches(msg, m.keys.prevFeature):
		if cmd := m.cycleFeature(-1); cmd != nil {
			return true, cmd
		}
		return true, nil
	case key.Matches(msg, m.keys.toggleLogs):
		m.showLogs = !m.showLogs
		m.applyLayout()
		return true, nil
	case key.Matches(msg, m.keys.cancelJob):
		cmd := m.cancelActiveJob()
		return true, cmd
	case key.Matches(msg, m.keys.toggleHelp):
		m.help.ShowAll = !m.help.ShowAll
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

	if m.currentFeature == "env" && m.usingEnvLayout {
		switch strings.ToLower(msg.String()) {
		case "ctrl+s":
			m.saveCurrentEnvFile()
			return true, nil
		case "n":
			m.promptEnvNewEntry()
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
			if m.currentFeature == "docs" {
				if handled, cmd := m.handleDocsPreviewEnter(); handled {
					return true, cmd
				}
			}
			if m.currentFeature == "reports" {
				m.openSelectedReport()
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

func (m *model) scrollFocusedColumn(delta int) bool {
	if delta == 0 || m.focus < 0 || m.focus >= len(m.columns) {
		return false
	}
	col := m.columns[m.focus]
	if col == nil {
		return false
	}
	if col.ScrollHorizontal(delta) {
		m.columns[m.focus] = col
		return true
	}
	return false
}

func (m *model) applyMarkdownTheme(theme markdownTheme, announce bool) {
	setMarkdownTheme(theme)
	m.markdownTheme = theme
	if m.previewCol != nil {
		m.previewCol.Refresh()
	}
	m.refreshCommandCatalog()
	if announce {
		message := fmt.Sprintf("Markdown theme: %s", markdownThemeLabel(theme))
		m.appendLog(message)
		m.setToast(message, 3*time.Second)
	}
}

func (m *model) toggleMarkdownTheme() {
	m.cycleThemeSetting(1)
}

func (m *model) stepBack() {
	if m.currentFeature == "env" && m.usingEnvLayout {
		switch focusArea(m.focus) {
		case focusPreview:
			m.focus = int(focusItems)
			return
		case focusItems:
			m.focus = int(focusFeatures)
			return
		case focusFeatures:
			m.exitEnvEditor()
			m.currentFeature = ""
			m.itemsCol.SetItems(nil)
			m.previewCol.SetContent("Select an item to preview details.\n")
			m.focus = int(focusFeatures)
			return
		}
	}
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

func (m *model) handleWorkspaceSelected(item workspaceItem) tea.Cmd {
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
		cmd := m.openPathPicker("Add workspace root", "", inputAddRoot, true, false)
		m.inputField.Placeholder = "~/projects"
		return cmd
	}
	return nil
}

func (m *model) handleProjectSelected(project *discoveredProject) tea.Cmd {
	if project == nil {
		return nil
	}
	if m.usingEnvLayout {
		m.exitEnvEditor()
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
	m.envOpenTelemetrySent = false
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
	if feature.Key != "env" && m.usingEnvLayout {
		m.exitEnvEditor()
	}
	if feature.Key != "tokens" && m.usingTokensLayout {
		m.exitTokensView()
	}
	if feature.Key != "reports" && m.usingReportsLayout {
		m.exitReportsView()
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
	if feature.Key != "tasks" {
		m.hideSpinner()
	}
	if feature.Key == "env" {
		return m.startEnvEditor()
	}
	if feature.Key == "tasks" {
		m.useTasksLayout(true)
		m.backlogScope = backlogNode{}
		m.previewCol.SetContent("Loading backlog…\n")
		m.updateCredentialHint()
		m.focus = int(focusFeatures)
		m.backlogLoading = true
		m.showSpinner("Loading backlog…")
		return m.loadBacklogCmd()
	}
	m.useTasksLayout(false)
	if feature.Key == "tokens" {
		m.useArtifactsLayout(false)
		m.useServicesLayout(false)
		m.useEnvLayout(false)
		m.useTokensLayout(true)
		if len(tokensRangeOptions) == 0 {
			m.tokensRangeIndex = 0
		} else {
			if m.tokensRangeIndex < 0 {
				m.tokensRangeIndex = 0
			}
			if m.tokensRangeIndex >= len(tokensRangeOptions) {
				m.tokensRangeIndex = len(tokensRangeOptions) - 1
			}
		}
		m.tokensLoading = true
		m.tokensError = nil
		m.tokensUsage = nil
		m.tokensTelemetrySent = false
		m.tokensCol.SetPlaceholder("Loading token usage…")
		m.previewCol.SetContent("Loading token usage…\n")
		m.focus = int(focusItems)
		return m.loadTokensUsageCmd()
	}
	if feature.Key == "artifacts" {
		m.useServicesLayout(false)
		m.useEnvLayout(false)
		m.useArtifactsLayout(true)
		cmd := m.prepareArtifactsView()
		m.focus = int(focusFeatures)
		return cmd
	}
	if feature.Key == "services" {
		m.useEnvLayout(false)
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
	if feature.Key == "reports" {
		m.useEnvLayout(false)
		m.useServicesLayout(false)
		m.useArtifactsLayout(false)
		m.useTokensLayout(false)
		m.useReportsLayout(true)
		m.reportsLoading = true
		m.reportsError = nil
		m.reportEntries = nil
		m.reportsTelemetrySent = false
		m.reportsCol.SetPlaceholder("Loading reports…")
		m.previewCol.SetContent("Loading reports…\n")
		m.focus = int(focusItems)
		return m.loadReportsEntriesCmd()
	}
	if feature.Key == "settings" {
		m.useEnvLayout(false)
		m.useServicesLayout(false)
		m.useArtifactsLayout(false)
		m.useTokensLayout(false)
		m.useReportsLayout(false)
		m.refreshSettingsItems()
		m.focus = int(focusItems)
		return nil
	}
	m.useEnvLayout(false)
	m.useServicesLayout(false)
	m.useArtifactsLayout(false)
	m.useTokensLayout(false)
	m.useReportsLayout(false)
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
	var followCmds []tea.Cmd
	if item, ok := m.itemsCol.SelectedItem(); ok {
		if feature.Key == "overview" {
			m.suppressPipelineTelemetry = true
		}
		if cmd := m.applyItemSelection(m.currentProject, feature.Key, item, false); cmd != nil {
			followCmds = append(followCmds, cmd)
		}
	} else {
		m.previewCol.SetContent("Select an item to preview details.\n")
	}
	m.focus = int(focusItems)
	if len(followCmds) > 0 {
		return tea.Batch(followCmds...)
	}
	return nil
}

func (m *model) cycleFeature(delta int) tea.Cmd {
	if delta == 0 || m.featureCol == nil {
		return nil
	}
	items := m.featureCol.model.Items()
	length := len(items)
	if length == 0 {
		return nil
	}

	index := m.featureCol.model.Index()
	for i := 0; i < length; i++ {
		index = (index + delta + length) % length
		entry, ok := items[index].(listEntry)
		if !ok {
			continue
		}
		def, ok := entry.payload.(featureDefinition)
		if !ok || def.Key == "" {
			continue
		}
		m.featureCol.model.Select(index)
		return m.handleFeatureSelected(def)
	}

	if entry, ok := items[m.featureCol.model.Index()].(listEntry); ok {
		if def, ok := entry.payload.(featureDefinition); ok && def.Key != "" {
			return m.handleFeatureSelected(def)
		}
	}
	return nil
}

func (m *model) handleItemSelected(msg itemSelectedMsg) tea.Cmd {
	targetProject := msg.project
	if targetProject == nil {
		targetProject = m.currentProject
	}
	featureKey := msg.feature.Key
	if featureKey == "" {
		featureKey = m.currentFeature
	}
	if featureKey == "settings" {
		return m.handleSettingsSelection(msg.item, msg.activate)
	}
	if targetProject == nil {
		return nil
	}
	cmd := m.applyItemSelection(targetProject, featureKey, msg.item, msg.activate)
	if msg.activate {
		m.focus = int(focusPreview)
	}
	return cmd
}

func (m *model) applyItemSelection(project *discoveredProject, featureKey string, item featureItemDefinition, activate bool) tea.Cmd {
	if project == nil {
		return nil
	}
	m.currentItem = item
	m.currentFeature = featureKey
	m.currentProject = project
	var followCmds []tea.Cmd
	if featureKey == "docs" {
		if cmd := m.handleDocItemSelection(item, activate); cmd != nil {
			followCmds = append(followCmds, cmd)
		}
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
	if len(followCmds) > 0 {
		return tea.Batch(followCmds...)
	}
	return nil
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
	var cmds []tea.Cmd
	var followCmd tea.Cmd
	var reason string

	switch message := msg.(type) {
	case jobStartedMsg:
		status := m.ensureJobStatus(message.ID, message.Title)
		status.Status = "Running"
		status.Started = time.Now()
		status.Ended = time.Time{}
		status.Err = ""
		status.CancelRequested = false
		m.jobRunningCount++
		if m.jobRunningCount == 1 {
			if timingCmd := m.beginJobTiming(message.Title); timingCmd != nil {
				cmds = append(cmds, timingCmd)
			}
		}
		m.appendLog(fmt.Sprintf("[job] %s started", message.Title))
		m.emitTelemetry("job_started", map[string]string{
			"job_id": strconv.Itoa(message.ID),
			"title":  message.Title,
		})
		m.refreshLogs()
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

	case jobCancelledMsg:
		status := m.ensureJobStatus(message.ID, message.Title)
		status.Status = "Cancelled"
		status.CancelRequested = true
		status.Ended = time.Now()
		status.Err = "cancelled"
		m.appendLog(fmt.Sprintf("[job] %s cancelled", status.Title))
		m.setToast(fmt.Sprintf("%s cancelled", status.Title), 5*time.Second)
		m.emitTelemetry("job_stopped", map[string]string{
			"job_id": strconv.Itoa(message.ID),
			"title":  status.Title,
			"status": "cancelled",
		})
		m.refreshLogs()
		delete(m.jobProjectPaths, message.Title)
		m.refreshCreateProjectProgress(message.Title)

	case jobFinishedMsg:
		status := m.ensureJobStatus(message.ID, message.Title)
		if m.jobRunningCount > 0 {
			m.jobRunningCount--
		}
		if m.jobRunningCount == 0 {
			if timingCmd := m.stopJobTiming(); timingCmd != nil {
				cmds = append(cmds, timingCmd)
			}
		}
		status.Ended = time.Now()
		duration := time.Duration(0)
		if !status.Started.IsZero() {
			duration = status.Ended.Sub(status.Started)
		}
		fields := map[string]string{
			"job_id": strconv.Itoa(message.ID),
			"title":  status.Title,
		}
		if duration > 0 {
			fields["duration_ms"] = strconv.FormatInt(duration.Milliseconds(), 10)
		}
		elapsed := m.jobLastDuration
		if message.Err != nil {
			errText := message.Err.Error()
			status.Err = errText
			cancelled := status.CancelRequested || isInterruptError(message.Err)
			if cancelled {
				status.Status = "Cancelled"
				fields["status"] = "cancelled"
				m.appendLog(fmt.Sprintf("[job] %s cancelled", message.Title))
				m.setToast(fmt.Sprintf("%s cancelled", message.Title), 5*time.Second)
				m.emitTelemetry("job_stopped", fields)
			} else {
				status.Status = "Failed"
				fields["status"] = "failed"
				fields["error"] = errText
				m.appendLog(fmt.Sprintf("[job] %s failed: %v", message.Title, message.Err))
				if elapsed > 0 {
					m.setToast(fmt.Sprintf("%s failed after %s", message.Title, formatElapsed(elapsed)), 6*time.Second)
				} else {
					m.setToast(fmt.Sprintf("%s failed", message.Title), 6*time.Second)
				}
				m.emitTelemetry("job_failed", fields)
			}
		} else {
			status.Status = "Succeeded"
			status.Err = ""
			fields["status"] = "succeeded"
			m.appendLog(fmt.Sprintf("[job] %s completed successfully", message.Title))
			if elapsed > 0 {
				m.setToast(fmt.Sprintf("%s completed in %s", message.Title, formatElapsed(elapsed)), 6*time.Second)
			} else {
				m.setToast(fmt.Sprintf("%s completed", message.Title), 6*time.Second)
			}
			m.emitTelemetry("job_stopped", fields)

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
			case strings.Contains(lower, "run up"):
				reason = "run-up"
			case strings.Contains(lower, "run open"):
				reason = "run-open"
			case strings.Contains(lower, "verify acceptance"), strings.Contains(lower, "verify all"):
				reason = "verify"
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
				label := "Refreshing backlog…"
				if reason != "" {
					label = fmt.Sprintf("Refreshing backlog (%s)…", strings.ReplaceAll(reason, "-", " "))
				}
				m.showSpinner(label)
				followCmd = m.loadBacklogCmd()
			}
		}
		delete(m.jobProjectPaths, message.Title)
		m.refreshCreateProjectProgress(message.Title)

	case jobChannelClosedMsg:
		// handled via other cases
	}

	var runnerCmd tea.Cmd
	if m.jobRunner != nil {
		runnerCmd = m.jobRunner.Handle(msg)
	}
	if followCmd != nil {
		cmds = append(cmds, followCmd)
	}
	if runnerCmd != nil {
		cmds = append(cmds, runnerCmd)
	}

	switch reason {
	case "create-jira-tasks", "migrate-tasks", "refine-tasks", "create-tasks", "work-on-tasks":
		m.refreshBacklog()
	case "run-up", "run-open":
		m.refreshServices()
	case "verify":
		m.refreshVerifySummary()
	}

	m.pruneJobHistory()
	m.refreshLogs()

	switch len(cmds) {
	case 0:
		return nil
	case 1:
		return cmds[0]
	default:
		return tea.Batch(cmds...)
	}
}

func (m *model) beginJobTiming(title string) tea.Cmd {
	m.jobTimingTitle = title
	m.jobTimingActive = true
	m.jobLastDuration = 0
	return tea.Batch(m.jobStopwatch.Reset(), m.jobStopwatch.Start())
}

func (m *model) stopJobTiming() tea.Cmd {
	if !m.jobTimingActive {
		return nil
	}
	m.jobTimingActive = false
	m.jobLastDuration = m.jobStopwatch.Elapsed()
	m.jobTimingTitle = ""
	return m.jobStopwatch.Stop()
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
	allowEmpty := m.inputMode == inputEnvEditValue || m.inputMode == inputEnvNewValue
	if value == "" && !allowEmpty {
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
	case inputEnvEditValue:
		m.applyEnvValueEdit(value)
		return nil, false
	case inputEnvNewKey:
		key := strings.TrimSpace(value)
		if key == "" {
			m.setToast("Key required", 4*time.Second)
			return nil, true
		}
		m.pendingEnvKey = key
		m.openTextarea(fmt.Sprintf("Value for %s", key), "", inputEnvNewValue)
		return nil, true
	case inputEnvNewValue:
		if m.applyEnvNewValue(value) {
			return nil, false
		}
		return nil, true
	case inputSettingsWorkspaceAdd:
		path := m.resolvePath(value)
		if m.addCustomWorkspaceRoot(path) {
			return nil, false
		}
		return nil, true
	case inputSettingsWorkspaceRemove:
		trimmed := strings.TrimSpace(value)
		if trimmed == "" {
			return nil, true
		}
		candidate := trimmed
		if idx, err := strconv.Atoi(trimmed); err == nil {
			idx = idx - 1
			if idx >= 0 && idx < len(m.customWorkspaceRoots) {
				candidate = m.customWorkspaceRoots[idx]
			}
		}
		cleanCandidate := filepath.Clean(strings.TrimSpace(candidate))
		resolved := ""
		for _, root := range m.customWorkspaceRoots {
			if filepath.Clean(root) == cleanCandidate {
				resolved = root
				break
			}
		}
		if resolved == "" {
			resolved = m.resolvePath(candidate)
		}
		if m.removeCustomWorkspaceRoot(resolved) {
			return nil, false
		}
		m.setToast("Workspace root not found", 4*time.Second)
		return nil, true
	case inputSettingsDockerPath:
		trimmed := strings.TrimSpace(value)
		if trimmed == "" {
			m.clearDockerPath()
			return nil, false
		}
		resolved := trimmed
		if !filepath.IsAbs(resolved) {
			resolved = m.resolvePath(resolved)
		}
		m.setDockerPath(resolved)
		return nil, false
	case inputSettingsConcurrency:
		trimmed := strings.TrimSpace(value)
		n, err := strconv.Atoi(trimmed)
		if err != nil || n < 1 {
			m.setToast("Enter a positive number", 4*time.Second)
			return nil, true
		}
		if n > 32 {
			n = 32
		}
		cmd := m.setConcurrency(n)
		return cmd, false
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
	m.filePickerEnabled = false
	m.textAreaEnabled = false
	m.inputField.SetValue(placeholder)
	m.inputField.CursorEnd()
	m.inputField.Focus()
}

func (m *model) openTextarea(prompt, initial string, mode inputMode) {
	m.inputMode = mode
	m.inputPrompt = prompt
	m.inputActive = true
	m.filePickerEnabled = false
	m.textAreaEnabled = true
	m.inputField.Blur()
	m.inputArea.SetValue(initial)
	m.inputArea.CursorEnd()
	m.inputArea.Focus()
}

func (m *model) openPathPicker(prompt, initial string, mode inputMode, allowDirs, allowFiles bool) tea.Cmd {
	m.inputMode = mode
	m.inputPrompt = prompt
	m.inputActive = true
	m.filePickerAllowDirs = allowDirs
	m.filePickerAllowFiles = allowFiles
	m.filePickerEnabled = true
	m.textAreaEnabled = false
	initial = strings.TrimSpace(initial)
	m.inputField.SetValue(initial)
	m.inputField.Blur()
	return m.setupFilePicker(initial)
}

func (m *model) setupFilePicker(initial string) tea.Cmd {
	fp := filepicker.New()
	fp.DirAllowed = m.filePickerAllowDirs
	fp.FileAllowed = m.filePickerAllowFiles
	fp.ShowHidden = false
	fp.AutoHeight = false
	height := 12
	if m.height > 0 {
		maxHeight := m.height - 6
		if maxHeight < 8 {
			maxHeight = 8
		}
		height = min(maxHeight, 18)
	}
	fp.Height = height
	dir, suggestion := m.resolvePickerStart(initial)
	fp.CurrentDirectory = dir
	if m.filePickerAllowFiles && suggestion != "" {
		fp.Path = suggestion
	}
	m.filePicker = fp
	return m.filePicker.Init()
}

func (m *model) resolvePickerStart(initial string) (string, string) {
	path := strings.TrimSpace(initial)
	if path != "" {
		resolved := m.resolvePath(path)
		if info, err := os.Stat(resolved); err == nil {
			if info.IsDir() {
				return resolved, ""
			}
			return filepath.Dir(resolved), resolved
		}
		parent := filepath.Dir(resolved)
		if parent != "" && parent != "." && dirExists(parent) {
			return parent, ""
		}
	}
	if m.currentRoot != nil && dirExists(m.currentRoot.Path) {
		return m.currentRoot.Path, ""
	}
	if home, err := os.UserHomeDir(); err == nil {
		return home, ""
	}
	if cwd, err := os.Getwd(); err == nil {
		return cwd, ""
	}
	return ".", ""
}

func (m *model) toggleFilePickerMode() tea.Cmd {
	if m.filePickerEnabled {
		selected := strings.TrimSpace(m.filePicker.Path)
		if selected == "" {
			selected = strings.TrimSpace(m.filePicker.CurrentDirectory)
		}
		m.filePickerEnabled = false
		m.inputField.SetValue(selected)
		m.inputField.CursorEnd()
		m.inputField.Focus()
		return nil
	}
	m.filePickerEnabled = true
	m.inputField.Blur()
	return m.setupFilePicker(m.inputField.Value())
}

func (m *model) closeInput() {
	prevMode := m.inputMode
	m.filePickerEnabled = false
	m.textAreaEnabled = false
	if prevMode == inputCommandPalette {
		m.paletteMatches = nil
		m.paletteIndex = 0
		m.palettePaginator.Page = 0
		m.palettePaginator.TotalPages = 1
	}
	m.inputActive = false
	m.inputField.Blur()
	m.inputField.SetValue("")
	m.inputField.Placeholder = ""
	m.inputArea.Blur()
	m.inputArea.Reset()
	m.inputMode = inputNone
	if prevMode == inputNewProjectPath || prevMode == inputNewProjectTemplate || prevMode == inputNewProjectConfirm {
		m.pendingNewProjectPath = ""
		m.pendingNewProjectTemplate = ""
	}
	if prevMode == inputEnvEditValue {
		m.envEditingFile = nil
		m.envEditingEntry = envEntry{}
	}
	if prevMode == inputEnvNewKey || prevMode == inputEnvNewValue {
		m.pendingEnvKey = ""
	}
}

func (m *model) openCommandPalette() {
	m.refreshCommandCatalog()
	m.inputMode = inputCommandPalette
	m.inputPrompt = "Command"
	m.inputActive = true
	m.filePickerEnabled = false
	m.textAreaEnabled = false
	m.inputField.Placeholder = "e.g. run up"
	m.inputField.SetValue("")
	m.inputField.Focus()
	m.paletteIndex = 0
	m.updatePaletteMatches("")
	m.emitTelemetry("palette_opened", map[string]string{})
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
	if strings.TrimSpace(m.settingsDockerPath) != "" {
		req.env = append(req.env, "GC_DOCKER_BIN="+strings.TrimSpace(m.settingsDockerPath))
	}
	if m.settingsConcurrency > 0 {
		req.env = append(req.env, fmt.Sprintf("GC_MAX_CONCURRENCY=%d", m.settingsConcurrency))
	}
	if m.jobRunner == nil {
		m.jobRunner = newJobManager()
	}
	var concurrencyCmd tea.Cmd
	if m.settingsConcurrency > 0 {
		concurrencyCmd = m.jobRunner.SetMaxParallel(m.settingsConcurrency)
	}
	id, cmd := m.jobRunner.Enqueue(req)
	if concurrencyCmd != nil {
		if cmd != nil {
			cmd = tea.Batch(concurrencyCmd, cmd)
		} else {
			cmd = concurrencyCmd
		}
	}
	status := m.ensureJobStatus(id, req.title)
	status.Status = "Queued"
	status.Started = time.Time{}
	status.Ended = time.Time{}
	status.Err = ""
	status.CancelRequested = false
	m.refreshLogs()
	return cmd
}

func (m *model) ensureJobStatus(id int, title string) *jobStatus {
	if m.jobStatuses == nil {
		m.jobStatuses = make(map[int]*jobStatus)
	}
	status, ok := m.jobStatuses[id]
	if !ok {
		status = &jobStatus{ID: id, Title: title, Status: "Queued"}
		m.jobStatuses[id] = status
		m.jobOrder = append(m.jobOrder, id)
		m.pruneJobHistory()
	} else if title != "" && status.Title == "" {
		status.Title = title
	}
	return status
}

func (m *model) pruneJobHistory() {
	const maxJobs = 12
	if len(m.jobOrder) <= maxJobs {
		return
	}
	for len(m.jobOrder) > maxJobs {
		removable := -1
		for idx, id := range m.jobOrder {
			status := m.jobStatuses[id]
			if status == nil {
				removable = idx
				break
			}
			switch status.Status {
			case "Running", "Queued", "Cancelling":
				continue
			default:
				removable = idx
				break
			}
		}
		if removable == -1 {
			break
		}
		id := m.jobOrder[removable]
		m.jobOrder = append(m.jobOrder[:removable], m.jobOrder[removable+1:]...)
		delete(m.jobStatuses, id)
	}
}

func jobStatusIcon(status string) string {
	switch strings.ToLower(status) {
	case "running", "cancelling":
		return "▶"
	case "queued":
		return "…"
	case "succeeded":
		return "✓"
	case "failed":
		return "✗"
	case "cancelled":
		return "⚑"
	default:
		return "•"
	}
}

func (m *model) renderJobQueue() string {
	header := fmt.Sprintf("Jobs (Ctrl+K cancel running) — %d slot(s)", max(1, m.settingsConcurrency))
	if len(m.jobOrder) == 0 {
		return header + "\n  (no jobs)"
	}
	var lines []string
	lines = append(lines, header)
	for _, id := range m.jobOrder {
		status := m.jobStatuses[id]
		if status == nil {
			continue
		}
		label := status.Title
		if strings.TrimSpace(label) == "" {
			label = fmt.Sprintf("job-%d", id)
		}
		detail := status.Status
		switch status.Status {
		case "Running", "Cancelling":
			if !status.Started.IsZero() {
				detail = fmt.Sprintf("%s for %s", status.Status, formatElapsed(time.Since(status.Started)))
			}
		case "Queued":
			if status.CancelRequested {
				detail = "Queued (cancel pending)"
			}
		case "Succeeded", "Failed", "Cancelled":
			if !status.Ended.IsZero() {
				detail = fmt.Sprintf("%s %s ago", status.Status, formatRelativeTime(status.Ended))
			}
		}
		lines = append(lines, fmt.Sprintf("%s %s — %s", jobStatusIcon(status.Status), label, detail))
	}
	return strings.Join(lines, "\n")
}

func (m *model) cancelActiveJob() tea.Cmd {
	if m.jobRunner == nil {
		m.setToast("No jobs to cancel", 4*time.Second)
		return nil
	}
	var target *jobStatus
	for _, id := range m.jobOrder {
		status := m.jobStatuses[id]
		if status == nil {
			continue
		}
		if status.Status == "Running" || status.Status == "Cancelling" {
			target = status
			break
		}
	}
	if target == nil {
		for _, id := range m.jobOrder {
			status := m.jobStatuses[id]
			if status == nil {
				continue
			}
			if status.Status == "Queued" {
				target = status
				break
			}
		}
	}
	if target == nil {
		m.setToast("No jobs to cancel", 4*time.Second)
		return nil
	}
	target.CancelRequested = true
	if target.Status == "Running" {
		target.Status = "Cancelling"
	}
	m.refreshLogs()
	ok, cmd := m.jobRunner.Cancel(target.ID)
	if !ok {
		target.CancelRequested = false
		if target.Status == "Cancelling" {
			target.Status = "Running"
		}
		m.refreshLogs()
		m.setToast("Unable to cancel job", 4*time.Second)
		return nil
	}
	if target.Status == "Queued" {
		target.Status = "Cancelled"
		target.Ended = time.Now()
		m.refreshLogs()
	}
	toast := fmt.Sprintf("Cancelling %s", target.Title)
	if target.Status == "Cancelled" {
		toast = fmt.Sprintf("Cancelled %s", target.Title)
	}
	m.setToast(toast, 4*time.Second)
	return cmd
}

func isInterruptError(err error) bool {
	if err == nil {
		return false
	}
	text := strings.ToLower(err.Error())
	return strings.Contains(text, "signal: interrupt") || strings.Contains(text, "interrupted") || strings.Contains(text, "canceled") || strings.Contains(text, "cancelled")
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
	entries := make([]paletteEntry, 0, len(seen)+4)
	for _, entry := range seen {
		entries = append(entries, entry)
	}
	currentTheme := m.markdownTheme
	entries = append(entries,
		paletteEntry{
			label:       "Markdown Theme: Auto",
			description: themePaletteDescription(markdownThemeAuto, currentTheme),
			meta: map[string]string{
				"action": "set-markdown-theme",
				"theme":  markdownThemeAuto.String(),
			},
		},
		paletteEntry{
			label:       "Markdown Theme: Dark",
			description: themePaletteDescription(markdownThemeDark, currentTheme),
			meta: map[string]string{
				"action": "set-markdown-theme",
				"theme":  markdownThemeDark.String(),
			},
		},
		paletteEntry{
			label:       "Markdown Theme: Light",
			description: themePaletteDescription(markdownThemeLight, currentTheme),
			meta: map[string]string{
				"action": "set-markdown-theme",
				"theme":  markdownThemeLight.String(),
			},
		},
		paletteEntry{
			label:       "Markdown Theme: Toggle",
			description: fmt.Sprintf("Cycle Markdown theme (current: %s)", markdownThemeLabel(currentTheme)),
			meta: map[string]string{
				"action": "toggle-markdown-theme",
			},
		},
	)
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].label < entries[j].label
	})
	m.commandEntries = entries
	m.updatePaletteMatches(m.inputField.Value())
}

func themePaletteDescription(theme, current markdownTheme) string {
	suffix := ""
	if theme == current {
		suffix = " (current)"
	}
	return fmt.Sprintf("Use %s theme%s", markdownThemeLabel(theme), suffix)
}

func (m *model) updatePaletteMatches(query string) {
	q := strings.ToLower(strings.TrimSpace(query))
	if len(m.commandEntries) == 0 {
		m.paletteMatches = nil
		m.paletteIndex = 0
		m.palettePaginator.Page = 0
		m.configurePalettePaginator()
		return
	}
	if q == "" {
		m.paletteMatches = append([]paletteEntry(nil), m.commandEntries...)
		m.paletteIndex = 0
		m.palettePaginator.Page = 0
		m.configurePalettePaginator()
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
	}
	if len(m.paletteMatches) == 0 {
		m.paletteIndex = 0
	}
	m.palettePaginator.Page = 0
	m.configurePalettePaginator()
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
		m.palettePaginator.Page = 0
		m.configurePalettePaginator()
		return
	}
	count := len(m.paletteMatches)
	m.paletteIndex = (m.paletteIndex + delta + count) % count
	perPage := m.palettePaginator.PerPage
	if perPage <= 0 {
		perPage = count
	}
	m.palettePaginator.Page = m.paletteIndex / perPage
	m.configurePalettePaginator()
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

func (m *model) configurePalettePaginator() {
	if m.palettePaginator.PerPage <= 0 {
		m.palettePaginator.PerPage = 6
	}
	total := len(m.paletteMatches)
	if total == 0 {
		m.palettePaginator.TotalPages = 1
		m.palettePaginator.Page = 0
		m.paletteIndex = 0
		return
	}
	totalPages := total / m.palettePaginator.PerPage
	if total%m.palettePaginator.PerPage != 0 {
		totalPages++
	}
	if totalPages < 1 {
		totalPages = 1
	}
	m.palettePaginator.TotalPages = totalPages
	if m.palettePaginator.Page >= totalPages {
		m.palettePaginator.Page = totalPages - 1
	}
	if m.palettePaginator.Page < 0 {
		m.palettePaginator.Page = 0
	}
	if m.paletteIndex >= total {
		m.paletteIndex = total - 1
	}
	if m.paletteIndex < 0 {
		m.paletteIndex = 0
	}
	start := m.palettePaginator.Page * m.palettePaginator.PerPage
	if start >= total {
		start = (totalPages - 1) * m.palettePaginator.PerPage
		if start < 0 {
			start = 0
		}
		m.palettePaginator.Page = totalPages - 1
	}
	end := start + m.palettePaginator.PerPage
	if end > total {
		end = total
	}
	if end <= start {
		end = start + 1
		if end > total {
			end = total
		}
	}
	if m.paletteIndex < start {
		m.paletteIndex = start
	}
	if m.paletteIndex >= end {
		m.paletteIndex = end - 1
	}
	if m.paletteIndex < 0 {
		m.paletteIndex = 0
	}
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
	if len(entry.command) == 0 {
		if entry.meta != nil {
			switch entry.meta["action"] {
			case "toggle-markdown-theme":
				m.cycleThemeSetting(1)
			case "set-markdown-theme":
				m.setThemeSetting(markdownThemeFromString(entry.meta["theme"]))
			}
		}
		return nil
	}
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
	if width < 10 {
		width = 10
	}
	start, end := m.palettePaginator.GetSliceBounds(len(m.paletteMatches))
	if start < 0 {
		start = 0
	}
	if end > len(m.paletteMatches) {
		end = len(m.paletteMatches)
	}
	if start >= end {
		start = 0
		if m.palettePaginator.PerPage > 0 {
			end = min(len(m.paletteMatches), start+m.palettePaginator.PerPage)
		} else {
			end = len(m.paletteMatches)
		}
	}
	headerParts := []string{"↑/↓ select", "Enter run", "Esc cancel"}
	if m.palettePaginator.TotalPages > 1 {
		headerParts = append(headerParts, fmt.Sprintf("←/→ page %s", m.palettePaginator.View()))
	}
	header := m.styles.statusHint.Render(strings.Join(headerParts, " • "))
	var lines []string
	lines = append(lines, header)
	for i := start; i < end; i++ {
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
			style = style.Faint(true)
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

func (m *model) handleDocItemSelection(item featureItemDefinition, activate bool) tea.Cmd {
	if item.Meta == nil {
		m.resetDocSelection()
		return nil
	}
	docRel := strings.TrimSpace(item.Meta["docRelPath"])
	if docRel == "" {
		docRel = strings.TrimSpace(item.Meta["docDiffHead"])
	}
	m.currentDocRelPath = docRel
	m.currentDocDiffBase = strings.TrimSpace(item.Meta["docDiffBase"])
	m.currentDocType = strings.TrimSpace(item.Meta["docType"])
	var cmd tea.Cmd
	if activate && item.Meta["docsAction"] == "attach-rfp" {
		cmd = m.startAttachRFP()
	}
	m.recordDocPreviewTelemetry(item)
	return cmd
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
	if m.servicesPolling && m.servicesTimerActive {
		return nil
	}
	m.servicesPolling = true
	m.servicesTimer = timer.NewWithInterval(servicesPollInterval, time.Second)
	m.servicesTimerActive = true
	return m.servicesTimer.Init()
}

func (m *model) stopServicePolling() {
	m.servicesPolling = false
	m.servicesTimerActive = false
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

func (m *model) handleDocsPreviewEnter() (bool, tea.Cmd) {
	if m.currentItem.Meta == nil {
		return false, nil
	}
	switch m.currentItem.Meta["docsAction"] {
	case "attach-rfp":
		return true, m.startAttachRFP()
	}
	return false, nil
}

func (m *model) startAttachRFP() tea.Cmd {
	if m.currentProject == nil {
		m.appendLog("Select a project before attaching artifacts.")
		m.setToast("Select a project first", 5*time.Second)
		return nil
	}
	cmd := m.openPathPicker("Attach RFP file", "", inputAttachRFP, false, true)
	m.inputField.Placeholder = "~/path/to/rfp.md"
	m.appendLog("Attach RFP: Pick or enter a file to copy into .gpt-creator/staging/inputs/.")
	m.setToast("Choose an RFP file", 5*time.Second)
	return cmd
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
	m.writeUIConfig()
}

func (m *model) writeUIConfig() {
	if m.uiConfig == nil {
		m.uiConfig = &uiConfig{}
	}
	m.uiConfig.Pinned = sortedPaths(m.pinnedPaths)
	m.uiConfig.Theme = m.markdownTheme.String()
	m.uiConfig.Concurrency = m.settingsConcurrency
	m.uiConfig.DockerPath = strings.TrimSpace(m.settingsDockerPath)
	m.uiConfig.WorkspaceRoots = append([]string{}, m.customWorkspaceRoots...)
	if m.uiConfigPath == "" {
		_, m.uiConfigPath = loadUIConfig()
	}
	if err := saveUIConfig(m.uiConfig, m.uiConfigPath); err != nil {
		m.appendLog(fmt.Sprintf("Failed to persist settings: %v", err))
	}
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
	var parts []string
	if queue := strings.TrimSpace(m.renderJobQueue()); queue != "" {
		parts = append(parts, queue)
	}
	if len(m.logLines) > 0 {
		parts = append(parts, strings.Join(m.logLines, "\n"))
	}
	content := strings.Join(parts, "\n\n")
	m.logs.SetContent(content)
}

func (m *model) showSpinner(message string) {
	m.spinnerActive = true
	m.spinnerMessage = strings.TrimSpace(message)
}

func (m *model) hideSpinner() {
	m.spinnerActive = false
	m.spinnerMessage = ""
}

func (m *model) applyLayout() {
	if m.width == 0 || m.height == 0 {
		return
	}

	topChrome := 1
	bottomChrome := 1

	helpWidth := m.width - 4
	if helpWidth < 0 {
		helpWidth = 0
	}
	m.help.Width = helpWidth
	helpView := ""
	if m.width > 0 {
		helpView = m.help.View(m.keys)
	}
	if helpView != "" {
		bottomChrome += lipgloss.Height(helpView)
	}

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

	widths := []int{44, 52, 52, 28}
	if m.usingTasksLayout {
		widths = []int{44, 52, 64, 36}
	} else if m.usingServicesLayout {
		widths = []int{44, 52, 48, 44}
	} else if m.usingArtifactsLayout {
		widths = []int{44, 52, 52, 36}
	} else if m.usingReportsLayout {
		widths = []int{44, 52, 60, 36}
	} else if m.usingTokensLayout {
		widths = []int{44, 52, 60, 40}
	} else if m.usingEnvLayout {
		widths = []int{44, 52, 56, 42}
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

func (m *model) useTokensLayout(enable bool) {
	if enable {
		if m.usingTokensLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.featureCol,
			m.tokensCol,
			m.previewCol,
		}
		m.usingTokensLayout = true
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	} else {
		if !m.usingTokensLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.featureCol,
			m.itemsCol,
			m.previewCol,
		}
		m.usingTokensLayout = false
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	}
	m.applyLayout()
}

func (m *model) useReportsLayout(enable bool) {
	if enable {
		if m.usingReportsLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.featureCol,
			m.reportsCol,
			m.previewCol,
		}
		m.usingReportsLayout = true
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	} else {
		if !m.usingReportsLayout {
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
		m.usingReportsLayout = false
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

func (m *model) useEnvLayout(enable bool) {
	if enable {
		if m.usingEnvLayout {
			return
		}
		m.columns = []column{
			m.workspaceCol,
			m.projectsCol,
			m.featureCol,
			m.envTableCol,
			m.previewCol,
		}
		m.usingEnvLayout = true
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	} else {
		if !m.usingEnvLayout {
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
		m.usingEnvLayout = false
		if m.focus >= len(m.columns) {
			m.focus = len(m.columns) - 1
		}
	}
	m.applyLayout()
}

func (m *model) startEnvEditor() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	m.useTasksLayout(false)
	m.useArtifactsLayout(false)
	m.useServicesLayout(false)
	m.useEnvLayout(true)

	m.envFiles = nil
	m.currentEnvFile = nil
	m.envSelection = -1
	m.envEditingFile = nil
	m.envEditingEntry = envEntry{}
	m.pendingEnvKey = ""
	m.envOpenTelemetrySent = false
	m.envReveal = make(map[string]bool)
	m.envValidationNotified = make(map[string]bool)

	m.featureCol.title = "Env Editor"
	m.featureCol.SetHighlightFunc(func(entry listEntry) tea.Cmd {
		if item, ok := entry.payload.(envFileItem); ok {
			return func() tea.Msg { return envFileSelectedMsg{index: item.index, activate: false} }
		}
		return nil
	})
	m.featureCol.SetItems([]list.Item{
		listEntry{title: "Loading…", desc: "", payload: nil},
	})
	m.envTableCol.SetEntries(nil, m.envReveal)
	m.previewCol.SetContent("Loading environment files…\n")
	m.focus = int(focusFeatures)
	return m.loadEnvFilesCmd()
}

func (m *model) exitEnvEditor() {
	if !m.usingEnvLayout {
		return
	}
	m.useEnvLayout(false)
	m.featureCol.title = "Feature"
	m.featureCol.SetHighlightFunc(m.featureHighlightDefault)
	m.featureCol.SetItems(featureListEntries())
	m.envTableCol.SetEntries(nil, m.envReveal)
	m.envFiles = nil
	m.currentEnvFile = nil
	m.envSelection = -1
	m.envEditingFile = nil
	m.envEditingEntry = envEntry{}
	m.pendingEnvKey = ""
	m.previewCol.SetContent("Select an item to preview details.\n")
}

func (m *model) exitReportsView() {
	if !m.usingReportsLayout {
		return
	}
	m.useReportsLayout(false)
}

func (m *model) loadEnvFilesCmd() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	return func() tea.Msg {
		states, err := loadEnvFiles(projectPath)
		return envFilesLoadedMsg{states: states, err: err}
	}
}

func (m *model) handleEnvFilesLoaded(msg envFilesLoadedMsg) tea.Cmd {
	if msg.err != nil {
		m.envFiles = nil
		m.envSelection = -1
		m.featureCol.SetItems([]list.Item{
			listEntry{title: "Load failed", desc: msg.err.Error(), payload: nil},
		})
		m.envTableCol.SetEntries(nil, m.envReveal)
		m.previewCol.SetContent(fmt.Sprintf("Failed to load environment files: %v\n", msg.err))
		return nil
	}

	m.envFiles = msg.states
	m.envSelection = -1
	m.envEditingFile = nil
	m.envEditingEntry = envEntry{}
	m.pendingEnvKey = ""
	if m.envReveal == nil {
		m.envReveal = make(map[string]bool)
	}
	if m.envValidationNotified == nil {
		m.envValidationNotified = make(map[string]bool)
	}

	m.refreshEnvFileList()
	if len(m.envFiles) == 0 {
		m.previewCol.SetContent("No .env files found. Press 'n' to add keys and save to create one.\n")
		return nil
	}
	if !m.envOpenTelemetrySent && m.currentProject != nil {
		fields := map[string]string{
			"path":  filepath.Clean(m.currentProject.Path),
			"files": strconv.Itoa(len(m.envFiles)),
		}
		m.emitTelemetry("env_opened", fields)
		m.envOpenTelemetrySent = true
	}
	return func() tea.Msg { return envFileSelectedMsg{index: 0, activate: false} }
}

func (m *model) refreshEnvFileList() {
	if !m.usingEnvLayout {
		return
	}
	if len(m.envFiles) == 0 {
		m.envSelection = -1
		m.featureCol.SetItems([]list.Item{
			listEntry{title: "No .env files", desc: "Press 'n' to capture new entries", payload: nil},
		})
		return
	}
	items := make([]list.Item, 0, len(m.envFiles))
	for i, state := range m.envFiles {
		items = append(items, listEntry{
			title:   m.envFileTitle(state),
			desc:    m.envFileDescription(state),
			payload: envFileItem{index: i, state: state},
		})
	}
	m.featureCol.SetItems(items)
	if m.envSelection >= 0 && m.envSelection < len(items) {
		m.featureCol.model.Select(m.envSelection)
	}
}

func (m *model) handleEnvFileSelected(msg envFileSelectedMsg) {
	if msg.index < 0 || msg.index >= len(m.envFiles) {
		return
	}
	if !m.usingEnvLayout {
		return
	}
	state := m.envFiles[msg.index]
	m.envSelection = msg.index
	m.featureCol.model.Select(msg.index)
	m.currentEnvFile = state
	m.envEditingFile = nil
	m.envEditingEntry = envEntry{}
	state.rebuildEntries()
	state.refreshValidation()
	m.refreshEnvFileList()
	m.refreshEnvTable("")
	m.updateEnvPreview()
	if msg.activate {
		m.focus = int(focusItems)
	}
}

func (m *model) refreshEnvTable(selectID string) {
	if !m.usingEnvLayout {
		return
	}
	if m.currentEnvFile == nil {
		m.envTableCol.SetEntries(nil, m.envReveal)
		return
	}
	entries := append([]envEntry(nil), m.currentEnvFile.Entries...)
	m.envTableCol.SetEntries(entries, m.envReveal)
	if selectID != "" {
		for idx, entry := range entries {
			if envEntryIdentifier(entry) == selectID {
				m.envTableCol.table.SetCursor(idx)
				break
			}
		}
	}
}

func (m *model) updateEnvPreview() {
	m.previewCol.SetContent(m.renderEnvPreview())
}

func (m *model) renderEnvPreview() string {
	if !m.usingEnvLayout {
		return "Env Editor not active.\n"
	}
	if m.currentEnvFile == nil {
		if len(m.envFiles) == 0 {
			return "No .env files detected. Press 'n' to add a key and save to create one.\n"
		}
		return "Select an environment file to review keys and validation results.\n"
	}
	state := m.currentEnvFile
	var b strings.Builder
	name := state.RelPath
	if strings.TrimSpace(name) == "" {
		name = state.Path
	}
	status := []string{}
	if state.Dirty {
		status = append(status, "dirty")
	} else {
		status = append(status, "clean")
	}
	if !state.Exists {
		status = append(status, "will create on save")
	}
	if state.Validation.IsClean() {
		status = append(status, "validation ok")
	} else {
		status = append(status, "needs attention")
	}
	b.WriteString(fmt.Sprintf("%s (%s)\n", name, strings.Join(status, ", ")))
	b.WriteString(fmt.Sprintf("Keys: %d\n", len(state.Entries)))

	if len(state.Validation.Missing) > 0 {
		b.WriteString("Missing: " + strings.Join(state.Validation.Missing, ", ") + "\n")
	} else {
		b.WriteString("Missing: none\n")
	}
	if len(state.Validation.Empty) > 0 {
		b.WriteString("Empty values: " + strings.Join(state.Validation.Empty, ", ") + "\n")
	} else {
		b.WriteString("Empty values: none\n")
	}
	if len(state.Validation.Duplicates) > 0 {
		b.WriteString("Duplicates: " + strings.Join(state.Validation.Duplicates, ", ") + "\n")
	} else {
		b.WriteString("Duplicates: none\n")
	}

	allMissing := m.aggregateEnvMissingKeys()
	if len(allMissing) > 0 {
		b.WriteString("\nProject-wide missing keys:\n")
		for _, key := range allMissing {
			b.WriteString("  - " + key + "\n")
		}
	}

	b.WriteString("\nShortcuts: enter edit • n new key • r reveal/hide • y copy • ctrl+s save\n")
	b.WriteString("Secrets stay masked unless revealed; copied values are not logged.\n")
	b.WriteString("After saving, restart affected services from Run/Services.\n")
	return b.String()
}

func (m *model) aggregateEnvMissingKeys() []string {
	if len(m.envFiles) == 0 {
		return nil
	}
	unique := make(map[string]struct{})
	for _, state := range m.envFiles {
		for _, key := range state.Validation.Missing {
			unique[key] = struct{}{}
		}
	}
	if len(unique) == 0 {
		return nil
	}
	keys := make([]string, 0, len(unique))
	for key := range unique {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func (m *model) promptEnvValueEdit(entry envEntry) {
	if m.currentFeature != "env" || !m.usingEnvLayout || m.currentEnvFile == nil {
		return
	}
	m.envEditingFile = m.currentEnvFile
	m.envEditingEntry = entry
	m.openTextarea(fmt.Sprintf("Value for %s", entry.Key), entry.Value, inputEnvEditValue)
}

func (m *model) toggleEnvReveal(entry envEntry) {
	if m.envReveal == nil {
		m.envReveal = make(map[string]bool)
	}
	id := envEntryIdentifier(entry)
	m.envReveal[id] = !m.envReveal[id]
	m.refreshEnvTable(id)
}

func (m *model) copyEnvValue(entry envEntry) {
	if m.currentFeature != "env" || !m.usingEnvLayout {
		return
	}
	if err := clipboard.WriteAll(entry.Value); err != nil {
		m.setToast(fmt.Sprintf("Copy failed: %v", err), 5*time.Second)
		return
	}
	m.setToast(fmt.Sprintf("Copied %s", entry.Key), 4*time.Second)
}

func (m *model) promptEnvNewEntry() {
	if m.currentFeature != "env" || !m.usingEnvLayout || m.currentEnvFile == nil {
		return
	}
	m.pendingEnvKey = ""
	m.openInput("New key name", "", inputEnvNewKey)
}

func (m *model) applyEnvValueEdit(value string) {
	if m.envEditingFile == nil {
		return
	}
	state := m.envEditingFile
	entry := m.envEditingEntry
	key := entry.Key
	state.setValue(entry.LineIndex, value)
	if idxEntry, ok := findEnvEntryByLine(state, entry.LineIndex); ok {
		entry = idxEntry
	}
	selectID := envEntryIdentifier(entry)
	m.refreshEnvFileList()
	m.refreshEnvTable(selectID)
	m.updateEnvPreview()
	if m.envValidationNotified != nil {
		delete(m.envValidationNotified, state.RelPath)
	}
	m.envEditingFile = nil
	m.envEditingEntry = envEntry{}
	m.setToast(fmt.Sprintf("Updated %s", key), 4*time.Second)
}

func (m *model) applyEnvNewValue(value string) bool {
	if m.currentEnvFile == nil {
		return false
	}
	key := strings.TrimSpace(m.pendingEnvKey)
	if key == "" {
		m.setToast("Key required", 4*time.Second)
		return false
	}
	for _, entry := range m.currentEnvFile.Entries {
		if entry.Key == key {
			m.setToast("Key already exists in this file", 4*time.Second)
			return false
		}
	}
	index := m.currentEnvFile.addEntry(key, value)
	m.currentEnvFile.ensureTrailingNewline()
	selectID := ""
	if index >= 0 && index < len(m.currentEnvFile.Entries) {
		selectID = envEntryIdentifier(m.currentEnvFile.Entries[index])
	}
	m.pendingEnvKey = ""
	m.refreshEnvFileList()
	m.refreshEnvTable(selectID)
	m.updateEnvPreview()
	if m.envValidationNotified != nil {
		delete(m.envValidationNotified, m.currentEnvFile.RelPath)
	}
	m.setToast(fmt.Sprintf("Added %s", key), 4*time.Second)
	return true
}

func (m *model) saveCurrentEnvFile() {
	if m.currentFeature != "env" || !m.usingEnvLayout || m.currentEnvFile == nil {
		return
	}
	state := m.currentEnvFile
	if !state.Dirty {
		m.setToast("No env changes to save", 3*time.Second)
		return
	}
	if !state.Validation.IsClean() {
		key := state.RelPath
		if _, seen := m.envValidationNotified[key]; !seen && m.currentProject != nil {
			fields := map[string]string{
				"path":            filepath.Clean(m.currentProject.Path),
				"file":            key,
				"missing_count":   strconv.Itoa(len(state.Validation.Missing)),
				"empty_count":     strconv.Itoa(len(state.Validation.Empty)),
				"duplicate_count": strconv.Itoa(len(state.Validation.Duplicates)),
			}
			m.emitTelemetry("env_validation_failed", fields)
			m.envValidationNotified[key] = true
		}
		m.setToast("Validation failed - fix missing/empty keys before saving", 5*time.Second)
		m.updateEnvPreview()
		return
	}
	if m.currentProject != nil {
		delete(m.envValidationNotified, state.RelPath)
	}
	if err := writeEnvFile(state); err != nil {
		m.setToast(fmt.Sprintf("Save failed: %v", err), 5*time.Second)
		return
	}
	state.refreshValidation()
	m.refreshEnvFileList()
	m.refreshEnvTable("")
	m.updateEnvPreview()
	if m.currentProject != nil {
		fields := map[string]string{
			"path": filepath.Clean(m.currentProject.Path),
			"file": state.RelPath,
			"keys": strconv.Itoa(len(state.Entries)),
		}
		m.emitTelemetry("env_saved", fields)
	}
	m.appendLog(fmt.Sprintf("Saved env file: %s", state.RelPath))
	m.setToast("Saved. Restart affected services to apply changes.", 6*time.Second)
}

func (m *model) envFileTitle(state *envFileState) string {
	label := strings.TrimSpace(state.RelPath)
	if label == "" {
		label = strings.TrimSpace(state.Path)
	}
	if label == "" {
		label = ".env"
	}
	if state.Dirty {
		label = "* " + label
	}
	return label
}

func (m *model) envFileDescription(state *envFileState) string {
	var parts []string
	if state.Exists {
		parts = append(parts, fmt.Sprintf("%d keys", len(state.Entries)))
	} else {
		parts = append(parts, "not created")
	}
	if !state.Validation.IsClean() {
		var issues []string
		if len(state.Validation.Missing) > 0 {
			issues = append(issues, fmt.Sprintf("missing %d", len(state.Validation.Missing)))
		}
		if len(state.Validation.Empty) > 0 {
			issues = append(issues, fmt.Sprintf("empty %d", len(state.Validation.Empty)))
		}
		if len(state.Validation.Duplicates) > 0 {
			issues = append(issues, fmt.Sprintf("dup %d", len(state.Validation.Duplicates)))
		}
		if len(issues) > 0 {
			parts = append(parts, strings.Join(issues, ", "))
		}
	} else {
		if !state.Dirty {
			parts = append(parts, "ready")
		} else {
			parts = append(parts, "unsaved")
		}
	}
	return strings.Join(parts, " • ")
}

func findEnvEntryByLine(state *envFileState, lineIndex int) (envEntry, bool) {
	for _, entry := range state.Entries {
		if entry.LineIndex == lineIndex {
			return entry, true
		}
	}
	return envEntry{}, false
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
	m.hideSpinner()
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
	m.showSpinner("Updating task status…")
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
	if s.Tasks > 0 {
		percent := float64(s.DoneTasks) / float64(max(s.Tasks, 1))
		lines = append(lines,
			fmt.Sprintf("Progress %d/%d", s.DoneTasks, s.Tasks),
			renderProgressBar(percent, 36),
		)
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
			if story.Total > 0 {
				percent := float64(story.Completed) / float64(max(story.Total, 1))
				b.WriteString(renderProgressBar(percent, 32))
				b.WriteRune('\n')
			}
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

func (m *model) loadReportsEntriesCmd() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	return func() tea.Msg {
		entries, err := gatherProjectReports(projectPath)
		return reportsLoadedMsg{entries: entries, err: err}
	}
}

func (m *model) loadTokensUsageCmd() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	return func() tea.Msg {
		logPath := filepath.Join(projectPath, ".gpt-creator", "logs", "codex-usage.ndjson")
		usage, err := readTokensUsage(logPath)
		return tokensLoadedMsg{usage: usage, err: err}
	}
}

func (m *model) handleTokensLoaded(msg tokensLoadedMsg) tea.Cmd {
	m.tokensLoading = false
	m.tokensError = msg.err
	m.tokensUsage = msg.usage
	if msg.err != nil {
		m.tokensViewData = tokensViewData{}
		m.tokensCurrentRow = ""
		if os.IsNotExist(msg.err) {
			m.tokensCol.SetPlaceholder("No usage log found under .gpt-creator/logs/codex-usage.ndjson.")
			m.previewCol.SetContent("No token usage log found.\nRun codex-enabled commands to capture usage data.\n")
		} else {
			m.tokensCol.SetPlaceholder("Failed to read token usage log.")
			m.previewCol.SetContent(fmt.Sprintf("Failed to read token usage log:\n%v\n", msg.err))
		}
		return nil
	}
	cmd := m.refreshTokensView(true)
	if !m.tokensTelemetrySent && m.currentProject != nil {
		fields := map[string]string{
			"path":    filepath.Clean(m.currentProject.Path),
			"group":   string(m.tokensGroup),
			"records": strconv.Itoa(len(m.tokensViewData.Records)),
		}
		if idx := m.tokensRangeIndex; idx >= 0 && idx < len(tokensRangeOptions) {
			fields["range"] = tokensRangeOptions[idx].Key
		}
		if m.tokensViewData.Summary.TotalCalls > 0 {
			fields["calls"] = strconv.Itoa(m.tokensViewData.Summary.TotalCalls)
		}
		if m.tokensViewData.Summary.TotalTokens > 0 {
			fields["tokens"] = strconv.Itoa(m.tokensViewData.Summary.TotalTokens)
		}
		m.emitTelemetry("tokens_viewed", fields)
		m.tokensTelemetrySent = true
	}
	return cmd
}

func (m *model) handleReportsLoaded(msg reportsLoadedMsg) tea.Cmd {
	m.reportsLoading = false
	m.reportsError = msg.err
	if msg.err != nil {
		m.reportEntries = nil
		m.reportsCol.SetEntries(nil)
		m.reportsCol.SetPlaceholder("Failed to load reports.")
		if msg.err != nil {
			m.previewCol.SetContent(fmt.Sprintf("Failed to load reports:\n%v\n", msg.err))
		} else {
			m.previewCol.SetContent("Failed to load reports.\n")
		}
		return nil
	}
	m.reportEntries = append([]reportEntry(nil), msg.entries...)
	if !m.reportsTelemetrySent && m.currentProject != nil {
		fields := map[string]string{
			"path":  filepath.Clean(m.currentProject.Path),
			"count": strconv.Itoa(len(msg.entries)),
		}
		if len(msg.entries) > 0 && !msg.entries[0].Timestamp.IsZero() {
			fields["latest"] = msg.entries[0].Timestamp.UTC().Format(time.RFC3339)
		}
		m.emitTelemetry("reports_viewed", fields)
		m.reportsTelemetrySent = true
	}
	if len(msg.entries) == 0 {
		m.reportsCol.SetEntries(nil)
		m.reportsCol.SetPlaceholder("No reports captured yet.")
		m.previewCol.SetContent("No reports available.\nRun commands with --reports-on to capture automation reports.\n")
		m.currentReportKey = ""
		return nil
	}
	m.reportsCol.SetEntries(msg.entries)
	if m.currentReportKey != "" && m.reportsCol.SelectKey(m.currentReportKey) {
		if entry, ok := m.reportsCol.SelectedEntry(); ok {
			return func() tea.Msg { return reportsRowSelectedMsg{entry: entry} }
		}
	}
	if entry, ok := m.reportsCol.SelectedEntry(); ok {
		m.currentReportKey = entry.Key
		return func() tea.Msg { return reportsRowSelectedMsg{entry: entry} }
	}
	return nil
}

func (m *model) handleReportsRowSelected(msg reportsRowSelectedMsg) {
	entry := msg.entry
	m.currentReportKey = entry.Key
	m.previewCol.SetContent(m.renderReportPreview(entry))
	if msg.activate {
		m.openReportEntry(entry)
	}
}

func (m *model) refreshSettingsItems() {
	if m.currentFeature != "settings" {
		return
	}
	if m.itemsCol == nil {
		return
	}
	items := m.buildSettingsItems()
	m.itemsCol.SetTitle("Sections")
	m.itemsCol.SetItems(items)
	if len(items) == 0 {
		m.currentItem = featureItemDefinition{}
		if m.previewCol != nil {
			m.previewCol.SetContent("No settings available.\n")
		}
		return
	}
	currentKey := m.currentItem.Key
	selected := items[0]
	for _, item := range items {
		if item.Key == currentKey && currentKey != "" {
			selected = item
			break
		}
	}
	m.itemsCol.SelectKey(selected.Key)
	m.showSettingsItem(selected)
}

func (m *model) buildSettingsItems() []featureItemDefinition {
	items := make([]featureItemDefinition, 0, 5)

	desc, preview := m.settingsWorkspaceInfo()
	items = append(items, featureItemDefinition{
		Key:   "settings-workspaces",
		Title: "Workspace roots",
		Desc:  desc,
		Meta: map[string]string{
			"settings":        "workspace",
			"settingsPreview": preview,
		},
	})

	desc, preview = m.settingsThemeInfo()
	items = append(items, featureItemDefinition{
		Key:   "settings-theme",
		Title: "Theme",
		Desc:  desc,
		Meta: map[string]string{
			"settings":        "theme",
			"settingsPreview": preview,
		},
	})

	desc, preview = m.settingsConcurrencyInfo()
	items = append(items, featureItemDefinition{
		Key:   "settings-concurrency",
		Title: "Concurrency",
		Desc:  desc,
		Meta: map[string]string{
			"settings":        "concurrency",
			"settingsPreview": preview,
		},
	})

	desc, preview = m.settingsDockerInfo()
	items = append(items, featureItemDefinition{
		Key:   "settings-docker",
		Title: "Docker path",
		Desc:  desc,
		Meta: map[string]string{
			"settings":        "docker",
			"settingsPreview": preview,
		},
	})

	desc, preview = m.settingsUpdateInfo()
	items = append(items, featureItemDefinition{
		Key:   "settings-update",
		Title: "Update",
		Desc:  desc,
		Meta: map[string]string{
			"settings":        "update",
			"settingsPreview": preview,
		},
	})

	return items
}

func (m *model) showSettingsItem(item featureItemDefinition) {
	m.currentItem = item
	if m.previewCol == nil {
		return
	}
	preview := ""
	if item.Meta != nil {
		preview = strings.TrimSpace(item.Meta["settingsPreview"])
	}
	if preview == "" {
		preview = "Settings preview unavailable.\n"
	} else if !strings.HasSuffix(preview, "\n") {
		preview += "\n"
	}
	m.previewCol.SetContent(preview)
}

func (m *model) handleSettingsSelection(item featureItemDefinition, activate bool) tea.Cmd {
	m.itemsCol.SelectKey(item.Key)
	m.showSettingsItem(item)
	if activate {
		return m.activateSettingsItem(item)
	}
	return nil
}

func (m *model) activateSettingsItem(item featureItemDefinition) tea.Cmd {
	switch item.Key {
	case "settings-workspaces":
		return m.promptAddWorkspaceRoot()
	case "settings-theme":
		m.cycleThemeSetting(1)
		return nil
	case "settings-concurrency":
		return m.promptSettingsConcurrency()
	case "settings-docker":
		return m.promptDockerPath()
	case "settings-update":
		return m.runUpdate(false)
	default:
		return nil
	}
}

func (m *model) handleSettingsKey(msg tea.KeyMsg) (bool, tea.Cmd) {
	if m.currentItem.Key == "" {
		return false, nil
	}
	switch m.currentItem.Key {
	case "settings-workspaces":
		switch msg.String() {
		case "enter":
			return true, m.promptAddWorkspaceRoot()
		case "x", "X", "delete":
			return true, m.promptRemoveWorkspaceRoot()
		case "r", "R":
			if len(m.customWorkspaceRoots) == 0 {
				m.setToast("No custom roots to reset", 4*time.Second)
				return true, nil
			}
			m.resetCustomWorkspaceRoots()
			return true, nil
		}
	case "settings-theme":
		switch msg.String() {
		case "enter", " ":
			m.cycleThemeSetting(1)
			return true, nil
		case "1", "a", "A":
			m.setThemeSetting(markdownThemeAuto)
			return true, nil
		case "2", "d", "D":
			m.setThemeSetting(markdownThemeDark)
			return true, nil
		case "3":
			m.setThemeSetting(markdownThemeLight)
			return true, nil
		}
	case "settings-concurrency":
		switch msg.String() {
		case "enter":
			return true, m.promptSettingsConcurrency()
		case "+", "=":
			return true, m.adjustConcurrency(1)
		case "-", "_":
			return true, m.adjustConcurrency(-1)
		}
	case "settings-docker":
		switch msg.String() {
		case "enter":
			return true, m.promptDockerPath()
		case "c", "C":
			m.clearDockerPath()
			return true, nil
		}
	case "settings-update":
		switch msg.String() {
		case "enter":
			return true, m.runUpdate(false)
		case "f", "F":
			return true, m.runUpdate(true)
		}
	}
	return false, nil
}

func (m *model) settingsWorkspaceInfo() (string, string) {
	customTotal := len(m.customWorkspaceRoots)
	desc := "No custom roots"
	if customTotal == 1 {
		desc = "1 custom root"
	} else if customTotal > 1 {
		desc = fmt.Sprintf("%d custom roots", customTotal)
	}
	var b strings.Builder
	b.WriteString("Workspace Roots\n────────────────\n")
	if customTotal == 0 {
		b.WriteString("Using defaults only.\n")
	} else {
		for _, path := range m.customWorkspaceRoots {
			status := "✓"
			if !dirExists(path) {
				status = "⚠"
			}
			b.WriteString(fmt.Sprintf("%s %s\n", status, abbreviatePath(path)))
		}
	}
	b.WriteString("\nEnter add • X remove (path/index) • R reset custom roots\n")
	return desc, b.String()
}

func (m *model) settingsThemeInfo() (string, string) {
	label := markdownThemeLabel(m.markdownTheme)
	desc := "Theme: " + label
	var b strings.Builder
	b.WriteString("Theme\n────────\n")
	b.WriteString(fmt.Sprintf("Current: %s\n", label))
	b.WriteString("\nEnter cycle • 1 auto • 2 dark • 3 light\n")
	return desc, b.String()
}

func (m *model) settingsConcurrencyInfo() (string, string) {
	desc := fmt.Sprintf("Max jobs: %d", m.settingsConcurrency)
	var b strings.Builder
	b.WriteString("Concurrency\n────────────\n")
	b.WriteString(fmt.Sprintf("Current limit: %d job(s) in parallel\n", m.settingsConcurrency))
	b.WriteString("\n+ increase • - decrease • Enter set value (1–32)\n")
	return desc, b.String()
}

func (m *model) settingsDockerInfo() (string, string) {
	path := strings.TrimSpace(m.settingsDockerPath)
	desc := "Docker: Auto"
	if path != "" {
		desc = "Docker: " + abbreviatePath(path)
	}
	var b strings.Builder
	b.WriteString("Docker CLI\n───────────\n")
	if path == "" {
		status := "available"
		if !m.dockerAvailable {
			status = "not detected"
		}
		b.WriteString(fmt.Sprintf("Using system default (docker) — %s.\n", status))
	} else {
		status := "Available"
		if !pathExists(path) {
			status = "Not found"
		}
		b.WriteString(fmt.Sprintf("Path: %s\nStatus: %s\n", path, status))
	}
	b.WriteString("\nEnter choose path • C clear override\n")
	return desc, b.String()
}

func (m *model) settingsUpdateInfo() (string, string) {
	status := m.updateStatus
	if status == "" {
		status = "Idle"
	}
	desc := "Status: " + status
	var b strings.Builder
	b.WriteString("Updates\n───────\n")
	b.WriteString(fmt.Sprintf("Status: %s\n", status))
	if !m.updateLastRun.IsZero() {
		b.WriteString(fmt.Sprintf("Last run: %s (%s ago)\n", m.updateLastRun.Format(time.RFC822), formatRelativeTime(m.updateLastRun)))
	}
	if strings.TrimSpace(m.updateLastError) != "" {
		b.WriteString("Last error:\n")
		b.WriteString(m.updateLastError)
		b.WriteString("\n")
	}
	b.WriteString("\nEnter update • F force update --force\n")
	return desc, b.String()
}

func (m *model) cycleThemeSetting(step int) {
	next := nextMarkdownTheme(m.markdownTheme)
	if step < 0 {
		switch m.markdownTheme {
		case markdownThemeAuto:
			next = markdownThemeLight
		case markdownThemeDark:
			next = markdownThemeAuto
		default:
			next = markdownThemeDark
		}
	}
	m.setThemeSetting(next)
}

func (m *model) setThemeSetting(theme markdownTheme) {
	if theme == m.markdownTheme {
		return
	}
	m.applyMarkdownTheme(theme, true)
	m.writeUIConfig()
	m.emitSettingsChanged("theme", theme.String())
	m.refreshSettingsItems()
}

func (m *model) promptAddWorkspaceRoot() tea.Cmd {
	return m.openPathPicker("Add workspace root", "", inputSettingsWorkspaceAdd, true, false)
}

func (m *model) promptRemoveWorkspaceRoot() tea.Cmd {
	if len(m.customWorkspaceRoots) == 0 {
		m.setToast("No custom roots to remove", 4*time.Second)
		return nil
	}
	return m.openInput("Remove workspace root (path or index)", "", inputSettingsWorkspaceRemove)
}

func (m *model) promptDockerPath() tea.Cmd {
	return m.openPathPicker("Docker CLI path", m.settingsDockerPath, inputSettingsDockerPath, false, true)
}

func (m *model) promptSettingsConcurrency() tea.Cmd {
	return m.openInput("Set max concurrent jobs", strconv.Itoa(m.settingsConcurrency), inputSettingsConcurrency)
}

func (m *model) adjustConcurrency(delta int) tea.Cmd {
	value := m.settingsConcurrency + delta
	if value < 1 {
		value = 1
	}
	if value > 8 {
		value = 8
	}
	return m.setConcurrency(value)
}

func (m *model) setConcurrency(value int) tea.Cmd {
	if value < 1 {
		value = 1
	}
	if value == m.settingsConcurrency {
		return nil
	}
	m.settingsConcurrency = value
	var cmd tea.Cmd
	if m.jobRunner != nil {
		cmd = m.jobRunner.SetMaxParallel(value)
	}
	m.writeUIConfig()
	m.emitSettingsChanged("concurrency", strconv.Itoa(value))
	m.setToast(fmt.Sprintf("Max background jobs: %d", value), 4*time.Second)
	m.refreshSettingsItems()
	return cmd
}

func (m *model) addCustomWorkspaceRoot(path string) bool {
	clean := filepath.Clean(path)
	if clean == "" {
		return false
	}
	if !dirExists(clean) {
		m.setToast("Directory not found", 4*time.Second)
		return false
	}
	for _, existing := range m.customWorkspaceRoots {
		if filepath.Clean(existing) == clean {
			m.setToast("Root already configured", 4*time.Second)
			return false
		}
	}
	m.customWorkspaceRoots = append(m.customWorkspaceRoots, clean)
	sort.Strings(m.customWorkspaceRoots)
	if !m.hasWorkspaceRoot(clean) {
		m.workspaceRoots = append(m.workspaceRoots, workspaceRoot{Label: labelForPath(clean), Path: clean})
	}
	m.refreshWorkspaceColumn()
	m.writeUIConfig()
	m.emitSettingsChanged("workspace_root_added", clean)
	m.setToast("Workspace root added", 4*time.Second)
	m.refreshSettingsItems()
	return true
}

func (m *model) removeCustomWorkspaceRoot(path string) bool {
	clean := filepath.Clean(path)
	index := -1
	for i, existing := range m.customWorkspaceRoots {
		if filepath.Clean(existing) == clean {
			index = i
			break
		}
	}
	if index == -1 {
		return false
	}
	m.customWorkspaceRoots = append(m.customWorkspaceRoots[:index], m.customWorkspaceRoots[index+1:]...)
	delete(m.pinnedPaths, clean)
	filtered := make([]workspaceRoot, 0, len(m.workspaceRoots))
	for _, root := range m.workspaceRoots {
		if filepath.Clean(root.Path) == clean {
			continue
		}
		filtered = append(filtered, root)
	}
	m.workspaceRoots = filtered
	m.refreshWorkspaceColumn()
	m.writeUIConfig()
	m.emitSettingsChanged("workspace_root_removed", clean)
	m.setToast("Workspace root removed", 4*time.Second)
	m.refreshSettingsItems()
	return true
}

func (m *model) resetCustomWorkspaceRoots() {
	if len(m.customWorkspaceRoots) == 0 {
		m.setToast("No custom roots to reset", 4*time.Second)
		return
	}
	old := append([]string{}, m.customWorkspaceRoots...)
	for _, path := range old {
		delete(m.pinnedPaths, filepath.Clean(path))
	}
	m.customWorkspaceRoots = nil
	filtered := make([]workspaceRoot, 0, len(m.workspaceRoots))
	for _, root := range m.workspaceRoots {
		remove := false
		for _, custom := range old {
			if filepath.Clean(root.Path) == filepath.Clean(custom) {
				remove = true
				break
			}
		}
		if !remove {
			filtered = append(filtered, root)
		}
	}
	m.workspaceRoots = filtered
	m.refreshWorkspaceColumn()
	m.writeUIConfig()
	m.emitSettingsChanged("workspace_roots_reset", "")
	m.setToast("Custom workspace roots cleared", 4*time.Second)
	m.refreshSettingsItems()
}

func (m *model) setDockerPath(path string) {
	trimmed := strings.TrimSpace(path)
	if trimmed != "" {
		if info, err := os.Stat(trimmed); err == nil {
			if info.IsDir() {
				m.setToast("Invalid docker binary", 4*time.Second)
				return
			}
		} else {
			if resolved, err := exec.LookPath(trimmed); err == nil {
				trimmed = resolved
			} else {
				m.setToast("Docker binary not found", 4*time.Second)
				return
			}
		}
	}
	if trimmed == m.settingsDockerPath {
		return
	}
	m.settingsDockerPath = trimmed
	m.dockerAvailable = dockerCLIAvailableWithPath(trimmed)
	m.writeUIConfig()
	m.emitSettingsChanged("docker_path", trimmed)
	if trimmed == "" {
		m.setToast("Docker path cleared", 4*time.Second)
	} else {
		m.setToast("Docker path updated", 4*time.Second)
	}
	m.refreshSettingsItems()
}

func (m *model) clearDockerPath() {
	if m.settingsDockerPath == "" {
		return
	}
	m.settingsDockerPath = ""
	m.dockerAvailable = dockerCLIAvailableWithPath("")
	m.writeUIConfig()
	m.emitSettingsChanged("docker_path", "")
	m.setToast("Docker path cleared", 4*time.Second)
	m.refreshSettingsItems()
}

func (m *model) emitSettingsChanged(setting, value string) {
	fields := map[string]string{"setting": setting}
	if strings.TrimSpace(value) != "" {
		fields["value"] = strings.TrimSpace(value)
	}
	m.emitTelemetry("settings_changed", fields)
}

func (m *model) runUpdate(force bool) tea.Cmd {
	title := "Update gpt-creator"
	args := []string{"update"}
	if force {
		title = "Force update"
		args = append(args, "--force")
	}
	m.updateStatus = "Queued"
	m.refreshSettingsItems()
	m.appendLog(fmt.Sprintf("[job] %s queued", title))
	queuedToast := "Update queued"
	if force {
		queuedToast = "Force update queued"
	}
	m.setToast(queuedToast, 4*time.Second)
	return m.enqueueJob(jobRequest{
		title:   title,
		command: "gpt-creator",
		args:    args,
		onStart: func() {
			m.updateStatus = "Running"
			m.updateLastError = ""
			m.updateLastRun = time.Now()
			m.emitTelemetry("update_started", map[string]string{"force": strconv.FormatBool(force)})
			m.refreshSettingsItems()
		},
		onFinish: func(err error) {
			if err != nil {
				m.updateStatus = "Failed"
				m.updateLastError = err.Error()
				m.emitTelemetry("update_failed", map[string]string{"force": strconv.FormatBool(force), "error": err.Error()})
				m.setToast("Update failed", 5*time.Second)
			} else {
				m.updateStatus = "Succeeded"
				m.updateLastError = ""
				m.emitTelemetry("update_succeeded", map[string]string{"force": strconv.FormatBool(force)})
				m.setToast("Update completed", 5*time.Second)
			}
			m.updateLastRun = time.Now()
			m.refreshSettingsItems()
		},
	})
}

func (m *model) refreshTokensView(resetSelection bool) tea.Cmd {
	option := tokensRangeOption{Key: "all", Label: "All time"}
	if len(tokensRangeOptions) > 0 {
		if m.tokensRangeIndex < 0 {
			m.tokensRangeIndex = 0
		}
		if m.tokensRangeIndex >= len(tokensRangeOptions) {
			m.tokensRangeIndex = len(tokensRangeOptions) - 1
		}
		option = tokensRangeOptions[m.tokensRangeIndex]
	}
	data, err := buildTokensView(m.tokensUsage, option, m.tokensGroup)
	if err != nil {
		m.tokensViewData = tokensViewData{}
		m.tokensCurrentRow = ""
		m.tokensCol.SetPlaceholder("Unable to summarise token usage.")
		m.previewCol.SetContent(fmt.Sprintf("Failed to summarise token usage: %v\n", err))
		return nil
	}
	m.tokensViewData = data
	context := tokensContextString(data)
	emptyMessage := tokensEmptyMessage(data)
	m.tokensCol.SetData(data.Rows, data.Group, context, emptyMessage)
	if len(data.Rows) == 0 {
		m.tokensCurrentRow = ""
		if len(data.Records) == 0 {
			m.previewCol.SetContent("No usage entries found in this range.\nRun codex-enabled commands to capture usage data.\n")
		} else {
			m.previewCol.SetContent("No rollups available for this range.\nPress '-' or '=' to adjust the range, or 'g' to toggle grouping.\n")
		}
		return nil
	}
	if !resetSelection && m.tokensCurrentRow != "" && m.tokensCol.SelectKey(m.tokensCurrentRow) {
		if row, ok := m.tokensCol.SelectedRow(); ok {
			return func() tea.Msg { return tokensRowSelectedMsg{row: row} }
		}
	}
	row := data.Rows[0]
	m.tokensCurrentRow = row.Key
	m.tokensCol.SelectKey(row.Key)
	return func() tea.Msg { return tokensRowSelectedMsg{row: row} }
}

func tokensContextString(data tokensViewData) string {
	if data.Summary.RangeLabel == "" {
		return ""
	}
	parts := []string{data.Summary.RangeLabel}
	if label := strings.TrimSpace(data.Summary.GroupLabel); label != "" {
		parts = append(parts, label)
	}
	if data.Summary.TotalCalls > 0 {
		parts = append(parts, fmt.Sprintf("%d calls", data.Summary.TotalCalls))
	}
	if data.Summary.TotalTokens > 0 {
		parts = append(parts, fmt.Sprintf("%s tokens", formatIntComma(data.Summary.TotalTokens)))
	}
	if data.Summary.TotalCost > 0 {
		parts = append(parts, formatCost(data.Summary.TotalCost))
	}
	return strings.Join(parts, " • ")
}

func tokensEmptyMessage(data tokensViewData) string {
	if len(data.Records) == 0 {
		return "No usage entries recorded yet."
	}
	return "No rollups found for this range."
}

func (m *model) handleTokensRowSelected(row tokensTableRow) {
	m.tokensCurrentRow = row.Key
	if len(m.tokensViewData.Records) == 0 {
		m.previewCol.SetContent("No usage entries available.\n")
		return
	}
	m.previewCol.SetContent(renderTokensPreview(m.tokensViewData, row))
}

func (m *model) adjustTokensRange(delta int) tea.Cmd {
	if len(tokensRangeOptions) == 0 {
		return nil
	}
	newIndex := m.tokensRangeIndex + delta
	if newIndex < 0 {
		newIndex = 0
	}
	if newIndex >= len(tokensRangeOptions) {
		newIndex = len(tokensRangeOptions) - 1
	}
	if newIndex == m.tokensRangeIndex {
		return nil
	}
	m.tokensRangeIndex = newIndex
	m.tokensCurrentRow = ""
	return m.refreshTokensView(false)
}

func (m *model) toggleTokensGroup() tea.Cmd {
	if m.tokensGroup == tokensGroupByCommand {
		m.tokensGroup = tokensGroupByDay
	} else {
		m.tokensGroup = tokensGroupByCommand
	}
	m.tokensCurrentRow = ""
	return m.refreshTokensView(false)
}

func (m *model) exportTokensCSV() tea.Cmd {
	if m.currentProject == nil {
		return nil
	}
	records := append([]tokenLogRecord(nil), m.tokensViewData.Records...)
	if len(records) == 0 {
		m.setToast("No usage entries to export", 4*time.Second)
		return nil
	}
	projectPath := filepath.Clean(m.currentProject.Path)
	rangeKey := ""
	if idx := m.tokensRangeIndex; idx >= 0 && idx < len(tokensRangeOptions) {
		rangeKey = tokensRangeOptions[idx].Key
	}
	group := m.tokensGroup
	total := totalTokens(records)
	return func() tea.Msg {
		path, err := writeTokensCSV(projectPath, records)
		if err != nil {
			return tokensExportedMsg{err: err, rangeKey: rangeKey, group: group, records: len(records), tokens: total}
		}
		return tokensExportedMsg{path: path, rangeKey: rangeKey, group: group, records: len(records), tokens: total}
	}
}

func totalTokens(records []tokenLogRecord) int {
	total := 0
	for _, rec := range records {
		total += rec.TotalTokens
	}
	return total
}

func (m *model) handleTokensExported(msg tokensExportedMsg) {
	if msg.err != nil {
		m.appendLog(fmt.Sprintf("Tokens export failed: %v", msg.err))
		m.setToast("Tokens export failed", 6*time.Second)
		return
	}
	if strings.TrimSpace(msg.path) == "" {
		m.appendLog("Tokens export failed: empty path")
		m.setToast("Tokens export failed", 6*time.Second)
		return
	}
	m.appendLog(fmt.Sprintf("Tokens usage exported → %s", abbreviatePath(msg.path)))
	m.setToast("Tokens CSV exported", 5*time.Second)
	if m.currentProject != nil {
		fields := map[string]string{
			"path":    filepath.Clean(m.currentProject.Path),
			"file":    msg.path,
			"group":   string(msg.group),
			"records": strconv.Itoa(msg.records),
			"tokens":  strconv.Itoa(msg.tokens),
		}
		if msg.rangeKey != "" {
			fields["range"] = msg.rangeKey
		}
		m.emitTelemetry("tokens_exported", fields)
	}
}

func (m *model) exitTokensView() {
	if !m.usingTokensLayout {
		return
	}
	m.useTokensLayout(false)
	m.tokensUsage = nil
	m.tokensViewData = tokensViewData{}
	m.tokensCurrentRow = ""
	m.tokensLoading = false
	m.tokensError = nil
	m.tokensTelemetrySent = false
	m.tokensCol.SetPlaceholder("")
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
	if m.spinnerActive {
		spin := m.spinner.View()
		if trimmed := strings.TrimSpace(m.spinnerMessage); trimmed != "" {
			spin = fmt.Sprintf("%s %s", spin, trimmed)
		}
		segments = append(segments, m.styles.statusSeg.Render(spin))
	}
	if m.jobTimingActive && strings.TrimSpace(m.jobTimingTitle) != "" {
		title := strings.TrimSpace(m.jobTimingTitle)
		elapsed := m.jobStopwatch.Elapsed()
		segments = append(segments, m.styles.statusSeg.Render(fmt.Sprintf("Job: %s %s", title, formatElapsed(elapsed))))
	} else if !m.jobTimingActive && m.jobLastDuration > 0 {
		segments = append(segments, m.styles.statusSeg.Render("Last job "+formatElapsed(m.jobLastDuration)))
	}
	if m.servicesPolling && m.currentFeature == "services" && m.servicesTimerActive {
		remaining := m.servicesTimer.Timeout
		if remaining < 0 {
			remaining = 0
		}
		segments = append(segments, m.styles.statusSeg.Render("Refresh in "+formatElapsed(remaining)))
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
	content := strings.Join(segments, lipgloss.NewStyle().Render("│"))
	return m.styles.statusBar.Width(m.width).Render(content)
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

	if home, err := os.UserHomeDir(); err == nil {
		addRootIfExists(&roots, seen, filepath.Join(home, "gpt-projects"))
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

func (m *model) selectedReportEntry() (reportEntry, bool) {
	if m.reportsCol == nil {
		return reportEntry{}, false
	}
	return m.reportsCol.SelectedEntry()
}

func (m *model) openSelectedReport() {
	entry, ok := m.selectedReportEntry()
	if !ok {
		m.setToast("Select a report first", 4*time.Second)
		return
	}
	m.openReportEntry(entry)
}

func (m *model) exportSelectedReport() tea.Cmd {
	entry, ok := m.selectedReportEntry()
	if !ok {
		m.setToast("Select a report first", 4*time.Second)
		return nil
	}
	if m.currentProject == nil {
		m.setToast("Select a project first", 4*time.Second)
		return nil
	}
	if strings.TrimSpace(entry.AbsPath) == "" {
		m.setToast("Report path unavailable", 4*time.Second)
		return nil
	}
	info, err := os.Stat(entry.AbsPath)
	if err != nil {
		m.appendLog(fmt.Sprintf("Report not found: %s (%v)", entry.AbsPath, err))
		m.setToast("Report missing", 5*time.Second)
		return nil
	}
	destDir := filepath.Join(m.currentProject.Path, "reports", "exports")
	if err := os.MkdirAll(destDir, 0o755); err != nil {
		m.appendLog(fmt.Sprintf("Failed to prepare exports directory: %v", err))
		m.setToast("Export failed", 5*time.Second)
		return nil
	}
	baseName := filepath.Base(entry.AbsPath)
	ext := filepath.Ext(baseName)
	nameRoot := strings.TrimSuffix(baseName, ext)
	destPath := filepath.Join(destDir, baseName)
	for i := 1; ; i++ {
		if _, err := os.Stat(destPath); errors.Is(err, os.ErrNotExist) {
			break
		}
		destPath = filepath.Join(destDir, fmt.Sprintf("%s-%d%s", nameRoot, i, ext))
	}
	if err := copyFile(entry.AbsPath, destPath); err != nil {
		m.appendLog(fmt.Sprintf("Failed to export report: %v", err))
		m.setToast("Export failed", 5*time.Second)
		return nil
	}
	relDest, err := filepath.Rel(m.currentProject.Path, destPath)
	if err != nil {
		relDest = destPath
	} else {
		relDest = filepath.ToSlash(relDest)
	}
	m.appendLog(fmt.Sprintf("Report exported → %s", abbreviatePath(destPath)))
	m.setToast("Report exported", 4*time.Second)
	if m.currentProject != nil {
		fields := map[string]string{
			"project": filepath.Clean(m.currentProject.Path),
			"report":  entry.Key,
			"format":  strings.ToLower(entry.Format),
			"source":  entry.Source,
			"dest":    relDest,
		}
		if entry.RelPath != "" {
			fields["path"] = entry.RelPath
		}
		if info != nil {
			fields["size"] = strconv.FormatInt(info.Size(), 10)
		}
		m.emitTelemetry("report_exported", fields)
	}
	return m.loadReportsEntriesCmd()
}

func (m *model) copySelectedReportPath() {
	entry, ok := m.selectedReportEntry()
	if !ok {
		m.setToast("Select a report first", 4*time.Second)
		return
	}
	path := entry.AbsPath
	if strings.TrimSpace(path) == "" {
		path = entry.RelPath
	}
	if strings.TrimSpace(path) == "" {
		m.setToast("Report path unavailable", 4*time.Second)
		return
	}
	if err := clipboard.WriteAll(path); err != nil {
		m.appendLog(fmt.Sprintf("Failed to copy report path: %v", err))
		m.setToast("Clipboard unavailable", 4*time.Second)
		return
	}
	m.setToast("Report path copied", 3*time.Second)
}

func (m *model) copySelectedReportSnippet() {
	entry, ok := m.selectedReportEntry()
	if !ok {
		m.setToast("Select a report first", 4*time.Second)
		return
	}
	label, snippet := reportPreviewSnippet(entry)
	if strings.TrimSpace(snippet) == "" {
		m.setToast("No content available to copy", 4*time.Second)
		return
	}
	if err := clipboard.WriteAll(snippet); err != nil {
		m.appendLog(fmt.Sprintf("Failed to copy %s: %v", strings.ToLower(label), err))
		m.setToast("Clipboard unavailable", 4*time.Second)
		return
	}
	m.setToast(fmt.Sprintf("%s copied", label), 3*time.Second)
}

func (m *model) renderReportPreview(entry reportEntry) string {
	title := strings.TrimSpace(entry.Title)
	if title == "" {
		title = "Report"
	}
	var b strings.Builder
	b.WriteString(title)
	b.WriteRune('\n')
	b.WriteString(strings.Repeat("─", len(title)))
	b.WriteString("\n\n")

	if entry.Summary != "" {
		b.WriteString(trimMultiline(entry.Summary, 8))
		b.WriteString("\n\n")
	}

	meta := []string{}
	if entry.Type != "" {
		meta = append(meta, fmt.Sprintf("Type: %s", entry.Type))
	}
	if entry.Priority != "" {
		meta = append(meta, fmt.Sprintf("Priority: %s", entry.Priority))
	}
	if entry.Status != "" {
		meta = append(meta, fmt.Sprintf("Status: %s", entry.Status))
	}
	if entry.Reporter != "" {
		meta = append(meta, fmt.Sprintf("Reporter: %s", entry.Reporter))
	}
	if entry.Slug != "" {
		meta = append(meta, fmt.Sprintf("Slug: %s", entry.Slug))
	}
	if entry.Popularity > 0 {
		meta = append(meta, fmt.Sprintf("Popularity: %d (likes %d, comments %d)", entry.Popularity, entry.Likes, entry.Comments))
	}
	if entry.Source != "" {
		meta = append(meta, fmt.Sprintf("Source: %s", titleCase(entry.Source)))
	}
	if !entry.Timestamp.IsZero() {
		ts := entry.Timestamp.Local()
		meta = append(meta, fmt.Sprintf("Captured: %s (%s ago)", ts.Format(time.RFC822), formatRelativeTime(ts)))
	}
	if entry.RelPath != "" {
		meta = append(meta, fmt.Sprintf("Location: %s", entry.RelPath))
	}
	meta = append(meta, fmt.Sprintf("Format: %s", defaultIfEmpty(entry.Format, "unknown")))
	if entry.Size > 0 {
		meta = append(meta, fmt.Sprintf("Size: %s", formatByteSize(entry.Size)))
	}
	if len(meta) > 0 {
		b.WriteString(strings.Join(meta, "\n"))
		b.WriteString("\n\n")
	}

	mode := reportOpenMode(entry.Format)
	actions := []string{}
	if mode == "browser" {
		actions = append(actions, "enter/o open in browser")
	} else {
		actions = append(actions, "enter/o open in editor")
	}
	actions = append(actions, "e export copy", "y copy path", "Y copy snippet")
	b.WriteString("Actions: ")
	b.WriteString(strings.Join(actions, " • "))
	b.WriteString("\n\n")

	label, snippet := reportPreviewSnippet(entry)
	snippet = strings.TrimSpace(snippet)
	if snippet != "" {
		b.WriteString(label)
		b.WriteString(":\n")
		b.WriteString(snippet)
		b.WriteString("\n")
	} else {
		b.WriteString("No inline preview available. Use o to open the report.\n")
	}
	return b.String()
}

func reportPreviewSnippet(entry reportEntry) (string, string) {
	if entry.Source == "issue" {
		text := entry.Definition
		if strings.TrimSpace(text) == "" && entry.AbsPath != "" {
			text = readFileLimited(entry.AbsPath, maxPreviewBytes, maxPreviewLines)
		}
		return "Definition", trimMultiline(text, 24)
	}
	if strings.TrimSpace(entry.AbsPath) == "" {
		return "Content", ""
	}
	text := readFileLimited(entry.AbsPath, maxPreviewBytes, maxPreviewLines)
	if strings.EqualFold(entry.Format, "HTML") {
		text = stripHTMLTags(text)
	}
	return "Content", trimMultiline(text, 24)
}

func reportOpenMode(format string) string {
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "html", "htm":
		return "browser"
	default:
		return "editor"
	}
}

func (m *model) openReportEntry(entry reportEntry) {
	if m.currentProject == nil {
		m.setToast("Select a project first", 4*time.Second)
		return
	}
	if strings.TrimSpace(entry.AbsPath) == "" {
		m.setToast("Report path unavailable", 4*time.Second)
		return
	}
	if _, err := os.Stat(entry.AbsPath); err != nil {
		m.appendLog(fmt.Sprintf("Report not found: %s", entry.AbsPath))
		m.setToast("Report missing", 5*time.Second)
		return
	}
	mode := reportOpenMode(entry.Format)
	var (
		commandLine string
		err         error
	)
	if mode == "browser" {
		commandLine, err = launchBrowser(entry.AbsPath)
	} else {
		commandLine, err = launchEditor(entry.AbsPath)
	}
	if err != nil {
		m.appendLog(fmt.Sprintf("Failed to open report %s: %v", entry.RelPath, err))
		m.setToast("Failed to open report", 5*time.Second)
		return
	}
	if mode == "browser" {
		m.appendLog("Opening report in browser: " + commandLine)
		m.setToast("Opening report in browser", 4*time.Second)
	} else {
		m.appendLog("Opening report: " + commandLine)
		m.setToast("Opening report in editor", 4*time.Second)
	}
	if m.currentProject != nil {
		fields := map[string]string{
			"project": filepath.Clean(m.currentProject.Path),
			"report":  entry.Key,
			"format":  strings.ToLower(entry.Format),
			"source":  entry.Source,
			"mode":    mode,
		}
		if entry.RelPath != "" {
			fields["path"] = entry.RelPath
		}
		if !entry.Timestamp.IsZero() {
			fields["timestamp"] = entry.Timestamp.UTC().Format(time.RFC3339)
		}
		m.emitTelemetry("report_opened", fields)
	}
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

	done := 0
	blocks := make([]string, len(stats.Pipeline))
	for i, step := range stats.Pipeline {
		label := pipelineSteps[i].Label
		style := lipgloss.NewStyle()
		icon := "…"
		switch step.State {
		case pipelineStateDone:
			style = style.Bold(true)
			icon = "✓"
			done++
		case pipelineStateActive:
			style = style.Underline(true)
			icon = "●"
		default:
			style = style.Faint(true)
			icon = "…"
		}
		blocks[i] = style.Render("[" + icon + "] " + label)
	}
	total := len(stats.Pipeline)
	percent := 0.0
	if total > 0 {
		percent = float64(done) / float64(total)
	}
	bar := renderProgressBar(percent, 42)
	summary := fmt.Sprintf("Pipeline %d/%d\n%s\n", done, total, bar)
	return summary + strings.Join(blocks, "  ") + "\n"
}

func renderProgressBar(percent float64, width int) string {
	if percent < 0 {
		percent = 0
	} else if percent > 1 {
		percent = 1
	}
	if width <= 0 {
		width = 32
	}
	bar := progress.New(
		progress.WithDefaultGradient(),
		progress.WithWidth(width),
	)
	return bar.ViewAs(percent)
}

func formatElapsed(d time.Duration) string {
	if d <= 0 {
		return "0s"
	}
	if d < time.Second {
		return "<1s"
	}
	totalSeconds := int(d / time.Second)
	if totalSeconds < 60 {
		return fmt.Sprintf("%ds", totalSeconds)
	}
	totalMinutes := totalSeconds / 60
	if totalMinutes < 60 {
		seconds := totalSeconds % 60
		return fmt.Sprintf("%dm%02ds", totalMinutes, seconds)
	}
	hours := totalMinutes / 60
	minutes := totalMinutes % 60
	return fmt.Sprintf("%dh%02dm", hours, minutes)
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
