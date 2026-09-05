package main

import (
	"fmt"
	"image/color"
	"os"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

type screen int

const (
	home screen = iota
	groups
	decisions
	quarantine
	restore
	history
	help
)

type destination struct {
	icon, label, hint string
	page              screen
}

var destinations = []destination{
	{"✦", "Home", "mission control", home},
	{"◉", "Duplicate Groups", "explore constellations", groups},
	{"★", "Keeper Decisions", "choose the originals", decisions},
	{"◇", "Quarantine", "stage a safe voyage", quarantine},
	{"↶", "Restore", "bring files home", restore},
	{"≋", "History", "read the flight log", history},
	{"?", "Help", "keys and safety model", help},
}

type model struct {
	width, height int
	selected      int
	page          screen
	compact       bool
}

var (
	ink       = lipgloss.Color("#EDE9FF")
	muted     = lipgloss.Color("#918AAE")
	void      = lipgloss.Color("#090715")
	panel     = lipgloss.Color("#17112B")
	purple    = lipgloss.Color("#A855F7")
	cyan      = lipgloss.Color("#22D3EE")
	pink      = lipgloss.Color("#FF4FD8")
	lime      = lipgloss.Color("#B8FF65")
	gold      = lipgloss.Color("#FFD166")
	danger    = lipgloss.Color("#FF5C7A")
	logoStyle = lipgloss.NewStyle().Bold(true).Foreground(pink)
	mutedText = lipgloss.NewStyle().Foreground(muted)
	keyStyle  = lipgloss.NewStyle().Bold(true).Foreground(void).Background(cyan).Padding(0, 1)
)

func (m model) Init() tea.Cmd { return nil }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.compact = msg.Width < 96
	case tea.KeyPressMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "up", "k":
			if m.selected > 0 { m.selected-- }
		case "down", "j":
			if m.selected < len(destinations)-1 { m.selected++ }
		case "enter", "right", "l":
			m.page = destinations[m.selected].page
		case "esc", "left", "h":
			m.page = home
		case "1", "2", "3", "4", "5", "6", "7":
			i := int(msg.String()[0] - '1')
			m.selected, m.page = i, destinations[i].page
		}
	}
	return m, nil
}

func frame(title, subtitle, body string, width int, accent color.Color) string {
	w := max(28, width-4)
	header := lipgloss.NewStyle().Bold(true).Foreground(accent).Render(title)
	sub := mutedText.Render(subtitle)
	return lipgloss.NewStyle().
		Width(w).Border(lipgloss.RoundedBorder()).BorderForeground(accent).
		Background(panel).Foreground(ink).Padding(1, 2).
		Render(header + "\n" + sub + "\n\n" + body)
}

func metric(icon, value, label string, color color.Color) string {
	return lipgloss.NewStyle().Width(20).Padding(1, 2).
		Border(lipgloss.RoundedBorder()).BorderForeground(color).
		Render(lipgloss.NewStyle().Bold(true).Foreground(color).Render(icon+"  "+value) + "\n" + mutedText.Render(label))
}

func (m model) sidebar() string {
	rows := []string{logoStyle.Render("✦ ARCHIVE KEEPER"), mutedText.Render("  STORAGE GALAXY 2.0"), ""}
	for i, item := range destinations {
		label := fmt.Sprintf("%s  %-18s", item.icon, item.label)
		style := lipgloss.NewStyle().Width(23).Padding(0, 1).Foreground(muted)
		if i == m.selected {
			style = style.Bold(true).Foreground(void).Background(purple)
		}
		rows = append(rows, style.Render(label))
	}
	rows = append(rows, "", mutedText.Render("↑↓ navigate  ↵ open"), mutedText.Render("q exit · ? help"))
	return lipgloss.NewStyle().Width(27).Height(max(18, m.height-4)).
		Border(lipgloss.RoundedBorder()).BorderForeground(purple).
		Background(void).Padding(1).Render(strings.Join(rows, "\n"))
}

func homeView(width int) string {
	metrics := lipgloss.JoinHorizontal(lipgloss.Top,
		metric("◉", "—", "duplicate groups", cyan),
		metric("★", "—", "keeper decisions", lime),
		metric("◇", "—", "recoverable space", pink),
	)
	body := "Your storage universe, charted without moving a single byte.\n\n" + metrics +
		"\n\n" + lipgloss.NewStyle().Bold(true).Foreground(gold).Render("NEXT SAFE STEP") +
		"\nConnect the Python engine, load the rmlint report, then review keeper choices before staging quarantine."
	return frame("MISSION CONTROL", "Read-only overview · no files move from this screen", body, width, pink)
}

func pageView(page screen, width int) string {
	spec := map[screen][3]string{
		groups: {"DUPLICATE CONSTELLATIONS", "Browse groups by size, type, location, or confidence", "Group list and side-by-side copy inspector\n\nFilters  / search  ·  Space  potential  ·  Copies  path map\n\nEvery group keeps at least one verified original."},
		decisions: {"KEEPER ORBIT", "Choose what remains and understand why", "★ KEEP      selected original\n◇ QUARANTINE staged duplicate\n? UNDECIDED  requires attention\n\nManual decisions persist in decisions.sqlite3."},
		quarantine: {"QUARANTINE AIRLOCK", "Preview first; mutation always requires explicit confirmation", "1  Inspect the generated plan\n2  Run a bounded dry pilot\n3  Verify source and keeper\n4  Confirm --apply\n\nSafety interlocks remain owned by the Python engine."},
		restore: {"RESTORE BEACON", "Bring a quarantined file home without overwriting data", "Select a run from history, preview destinations, inspect collisions, then confirm restoration.\n\nDifferent-content collisions fail closed."},
		history: {"FLIGHT RECORDER", "Journaled actions, outcomes, retries, and recovery", "Runs will appear here with moved, reconciled, stale, timeout, failed, and restored counts.\n\nOperational source: journal.sqlite3"},
		help: {"GALACTIC FIELD GUIDE", "Navigation and non-negotiable safety rules", "↑↓ or j/k  navigate\nEnter       open\nEsc or h    home\n1–7         jump to screen\nq           quit\n\nColor is never the only status signal. Destructive actions require words, state, and confirmation."},
	}
	v := spec[page]
	return frame(v[0], v[1], v[2], width, cyan)
}

func (m model) View() tea.View {
	contentWidth := max(34, m.width-34)
	content := homeView(contentWidth)
	if m.page != home { content = pageView(m.page, contentWidth) }
	var rendered string
	if m.compact {
		rendered = logoStyle.Render("✦ ARCHIVE KEEPER · STORAGE GALAXY 2.0") + "\n" +
			mutedText.Render("1 Home · 2 Groups · 3 Keepers · 4 Quarantine · 5 Restore · 6 History · 7 Help") +
			"\n\n" + content
	} else {
		rendered = lipgloss.JoinHorizontal(lipgloss.Top, m.sidebar(), "  ", content)
	}
	footer := "\n" + keyStyle.Render(" SAFE BY DEFAULT ") + " " +
		lipgloss.NewStyle().Foreground(lime).Render("READ-ONLY") + "  " +
		mutedText.Render("Python engine offline · connect milestone next")
	v := tea.NewView(lipgloss.NewStyle().Background(void).Foreground(ink).Padding(1).Render(rendered + footer))
	v.AltScreen = true
	v.MouseMode = tea.MouseModeCellMotion
	v.WindowTitle = "Archive Keeper · Storage Galaxy"
	v.BackgroundColor = void
	v.ForegroundColor = ink
	return v
}

func main() {
	p := tea.NewProgram(model{page: home})
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "archive-keeper-ui:", err)
		os.Exit(1)
	}
}
