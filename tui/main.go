package main

import (
	"flag"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	theme := flag.String("theme", "auto", "Markdown rendering theme: auto, light, or dark")
	flag.Parse()
	setMarkdownTheme(markdownThemeFromString(*theme))

	if _, err := tea.NewProgram(
		initialModel(),
		tea.WithAltScreen(),
		tea.WithMouseCellMotion(),
	).Run(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
