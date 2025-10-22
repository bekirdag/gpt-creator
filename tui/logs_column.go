package main

import (
	"fmt"
	"math"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const (
	logsColumnWidth  = 88
	logsColumnHeight = 14
)

type logsColumn struct {
	model *model
	title string

	width  int
	height int

	panelStyle        lipgloss.Style
	panelFocusedStyle lipgloss.Style
	columnTitleStyle  lipgloss.Style
	scrollTrackStyle  lipgloss.Style
	scrollThumbStyle  lipgloss.Style

	panelFrameWidth  int
	panelFrameHeight int

	barWidth int

	contentWidth   int
	contentHeight  int
	contentOffsetX int
	contentOffsetY int
}

func newLogsColumn(m *model) *logsColumn {
	return &logsColumn{
		model:    m,
		title:    "Job / Logs / Status",
		barWidth: 1,
	}
}

func (c *logsColumn) ApplyStyles(s styles) {
	c.panelStyle = s.panel
	c.panelFocusedStyle = s.panelFocused
	c.columnTitleStyle = s.columnTitle
	c.scrollTrackStyle = s.statusHint.Copy().Foreground(crushForegroundFaint)
	c.scrollThumbStyle = s.cmdPrompt.Copy().Foreground(crushAccent)
	c.recalcMetrics()
}

func (c *logsColumn) SetSize(width, height int) {
	if width < 0 {
		width = 0
	}
	if height < 3 {
		height = 3
	}
	c.width = width
	c.height = height
	c.recalcMetrics()
}

func (c *logsColumn) recalcMetrics() {
	if c.model == nil {
		return
	}

	c.panelFrameWidth = maxInt(
		c.panelStyle.GetHorizontalFrameSize(),
		c.panelFocusedStyle.GetHorizontalFrameSize(),
	)
	c.panelFrameHeight = maxInt(
		c.panelStyle.GetVerticalFrameSize(),
		c.panelFocusedStyle.GetVerticalFrameSize(),
	)

	innerWidth := c.width - c.panelFrameWidth
	if innerWidth < c.barWidth+1 {
		innerWidth = c.barWidth + 1
	}
	c.contentWidth = innerWidth - c.barWidth
	if c.contentWidth < 1 {
		c.contentWidth = 1
	}

	innerHeight := c.height - c.panelFrameHeight
	if innerHeight < 1 {
		innerHeight = 1
	}

	titleFrame := horizontalInnerFrameSize(c.columnTitleStyle)
	titleWidth := columnHeaderWidth(c.width, c.panelFrameWidth, titleFrame)
	if titleWidth < 1 {
		titleWidth = 1
	}
	title := c.columnTitleStyle.Width(titleWidth).Render(c.title)
	titleHeight := lipgloss.Height(title)
	if titleHeight < 1 {
		titleHeight = 1
	}

	c.contentHeight = innerHeight - titleHeight
	if c.contentHeight < 1 {
		c.contentHeight = 1
	}

	panelLeft := maxInt(
		c.panelStyle.GetBorderLeftSize()+c.panelStyle.GetPaddingLeft(),
		c.panelFocusedStyle.GetBorderLeftSize()+c.panelFocusedStyle.GetPaddingLeft(),
	)
	panelTop := maxInt(
		c.panelStyle.GetBorderTopSize()+c.panelStyle.GetPaddingTop(),
		c.panelFocusedStyle.GetBorderTopSize()+c.panelFocusedStyle.GetPaddingTop(),
	)
	c.contentOffsetX = panelLeft
	c.contentOffsetY = panelTop + titleHeight

	if c.model.logs.Width != c.contentWidth {
		c.model.logs.Width = c.contentWidth
	}
	if c.model.logs.Height != c.contentHeight {
		c.model.logs.Height = c.contentHeight
	}
	maxOffset := len(c.model.logLines) - c.model.logs.Height
	if maxOffset < 0 {
		maxOffset = 0
	}
	if c.model.logs.YOffset > maxOffset {
		c.model.logs.SetYOffset(maxOffset)
	}
}

func (c *logsColumn) Update(msg tea.Msg) (column, tea.Cmd) {
	return c, nil
}

func (c *logsColumn) View(s styles, focused bool) string {
	panel := c.panelStyle
	bg := crushSurface
	if focused {
		panel = c.panelFocusedStyle
		bg = crushSurfaceElevated
	}

	titleFrame := horizontalInnerFrameSize(c.columnTitleStyle)
	titleWidth := columnHeaderWidth(c.width, c.panelFrameWidth, titleFrame)
	if titleWidth < 1 {
		titleWidth = 1
	}
	title := c.columnTitleStyle.Width(titleWidth).Render(c.title)
	headerLines := lipgloss.Height(title)
	content := c.renderContent()
	body := lipgloss.JoinVertical(lipgloss.Left, title, content)
	return renderPanelWithScroll(panel, c.width, c.height, 0, body, bg, headerLines)
}

func (c *logsColumn) renderContent() string {
	if c.model == nil {
		return ""
	}
	view := c.model.logs.View()
	lines := strings.Split(view, "\n")
	height := c.contentHeight
	if height < 1 {
		height = len(lines)
	}
	if len(lines) < height {
		for len(lines) < height {
			lines = append(lines, "")
		}
	} else if len(lines) > height {
		lines = lines[:height]
	}

	bar := c.renderScrollBar(height)
	for i := 0; i < height && i < len(lines); i++ {
		lines[i] = bar[i] + lines[i]
	}
	return strings.Join(lines, "\n")
}

func (c *logsColumn) renderScrollBar(height int) []string {
	lines := make([]string, height)
	track := c.scrollTrackStyle.Render("│")
	thumb := c.scrollThumbStyle.Render("│")

	total := c.model.logs.TotalLineCount()
	if total <= 0 {
		for i := range lines {
			lines[i] = track
		}
		return lines
	}

	if height <= 0 {
		return lines
	}

	visible := c.model.logs.Height
	if visible <= 0 {
		visible = height
	}

	if total <= visible {
		for i := range lines {
			lines[i] = track
		}
		return lines
	}

	thumbHeight := int(math.Round(float64(visible) / float64(total) * float64(height)))
	if thumbHeight < 1 {
		thumbHeight = 1
	}
	maxOffset := total - visible
	if maxOffset < 1 {
		maxOffset = 1
	}
	offset := c.model.logs.YOffset
	if offset < 0 {
		offset = 0
	}
	if offset > maxOffset {
		offset = maxOffset
	}
	ratio := float64(offset) / float64(maxOffset)
	thumbStart := int(math.Round(ratio * float64(height-thumbHeight)))
	if thumbStart < 0 {
		thumbStart = 0
	}
	if thumbStart+thumbHeight > height {
		thumbStart = height - thumbHeight
	}
	for i := 0; i < height; i++ {
		if i >= thumbStart && i < thumbStart+thumbHeight {
			lines[i] = thumb
		} else {
			lines[i] = track
		}
	}
	return lines
}

func (c *logsColumn) Title() string {
	return c.title
}

func (c *logsColumn) FocusValue() string {
	if c.model == nil {
		return ""
	}
	total := len(c.model.logLines)
	if total == 0 {
		return "Idle"
	}
	if c.model.logsSelectionActive && c.model.logsSelectionCursor >= 0 && c.model.logsSelectionCursor < total {
		return fmt.Sprintf("Line %d/%d", c.model.logsSelectionCursor+1, total)
	}
	start := c.model.logs.YOffset + 1
	end := start + c.model.logs.Height - 1
	if end > total {
		end = total
	}
	if start < 1 {
		start = 1
	}
	return fmt.Sprintf("Showing %d-%d/%d", start, end, total)
}

func (c *logsColumn) ScrollHorizontal(int) bool {
	return false
}

func (c *logsColumn) HandleMouse(localX, localY int, msg tea.MouseMsg) (column, tea.Cmd) {
	if c.model == nil {
		return c, nil
	}
	switch msg.Type {
	case tea.MouseWheelUp, tea.MouseWheelDown:
		var cmd tea.Cmd
		c.model.logs, cmd = c.model.logs.Update(msg)
		if c.model.logsSelectionActive {
			c.model.ensureLogCursorVisible()
		}
		return c, cmd
	case tea.MouseLeft:
		if len(c.model.logLines) == 0 {
			return c, nil
		}
		if localY < c.contentOffsetY {
			return c, nil
		}
		row := localY - c.contentOffsetY
		if row < 0 {
			row = 0
		}
		if row >= c.contentHeight {
			row = c.contentHeight - 1
		}
		index := c.model.logs.YOffset + row
		if index < 0 {
			index = 0
		}
		if index >= len(c.model.logLines) {
			index = len(c.model.logLines) - 1
		}
		if !c.model.logsSelectionActive {
			c.model.logsSelectionActive = true
			c.model.logsSelectionAnchor = index
		}
		c.model.logsSelectionCursor = index
		c.model.refreshLogs()
		c.model.ensureLogCursorVisible()
		return c, nil
	}
	return c, nil
}

func (c *logsColumn) CanMoveDown() bool {
	if c.model == nil {
		return false
	}
	if c.model.logsSelectionActive {
		return c.model.logsSelectionCursor < len(c.model.logLines)-1
	}
	return !c.model.logs.AtBottom()
}
