package main

import "github.com/charmbracelet/lipgloss"

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
	cmdOverlay, cmdPrompt, cmdHint     lipgloss.Style
}

func newStyles() styles {
	base := lipgloss.NewStyle()
	panelBorder := lipgloss.NormalBorder()
	focusedBorder := lipgloss.DoubleBorder()

	return styles{
		app:            base,
		topBar:         base.Padding(0, 1),
		topMenu:        base,
		topStatus:      base,
		sidebar:        base.BorderStyle(panelBorder),
		sidebarTitle:   base.Copy().Bold(true).Padding(0, 1),
		columnTitle:    base.Copy().Bold(true).Padding(0, 1),
		body:           base,
		panel:          base.BorderStyle(panelBorder),
		panelFocused:   base.BorderStyle(focusedBorder),
		tabActive:      base.Copy().Bold(true).Padding(0, 1),
		tabInactive:    base.Padding(0, 1),
		tabsRow:        base.Padding(0, 1),
		breadcrumbs:    base.Padding(0, 1),
		statusBar:      base.Padding(0, 1),
		statusSeg:      base.Padding(0, 1).MarginRight(1),
		statusHint:     base,
		listItem:       base.Padding(0, 1),
		listSel:        base.Padding(0, 1).Bold(true),
		rightPaneTitle: base.Copy().Bold(true).Padding(0, 1),
		cmdOverlay:     base.Border(lipgloss.RoundedBorder()).Padding(1, 2),
		cmdPrompt:      base.Copy().Bold(true),
		cmdHint:        base.Copy().Faint(true),
	}
}
