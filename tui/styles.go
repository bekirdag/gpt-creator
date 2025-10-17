package main

import "github.com/charmbracelet/lipgloss"

type colorPalette struct {
	bg, surface, muted, text, textMuted           lipgloss.Color
	primary, success, warning, danger, info       lipgloss.Color
	accent1, accent2, accent3, accent4, focusRing lipgloss.Color
	selection, border, shadow                     lipgloss.Color
}

var palette = colorPalette{
	bg:        lipgloss.Color("#F7F7FA"),
	surface:   lipgloss.Color("#FFFFFF"),
	muted:     lipgloss.Color("#EEF1F6"),
	text:      lipgloss.Color("#3A3A3A"),
	textMuted: lipgloss.Color("#6E6E6E"),

	primary: lipgloss.Color("#7EB6FF"),
	success: lipgloss.Color("#9EE6A0"),
	warning: lipgloss.Color("#FFD59E"),
	danger:  lipgloss.Color("#FFB3B3"),
	info:    lipgloss.Color("#BFD9FF"),

	accent1:   lipgloss.Color("#C7E9FF"),
	accent2:   lipgloss.Color("#FFE6F2"),
	accent3:   lipgloss.Color("#EAE7FF"),
	accent4:   lipgloss.Color("#E8FFF2"),
	focusRing: lipgloss.Color("#7EB6FF"),
	selection: lipgloss.Color("#DCEBFF"),

	border: lipgloss.Color("#D8DDE5"),
	shadow: lipgloss.Color("#C9D2E0"),
}

type styles struct {
	app, topBar, topMenu, topStatus    lipgloss.Style
	sidebar, sidebarTitle, columnTitle lipgloss.Style
	body                               lipgloss.Style
	panel, panelFocused                lipgloss.Style
	tabActive, tabInactive             lipgloss.Style
	tabsRow                            lipgloss.Style
	breadcrumbs                        lipgloss.Style
	statusBar, statusSeg, statusHint   lipgloss.Style
	listItem, listSel                  lipgloss.Style
	rightPaneTitle                     lipgloss.Style
	cmdOverlay, cmdPrompt              lipgloss.Style
}

func newStyles() styles {
	border := lipgloss.NormalBorder()
	return styles{
		app: lipgloss.NewStyle().
			Background(palette.bg).
			Foreground(palette.text),

		topBar: lipgloss.NewStyle().
			Background(palette.surface).
			Foreground(palette.text).
			Padding(0, 1),

		topMenu: lipgloss.NewStyle().
			Foreground(palette.textMuted),

		topStatus: lipgloss.NewStyle().
			Foreground(palette.textMuted),

		sidebar: lipgloss.NewStyle().
			Background(palette.surface).
			BorderStyle(border).
			BorderForeground(palette.border),

		sidebarTitle: lipgloss.NewStyle().
			Bold(true).
			Foreground(palette.textMuted).
			Padding(0, 1),

		columnTitle: lipgloss.NewStyle().
			Bold(true).
			Foreground(palette.textMuted).
			Padding(0, 1),

		body: lipgloss.NewStyle(),

		panel: lipgloss.NewStyle().
			Background(palette.surface).
			BorderStyle(border).
			BorderForeground(palette.border),

		panelFocused: lipgloss.NewStyle().
			Background(palette.surface).
			BorderStyle(border).
			BorderForeground(palette.focusRing),

		tabActive: lipgloss.NewStyle().
			Bold(true).
			Foreground(palette.text).
			Background(palette.surface).
			BorderStyle(lipgloss.Border{
				Top:         " ",
				Bottom:      "━",
				Left:        " ",
				Right:       " ",
				TopLeft:     " ",
				TopRight:    " ",
				BottomLeft:  " ",
				BottomRight: " ",
			}).
			BorderForeground(palette.focusRing).
			Padding(0, 1),

		tabInactive: lipgloss.NewStyle().
			Foreground(palette.textMuted).
			Background(palette.muted).
			Padding(0, 1),

		tabsRow: lipgloss.NewStyle().
			Background(palette.muted).
			Padding(0, 1),

		breadcrumbs: lipgloss.NewStyle().
			Background(palette.muted).
			Foreground(palette.textMuted).
			Padding(0, 1),

		statusBar: lipgloss.NewStyle().
			Background(palette.surface).
			Foreground(palette.textMuted).
			Padding(0, 1),

		statusSeg: lipgloss.NewStyle().
			Padding(0, 1).
			MarginRight(1).
			Background(palette.surface).
			Foreground(palette.text),

		statusHint: lipgloss.NewStyle().
			Foreground(palette.textMuted),

		listItem: lipgloss.NewStyle().
			Padding(0, 1),

		listSel: lipgloss.NewStyle().
			Background(palette.selection).
			Foreground(palette.text),

		rightPaneTitle: lipgloss.NewStyle().
			Bold(true).
			Foreground(palette.textMuted).
			Padding(0, 1),

		cmdOverlay: lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(palette.focusRing).
			Background(palette.surface).
			Padding(1, 2),

		cmdPrompt: lipgloss.NewStyle().
			Bold(true).
			Foreground(palette.primary),
	}
}
