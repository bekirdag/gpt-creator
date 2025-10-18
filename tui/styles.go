package main

import "github.com/charmbracelet/lipgloss"

var (
	crushBackground      = lipgloss.Color("#0B0D1E")
	crushSurface         = lipgloss.Color("#161A31")
	crushSurfaceElevated = lipgloss.Color("#20263F")
	crushSurfaceSoft     = lipgloss.Color("#1C2136")
	crushSurfacePassive  = crushSurfaceElevated
	crushDanger          = lipgloss.Color("#B42323")

	crushForeground      = lipgloss.Color("#F8F9FF")
	crushForegroundMuted = lipgloss.Color("#A1A2C3")
	crushForegroundFaint = lipgloss.Color("#6E6A89")

	crushPrimary       = lipgloss.Color("#9D7DFF")
	crushPrimaryBright = lipgloss.Color("#C7ADFF")
	crushAccent        = lipgloss.Color("#5DE4C7")

	crushBorder       = lipgloss.Color("#2F3253")
	crushBorderSoft   = lipgloss.Color("#24273D")
	crushBorderActive = lipgloss.Color("#7F5AF0")
)

type styles struct {
	app, topBar, topMenu, topStatus     lipgloss.Style
	headerLogo, headerInfo              lipgloss.Style
	headerBreadcrumb, headerSearch      lipgloss.Style
	headerSearchHint                    lipgloss.Style
	sidebar, sidebarTitle, columnTitle  lipgloss.Style
	body                                lipgloss.Style
	panel, panelFocused                 lipgloss.Style
	tabActive, tabInactive              lipgloss.Style
	tabsRow                             lipgloss.Style
	breadcrumbs                         lipgloss.Style
	statusBar, statusSeg, statusHint    lipgloss.Style
	tableHeader, tableCell, tableActive lipgloss.Style
	listItem, listSel, textBlock        lipgloss.Style
	rightPaneTitle                      lipgloss.Style
	cmdOverlay, cmdPrompt, cmdHint      lipgloss.Style
}

func newStyles() styles {
	base := lipgloss.NewStyle().Foreground(crushForeground)

	topBarBorder := lipgloss.Border{
		Left:        " ",
		Right:       " ",
		Top:         " ",
		Bottom:      "─",
		TopLeft:     " ",
		TopRight:    " ",
		BottomLeft:  "╰",
		BottomRight: "╯",
	}

	panelBorder := lipgloss.RoundedBorder()

	panelStyle := base.Copy().
		Background(crushSurface).
		BorderStyle(panelBorder).
		BorderForeground(crushBorder).
		Padding(0, 1)

	panelFocusedStyle := panelStyle.Copy().
		Background(crushSurfaceElevated).
		BorderForeground(crushBorderActive)

	listHighlight := base.Copy().
		Bold(true).
		Foreground(crushForeground).
		Background(crushSurfaceElevated).
		ColorWhitespace(true).
		BorderStyle(lipgloss.Border{
			Left:        "┃",
			Right:       " ",
			Top:         " ",
			Bottom:      " ",
			TopLeft:     "┃",
			BottomLeft:  "┃",
			TopRight:    " ",
			BottomRight: " ",
		}).
		BorderLeft(true).
		BorderForeground(crushAccent).
		Padding(0, 1)

	return styles{
		app: base.Copy().
			Background(crushBackground),
		topBar: base.Copy().
			Bold(true).
			Background(crushSurfaceElevated).
			Padding(0, 2).
			BorderStyle(topBarBorder).
			BorderBottom(true).
			BorderForeground(crushBorder),
		topMenu: base.Copy().
			Foreground(crushPrimaryBright),
		topStatus: base.Copy().
			Foreground(crushForegroundMuted),
		headerLogo: base.Copy().
			Foreground(crushPrimaryBright).
			Bold(true).
			MarginRight(3),
		headerInfo: base.Copy().
			MarginLeft(2),
		headerBreadcrumb: base.Copy().
			Bold(true).
			Foreground(crushForeground).
			Background(crushSurfaceSoft).
			Padding(0, 1).
			MarginBottom(1),
		headerSearch: base.Copy().
			Foreground(crushForeground).
			Background(crushSurfaceElevated).
			Padding(0, 2),
		headerSearchHint: base.Copy().
			Foreground(crushForegroundMuted).
			MarginTop(1),
		sidebar: panelStyle,
		sidebarTitle: base.Copy().
			Foreground(crushPrimaryBright).
			Bold(true).
			Padding(0, 0),
		columnTitle: base.Copy().
			Bold(true).
			Foreground(crushForeground).
			Background(crushSurfaceElevated).
			Padding(0, 0, 0, 0).
			BorderStyle(lipgloss.Border{
				Left:        " ",
				Right:       " ",
				Top:         " ",
				Bottom:      "═",
				TopLeft:     " ",
				TopRight:    " ",
				BottomLeft:  "╞",
				BottomRight: "╡",
			}).
			BorderBottom(true).
			BorderForeground(crushBorderActive),
		body:         base.Copy(),
		panel:        panelStyle,
		panelFocused: panelFocusedStyle,
		tabActive: base.Copy().
			Bold(true).
			Foreground(crushForeground).
			Background(crushSurfaceElevated).
			Padding(0, 2).
			BorderStyle(lipgloss.NormalBorder()).
			BorderBottom(false).
			BorderForeground(crushBorderActive),
		tabInactive: base.Copy().
			Foreground(crushForegroundMuted).
			Background(crushSurface).
			Padding(0, 2),
		tabsRow: base.Copy().
			Background(crushSurface).
			Foreground(crushForegroundMuted).
			Padding(0, 1),
		breadcrumbs: base.Copy().
			Foreground(crushForegroundMuted).
			Padding(0, 1).
			Margin(0, 0, 1, 0),
		statusBar: base.Copy().
			Foreground(crushForegroundMuted).
			Background(crushSurfaceElevated).
			Padding(0, 2).
			BorderStyle(lipgloss.Border{
				Left:        " ",
				Right:       " ",
				Top:         "─",
				Bottom:      " ",
				TopLeft:     "╭",
				TopRight:    "╮",
				BottomLeft:  " ",
				BottomRight: " ",
			}).
			BorderTop(true).
			BorderForeground(crushBorder),
		statusSeg: base.Copy().
			Foreground(crushForeground).
			Background(crushSurfaceElevated).
			Padding(0, 1).
			MarginRight(1),
		statusHint: base.Copy().
			Foreground(crushForegroundFaint),
		tableHeader: base.Copy().
			Foreground(crushPrimaryBright).
			Background(crushSurfaceSoft).
			Bold(true).
			Padding(0, 1).
			BorderStyle(lipgloss.Border{
				Left:        " ",
				Right:       " ",
				Top:         " ",
				Bottom:      "─",
				TopLeft:     " ",
				TopRight:    " ",
				BottomLeft:  "╶",
				BottomRight: "╴",
			}).
			BorderBottom(true).
			BorderForeground(crushBorderSoft),
		tableCell: base.Copy().
			Foreground(crushForegroundMuted).
			Background(crushSurface).
			ColorWhitespace(true).
			Padding(0, 1),
		tableActive: base.Copy().
			Foreground(crushForeground).
			Background(crushSurfaceElevated).
			Bold(true).
			ColorWhitespace(true).
			Padding(0, 1),
		listItem: base.Copy().
			Foreground(crushForegroundMuted).
			Background(crushSurface).
			ColorWhitespace(true).
			Padding(0, 1),
		textBlock: base.Copy().
			Foreground(crushForeground).
			Background(crushSurface).
			ColorWhitespace(true).
			Padding(0, 1),
		listSel: listHighlight,
		rightPaneTitle: base.Copy().
			Bold(true).
			Foreground(crushPrimary).
			Padding(0, 1),
		cmdOverlay: base.Copy().
			Background(crushSurface).
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(crushAccent).
			Padding(1, 2),
		cmdPrompt: base.Copy().
			Bold(true).
			Foreground(crushAccent),
		cmdHint: base.Copy().
			Foreground(crushForegroundMuted).
			Faint(true),
	}
}

func (s styles) renderText(width int, content string) string {
	if width < 1 {
		width = 1
	}
	return s.textBlock.Copy().Width(width).Render(content)
}
