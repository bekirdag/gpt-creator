package main

import (
	"strings"
	"sync"

	"github.com/charmbracelet/glamour"
)

type markdownTheme string

const (
	markdownThemeAuto  markdownTheme = "auto"
	markdownThemeDark  markdownTheme = "dark"
	markdownThemeLight markdownTheme = "light"
)

var (
	markdownMu       sync.Mutex
	markdownRenderer *glamour.TermRenderer
	markdownErr      error
	markdownStyle    = markdownThemeAuto
	markdownWordWrap = 80
)

// RenderMarkdown returns Glamour-rendered terminal output for the provided Markdown.
func RenderMarkdown(content string) string {
	renderer := ensureMarkdownRenderer()
	if renderer == nil {
		return content
	}
	out, err := renderer.Render(content)
	if err != nil {
		return content
	}
	return out
}

func ensureMarkdownRenderer() *glamour.TermRenderer {
	markdownMu.Lock()
	defer markdownMu.Unlock()
	if markdownRenderer != nil && markdownErr == nil {
		return markdownRenderer
	}
	options := []glamour.TermRendererOption{
		glamour.WithAutoStyle(),
	}
	if markdownWordWrap > 0 {
		options = append(options, glamour.WithWordWrap(markdownWordWrap))
	} else {
		options = append(options, glamour.WithWordWrap(0))
	}
	switch markdownStyle {
	case markdownThemeLight:
		options = append(options, glamour.WithStandardStyle("light"))
	case markdownThemeDark:
		options = append(options, glamour.WithStandardStyle("dark"))
	}
	markdownRenderer, markdownErr = glamour.NewTermRenderer(options...)
	if markdownErr != nil {
		return nil
	}
	return markdownRenderer
}

func setMarkdownWordWrap(width int) {
	markdownMu.Lock()
	if width < 0 {
		width = 0
	}
	if markdownWordWrap != width {
		markdownWordWrap = width
		markdownRenderer = nil
		markdownErr = nil
	}
	markdownMu.Unlock()
}

func setMarkdownTheme(theme markdownTheme) {
	markdownMu.Lock()
	if theme == "" {
		theme = markdownThemeAuto
	}
	if markdownStyle != theme {
		markdownStyle = theme
		markdownRenderer = nil
		markdownErr = nil
	}
	markdownMu.Unlock()
}

func currentMarkdownTheme() markdownTheme {
	markdownMu.Lock()
	defer markdownMu.Unlock()
	return markdownStyle
}

func markdownThemeFromString(value string) markdownTheme {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "dark":
		return markdownThemeDark
	case "light":
		return markdownThemeLight
	case "auto":
		return markdownThemeAuto
	default:
		return markdownThemeAuto
	}
}

func (t markdownTheme) String() string {
	switch t {
	case markdownThemeDark:
		return "dark"
	case markdownThemeLight:
		return "light"
	default:
		return "auto"
	}
}

func markdownThemeLabel(theme markdownTheme) string {
	switch theme {
	case markdownThemeDark:
		return "Dark"
	case markdownThemeLight:
		return "Light"
	default:
		return "Auto"
	}
}

func nextMarkdownTheme(theme markdownTheme) markdownTheme {
	switch theme {
	case markdownThemeAuto:
		return markdownThemeDark
	case markdownThemeDark:
		return markdownThemeLight
	default:
		return markdownThemeAuto
	}
}
