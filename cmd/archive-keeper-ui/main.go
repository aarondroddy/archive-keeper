package main

import (
	"encoding/json"
	"fmt"
	"image/color"
	"os"
	"os/exec"
	"path/filepath"
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
	confirmAction string
	savingKeeper  bool
	savingAction  bool
	statusMessage string
	plan          quarantinePlan
	planLoading   bool
	planErr       error
	planCursor    int
	confirmDryRun bool
	dryRunning    bool
	dryRun        dryRunResult
	dryRunErr     error
	confirmApply  bool
	applyInput    string
	applying      bool
	applyResult   controlledApplyResult
	applyErr      error
	restoreCatalog restoreCatalog
	restoreCatalogLoading bool
	restoreCatalogErr error
	restoreCursor int
	restoreInspecting bool
	restorePlan restorePlan
	restorePlanLoading bool
	restorePlanErr error
	restorePlanCursor int
	confirmRestore bool
	restoreInput string
	restoring bool
	restoreResult controlledRestoreResult
	restoreErr error
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
		KeeperPaths   map[string]string `json:"keeper_paths"`
		FileActions   map[string]string `json:"file_actions"`
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

type actionSavedMsg struct {
	groupID int
	path    string
	action  string
	err     error
}

type quarantinePlan struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	Mode            string `json:"mode"`
	FilesMoved      int    `json:"files_moved"`
	RunID           string `json:"run_id"`
	QuarantineName  string `json:"quarantine_name"`
	TotalFiles      int    `json:"total_files"`
	TotalHuman      string `json:"total_human"`
	ReadyFiles      int    `json:"ready_files"`
	BlockedFiles    int    `json:"blocked_files"`
	Items           []struct {
		GroupID     int      `json:"group_id"`
		Status      string   `json:"status"`
		SizeHuman   string   `json:"size_human"`
		Source      string   `json:"source"`
		Keeper      string   `json:"keeper"`
		Destination string   `json:"destination"`
		Warnings    []string `json:"warnings"`
	} `json:"items"`
	Warnings []string `json:"warnings"`
}

type quarantinePlanLoadedMsg struct {
	plan quarantinePlan
	err  error
}

type dryRunResult struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	Mode            string `json:"mode"`
	FilesMoved      int    `json:"files_moved"`
	JournalWrites   int    `json:"journal_writes"`
	Limit           int    `json:"limit"`
	TotalStaged     int    `json:"total_staged"`
	Attempted       int    `json:"attempted"`
	Verified        int    `json:"verified"`
	Blocked         int    `json:"blocked"`
	TimedOut        int    `json:"timed_out"`
	VerifiedHuman   string `json:"verified_human"`
	Limited         bool   `json:"limited"`
	Warnings        []string `json:"warnings"`
}

type dryRunFinishedMsg struct {
	result dryRunResult
	err    error
}

type controlledApplyResult struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	FilesMoved      int    `json:"files_moved"`
	BytesMovedHuman string `json:"bytes_moved_human"`
	Reconciled      int    `json:"reconciled"`
	Stale           int    `json:"stale"`
	Failed          int    `json:"failed"`
	TimedOut        int    `json:"timed_out"`
	Limit           int    `json:"limit"`
	RunID           string `json:"run_id"`
	Error           string `json:"error"`
}

type controlledApplyFinishedMsg struct {
	result controlledApplyResult
	err    error
}

type restoreRun struct {
	RunID string `json:"run_id"`
	Status string `json:"status"`
	RestorableFiles int `json:"restorable_files"`
	RestorableHuman string `json:"restorable_human"`
}
type restoreCatalog struct {
	ProtocolVersion int `json:"protocol_version"`
	OK bool `json:"ok"`
	Runs []restoreRun `json:"runs"`
	Warnings []string `json:"warnings"`
}
type restoreCatalogLoadedMsg struct { catalog restoreCatalog; err error }
type restorePlan struct {
	ProtocolVersion int `json:"protocol_version"`
	OK bool `json:"ok"`
	RunID string `json:"run_id"`
	TotalFiles int `json:"total_files"`
	TotalHuman string `json:"total_human"`
	ReadyFiles int `json:"ready_files"`
	BlockedFiles int `json:"blocked_files"`
	Items []struct {
		GroupID int `json:"group_id"`; Status string `json:"status"`; SizeHuman string `json:"size_human"`
		Source string `json:"source"`; Keeper string `json:"keeper"`; Destination string `json:"destination"`
		Warnings []string `json:"warnings"`
	} `json:"items"`
	Warnings []string `json:"warnings"`
}
type restorePlanLoadedMsg struct { plan restorePlan; err error }
type controlledRestoreResult struct {
	ProtocolVersion int `json:"protocol_version"`
	OK bool `json:"ok"`; RunID string `json:"run_id"`; Restored int `json:"restored"`
	BytesRestoredHuman string `json:"bytes_restored_human"`; Failed int `json:"failed"`
	Remaining int `json:"remaining"`; Error string `json:"error"`
}
type controlledRestoreFinishedMsg struct { result controlledRestoreResult; err error }

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

func loadQuarantinePlan() tea.Msg {
	python, args := bridgeArgs("quarantine-plan")
	for _, setting := range []struct{ env, flag string }{
		{"ARCHIVE_KEEPER_REPORT", "--report"},
		{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
		{"ARCHIVE_KEEPER_QUARANTINE_NAME", "--quarantine-name"},
		{"ARCHIVE_KEEPER_RUN_ID", "--run-id"},
	} {
		if value := os.Getenv(setting.env); value != "" {
			args = append(args, setting.flag, value)
		}
	}
	if value := os.Getenv("ARCHIVE_KEEPER_MOUNT_ROOTS"); value != "" {
		for _, root := range filepath.SplitList(value) {
			if root != "" {
				args = append(args, "--mount-root", root)
			}
		}
	}
	output, err := exec.Command(python, args...).CombinedOutput()
	var plan quarantinePlan
	if jsonErr := json.Unmarshal(output, &plan); jsonErr != nil {
		if err != nil {
			return quarantinePlanLoadedMsg{err: fmt.Errorf("bridge command: %w", err)}
		}
		return quarantinePlanLoadedMsg{err: fmt.Errorf("bridge JSON: %w", jsonErr)}
	}
	if err != nil || !plan.OK {
		message := "quarantine preview was not generated"
		if len(plan.Warnings) > 0 {
			message = strings.Join(plan.Warnings, "; ")
		}
		return quarantinePlanLoadedMsg{err: fmt.Errorf("%s", message)}
	}
	if plan.ProtocolVersion != 1 {
		return quarantinePlanLoadedMsg{err: fmt.Errorf("unsupported bridge protocol %d", plan.ProtocolVersion)}
	}
	return quarantinePlanLoadedMsg{plan: plan}
}

func runQuarantineDryRun() tea.Msg {
	python, args := bridgeArgs("quarantine-dry-run")
	for _, setting := range []struct{ env, flag string }{
		{"ARCHIVE_KEEPER_REPORT", "--report"},
		{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
		{"ARCHIVE_KEEPER_QUARANTINE_NAME", "--quarantine-name"},
		{"ARCHIVE_KEEPER_RUN_ID", "--run-id"},
		{"ARCHIVE_KEEPER_DRY_RUN_LIMIT", "--limit"},
		{"ARCHIVE_KEEPER_VERIFY_TIMEOUT", "--verify-timeout"},
	} {
		if value := os.Getenv(setting.env); value != "" {
			args = append(args, setting.flag, value)
		}
	}
	if value := os.Getenv("ARCHIVE_KEEPER_MOUNT_ROOTS"); value != "" {
		for _, root := range filepath.SplitList(value) {
			if root != "" { args = append(args, "--mount-root", root) }
		}
	}
	output, err := exec.Command(python, args...).CombinedOutput()
	var result dryRunResult
	if jsonErr := json.Unmarshal(output, &result); jsonErr != nil {
		if err != nil { return dryRunFinishedMsg{err: fmt.Errorf("bridge command: %w", err)} }
		return dryRunFinishedMsg{err: fmt.Errorf("bridge JSON: %w", jsonErr)}
	}
	if err != nil || !result.OK {
		message := "dry pilot did not complete"
		if len(result.Warnings) > 0 { message = strings.Join(result.Warnings, "; ") }
		return dryRunFinishedMsg{result: result, err: fmt.Errorf("%s", message)}
	}
	if result.ProtocolVersion != 1 {
		return dryRunFinishedMsg{result: result, err: fmt.Errorf("unsupported bridge protocol %d", result.ProtocolVersion)}
	}
	return dryRunFinishedMsg{result: result}
}

func controlledApplyLimit() int {
	limit := 10
	if value := os.Getenv("ARCHIVE_KEEPER_APPLY_LIMIT"); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil && parsed >= 1 && parsed <= 10 {
			limit = parsed
		}
	}
	return limit
}

func expectedApplyConfirmation() string {
	return fmt.Sprintf("QUARANTINE UP TO %d FILES", controlledApplyLimit())
}

func appendApplyConfirmationInput(current, key string) string {
	if key == "space" {
		return current + " "
	}
	if runes := []rune(key); len(runes) == 1 {
		return current + strings.ToUpper(key)
	}
	return current
}

func controlledRestoreLimit() int {
	limit := 10
	if value := os.Getenv("ARCHIVE_KEEPER_RESTORE_LIMIT"); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil && parsed >= 1 && parsed <= 10 { limit = parsed }
	}
	return limit
}
func expectedRestoreConfirmation() string { return fmt.Sprintf("RESTORE UP TO %d FILES", controlledRestoreLimit()) }

func restoreBridgeArgs(command string) (string, []string) {
	python, args := bridgeArgs(command)
	if value := os.Getenv("ARCHIVE_KEEPER_STATE_DB"); value != "" { args = append(args, "--state-db", value) }
	return python, args
}
func mountRootArgs(args []string) []string {
	if value := os.Getenv("ARCHIVE_KEEPER_MOUNT_ROOTS"); value != "" {
		for _, root := range filepath.SplitList(value) { if root != "" { args = append(args, "--mount-root", root) } }
	}
	return args
}
func loadRestoreCatalog() tea.Msg {
	python, args := restoreBridgeArgs("restore-catalog")
	output, err := exec.Command(python, args...).CombinedOutput()
	var catalog restoreCatalog
	if jsonErr := json.Unmarshal(output, &catalog); jsonErr != nil { if err != nil { return restoreCatalogLoadedMsg{err: fmt.Errorf("bridge command: %w", err)} }; return restoreCatalogLoadedMsg{err: jsonErr} }
	if err != nil || !catalog.OK { return restoreCatalogLoadedMsg{catalog: catalog, err: fmt.Errorf("%s", strings.Join(catalog.Warnings, "; "))} }
	return restoreCatalogLoadedMsg{catalog: catalog}
}
func loadRestorePlan(runID string) tea.Cmd { return func() tea.Msg {
	python, args := restoreBridgeArgs("restore-plan")
	args = mountRootArgs(append(args, "--run-id", runID))
	output, err := exec.Command(python, args...).CombinedOutput(); var plan restorePlan
	if jsonErr := json.Unmarshal(output, &plan); jsonErr != nil { if err != nil { return restorePlanLoadedMsg{err: fmt.Errorf("bridge command: %w", err)} }; return restorePlanLoadedMsg{err: jsonErr} }
	if err != nil || !plan.OK { return restorePlanLoadedMsg{plan: plan, err: fmt.Errorf("%s", strings.Join(plan.Warnings, "; "))} }
	return restorePlanLoadedMsg{plan: plan}
} }
func runControlledRestore(runID, confirmation string) tea.Cmd { return func() tea.Msg {
	python, args := restoreBridgeArgs("restore-apply")
	args = mountRootArgs(append(args, "--run-id", runID, "--limit", strconv.Itoa(controlledRestoreLimit()), "--confirm", confirmation))
	output, err := exec.Command(python, args...).CombinedOutput(); var result controlledRestoreResult
	if jsonErr := json.Unmarshal(output, &result); jsonErr != nil { if err != nil { return controlledRestoreFinishedMsg{err: fmt.Errorf("bridge command: %w", err)} }; return controlledRestoreFinishedMsg{err: jsonErr} }
	if err != nil || !result.OK { message := result.Error; if message == "" { message = "controlled restore did not complete" }; return controlledRestoreFinishedMsg{result: result, err: fmt.Errorf("%s", message)} }
	return controlledRestoreFinishedMsg{result: result}
} }

func runControlledApply(confirmation string) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("quarantine-apply")
		for _, setting := range []struct{ env, flag string }{
			{"ARCHIVE_KEEPER_REPORT", "--report"},
			{"ARCHIVE_KEEPER_STATE_DB", "--state-db"},
			{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
			{"ARCHIVE_KEEPER_QUARANTINE_NAME", "--quarantine-name"},
			{"ARCHIVE_KEEPER_RUN_ID", "--run-id"},
			{"ARCHIVE_KEEPER_VERIFY_TIMEOUT", "--verify-timeout"},
		} {
			if value := os.Getenv(setting.env); value != "" {
				args = append(args, setting.flag, value)
			}
		}
		args = append(args, "--limit", strconv.Itoa(controlledApplyLimit()))
		if value := os.Getenv("ARCHIVE_KEEPER_MOUNT_ROOTS"); value != "" {
			for _, root := range filepath.SplitList(value) {
				if root != "" { args = append(args, "--mount-root", root) }
			}
		}
		args = append(args, "--confirm", confirmation)
		output, err := exec.Command(python, args...).CombinedOutput()
		var result controlledApplyResult
		if jsonErr := json.Unmarshal(output, &result); jsonErr != nil {
			if err != nil { return controlledApplyFinishedMsg{err: fmt.Errorf("bridge command: %w", err)} }
			return controlledApplyFinishedMsg{err: fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !result.OK {
			message := result.Error
			if message == "" { message = "controlled quarantine did not complete" }
			return controlledApplyFinishedMsg{result: result, err: fmt.Errorf("%s", message)}
		}
		if result.ProtocolVersion != 1 {
			return controlledApplyFinishedMsg{result: result, err: fmt.Errorf("unsupported bridge protocol %d", result.ProtocolVersion)}
		}
		return controlledApplyFinishedMsg{result: result}
	}
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

func saveFileAction(groupID int, path, action string) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("set-file-action")
		for _, setting := range []struct{ env, flag string }{
			{"ARCHIVE_KEEPER_REPORT", "--report"},
			{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
		} {
			if value := os.Getenv(setting.env); value != "" {
				args = append(args, setting.flag, value)
			}
		}
		args = append(args, "--group-id", strconv.Itoa(groupID), "--path", path, "--action", action)
		output, err := exec.Command(python, args...).CombinedOutput()
		var result keeperResult
		if jsonErr := json.Unmarshal(output, &result); jsonErr != nil {
			if err != nil {
				return actionSavedMsg{groupID, path, action, fmt.Errorf("bridge command: %w", err)}
			}
			return actionSavedMsg{groupID, path, action, fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !result.OK {
			message := result.Error
			if message == "" {
				message = "file decision was not saved"
			}
			return actionSavedMsg{groupID, path, action, fmt.Errorf("%s", message)}
		}
		return actionSavedMsg{groupID: groupID, path: path, action: action}
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
	case actionSavedMsg:
		m.savingAction = false
		m.confirmAction = ""
		if msg.err != nil {
			m.statusMessage = "STAGING FAILED · " + msg.err.Error()
			return m, nil
		}
		verb := "STAGED " + msg.action
		if msg.action == "CLEAR" {
			verb = "STAGED DECISION CLEARED"
		}
		m.statusMessage = verb + " · no files moved"
		return m, loadDashboard
	case quarantinePlanLoadedMsg:
		m.planLoading = false
		m.plan = msg.plan
		m.planErr = msg.err
		if m.planCursor >= len(m.plan.Items) {
			m.planCursor = max(0, len(m.plan.Items)-1)
		}
	case dryRunFinishedMsg:
		m.dryRunning = false
		m.confirmDryRun = false
		m.dryRun = msg.result
		m.dryRunErr = msg.err
	case controlledApplyFinishedMsg:
		m.applying = false
		m.confirmApply = false
		m.applyInput = ""
		m.applyResult = msg.result
		m.applyErr = msg.err
		m.planLoading = true
		return m, loadQuarantinePlan
	case restoreCatalogLoadedMsg:
		m.restoreCatalogLoading = false; m.restoreCatalog = msg.catalog; m.restoreCatalogErr = msg.err
		if m.restoreCursor >= len(m.restoreCatalog.Runs) { m.restoreCursor = max(0, len(m.restoreCatalog.Runs)-1) }
	case restorePlanLoadedMsg:
		m.restorePlanLoading = false; m.restorePlan = msg.plan; m.restorePlanErr = msg.err
		if m.restorePlanCursor >= len(m.restorePlan.Items) { m.restorePlanCursor = max(0, len(m.restorePlan.Items)-1) }
	case controlledRestoreFinishedMsg:
		m.restoring = false; m.confirmRestore = false; m.restoreInput = ""; m.restoreResult = msg.result; m.restoreErr = msg.err
		m.restorePlanLoading = true
		return m, loadRestorePlan(m.restorePlan.RunID)
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.compact = msg.Width < 96
	case tea.KeyPressMsg:
		shortcut := strings.ToLower(msg.String())
		if m.confirmRestore {
			key := msg.String()
			switch key {
			case "ctrl+c": return m, tea.Quit
			case "enter":
				if m.restoreInput == expectedRestoreConfirmation() && !m.restoring { m.restoring = true; m.restoreErr = nil; return m, runControlledRestore(m.restorePlan.RunID, m.restoreInput) }
				m.restoreErr = fmt.Errorf("confirmation phrase does not match")
			case "backspace", "ctrl+h": runes := []rune(m.restoreInput); if len(runes) > 0 { m.restoreInput = string(runes[:len(runes)-1]) }
			case "left", "ctrl+g": m.confirmRestore = false; m.restoreInput = ""; m.restoreErr = nil
			default: m.restoreInput = appendApplyConfirmationInput(m.restoreInput, key)
			}
			return m, nil
		}
		if m.confirmApply {
			key := msg.String()
			switch key {
			case "ctrl+c":
				return m, tea.Quit
			case "enter":
				if m.applyInput == expectedApplyConfirmation() && !m.applying {
					m.applying = true
					m.applyErr = nil
					return m, runControlledApply(m.applyInput)
				}
				m.applyErr = fmt.Errorf("confirmation phrase does not match")
			case "backspace", "ctrl+h":
				runes := []rune(m.applyInput)
				if len(runes) > 0 { m.applyInput = string(runes[:len(runes)-1]) }
			case "left", "ctrl+g":
				m.confirmApply = false
				m.applyInput = ""
				m.applyErr = nil
			default:
				m.applyInput = appendApplyConfirmationInput(m.applyInput, key)
			}
			return m, nil
		}
		switch shortcut {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "1", "2", "3", "4", "5", "6", "7":
			i := int(shortcut[0] - '1')
			m.selected, m.page = i, destinations[i].page
			m.contentFocus = m.page == groups || m.page == quarantine || m.page == restore
			m.inspecting = false
			m.fileCursor = 0
			m.confirmKeeper = false
			m.confirmAction = ""
			m.confirmDryRun = false
			m.confirmApply = false
			m.applyInput = ""
			if m.page == quarantine {
				m.planLoading = true
				m.planErr = nil
				return m, loadQuarantinePlan
			}
			if m.page == restore { m.restoreCatalogLoading = true; m.restoreCatalogErr = nil; m.restoreInspecting = false; return m, loadRestoreCatalog }
			return m, nil
		}
		if m.page == groups && m.contentFocus {
			if m.confirmKeeper {
				switch shortcut {
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
			if m.confirmAction != "" {
				switch shortcut {
				case "y", "enter":
					if !m.savingAction {
						group := m.dashboard.Report.LargestGroups[m.groupCursor]
						file := group.Files[m.fileCursor]
						m.savingAction = true
						m.statusMessage = "SAVING STAGED DECISION…"
						return m, saveFileAction(group.GroupID, file.Path, m.confirmAction)
					}
				case "n", "esc", "left", "h":
					m.confirmAction = ""
					m.statusMessage = "Staged decision cancelled"
				}
				return m, nil
			}
			switch shortcut {
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
			case "x":
				if m.inspecting {
					m.confirmAction = "QUARANTINE"
					m.statusMessage = "Confirm quarantine staging"
				}
			case "u":
				if m.inspecting {
					m.confirmAction = "UNDECIDED"
					m.statusMessage = "Confirm undecided staging"
				}
			case "c":
				if m.inspecting {
					m.confirmAction = "CLEAR"
					m.statusMessage = "Confirm clearing staged decision"
				}
			case "esc", "left", "h":
				if m.inspecting {
					m.inspecting = false
					m.fileCursor = 0
					m.confirmKeeper = false
					m.confirmAction = ""
				} else {
					m.contentFocus = false
				}
			}
			return m, nil
		}
		if m.page == quarantine && m.contentFocus {
			if m.confirmDryRun {
				switch shortcut {
				case "y", "enter":
					if !m.dryRunning {
						m.dryRunning = true
						m.dryRunErr = nil
						return m, runQuarantineDryRun
					}
				case "n", "esc", "left", "h":
					m.confirmDryRun = false
				}
				return m, nil
			}
			switch shortcut {
			case "up", "k":
				if m.planCursor > 0 { m.planCursor-- }
			case "down", "j":
				if m.planCursor < len(m.plan.Items)-1 { m.planCursor++ }
			case "r":
				m.planLoading = true
				m.planErr = nil
				m.dryRun = dryRunResult{}
				m.dryRunErr = nil
				m.applyResult = controlledApplyResult{}
				m.applyErr = nil
				return m, loadQuarantinePlan
			case "d":
				if len(m.plan.Items) > 0 && !m.planLoading {
					m.confirmDryRun = true
				}
			case "a":
				if m.dryRun.ProtocolVersion == 1 && m.dryRun.Verified > 0 && m.dryRun.Blocked == 0 && m.dryRun.TimedOut == 0 {
					m.confirmApply = true
					m.applyInput = ""
					m.applyErr = nil
				}
			case "esc", "left", "h":
				m.contentFocus = false
				m.page = home
				m.confirmDryRun = false
				m.confirmApply = false
				m.applyInput = ""
			}
			return m, nil
		}
		if m.page == restore && m.contentFocus {
			if m.restoreInspecting {
				switch shortcut {
				case "up", "k": if m.restorePlanCursor > 0 { m.restorePlanCursor-- }
				case "down", "j": if m.restorePlanCursor < len(m.restorePlan.Items)-1 { m.restorePlanCursor++ }
				case "r": m.restorePlanLoading = true; m.restorePlanErr = nil; m.restoreResult = controlledRestoreResult{}; m.restoreErr = nil; return m, loadRestorePlan(m.restorePlan.RunID)
				case "a": if m.restorePlan.ReadyFiles > 0 && m.restorePlan.BlockedFiles == 0 { m.confirmRestore = true; m.restoreInput = ""; m.restoreErr = nil }
				case "esc", "left", "h": m.restoreInspecting = false; m.restorePlanCursor = 0; m.confirmRestore = false; m.restoreCatalogLoading = true; return m, loadRestoreCatalog
				}
			} else {
				switch shortcut {
				case "up", "k": if m.restoreCursor > 0 { m.restoreCursor-- }
				case "down", "j": if m.restoreCursor < len(m.restoreCatalog.Runs)-1 { m.restoreCursor++ }
				case "enter", "right", "l": if len(m.restoreCatalog.Runs) > 0 { m.restoreInspecting = true; m.restorePlanLoading = true; m.restorePlanErr = nil; return m, loadRestorePlan(m.restoreCatalog.Runs[m.restoreCursor].RunID) }
				case "r": m.restoreCatalogLoading = true; m.restoreCatalogErr = nil; return m, loadRestoreCatalog
				case "esc", "left", "h": m.contentFocus = false; m.page = home
				}
			}
			return m, nil
		}
		switch shortcut {
		case "up", "k":
			if m.selected > 0 { m.selected-- }
		case "down", "j":
			if m.selected < len(destinations)-1 { m.selected++ }
		case "enter", "right", "l":
			m.page = destinations[m.selected].page
			m.contentFocus = m.page == groups || m.page == quarantine || m.page == restore
			if m.page == quarantine {
				m.planLoading = true
				m.planErr = nil
				return m, loadQuarantinePlan
			}
			if m.page == restore { m.restoreCatalogLoading = true; m.restoreCatalogErr = nil; m.restoreInspecting = false; return m, loadRestoreCatalog }
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
		help: {"GALACTIC FIELD GUIDE", "Navigation and non-negotiable safety rules", "↑↓ or j/k  navigate\nEnter       open / choose keeper\nX           stage quarantine\nU           mark undecided\nC           clear staged choice\nD           run bounded dry pilot\nA           open controlled apply gate\nH or ←      back / cancel gate\n1–7         jump to screen\nq           quit\n\nA clean dry pilot unlocks apply. Apply moves at most 10 explicitly staged files and requires the exact confirmation phrase. Choices and every move are journaled for recovery."},
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
					groupKey := strconv.Itoa(group.GroupID)
					actionKey := groupKey + "\n" + files[i].Path
					if m.dashboard.Decisions.KeeperPaths[groupKey] == files[i].Path {
						hint = "KEEPER"
					} else if action := m.dashboard.Decisions.FileActions[actionKey]; action != "" {
						hint = action
					} else if files[i].OriginalHint {
						hint = "ORIGINAL HINT"
					}
					line := fmt.Sprintf("%s%-13s %10s  %s", marker, hint, files[i].SizeHuman, compactPath(files[i].Path, max(20, width-39)))
					if i == m.fileCursor {
						line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line)
					}
					lines = append(lines, line)
				}
				if m.confirmKeeper {
					lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render("SAVE THIS COPY AS KEEPER?"),
						"Enter/Y confirm · N/H/← cancel · this records a decision only")
				} else if m.confirmAction != "" {
					prompt := "STAGE " + m.confirmAction + " FOR THIS COPY?"
					if m.confirmAction == "CLEAR" {
						prompt = "CLEAR THE STAGED DECISION FOR THIS COPY?"
					}
					lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render(prompt),
						"Enter/Y confirm · N/H/← cancel · no archive files move")
				} else {
					lines = append(lines, "", fmt.Sprintf("Copy %d of %d · Enter keeper · X quarantine · U undecided · C clear · H/← back", m.fileCursor+1, len(files)))
				}
				if m.statusMessage != "" { lines = append(lines, "", m.statusMessage) }
				return frame(fmt.Sprintf("CONSTELLATION %d", group.GroupID), fmt.Sprintf("%d copies · %s recoverable · keeper decisions enabled", group.Copies, group.RecoverableHuman), strings.Join(lines, "\n"), width, cyan)
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
			v[2] = strings.Join(lines, "\n") + "\n\n↑↓ select · Enter inspect copies · H/← return to menu"
		case decisions:
			v[2] = fmt.Sprintf("★ KEEP       %d selected originals\n◇ QUARANTINE %d staged copies\n? UNDECIDED  %d marked for attention\n\n%d favorites saved.",
				m.dashboard.Decisions.Keepers,
				m.dashboard.Decisions.Actions["QUARANTINE"],
				m.dashboard.Decisions.Actions["UNDECIDED"],
				m.dashboard.Decisions.Favorites)
		case quarantine:
			if m.planLoading {
				v[2] = "Scanning staged decisions and checking live paths…\n\nNo files or journal rows are being changed."
				break
			}
			if m.planErr != nil {
				v[2] = lipgloss.NewStyle().Bold(true).Foreground(danger).Render("PREVIEW UNAVAILABLE") +
					"\n" + m.planErr.Error() + "\n\nR reload · H/← return"
				break
			}
			if len(m.plan.Items) == 0 {
				v[2] = "No copies are staged for quarantine.\n\nOpen Duplicate Groups, inspect a group, then press X on a nonkeeper copy.\n\nR reload · H/← return"
				break
			}
			lines := []string{
				fmt.Sprintf("%d staged · %s · %d ready · %d blocked", m.plan.TotalFiles, m.plan.TotalHuman, m.plan.ReadyFiles, m.plan.BlockedFiles),
				"",
			}
			visible := max(3, min(8, m.height-24))
			start := 0
			if m.planCursor >= visible { start = m.planCursor-visible+1 }
			end := min(len(m.plan.Items), start+visible)
			for i := start; i < end; i++ {
				item := m.plan.Items[i]
				marker := "  "
				if i == m.planCursor { marker = "▶ " }
				line := fmt.Sprintf("%s%-7s Group %-5d %10s  %s", marker, item.Status, item.GroupID, item.SizeHuman, compactPath(item.Source, max(18, width-48)))
				if i == m.planCursor {
					line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line)
				} else if item.Status == "BLOCKED" {
					line = lipgloss.NewStyle().Foreground(danger).Render(line)
				}
				lines = append(lines, line)
			}
			item := m.plan.Items[m.planCursor]
			lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("SOURCE"), compactPath(item.Source, max(24, width-10)))
			lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(lime).Render("KEEPER"), compactPath(item.Keeper, max(24, width-10)))
			lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(pink).Render("DESTINATION"), compactPath(item.Destination, max(24, width-10)))
			if len(item.Warnings) > 0 {
				lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(danger).Render("BLOCKED · "+strings.Join(item.Warnings, " · ")))
			} else {
				lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(lime).Render("READY · structural and live checks passed"))
			}
			if m.applying {
				lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(pink).Render("QUARANTINE IN PROGRESS · do not close this terminal"))
			} else if m.confirmApply {
				phrase := expectedApplyConfirmation()
				lines = append(lines, "",
					lipgloss.NewStyle().Bold(true).Foreground(danger).Render("FINAL SAFETY GATE · REAL FILES WILL MOVE"),
					"Type exactly: "+phrase,
					lipgloss.NewStyle().Bold(true).Foreground(gold).Render("> "+m.applyInput+"▌"),
					"Enter submits · ← or Ctrl+G cancels")
				if m.applyErr != nil { lines = append(lines, lipgloss.NewStyle().Foreground(danger).Render(m.applyErr.Error())) }
			} else if m.applyErr != nil {
				lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(danger).Render("QUARANTINE FAILED · "+m.applyErr.Error()))
			} else if m.applyResult.ProtocolVersion == 1 {
				label := fmt.Sprintf("QUARANTINE COMPLETE · %d moved · %s · %d failed", m.applyResult.FilesMoved, m.applyResult.BytesMovedHuman, m.applyResult.Failed)
				style := lipgloss.NewStyle().Bold(true).Foreground(lime)
				if m.applyResult.Failed > 0 { style = style.Foreground(gold) }
				lines = append(lines, "", style.Render(label),
					"Run ID: "+m.applyResult.RunID,
					"Restore command: archive-keeper restore "+m.applyResult.RunID+" --apply")
			} else if m.dryRunning {
				lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("DRY PILOT RUNNING · bounded verification only"))
			} else if m.confirmDryRun {
				lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render("RUN BOUNDED DRY PILOT?"),
					"Enter/Y confirm · N/H/← cancel · zero moves · zero journal writes")
			} else if m.dryRunErr != nil {
				lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(danger).Render("DRY PILOT FAILED · "+m.dryRunErr.Error()))
			} else if m.dryRun.ProtocolVersion == 1 {
				label := fmt.Sprintf("DRY PILOT COMPLETE · %d/%d verified · %d blocked · %d timed out · %s", m.dryRun.Verified, m.dryRun.Attempted, m.dryRun.Blocked, m.dryRun.TimedOut, m.dryRun.VerifiedHuman)
				style := lipgloss.NewStyle().Bold(true).Foreground(lime)
				if m.dryRun.Blocked > 0 || m.dryRun.TimedOut > 0 { style = style.Foreground(gold) }
				lines = append(lines, "", style.Render(label))
				if m.dryRun.Limited { lines = append(lines, fmt.Sprintf("Pilot stopped safely at limit %d of %d staged files.", m.dryRun.Limit, m.dryRun.TotalStaged)) }
				if m.dryRun.Verified > 0 && m.dryRun.Blocked == 0 && m.dryRun.TimedOut == 0 {
					lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(pink).Render("A controlled apply · typed confirmation required"))
				}
			}
			lines = append(lines, "", "↑↓ inspect · D dry pilot · R reload · H/← return")
			v[2] = strings.Join(lines, "\n")
		case restore:
			if !m.restoreInspecting {
				if m.restoreCatalogLoading { v[2] = "Reading journaled quarantine runs…\n\nNo files are being changed."; break }
				if m.restoreCatalogErr != nil { v[2] = lipgloss.NewStyle().Bold(true).Foreground(danger).Render("RESTORE CATALOG UNAVAILABLE")+"\n"+m.restoreCatalogErr.Error()+"\n\nR reload · H/← return"; break }
				lines := []string{"Choose a quarantine run to preview:" , ""}
				for i, run := range m.restoreCatalog.Runs {
					marker := "  "; if i == m.restoreCursor { marker = "▶ " }
					line := fmt.Sprintf("%s%-28s %3d files  %10s  %s", marker, run.RunID, run.RestorableFiles, run.RestorableHuman, run.Status)
					if i == m.restoreCursor { line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line) }
					lines = append(lines, line)
				}
				if len(m.restoreCatalog.Runs) == 0 { lines = append(lines, "No quarantined files remain to restore.") }
				lines = append(lines, "", "↑↓ select · Enter preview · R reload · H/← return")
				v[2] = strings.Join(lines, "\n"); break
			}
			if m.restorePlanLoading { v[2] = "Checking restore destinations and collisions…\n\nNo files are being changed."; break }
			if m.restorePlanErr != nil { v[2] = lipgloss.NewStyle().Bold(true).Foreground(danger).Render("RESTORE PREVIEW UNAVAILABLE")+"\n"+m.restorePlanErr.Error()+"\n\nH/← return"; break }
			if m.restoreResult.ProtocolVersion == 1 && m.restoreResult.Remaining == 0 && !m.restoring {
				label := fmt.Sprintf("RESTORE VERIFIED · %d restored · %s · %d failed · 0 remaining", m.restoreResult.Restored, m.restoreResult.BytesRestoredHuman, m.restoreResult.Failed)
				style := lipgloss.NewStyle().Bold(true).Foreground(lime)
				if m.restoreResult.Failed > 0 { style = style.Foreground(gold) }
				v[2] = style.Render(label) + "\n\nRun ID: " + m.restoreResult.RunID +
					"\nJournal status: restored\nOriginal path restored with no overwrite.\n\nH/← return to restorable runs"
				break
			}
			lines := []string{fmt.Sprintf("Run %s · %d files · %s · %d ready · %d blocked", m.restorePlan.RunID, m.restorePlan.TotalFiles, m.restorePlan.TotalHuman, m.restorePlan.ReadyFiles, m.restorePlan.BlockedFiles), ""}
			visible := max(3, min(8, m.height-24)); start := 0
			if m.restorePlanCursor >= visible { start = m.restorePlanCursor-visible+1 }; end := min(len(m.restorePlan.Items), start+visible)
			for i := start; i < end; i++ { item := m.restorePlan.Items[i]; marker := "  "; if i == m.restorePlanCursor { marker = "▶ " }; line := fmt.Sprintf("%s%-7s Group %-5d %10s  %s", marker, item.Status, item.GroupID, item.SizeHuman, compactPath(item.Source, max(18, width-48))); if i == m.restorePlanCursor { line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line) } else if item.Status == "BLOCKED" { line = lipgloss.NewStyle().Foreground(danger).Render(line) }; lines = append(lines, line) }
			if len(m.restorePlan.Items) > 0 { item := m.restorePlan.Items[m.restorePlanCursor]; lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("RESTORE TO"), compactPath(item.Source, max(24,width-10)), lipgloss.NewStyle().Bold(true).Foreground(pink).Render("FROM QUARANTINE"), compactPath(item.Destination,max(24,width-10))); if len(item.Warnings)>0 { lines=append(lines,lipgloss.NewStyle().Bold(true).Foreground(danger).Render("BLOCKED · "+strings.Join(item.Warnings," · "))) } else { lines=append(lines,lipgloss.NewStyle().Bold(true).Foreground(lime).Render("READY · original path is clear; no-overwrite guard armed")) } }
			if m.restoring { lines=append(lines,"",lipgloss.NewStyle().Bold(true).Foreground(pink).Render("RESTORE IN PROGRESS · do not close this terminal"))
			} else if m.confirmRestore { phrase:=expectedRestoreConfirmation(); lines=append(lines,"",lipgloss.NewStyle().Bold(true).Foreground(danger).Render("FINAL SAFETY GATE · QUARANTINED FILES WILL MOVE"),"Type exactly: "+phrase,lipgloss.NewStyle().Bold(true).Foreground(gold).Render("> "+m.restoreInput+"▌"),"Enter submits · ← or Ctrl+G cancels"); if m.restoreErr != nil { lines=append(lines,lipgloss.NewStyle().Foreground(danger).Render(m.restoreErr.Error())) }
			} else if m.restoreErr != nil { lines=append(lines,"",lipgloss.NewStyle().Bold(true).Foreground(danger).Render("RESTORE FAILED · "+m.restoreErr.Error()))
			} else if m.restoreResult.ProtocolVersion == 1 { label:=fmt.Sprintf("RESTORE VERIFIED · %d restored · %s · %d failed · %d remaining",m.restoreResult.Restored,m.restoreResult.BytesRestoredHuman,m.restoreResult.Failed,m.restoreResult.Remaining); style:=lipgloss.NewStyle().Bold(true).Foreground(lime); if m.restoreResult.Failed>0 { style=style.Foreground(gold) }; lines=append(lines,"",style.Render(label),"Run ID: "+m.restoreResult.RunID) }
			if m.restorePlan.ReadyFiles > 0 && m.restorePlan.BlockedFiles == 0 && !m.confirmRestore && !m.restoring { lines=append(lines,"",lipgloss.NewStyle().Bold(true).Foreground(pink).Render("A controlled restore · typed confirmation required")) }
			lines=append(lines,"","↑↓ inspect · A controlled restore · R reload · H/← runs")
			v[2]=strings.Join(lines,"\n")
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
		bridgeStatus = "GROUP INSPECTOR · Enter keeper · X stage · U undecided · C clear · files untouched"
	} else if m.page == quarantine && m.contentFocus {
		bridgeStatus = "QUARANTINE PREVIEW · D dry pilot · R reload · no moves · no journal writes"
		if m.confirmApply {
			bridgeStatus = "FINAL SAFETY GATE · type the exact phrase · ← cancels"
		} else if m.applying {
			bridgeStatus = "CONTROLLED QUARANTINE · bounded apply · journal enabled"
		}
	} else if m.page == restore && m.contentFocus {
		bridgeStatus = "RESTORE PREVIEW · journaled moves only · no overwrite"
		if m.confirmRestore { bridgeStatus = "FINAL RESTORE GATE · type the exact phrase · ← cancels" } else if m.restoring { bridgeStatus = "CONTROLLED RESTORE · bounded apply · journal enabled" }
	}
	footerLine := keyStyle.Render(" FILES UNTOUCHED ") + " " +
		lipgloss.NewStyle().Foreground(lime).Render("DECISIONS ENABLED") + "  " +
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
