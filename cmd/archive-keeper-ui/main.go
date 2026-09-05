package main

import (
	"encoding/json"
	"fmt"
	"image/color"
	"os"
	"os/exec"
	"strconv"
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
	dashboard     dashboardSnapshot
	loading       bool
	loadErr       error
	contentFocus  bool
	groupCursor   int
	fileCursor    int
	inspecting    bool
	confirmKeeper bool
	savingKeeper  bool
	statusMessage string
}

type dashboardSnapshot struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	Mode            string `json:"mode"`
	Version         string `json:"archive_keeper_version"`
	Report          struct {
		Path             string `json:"path"`
		Exists           bool   `json:"exists"`
		Groups           int    `json:"groups"`
		Files            int    `json:"files"`
		RecoverableHuman string `json:"recoverable_human"`
		LargestGroups    []struct {
			GroupID          int    `json:"group_id"`
			Copies           int    `json:"copies"`
			RecoverableHuman string `json:"recoverable_human"`
			SamplePath       string `json:"sample_path"`
			Files            []struct {
				Path         string `json:"path"`
				SizeHuman    string `json:"size_human"`
				OriginalHint bool   `json:"original_hint"`
				Checksum     string `json:"checksum"`
			} `json:"files"`
		} `json:"largest_groups"`
	} `json:"report"`
	Decisions struct {
		Exists        bool           `json:"exists"`
		Keepers       int            `json:"keepers"`
		FileDecisions int            `json:"file_decisions"`
		Favorites     int            `json:"favorites"`
		Actions       map[string]int `json:"actions"`
	} `json:"decisions"`
	Journal struct {
		Exists       bool           `json:"exists"`
		Runs         int            `json:"runs"`
		StatusCounts map[string]int `json:"status_counts"`
		LatestRuns   []struct {
			RunID  string `json:"run_id"`
			Mode   string `json:"mode"`
			Status string `json:"status"`
		} `json:"latest_runs"`
	} `json:"journal"`
	Warnings []string `json:"warnings"`
}

type dashboardLoadedMsg struct {
	snapshot dashboardSnapshot
	err      error
}

type keeperSavedMsg struct {
	groupID int
	path    string
	err     error
}

type keeperResult struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	Error           string `json:"error"`
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

func loadDashboard() tea.Msg {
	python := os.Getenv("ARCHIVE_KEEPER_PYTHON")
	if python == "" {
		python = "python3"
	}
	args := []string{"-m", "archive_keeper.ui_bridge", "dashboard"}
	for _, setting := range []struct{ env, flag string }{
		{"ARCHIVE_KEEPER_REPORT", "--report"},
		{"ARCHIVE_KEEPER_STATE_DB", "--state-db"},
		{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
	} {
		if value := os.Getenv(setting.env); value != "" {
			args = append(args, setting.flag, value)
		}
	}
	output, err := exec.Command(python, args...).Output()
	if err != nil {
		return dashboardLoadedMsg{err: fmt.Errorf("bridge command: %w", err)}
	}
	var snapshot dashboardSnapshot
	if err := json.Unmarshal(output, &snapshot); err != nil {
		return dashboardLoadedMsg{err: fmt.Errorf("bridge JSON: %w", err)}
	}
	if snapshot.ProtocolVersion != 1 {
		return dashboardLoadedMsg{err: fmt.Errorf("unsupported bridge protocol %d", snapshot.ProtocolVersion)}
	}
	return dashboardLoadedMsg{snapshot: snapshot}
}

func bridgeArgs(command string) (string, []string) {
	python := os.Getenv("ARCHIVE_KEEPER_PYTHON")
	if python == "" {
		python = "python3"
	}
	args := []string{"-m", "archive_keeper.ui_bridge", command}
	return python, args
}

func saveKeeper(groupID int, path string) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("select-keeper")
		for _, setting := range []struct{ env, flag string }{
			{"ARCHIVE_KEEPER_REPORT", "--report"},
			{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
		} {
			if value := os.Getenv(setting.env); value != "" {
				args = append(args, setting.flag, value)
			}
		}
		args = append(args, "--group-id", strconv.Itoa(groupID), "--keeper", path)
		output, err := exec.Command(python, args...).CombinedOutput()
		var result keeperResult
		if jsonErr := json.Unmarshal(output, &result); jsonErr != nil {
			if err != nil {
				return keeperSavedMsg{groupID, path, fmt.Errorf("bridge command: %w", err)}
			}
			return keeperSavedMsg{groupID, path, fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !result.OK {
			message := result.Error
			if message == "" {
				message = "keeper decision was not saved"
			}
			return keeperSavedMsg{groupID, path, fmt.Errorf("%s", message)}
		}
		return keeperSavedMsg{groupID: groupID, path: path}
	}
}

func (m model) Init() tea.Cmd { return loadDashboard }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case dashboardLoadedMsg:
		m.loading = false
		m.dashboard = msg.snapshot
		m.loadErr = msg.err
	case keeperSavedMsg:
		m.savingKeeper = false
		m.confirmKeeper = false
		if msg.err != nil {
			m.statusMessage = "SAVE FAILED · " + msg.err.Error()
			return m, nil
		}
		m.statusMessage = fmt.Sprintf("KEEPER SAVED · Group %d · no files moved", msg.groupID)
		return m, loadDashboard
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.compact = msg.Width < 96
	case tea.KeyPressMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "1", "2", "3", "4", "5", "6", "7":
			i := int(msg.String()[0] - '1')
			m.selected, m.page = i, destinations[i].page
			m.contentFocus = m.page == groups
			m.inspecting = false
			m.fileCursor = 0
			return m, nil
		}
		if m.page == groups && m.contentFocus {
			if m.confirmKeeper {
				switch msg.String() {
				case "y", "enter":
					if !m.savingKeeper {
						group := m.dashboard.Report.LargestGroups[m.groupCursor]
						file := group.Files[m.fileCursor]
						m.savingKeeper = true
						m.statusMessage = "SAVING KEEPER DECISION…"
						return m, saveKeeper(group.GroupID, file.Path)
					}
				case "n", "esc", "left", "h":
					m.confirmKeeper = false
					m.statusMessage = "Keeper selection cancelled"
				}
				return m, nil
			}
			switch msg.String() {
			case "up", "k":
				if m.inspecting {
					if m.fileCursor > 0 {
						m.fileCursor--
					}
				} else if m.groupCursor > 0 {
					m.groupCursor--
				}
			case "down", "j":
				if m.inspecting {
					files := m.currentGroupFiles()
					if m.fileCursor < len(files)-1 {
						m.fileCursor++
					}
				} else if m.groupCursor < len(m.dashboard.Report.LargestGroups)-1 {
					m.groupCursor++
				}
			case "enter", "right", "l":
				if m.inspecting {
					m.confirmKeeper = true
					m.statusMessage = "Confirm keeper selection"
				} else if len(m.dashboard.Report.LargestGroups) > 0 {
					m.inspecting = true
					m.fileCursor = 0
				}
			case "esc", "left", "h":
				if m.inspecting {
					m.inspecting = false
					m.fileCursor = 0
				} else {
					m.contentFocus = false
				}
			}
			return m, nil
		}
		switch msg.String() {
		case "up", "k":
			if m.selected > 0 { m.selected-- }
		case "down", "j":
			if m.selected < len(destinations)-1 { m.selected++ }
		case "enter", "right", "l":
			m.page = destinations[m.selected].page
			m.contentFocus = m.page == groups
		case "esc", "left", "h":
			m.page = home
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


func dashboardValue(ready bool, value int) string {
	if !ready {
		return "—"
	}
	return strconv.Itoa(value)
}

func compactPath(path string, width int) string {
	characters := []rune(path)
	if width < 5 || len(characters) <= width {
		return path
	}
	left := (width - 1) / 2
	right := width - left - 1
	return string(characters[:left]) + "…" + string(characters[len(characters)-right:])
}

func (m model) currentGroupFiles() []struct {
	Path         string `json:"path"`
	SizeHuman    string `json:"size_human"`
	OriginalHint bool   `json:"original_hint"`
	Checksum     string `json:"checksum"`
} {
	if m.groupCursor < 0 || m.groupCursor >= len(m.dashboard.Report.LargestGroups) {
		return nil
	}
	return m.dashboard.Report.LargestGroups[m.groupCursor].Files
}

func (m model) homeView(width int) string {
	ready := m.loadErr == nil && m.dashboard.ProtocolVersion == 1
	recoverable := "—"
	if ready {
		recoverable = m.dashboard.Report.RecoverableHuman
	}
	metrics := lipgloss.JoinHorizontal(lipgloss.Top,
		metric("◉", dashboardValue(ready, m.dashboard.Report.Groups), "duplicate groups", cyan),
		metric("★", dashboardValue(ready, m.dashboard.Decisions.Keepers), "keeper decisions", lime),
		metric("◇", recoverable, "recoverable space", pink),
	)
	status := lipgloss.NewStyle().Bold(true).Foreground(gold).Render("NEXT SAFE STEP") +
		"\nLoad the rmlint report, then review keeper choices before staging quarantine."
	if m.loading {
		status = lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("SCANNING LOCAL TELEMETRY") +
			"\nReading the report and existing state databases without changing them."
	} else if m.loadErr != nil {
		status = lipgloss.NewStyle().Bold(true).Foreground(danger).Render("BRIDGE OFFLINE") +
			"\n" + m.loadErr.Error() + "\nRun from the repository or install the Python package."
	} else if len(m.dashboard.Warnings) > 0 {
		status = lipgloss.NewStyle().Bold(true).Foreground(gold).Render("CONNECTION CHECK") +
			"\n" + strings.Join(m.dashboard.Warnings, "\n")
	} else {
		status = lipgloss.NewStyle().Bold(true).Foreground(lime).Render("TELEMETRY ONLINE · READ-ONLY") +
			fmt.Sprintf("\n%d files charted across %d duplicate groups.", m.dashboard.Report.Files, m.dashboard.Report.Groups)
	}
	body := "Your storage universe, charted without moving a single byte.\n\n" + metrics +
		"\n\n" + status
	return frame("MISSION CONTROL", "Read-only overview · no files move from this screen", body, width, pink)
}

func (m model) pageView(page screen, width int) string {
	spec := map[screen][3]string{
		groups: {"DUPLICATE CONSTELLATIONS", "Browse groups by size, type, location, or confidence", "Group list and side-by-side copy inspector\n\nFilters  / search  ·  Space  potential  ·  Copies  path map\n\nEvery group keeps at least one verified original."},
		decisions: {"KEEPER ORBIT", "Choose what remains and understand why", "★ KEEP      selected original\n◇ QUARANTINE staged duplicate\n? UNDECIDED  requires attention\n\nManual decisions persist in decisions.sqlite3."},
		quarantine: {"QUARANTINE AIRLOCK", "Preview first; mutation always requires explicit confirmation", "1  Inspect the generated plan\n2  Run a bounded dry pilot\n3  Verify source and keeper\n4  Confirm --apply\n\nSafety interlocks remain owned by the Python engine."},
		restore: {"RESTORE BEACON", "Bring a quarantined file home without overwriting data", "Select a run from history, preview destinations, inspect collisions, then confirm restoration.\n\nDifferent-content collisions fail closed."},
		history: {"FLIGHT RECORDER", "Journaled actions, outcomes, retries, and recovery", "Runs will appear here with moved, reconciled, stale, timeout, failed, and restored counts.\n\nOperational source: journal.sqlite3"},
		help: {"GALACTIC FIELD GUIDE", "Navigation and non-negotiable safety rules", "↑↓ or j/k  navigate\nEnter       open\nEsc or h    home\n1–7         jump to screen\nq           quit\n\nColor is never the only status signal. Destructive actions require words, state, and confirmation."},
	}
	v := spec[page]
	if m.loadErr == nil && m.dashboard.ProtocolVersion == 1 {
		switch page {
		case groups:
			if m.inspecting && m.groupCursor < len(m.dashboard.Report.LargestGroups) {
				group := m.dashboard.Report.LargestGroups[m.groupCursor]
				files := group.Files
				visible := max(5, m.height-18)
				start := 0
				if m.fileCursor >= visible { start = m.fileCursor-visible+1 }
				end := min(len(files), start+visible)
				lines := []string{}
				for i := start; i < end; i++ {
					marker := "  "
					if i == m.fileCursor { marker = "▶ " }
					hint := "COPY"
					if files[i].OriginalHint { hint = "ORIGINAL HINT" }
					line := fmt.Sprintf("%s%-13s %10s  %s", marker, hint, files[i].SizeHuman, compactPath(files[i].Path, max(20, width-39)))
					if i == m.fileCursor {
						line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line)
					}
					lines = append(lines, line)
				}
				if m.confirmKeeper {
					lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render("SAVE THIS COPY AS KEEPER?"),
						"Enter/Y confirm · N/H/← cancel · this records a decision only")
				} else {
					lines = append(lines, "", fmt.Sprintf("Copy %d of %d · ↑↓ inspect · Enter choose keeper · H/← back", m.fileCursor+1, len(files)))
				}
				if m.statusMessage != "" { lines = append(lines, "", m.statusMessage) }
				return frame(fmt.Sprintf("CONSTELLATION %d", group.GroupID), fmt.Sprintf("%d copies · %s recoverable · report inspection only", group.Copies, group.RecoverableHuman), strings.Join(lines, "\n"), width, cyan)
			}
			lines := []string{}
			for i, group := range m.dashboard.Report.LargestGroups {
				marker := "  "
				if i == m.groupCursor { marker = "▶ " }
				pathWidth := max(18, width-64)
				line := fmt.Sprintf("%sGroup %-5d  %2d copies  %10s  %s", marker, group.GroupID, group.Copies, group.RecoverableHuman, compactPath(group.SamplePath, pathWidth))
				if i == m.groupCursor {
					line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line)
				}
				lines = append(lines, line)
			}
			if len(lines) == 0 {
				lines = append(lines, "No duplicate groups are loaded yet.")
			}
			v[2] = strings.Join(lines, "\n") + "\n\n↑↓ select · Enter inspect copies · Esc return to menu"
		case decisions:
			v[2] = fmt.Sprintf("★ KEEP       %d selected originals\n◇ QUARANTINE %d staged copies\n? UNDECIDED  %d marked for attention\n\n%d favorites saved.",
				m.dashboard.Decisions.Keepers,
				m.dashboard.Decisions.Actions["QUARANTINE"],
				m.dashboard.Decisions.Actions["UNDECIDED"],
				m.dashboard.Decisions.Favorites)
		case history:
			lines := []string{fmt.Sprintf("%d journaled runs", m.dashboard.Journal.Runs)}
			for _, run := range m.dashboard.Journal.LatestRuns {
				lines = append(lines, fmt.Sprintf("≋ %-24s  %-8s  %s", run.RunID, run.Mode, run.Status))
			}
			if len(m.dashboard.Journal.LatestRuns) == 0 {
				lines = append(lines, "No journaled runs yet.")
			}
			v[2] = strings.Join(lines, "\n") + "\n\nOperational source: journal.sqlite3 (opened read-only)"
		}
	}
	return frame(v[0], v[1], v[2], width, cyan)
}

func (m model) View() tea.View {
	contentWidth := max(34, m.width-34)
	content := m.homeView(contentWidth)
	if m.page != home { content = m.pageView(m.page, contentWidth) }
	var rendered string
	if m.compact {
		rendered = logoStyle.Render("✦ ARCHIVE KEEPER · STORAGE GALAXY 2.0") + "\n" +
			mutedText.Render("1 Home · 2 Groups · 3 Keepers · 4 Quarantine · 5 Restore · 6 History · 7 Help") +
			"\n\n" + content
	} else {
		rendered = lipgloss.JoinHorizontal(lipgloss.Top, m.sidebar(), "  ", content)
	}
	bridgeStatus := "Python bridge loading · read-only"
	if m.loadErr != nil {
		bridgeStatus = "Python bridge offline · " + m.loadErr.Error()
	} else if !m.loading && m.dashboard.ProtocolVersion == 1 {
		bridgeStatus = fmt.Sprintf("Python %s · protocol v%d · read-only", m.dashboard.Version, m.dashboard.ProtocolVersion)
	}
	if m.page == groups && m.contentFocus {
		bridgeStatus = "GROUP INSPECTOR · ↑↓ select · Enter open/choose · H/← back · files untouched"
	}
	footerLine := keyStyle.Render(" SAFE BY DEFAULT ") + " " +
		lipgloss.NewStyle().Foreground(lime).Render("READ-ONLY") + "  " +
		mutedText.Render(bridgeStatus)
	footer := "\n" + lipgloss.NewStyle().Width(max(30, m.width-2)).Background(panel).Render(footerLine)
	canvas := lipgloss.NewStyle().
		Width(max(30, m.width-2)).
		Height(max(10, m.height-2)).
		Background(void).
		Foreground(ink).
		Render(rendered + footer)
	v := tea.NewView(lipgloss.NewStyle().Background(void).Padding(1).Render(canvas))
	v.AltScreen = true
	v.MouseMode = tea.MouseModeCellMotion
	v.WindowTitle = "Archive Keeper · Storage Galaxy"
	v.BackgroundColor = void
	v.ForegroundColor = ink
	return v
}

func main() {
	p := tea.NewProgram(model{page: home, loading: true})
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "archive-keeper-ui:", err)
		os.Exit(1)
	}
}
