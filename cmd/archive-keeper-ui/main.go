package main

import (
	"context"
	"encoding/json"
	"fmt"
	"image/color"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

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
	settings
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
	{"⚙", "Storage Setup", "configure managed mounts", settings},
}

type mountCandidate struct {
	Path       string
	Filesystem string
	Source     string
}

type uiConfig struct {
	Version          int      `json:"version"`
	MountRoots       []string `json:"mount_roots"`
	ReportPath       string   `json:"report_path"`
	StateDBPath      string   `json:"state_db_path"`
	DecisionsDBPath  string   `json:"decisions_db_path"`
	QuarantineName   string   `json:"quarantine_name"`
	PreferredRoots   []string `json:"preferred_roots"`
	ProtectedRoots   []string `json:"protected_roots"`
	ExcludedRoots    []string `json:"excluded_roots"`
}

type scanFinishedMsg struct {
	reportPath string
	backupPath string
	output     string
	err        error
}

type duplicateFile struct {
	Path         string `json:"path"`
	SizeHuman    string `json:"size_human"`
	OriginalHint bool   `json:"original_hint"`
	Checksum     string `json:"checksum"`
}

type duplicateGroup struct {
	GroupID          int             `json:"group_id"`
	Copies           int             `json:"copies"`
	RecoverableBytes int64           `json:"recoverable_bytes"`
	RecoverableHuman string          `json:"recoverable_human"`
	SamplePath       string          `json:"sample_path"`
	MountRoot        string          `json:"mount_root"`
	Files            []duplicateFile `json:"files"`
}

type groupCatalog struct {
	ProtocolVersion int              `json:"protocol_version"`
	OK              bool             `json:"ok"`
	Mode            string           `json:"mode"`
	Query           string           `json:"query"`
	RootFilter      string           `json:"root_filter"`
	Sort            string           `json:"sort"`
	Page            int              `json:"page"`
	PageSize        int              `json:"page_size"`
	TotalPages      int              `json:"total_pages"`
	TotalGroups     int              `json:"total_groups"`
	FilteredGroups  int              `json:"filtered_groups"`
	Items           []duplicateGroup `json:"items"`
	Warnings        []string         `json:"warnings"`
}

type groupCatalogLoadedMsg struct {
	catalog groupCatalog
	err     error
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
	galaxyMode    bool
	groupCatalog  groupCatalog
	groupLoading  bool
	groupErr      error
	groupQuery    string
	groupSearchInput string
	groupSearch   bool
	groupSort     string
	groupRoot     string
	scanPhase     int
	setupCandidates []mountCandidate
	setupSelected   map[string]bool
	setupCursor     int
	setupFirstRun   bool
	setupMessage    string
	configSource    string
	reportPath      string
	stateDBPath     string
	decisionsDBPath string
	quarantineName  string
	preferredRoots  []string
	protectedRoots  []string
	excludedRoots   []string
	advancedMode    bool
	advancedCursor  int
	advancedEditing bool
	advancedInput   string
	confirmScan     bool
	scanRunning     bool
	scanStartedAt   time.Time
	scanCancel      context.CancelFunc
	scanMessage     string
	scanErr         error
	scanSummaryVisible bool
	scanDuration       time.Duration
	scanRoots          []string
	scanReportPath     string
	scanBackupPath     string
	scanOutput         string
	fileCursor    int
	inspecting    bool
	confirmKeeper bool
	confirmAction string
	confirmBulk   bool
	savingKeeper  bool
	savingAction  bool
	savingBulk    bool
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
	historyCursor int
	historyInspecting bool
	historyDetail historyRunDetail
	historyLoading bool
	historyErr error
	historyActionCursor int
	recoveryRunning bool
	recoveryKind string
	recoveryResult recoveryResult
	recoveryErr error
	confirmRecovery bool
	recoveryInput string
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
		LargestGroups    []duplicateGroup `json:"largest_groups"`
	} `json:"report"`
	Mounts struct {
		AllReady bool `json:"all_ready"`
		Roots []struct {
			Path       string `json:"path"`
			Mounted    bool   `json:"mounted"`
			Filesystem string `json:"filesystem"`
			Source     string `json:"source"`
			Status     string `json:"status"`
		} `json:"roots"`
	} `json:"mounts"`
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

type historyRunDetail struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	Mode            string `json:"mode"`
	Operation       string `json:"operation"`
	Run struct {
		RunID          string  `json:"run_id"`
		CreatedAt      float64 `json:"created_at"`
		CreatedAtHuman string  `json:"created_at_human"`
		ReportPath     string  `json:"report_path"`
		Mode           string  `json:"mode"`
		Status         string  `json:"status"`
	} `json:"run"`
	Actions []struct {
		ID          int     `json:"id"`
		GroupID     int     `json:"group_id"`
		Keeper      string  `json:"keeper"`
		Source      string  `json:"source"`
		Destination string  `json:"destination"`
		Size        int64   `json:"size"`
		SizeHuman   string  `json:"size_human"`
		Status      string  `json:"status"`
		Message     string  `json:"message"`
		CreatedAt   float64 `json:"created_at"`
		UpdatedAt   float64 `json:"updated_at"`
	} `json:"actions"`
	StatusCounts map[string]int `json:"status_counts"`
	TotalActions int            `json:"total_actions"`
	TotalBytes   int64          `json:"total_bytes"`
	TotalHuman   string         `json:"total_human"`
	Warnings     []string       `json:"warnings"`
}

type historyRunLoadedMsg struct {
	detail historyRunDetail
	err    error
}

type recoveryResult struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	Mode            string `json:"mode"`
	Kind            string `json:"kind"`
	RunID           string `json:"run_id"`
	ActionID        int    `json:"action_id"`
	ExpectedConfirm string `json:"expected_confirmation"`
	JournalUpdated  bool   `json:"journal_updated"`
	FilesMoved      int    `json:"files_moved"`
	BeforeStatus    string `json:"before_status"`
	AfterStatus     string `json:"after_status"`
	Output          string `json:"output"`
	Error           string `json:"error"`
}

type recoveryFinishedMsg struct {
	result recoveryResult
	err error
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

type bulkSavedMsg struct {
	groupID int
	staged  int
	err     error
}

type bulkStageResult struct {
	ProtocolVersion int    `json:"protocol_version"`
	OK              bool   `json:"ok"`
	GroupID         int    `json:"group_id"`
	Staged          int    `json:"staged"`
	KeeperPath      string `json:"keeper_path"`
	Error           string `json:"error"`
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

func decodeMountPath(value string) string {
	return strings.NewReplacer("\\040", " ", "\\011", "\t", "\\012", "\n", "\\134", "\\").Replace(value)
}

func storageMountCandidate(path, filesystem string) bool {
	if !(strings.HasPrefix(path, "/mnt/") || strings.HasPrefix(path, "/media/") || strings.HasPrefix(path, "/run/media/")) {
		return false
	}
	pseudo := map[string]bool{
		"autofs": true, "bpf": true, "cgroup": true, "cgroup2": true, "configfs": true,
		"debugfs": true, "devpts": true, "devtmpfs": true, "fusectl": true, "hugetlbfs": true,
		"mqueue": true, "nsfs": true, "overlay": true, "proc": true, "pstore": true,
		"securityfs": true, "squashfs": true, "sysfs": true, "tmpfs": true, "tracefs": true,
	}
	return !pseudo[filesystem]
}

func parseMountCandidates(mountinfo string) []mountCandidate {
	byPath := map[string]mountCandidate{}
	for _, line := range strings.Split(mountinfo, "\n") {
		parts := strings.SplitN(line, " - ", 2)
		if len(parts) != 2 {
			continue
		}
		left, right := strings.Fields(parts[0]), strings.Fields(parts[1])
		if len(left) < 5 || len(right) < 2 {
			continue
		}
		path := filepath.Clean(decodeMountPath(left[4]))
		filesystem := right[0]
		if !storageMountCandidate(path, filesystem) {
			continue
		}
		byPath[path] = mountCandidate{Path: path, Filesystem: filesystem, Source: decodeMountPath(right[1])}
	}
	result := make([]mountCandidate, 0, len(byPath))
	for _, candidate := range byPath {
		result = append(result, candidate)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Path < result[j].Path })
	return result
}

func discoverMountCandidates() ([]mountCandidate, error) {
	data, err := os.ReadFile("/proc/self/mountinfo")
	if err != nil {
		return nil, err
	}
	return parseMountCandidates(string(data)), nil
}

func uiConfigPath() (string, error) {
	if value := os.Getenv("ARCHIVE_KEEPER_UI_CONFIG"); value != "" {
		return filepath.Clean(value), nil
	}
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "archive-keeper", "ui.json"), nil
}

func loadUIConfig() (uiConfig, error) {
	path, err := uiConfigPath()
	if err != nil {
		return uiConfig{}, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return uiConfig{}, err
	}
	var config uiConfig
	if err := json.Unmarshal(data, &config); err != nil {
		return uiConfig{}, fmt.Errorf("parse %s: %w", path, err)
	}
	return config, nil
}

func defaultReportPath() string {
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".local", "share", "archive-keeper", "rmlint.json")
	}
	return filepath.Join(".", "rmlint.json")
}

func defaultStateDBPath() string {
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".local", "state", "archive-keeper", "journal.sqlite3")
	}
	return filepath.Join(".", "journal.sqlite3")
}

func defaultDecisionsDBPath() string {
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".local", "state", "archive-keeper", "decisions.sqlite3")
	}
	return filepath.Join(".", "decisions.sqlite3")
}

func normalizeAbsolutePaths(values []string) ([]string, error) {
	clean := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" { continue }
		value = filepath.Clean(value)
		if !filepath.IsAbs(value) { return nil, fmt.Errorf("path must be absolute: %s", value) }
		if !seen[value] { seen[value] = true; clean = append(clean, value) }
	}
	sort.Strings(clean)
	return clean, nil
}

func splitPathSetting(value string) []string {
	if strings.TrimSpace(value) == "" { return nil }
	return filepath.SplitList(value)
}

func joinPathSetting(values []string) string {
	return strings.Join(values, string(os.PathListSeparator))
}

func pathWithinAny(path string, roots []string) bool {
	path = filepath.Clean(path)
	for _, root := range roots {
		root = filepath.Clean(root)
		rel, err := filepath.Rel(root, path)
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(os.PathSeparator)) { return true }
	}
	return false
}

func (m model) preferredFileCursor(group duplicateGroup) int {
	for i, file := range group.Files {
		if pathWithinAny(file.Path, m.preferredRoots) {
			return i
		}
	}
	return 0
}

func saveUIConfig(config uiConfig) error {
	if len(config.MountRoots) == 0 {
		return fmt.Errorf("select at least one storage root")
	}
	clean := make([]string, 0, len(config.MountRoots))
	seen := map[string]bool{}
	for _, root := range config.MountRoots {
		root = filepath.Clean(root)
		if !filepath.IsAbs(root) {
			return fmt.Errorf("storage root must be absolute: %s", root)
		}
		if !seen[root] {
			seen[root] = true
			clean = append(clean, root)
		}
	}
	sort.Strings(clean)
	config.Version = 1
	config.MountRoots = clean
	if config.ReportPath == "" {
		config.ReportPath = defaultReportPath()
	}
	if !filepath.IsAbs(config.ReportPath) {
		return fmt.Errorf("report path must be absolute: %s", config.ReportPath)
	}
	if config.StateDBPath == "" { config.StateDBPath = defaultStateDBPath() }
	if config.DecisionsDBPath == "" { config.DecisionsDBPath = defaultDecisionsDBPath() }
	if !filepath.IsAbs(config.StateDBPath) { return fmt.Errorf("state database path must be absolute: %s", config.StateDBPath) }
	if !filepath.IsAbs(config.DecisionsDBPath) { return fmt.Errorf("decisions database path must be absolute: %s", config.DecisionsDBPath) }
	if config.QuarantineName == "" { config.QuarantineName = "ArchiveKeeper Quarantine" }
	if config.QuarantineName == "." || config.QuarantineName == ".." || filepath.Base(config.QuarantineName) != config.QuarantineName {
		return fmt.Errorf("quarantine name must be one folder name")
	}
	var err error
	if config.PreferredRoots, err = normalizeAbsolutePaths(config.PreferredRoots); err != nil { return fmt.Errorf("preferred roots: %w", err) }
	if config.ProtectedRoots, err = normalizeAbsolutePaths(config.ProtectedRoots); err != nil { return fmt.Errorf("protected roots: %w", err) }
	if config.ExcludedRoots, err = normalizeAbsolutePaths(config.ExcludedRoots); err != nil { return fmt.Errorf("exclusions: %w", err) }
	path, err := uiConfigPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if err := os.WriteFile(path, data, 0600); err != nil {
		return err
	}
	return os.Chmod(path, 0600)
}

func mergeConfiguredCandidates(candidates []mountCandidate, roots []string) []mountCandidate {
	seen := map[string]bool{}
	for _, candidate := range candidates {
		seen[candidate.Path] = true
	}
	for _, root := range roots {
		root = filepath.Clean(root)
		if !seen[root] {
			candidates = append(candidates, mountCandidate{Path: root, Filesystem: "configured"})
			seen[root] = true
		}
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].Path < candidates[j].Path })
	return candidates
}

func configuredRootList() []string {
	value := os.Getenv("ARCHIVE_KEEPER_MOUNT_ROOTS")
	if value == "" {
		return nil
	}
	roots := []string{}
	for _, root := range filepath.SplitList(value) {
		if root != "" {
			roots = append(roots, filepath.Clean(root))
		}
	}
	return roots
}

func applyRootConfiguration(roots []string) {
	_ = os.Setenv("ARCHIVE_KEEPER_MOUNT_ROOTS", strings.Join(roots, string(os.PathListSeparator)))
}

func applyAdvancedConfiguration(config uiConfig) {
	_ = os.Setenv("ARCHIVE_KEEPER_REPORT", config.ReportPath)
	_ = os.Setenv("ARCHIVE_KEEPER_STATE_DB", config.StateDBPath)
	_ = os.Setenv("ARCHIVE_KEEPER_DECISIONS_DB", config.DecisionsDBPath)
	_ = os.Setenv("ARCHIVE_KEEPER_QUARANTINE_NAME", config.QuarantineName)
	_ = os.Setenv("ARCHIVE_KEEPER_PREFERRED_ROOTS", joinPathSetting(config.PreferredRoots))
	_ = os.Setenv("ARCHIVE_KEEPER_PROTECTED_ROOTS", joinPathSetting(config.ProtectedRoots))
	_ = os.Setenv("ARCHIVE_KEEPER_EXCLUDED_ROOTS", joinPathSetting(config.ExcludedRoots))
}

func activeReportPath() string {
	if value := os.Getenv("ARCHIVE_KEEPER_REPORT"); value != "" {
		return value
	}
	return defaultReportPath()
}

func initialModel() model {
	m := model{
		page: home, loading: true, galaxyMode: true, groupSort: "space-desc",
		setupSelected: map[string]bool{}, reportPath: activeReportPath(),
		stateDBPath: defaultStateDBPath(), decisionsDBPath: defaultDecisionsDBPath(),
		quarantineName: "ArchiveKeeper Quarantine",
	}
	candidates, err := discoverMountCandidates()
	if err != nil {
		m.setupMessage = "Mount discovery failed: " + err.Error()
	}
	config, configErr := loadUIConfig()
	if configErr == nil {
		if config.ReportPath != "" { m.reportPath = config.ReportPath }
		if config.StateDBPath != "" { m.stateDBPath = config.StateDBPath }
		if config.DecisionsDBPath != "" { m.decisionsDBPath = config.DecisionsDBPath }
		if config.QuarantineName != "" { m.quarantineName = config.QuarantineName }
		m.preferredRoots = append([]string{}, config.PreferredRoots...)
		m.protectedRoots = append([]string{}, config.ProtectedRoots...)
		m.excludedRoots = append([]string{}, config.ExcludedRoots...)
	}
	for _, override := range []struct{ env string; target *string }{
		{"ARCHIVE_KEEPER_REPORT", &m.reportPath},
		{"ARCHIVE_KEEPER_STATE_DB", &m.stateDBPath},
		{"ARCHIVE_KEEPER_DECISIONS_DB", &m.decisionsDBPath},
		{"ARCHIVE_KEEPER_QUARANTINE_NAME", &m.quarantineName},
	} { if value := os.Getenv(override.env); value != "" { *override.target = value } }
	if value := os.Getenv("ARCHIVE_KEEPER_PREFERRED_ROOTS"); value != "" { m.preferredRoots = splitPathSetting(value) }
	if value := os.Getenv("ARCHIVE_KEEPER_PROTECTED_ROOTS"); value != "" { m.protectedRoots = splitPathSetting(value) }
	if value := os.Getenv("ARCHIVE_KEEPER_EXCLUDED_ROOTS"); value != "" { m.excludedRoots = splitPathSetting(value) }
	roots := configuredRootList()
	if len(roots) > 0 {
		m.configSource = "environment override"
	} else {
		if configErr == nil && len(config.MountRoots) > 0 {
			roots = config.MountRoots
			m.configSource = "saved configuration"
			applyRootConfiguration(roots)
		} else if configErr != nil && !os.IsNotExist(configErr) {
			m.setupMessage = "Configuration could not be read: " + configErr.Error()
		}
	}
	applyAdvancedConfiguration(uiConfig{ReportPath: m.reportPath, StateDBPath: m.stateDBPath,
		DecisionsDBPath: m.decisionsDBPath, QuarantineName: m.quarantineName,
		PreferredRoots: m.preferredRoots, ProtectedRoots: m.protectedRoots, ExcludedRoots: m.excludedRoots})
	m.setupCandidates = mergeConfiguredCandidates(candidates, roots)
	for _, root := range roots {
		m.setupSelected[filepath.Clean(root)] = true
	}
	if len(roots) == 0 {
		m.page = settings
		m.selected = len(destinations) - 1
		m.contentFocus = true
		m.setupFirstRun = true
		m.configSource = "first-run setup"
		for _, candidate := range m.setupCandidates {
			m.setupSelected[candidate.Path] = true
		}
	}
	return m
}

func rmlintScanArgs(roots []string, tempPath string) []string {
	args := append([]string{}, roots...)
	return append(args, "-", "-T", "duplicates", "-o", "json:"+tempPath)
}

func runRmlintScan(ctx context.Context, roots []string, reportPath string) tea.Cmd {
	return func() tea.Msg {
		if len(roots) == 0 {
			return scanFinishedMsg{err: fmt.Errorf("select at least one mounted storage root")}
		}
		if _, err := exec.LookPath("rmlint"); err != nil {
			return scanFinishedMsg{err: fmt.Errorf("rmlint is not installed or not on PATH")}
		}
		reportPath = filepath.Clean(reportPath)
		if !filepath.IsAbs(reportPath) {
			return scanFinishedMsg{err: fmt.Errorf("report path must be absolute")}
		}
		reportDir := filepath.Dir(reportPath)
		if err := os.MkdirAll(reportDir, 0700); err != nil {
			return scanFinishedMsg{err: fmt.Errorf("create report directory: %w", err)}
		}
		temp, err := os.CreateTemp(reportDir, ".rmlint-scan-*.json")
		if err != nil {
			return scanFinishedMsg{err: fmt.Errorf("create temporary report: %w", err)}
		}
		tempPath := temp.Name()
		if err := temp.Close(); err != nil {
			_ = os.Remove(tempPath)
			return scanFinishedMsg{err: fmt.Errorf("close temporary report: %w", err)}
		}
		_ = os.Remove(tempPath)
		output, runErr := exec.CommandContext(ctx, "rmlint", rmlintScanArgs(roots, tempPath)...).CombinedOutput()
		summary := strings.TrimSpace(string(output))
		if len(summary) > 600 {
			summary = summary[len(summary)-600:]
		}
		if runErr != nil {
			_ = os.Remove(tempPath)
			if ctx.Err() != nil {
				return scanFinishedMsg{output: summary, err: fmt.Errorf("rmlint scan cancelled")}
			}
			return scanFinishedMsg{output: summary, err: fmt.Errorf("rmlint scan failed: %w", runErr)}
		}
		info, err := os.Stat(tempPath)
		if err != nil || info.Size() == 0 {
			_ = os.Remove(tempPath)
			return scanFinishedMsg{output: summary, err: fmt.Errorf("rmlint did not produce a usable JSON report")}
		}
		if err := os.Chmod(tempPath, 0600); err != nil {
			_ = os.Remove(tempPath)
			return scanFinishedMsg{output: summary, err: fmt.Errorf("secure temporary report: %w", err)}
		}
		backupPath := ""
		if _, err := os.Stat(reportPath); err == nil {
			backupPath = reportPath + ".previous-" + time.Now().UTC().Format("20060102T150405Z")
			if err := os.Rename(reportPath, backupPath); err != nil {
				_ = os.Remove(tempPath)
				return scanFinishedMsg{output: summary, err: fmt.Errorf("preserve previous report: %w", err)}
			}
		}
		if err := os.Rename(tempPath, reportPath); err != nil {
			if backupPath != "" {
				_ = os.Rename(backupPath, reportPath)
			}
			_ = os.Remove(tempPath)
			return scanFinishedMsg{output: summary, err: fmt.Errorf("activate new report: %w", err)}
		}
		return scanFinishedMsg{reportPath: reportPath, backupPath: backupPath, output: summary}
	}
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
	if value := os.Getenv("ARCHIVE_KEEPER_MOUNT_ROOTS"); value != "" {
		for _, root := range filepath.SplitList(value) {
			if root != "" {
				args = append(args, "--mount-root", root)
			}
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

func loadGroupCatalog(query, root, sortMode string, page int) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("group-catalog")
		if value := os.Getenv("ARCHIVE_KEEPER_REPORT"); value != "" {
			args = append(args, "--report", value)
		}
		for _, mountRoot := range configuredRootList() {
			args = append(args, "--mount-root", mountRoot)
		}
		args = append(args, "--query", query, "--sort", sortMode,
			"--page", strconv.Itoa(page), "--page-size", "12")
		if root != "" {
			args = append(args, "--root-filter", root)
		}
		output, err := exec.Command(python, args...).CombinedOutput()
		var catalog groupCatalog
		if jsonErr := json.Unmarshal(output, &catalog); jsonErr != nil {
			if err != nil { return groupCatalogLoadedMsg{err: fmt.Errorf("bridge command: %w", err)} }
			return groupCatalogLoadedMsg{err: fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !catalog.OK {
			message := "duplicate groups could not be loaded"
			if len(catalog.Warnings) > 0 { message = strings.Join(catalog.Warnings, "; ") }
			return groupCatalogLoadedMsg{catalog: catalog, err: fmt.Errorf("%s", message)}
		}
		return groupCatalogLoadedMsg{catalog: catalog}
	}
}

func loadHistoryRun(runID string) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("history-run")
		if value := os.Getenv("ARCHIVE_KEEPER_STATE_DB"); value != "" {
			args = append(args, "--state-db", value)
		}
		args = append(args, "--run-id", runID)
		output, err := exec.Command(python, args...).CombinedOutput()
		var detail historyRunDetail
		if jsonErr := json.Unmarshal(output, &detail); jsonErr != nil {
			if err != nil {
				return historyRunLoadedMsg{err: fmt.Errorf("bridge command: %w", err)}
			}
			return historyRunLoadedMsg{err: fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !detail.OK {
			message := strings.Join(detail.Warnings, " · ")
			if message == "" {
				message = "journal run could not be loaded"
			}
			return historyRunLoadedMsg{detail: detail, err: fmt.Errorf("%s", message)}
		}
		return historyRunLoadedMsg{detail: detail}
	}
}

func runRecoveryAction(kind, runID string, actionID int, apply bool, confirmation string) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("recover-action")
		if value := os.Getenv("ARCHIVE_KEEPER_STATE_DB"); value != "" {
			args = append(args, "--state-db", value)
		}
		args = append(args, "--run-id", runID, "--action-id", strconv.Itoa(actionID), "--kind", kind)
		for _, root := range configuredRootList() {
			args = append(args, "--mount-root", root)
		}
		if apply {
			args = append(args, "--apply", "--confirm", confirmation)
		}
		output, err := exec.Command(python, args...).CombinedOutput()
		var result recoveryResult
		if jsonErr := json.Unmarshal(output, &result); jsonErr != nil {
			if err != nil { return recoveryFinishedMsg{err: fmt.Errorf("bridge command: %w", err)} }
			return recoveryFinishedMsg{err: fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !result.OK {
			message := result.Error
			if message == "" { message = "recovery action did not complete" }
			return recoveryFinishedMsg{result: result, err: fmt.Errorf("%s", message)}
		}
		return recoveryFinishedMsg{result: result}
	}
}

func expectedRecoveryConfirmation(kind string, actionID int) string {
	return fmt.Sprintf("%s ACTION %d", strings.ToUpper(kind), actionID)
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
	args = safetyRuleArgs(args)
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
	args = safetyRuleArgs(args)
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
func safetyRuleArgs(args []string) []string {
	for _, setting := range []struct{ env, flag string }{
		{"ARCHIVE_KEEPER_PROTECTED_ROOTS", "--protect"},
		{"ARCHIVE_KEEPER_EXCLUDED_ROOTS", "--exclude"},
	} {
		for _, root := range splitPathSetting(os.Getenv(setting.env)) {
			if root != "" { args = append(args, setting.flag, root) }
		}
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
		args = safetyRuleArgs(args)
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
		args = safetyRuleArgs(args)
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

func saveBulkGroup(groupID int) tea.Cmd {
	return func() tea.Msg {
		python, args := bridgeArgs("bulk-stage-group")
		for _, setting := range []struct{ env, flag string }{
			{"ARCHIVE_KEEPER_REPORT", "--report"},
			{"ARCHIVE_KEEPER_DECISIONS_DB", "--decisions-db"},
		} {
			if value := os.Getenv(setting.env); value != "" { args = append(args, setting.flag, value) }
		}
		args = append(args, "--group-id", strconv.Itoa(groupID))
		args = safetyRuleArgs(args)
		output, err := exec.Command(python, args...).CombinedOutput()
		var result bulkStageResult
		if jsonErr := json.Unmarshal(output, &result); jsonErr != nil {
			if err != nil { return bulkSavedMsg{groupID: groupID, err: fmt.Errorf("bridge command: %w", err)} }
			return bulkSavedMsg{groupID: groupID, err: fmt.Errorf("bridge JSON: %w", jsonErr)}
		}
		if err != nil || !result.OK {
			message := result.Error
			if message == "" { message = "bulk decisions were not saved" }
			return bulkSavedMsg{groupID: groupID, err: fmt.Errorf("%s", message)}
		}
		return bulkSavedMsg{groupID: result.GroupID, staged: result.Staged}
	}
}

type scanTickMsg time.Time

func scanTick() tea.Cmd {
	return tea.Tick(360*time.Millisecond, func(t time.Time) tea.Msg { return scanTickMsg(t) })
}

func (m model) Init() tea.Cmd { return tea.Batch(loadDashboard, scanTick()) }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case scanTickMsg:
		m.scanPhase = (m.scanPhase + 1) % 4
		return m, scanTick()
	case scanFinishedMsg:
		m.scanRunning = false
		m.scanCancel = nil
		m.confirmScan = false
		m.scanErr = msg.err
		m.scanDuration = time.Since(m.scanStartedAt).Round(time.Second)
		m.scanReportPath = msg.reportPath
		m.scanBackupPath = msg.backupPath
		m.scanOutput = msg.output
		m.scanSummaryVisible = true
		if msg.err != nil {
			m.scanMessage = "SCAN FAILED · " + msg.err.Error()
			if msg.output != "" {
				m.scanMessage += " · " + strings.ReplaceAll(msg.output, "\n", " ")
			}
			return m, nil
		}
		m.scanMessage = "SCAN COMPLETE · active report: " + msg.reportPath
		if msg.backupPath != "" {
			m.scanMessage += " · previous report: " + msg.backupPath
		}
		m.loading = true
		m.loadErr = nil
		return m, loadDashboard
	case dashboardLoadedMsg:
		m.loading = false
		m.dashboard = msg.snapshot
		m.loadErr = msg.err
	case groupCatalogLoadedMsg:
		m.groupLoading = false
		m.groupCatalog = msg.catalog
		m.groupErr = msg.err
		if m.groupCursor >= len(m.groupCatalog.Items) {
			m.groupCursor = max(0, len(m.groupCatalog.Items)-1)
		}
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
	case bulkSavedMsg:
		m.savingBulk = false
		m.confirmBulk = false
		if msg.err != nil {
			m.statusMessage = "BULK STAGING BLOCKED · " + msg.err.Error()
			return m, nil
		}
		m.statusMessage = fmt.Sprintf("GROUP %d REVIEWED · %d nonkeepers staged · keeper protected · no files moved", msg.groupID, msg.staged)
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
	case historyRunLoadedMsg:
		m.historyLoading = false
		m.historyDetail = msg.detail
		m.historyErr = msg.err
		if m.historyActionCursor >= len(m.historyDetail.Actions) {
			m.historyActionCursor = max(0, len(m.historyDetail.Actions)-1)
		}
	case recoveryFinishedMsg:
		m.recoveryRunning = false
		m.confirmRecovery = false
		m.recoveryInput = ""
		m.recoveryResult = msg.result
		m.recoveryErr = msg.err
		if msg.result.Mode == "apply" && m.historyDetail.Run.RunID != "" {
			m.historyLoading = true
			return m, tea.Batch(loadDashboard, loadHistoryRun(m.historyDetail.Run.RunID))
		}
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
		if m.groupSearch {
			key := msg.String()
			switch key {
			case "ctrl+c":
				return m, tea.Quit
			case "enter":
				m.groupSearch = false
				m.groupQuery = strings.TrimSpace(m.groupSearchInput)
				m.groupCursor = 0
				m.groupLoading = true
				m.groupErr = nil
				return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, 1)
			case "esc", "left", "ctrl+g":
				m.groupSearch = false
				m.groupSearchInput = m.groupQuery
			case "backspace", "ctrl+h":
				runes := []rune(m.groupSearchInput)
				if len(runes) > 0 { m.groupSearchInput = string(runes[:len(runes)-1]) }
			default:
				if key == "space" { m.groupSearchInput += " " } else if runes := []rune(key); len(runes) == 1 { m.groupSearchInput += key }
			}
			return m, nil
		}
		if m.advancedEditing {
			key := msg.String()
			switch key {
			case "ctrl+c":
				return m, tea.Quit
			case "enter":
				if err := m.setAdvancedSetting(m.advancedCursor, m.advancedInput); err != nil {
					m.setupMessage = "SETTING NOT SAVED · " + err.Error()
				} else {
					m.advancedEditing = false
					m.setupMessage = "Value accepted · press S to save all settings"
				}
			case "esc", "ctrl+g":
				m.advancedEditing = false
				m.setupMessage = "Edit cancelled"
			case "backspace", "ctrl+h":
				runes := []rune(m.advancedInput)
				if len(runes) > 0 { m.advancedInput = string(runes[:len(runes)-1]) }
			default:
				if key == "space" { m.advancedInput += " " } else if runes := []rune(key); len(runes) == 1 { m.advancedInput += key }
			}
			return m, nil
		}
		if m.confirmRecovery {
			key := msg.String()
			switch key {
			case "ctrl+c":
				return m, tea.Quit
			case "enter":
				if !m.dashboard.Mounts.AllReady {
					m.recoveryErr = fmt.Errorf("mount array is not ready")
					return m, nil
				}
				expected := expectedRecoveryConfirmation(m.recoveryKind, m.recoveryResult.ActionID)
				if m.recoveryInput == expected && !m.recoveryRunning {
					m.recoveryRunning = true
					m.recoveryErr = nil
					return m, runRecoveryAction(m.recoveryKind, m.recoveryResult.RunID, m.recoveryResult.ActionID, true, m.recoveryInput)
				}
				m.recoveryErr = fmt.Errorf("confirmation phrase does not match")
			case "backspace", "ctrl+h":
				runes := []rune(m.recoveryInput)
				if len(runes) > 0 { m.recoveryInput = string(runes[:len(runes)-1]) }
			case "left", "ctrl+g":
				m.confirmRecovery = false
				m.recoveryInput = ""
				m.recoveryErr = nil
			default:
				m.recoveryInput = appendApplyConfirmationInput(m.recoveryInput, key)
			}
			return m, nil
		}
		if m.confirmRestore {
			key := msg.String()
			switch key {
			case "ctrl+c": return m, tea.Quit
			case "enter":
				if !m.dashboard.Mounts.AllReady { m.restoreErr = fmt.Errorf("mount array is not ready"); return m, nil }
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
				if !m.dashboard.Mounts.AllReady { m.applyErr = fmt.Errorf("mount array is not ready"); return m, nil }
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
		if shortcut == "?" {
			m.selected = 6
			m.page = help
			m.contentFocus = false
			return m, nil
		}
		switch shortcut {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "1", "2", "3", "4", "5", "6", "7", "8":
			m.scanSummaryVisible = false
			i := int(shortcut[0] - '1')
			m.selected, m.page = i, destinations[i].page
			m.contentFocus = m.page == groups || m.page == quarantine || m.page == restore || m.page == history || m.page == settings
			m.inspecting = false
			m.fileCursor = 0
			m.confirmKeeper = false
			m.confirmAction = ""
			m.confirmBulk = false
			m.confirmDryRun = false
			m.confirmApply = false
			m.applyInput = ""
			m.historyInspecting = false
			m.historyActionCursor = 0
			m.historyErr = nil
			if m.page == groups {
				m.groupLoading = true
				m.groupErr = nil
				m.groupCursor = 0
				return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, max(1, m.groupCatalog.Page))
			}
			if m.page == quarantine {
				m.planLoading = true
				m.planErr = nil
				return m, loadQuarantinePlan
			}
			if m.page == restore { m.restoreCatalogLoading = true; m.restoreCatalogErr = nil; m.restoreInspecting = false; return m, loadRestoreCatalog }
			return m, nil
		}
		if m.page == settings && m.contentFocus {
			if m.scanRunning {
				switch shortcut {
				case "x", "esc", "left", "h":
					if m.scanCancel != nil {
						m.scanCancel()
						m.scanMessage = "CANCELLING RMLINT SCAN…"
					}
				}
				return m, nil
			}
			if m.scanSummaryVisible {
				switch shortcut {
				case "enter", "g":
					if m.scanErr == nil && !m.loading && m.dashboard.Report.Groups > 0 {
						m.scanSummaryVisible = false
						m.selected = 1
						m.page = groups
						m.contentFocus = true
						m.groupCursor = 0
						m.groupLoading = true
						m.groupErr = nil
						return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, 1)
					}
				case "r", "esc", "left", "h":
					m.scanSummaryVisible = false
					m.scanMessage = ""
				}
				return m, nil
			}
			if m.confirmScan {
				switch shortcut {
				case "enter":
					roots := m.selectedSetupRoots()
					if len(roots) == 0 {
						m.scanErr = fmt.Errorf("select at least one mounted root")
						m.scanMessage = "SCAN BLOCKED · " + m.scanErr.Error()
						m.confirmScan = false
						return m, nil
					}
					m.scanRunning = true
					m.scanStartedAt = time.Now()
					m.scanRoots = append([]string{}, roots...)
					m.scanSummaryVisible = false
					m.scanErr = nil
					m.scanMessage = ""
					ctx, cancel := context.WithCancel(context.Background())
					m.scanCancel = cancel
					return m, runRmlintScan(ctx, roots, m.reportPath)
				case "esc", "left", "h":
					m.confirmScan = false
				}
				return m, nil
			}
			if m.advancedMode {
				settings := m.advancedSettings()
				switch shortcut {
				case "up", "k":
					if m.advancedCursor > 0 { m.advancedCursor-- }
				case "down", "j":
					if m.advancedCursor < len(settings)-1 { m.advancedCursor++ }
				case "enter", "right", "l":
					if m.advancedCursor >= 0 && m.advancedCursor < len(settings) {
						m.advancedInput = settings[m.advancedCursor].value
						m.advancedEditing = true
						m.setupMessage = "Editing " + settings[m.advancedCursor].label
					}
				case "s":
					roots := m.selectedSetupRoots()
					if err := m.saveCurrentConfiguration(roots); err != nil {
						m.setupMessage = "Configuration save failed: " + err.Error()
					} else {
						m.configSource = "saved configuration"
						m.setupMessage = "Advanced settings saved · runtime configuration reloaded"
						m.loading = true; m.loadErr = nil
						return m, loadDashboard
					}
				case "e", "esc", "left", "h":
					m.advancedMode = false
					m.setupMessage = "Returned to storage-root setup"
				}
				return m, nil
			}
			switch shortcut {
			case "up", "k":
				if m.setupCursor > 0 {
					m.setupCursor--
				}
			case "down", "j":
				if m.setupCursor < len(m.setupCandidates)-1 {
					m.setupCursor++
				}
			case "space", " ", "enter":
				if m.setupCursor >= 0 && m.setupCursor < len(m.setupCandidates) {
					path := m.setupCandidates[m.setupCursor].Path
					m.setupSelected[path] = !m.setupSelected[path]
				}
			case "a":
				for _, candidate := range m.setupCandidates {
					m.setupSelected[candidate.Path] = true
				}
			case "n":
				m.setupSelected = map[string]bool{}
			case "r":
				m.rescanSetupCandidates()
			case "s":
				roots := m.selectedSetupRoots()
				if len(roots) == 0 {
					m.setupMessage = "Select at least one mounted storage root before saving"
					return m, nil
				}
				if err := m.saveCurrentConfiguration(roots); err != nil {
					m.setupMessage = "Configuration save failed: " + err.Error()
					return m, nil
				}
				m.setupFirstRun = false
				m.configSource = "saved configuration"
				m.setupMessage = fmt.Sprintf("Saved %d managed storage root(s)", len(roots))
				m.page = home
				m.selected = 0
				m.contentFocus = false
				m.loading = true
				m.loadErr = nil
				return m, loadDashboard
			case "f":
				roots := m.selectedSetupRoots()
				if len(roots) == 0 {
					m.scanErr = fmt.Errorf("select at least one mounted root")
					m.scanMessage = "SCAN BLOCKED · " + m.scanErr.Error()
					return m, nil
				}
				if err := m.saveCurrentConfiguration(roots); err != nil {
					m.scanErr = err
					m.scanMessage = "SCAN BLOCKED · configuration save failed: " + err.Error()
					return m, nil
				}
				m.setupFirstRun = false
				m.configSource = "saved configuration"
				m.confirmScan = true
				m.scanMessage = ""
				m.scanErr = nil
			case "e":
				m.advancedMode = true
				m.advancedCursor = 0
				m.setupMessage = "Advanced settings · Enter edits the selected value"
			case "esc", "left", "h":
				if !m.setupFirstRun {
					m.contentFocus = false
					m.page = home
					m.selected = 0
				}
			}
			return m, nil
		}
		if m.page == groups && m.contentFocus {
			if m.confirmKeeper {
				switch shortcut {
				case "y", "enter":
					if !m.savingKeeper {
						group := m.groupCatalog.Items[m.groupCursor]
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
			if m.confirmBulk {
				switch shortcut {
				case "y", "enter":
					if !m.savingBulk && m.groupCursor < len(m.groupCatalog.Items) {
						group := m.groupCatalog.Items[m.groupCursor]
						m.savingBulk = true
						m.statusMessage = "SAVING BULK GROUP DECISIONS…"
						return m, saveBulkGroup(group.GroupID)
					}
				case "n", "esc", "left", "h":
					m.confirmBulk = false
					m.statusMessage = "Bulk staging cancelled"
				}
				return m, nil
			}
			if m.confirmAction != "" {
				switch shortcut {
				case "y", "enter":
					if !m.savingAction {
						group := m.groupCatalog.Items[m.groupCursor]
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
			case "/":
				if !m.inspecting {
					m.groupSearch = true
					m.groupSearchInput = m.groupQuery
				}
			case "s":
				if !m.inspecting {
					m.groupSort = nextGroupSort(m.groupSort)
					m.groupCursor = 0; m.groupLoading = true; m.groupErr = nil
					return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, 1)
				}
			case "f":
				if !m.inspecting {
					m.groupRoot = m.nextGroupRoot()
					m.groupCursor = 0; m.groupLoading = true; m.groupErr = nil
					return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, 1)
				}
			case "pgup", "[":
				if !m.inspecting && m.groupCatalog.Page > 1 {
					m.groupCursor = 0; m.groupLoading = true
					return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, m.groupCatalog.Page-1)
				}
			case "pgdown", "]":
				if !m.inspecting && m.groupCatalog.Page < m.groupCatalog.TotalPages {
					m.groupCursor = 0; m.groupLoading = true
					return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, m.groupCatalog.Page+1)
				}
			case "g":
				if !m.inspecting { m.galaxyMode = !m.galaxyMode }
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
				} else if m.groupCursor < len(m.groupCatalog.Items)-1 {
					m.groupCursor++
				}
			case "enter", "right", "l":
				if m.inspecting {
					m.confirmKeeper = true
					m.statusMessage = "Confirm keeper selection"
				} else if len(m.groupCatalog.Items) > 0 {
					m.inspecting = true
					m.fileCursor = m.preferredFileCursor(m.groupCatalog.Items[m.groupCursor])
				}
			case "x":
				if m.inspecting {
					m.confirmAction = "QUARANTINE"
					m.statusMessage = "Confirm quarantine staging"
				}
			case "b":
				if m.inspecting && m.groupCursor < len(m.groupCatalog.Items) {
					group := m.groupCatalog.Items[m.groupCursor]
					keeper := m.dashboard.Decisions.KeeperPaths[strconv.Itoa(group.GroupID)]
					if keeper == "" {
						m.statusMessage = "BULK STAGING BLOCKED · choose and save a keeper first"
					} else {
						m.confirmBulk = true
						m.statusMessage = fmt.Sprintf("Review: keep 1 and stage %d nonkeepers", max(0, len(group.Files)-1))
					}
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
					m.confirmBulk = false
				} else {
					m.contentFocus = false
				}
			}
			return m, nil
		}
		if m.page == history && m.contentFocus {
			if m.historyInspecting {
				switch shortcut {
				case "up", "k":
					if m.historyActionCursor > 0 { m.historyActionCursor-- }
				case "down", "j":
					if m.historyActionCursor < len(m.historyDetail.Actions)-1 { m.historyActionCursor++ }
				case "r":
					if m.historyDetail.Run.RunID != "" {
						m.historyLoading = true
						m.historyErr = nil
						return m, loadHistoryRun(m.historyDetail.Run.RunID)
					}
				case "t", "c":
					if !m.recoveryRunning && m.historyActionCursor < len(m.historyDetail.Actions) {
						action := m.historyDetail.Actions[m.historyActionCursor]
						kind := "retry"
						if shortcut == "c" { kind = "reconcile" }
						m.recoveryRunning = true
						m.recoveryKind = kind
						m.recoveryErr = nil
						m.recoveryResult = recoveryResult{}
						return m, runRecoveryAction(kind, m.historyDetail.Run.RunID, action.ID, false, "")
					}
				case "a":
					if m.historyActionCursor < len(m.historyDetail.Actions) {
						action := m.historyDetail.Actions[m.historyActionCursor]
						if m.recoveryResult.OK && m.recoveryResult.Mode == "dry-run" &&
							m.recoveryResult.ActionID == action.ID {
							m.confirmRecovery = true
							m.recoveryInput = ""
							m.recoveryErr = nil
						} else {
							m.recoveryErr = fmt.Errorf("run T retry preview or C reconcile preview for this action first")
						}
					}
				case "esc", "left", "h":
					m.historyInspecting = false
					m.historyActionCursor = 0
					m.historyErr = nil
				}
			} else {
				switch shortcut {
				case "up", "k":
					if m.historyCursor > 0 { m.historyCursor-- }
				case "down", "j":
					if m.historyCursor < len(m.dashboard.Journal.LatestRuns)-1 { m.historyCursor++ }
				case "enter", "right", "l":
					if len(m.dashboard.Journal.LatestRuns) > 0 {
						m.historyInspecting = true
						m.historyLoading = true
						m.historyErr = nil
						m.historyActionCursor = 0
						return m, loadHistoryRun(m.dashboard.Journal.LatestRuns[m.historyCursor].RunID)
					}
				case "r":
					m.loading = true
					m.loadErr = nil
					return m, loadDashboard
				case "esc", "left", "h":
					m.contentFocus = false
					m.page = home
					m.selected = 0
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
				if m.dashboard.Mounts.AllReady && m.dryRun.ProtocolVersion == 1 && m.dryRun.Verified > 0 && m.dryRun.Blocked == 0 && m.dryRun.TimedOut == 0 {
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
				case "a": if m.dashboard.Mounts.AllReady && m.restorePlan.ReadyFiles > 0 && m.restorePlan.BlockedFiles == 0 { m.confirmRestore = true; m.restoreInput = ""; m.restoreErr = nil }
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
			m.contentFocus = m.page == groups || m.page == quarantine || m.page == restore || m.page == history || m.page == settings
			if m.page == groups {
				m.groupLoading = true
				m.groupErr = nil
				m.groupCursor = 0
				return m, loadGroupCatalog(m.groupQuery, m.groupRoot, m.groupSort, max(1, m.groupCatalog.Page))
			}
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

func (m model) currentGroupFiles() []duplicateFile {
	if m.groupCursor < 0 || m.groupCursor >= len(m.groupCatalog.Items) {
		return nil
	}
	return m.groupCatalog.Items[m.groupCursor].Files
}

func nextGroupSort(current string) string {
	modes := []string{"space-desc", "space-asc", "copies-desc", "path-asc", "group-asc"}
	for i, mode := range modes {
		if current == mode { return modes[(i+1)%len(modes)] }
	}
	return modes[0]
}

func groupSortLabel(mode string) string {
	labels := map[string]string{
		"space-desc": "most space", "space-asc": "least space",
		"copies-desc": "most copies", "path-asc": "path A–Z", "group-asc": "group number",
	}
	if label := labels[mode]; label != "" { return label }
	return mode
}

func (m model) nextGroupRoot() string {
	roots := []string{""}
	for _, root := range m.dashboard.Mounts.Roots { roots = append(roots, root.Path) }
	for i, root := range roots {
		if root == m.groupRoot { return roots[(i+1)%len(roots)] }
	}
	return ""
}

func galaxyGlyph(value, maximum int64, selected bool, phase int) string {
	if maximum <= 0 {
		return "·  "
	}
	ratio := float64(value) / float64(maximum)
	glyph := "·  "
	switch {
	case ratio >= 0.66:
		glyph = "✦✦✦"
	case ratio >= 0.25:
		glyph = "✦✦ "
	case ratio >= 0.10:
		glyph = "✦  "
	}
	if selected && phase%2 == 0 {
		glyph = strings.NewReplacer("✦", "✹", "·", "•").Replace(glyph)
	}
	return glyph
}

func (m model) mountHealthView(width int) string {
	title := lipgloss.NewStyle().Bold(true).Foreground(danger).Render("MOUNT ARRAY LOCKED")
	if m.dashboard.Mounts.AllReady {
		title = lipgloss.NewStyle().Bold(true).Foreground(lime).Render("MOUNT ARRAY ONLINE")
	}
	lines := []string{title}
	for _, root := range m.dashboard.Mounts.Roots {
		icon := "○"
		state := "OFFLINE"
		style := lipgloss.NewStyle().Foreground(danger)
		if root.Mounted {
			icon, state = "●", "ONLINE"
			style = lipgloss.NewStyle().Foreground(lime)
		}
		detail := root.Filesystem
		if root.Source != "" {
			detail += " · " + root.Source
		}
		line := fmt.Sprintf("%s %-7s %-18s %s", icon, state, compactPath(root.Path, 18), compactPath(detail, max(16, width-48)))
		lines = append(lines, style.Render(line))
	}
	if len(m.dashboard.Mounts.Roots) == 0 {
		lines = append(lines, lipgloss.NewStyle().Foreground(danger).Render("○ OFFLINE  no mount roots configured"))
	}
	return strings.Join(lines, "\n")
}

func (m model) galaxyView(width int) string {
	groups := m.groupCatalog.Items
	if len(groups) == 0 {
		return "No duplicate systems are loaded yet."
	}
	maximum := int64(0)
	for _, group := range groups {
		if group.RecoverableBytes > maximum {
			maximum = group.RecoverableBytes
		}
	}
	frames := []string{"◐", "◓", "◑", "◒"}
	scan := frames[m.scanPhase%len(frames)]
	panels := []string{}
	roots := m.dashboard.Mounts.Roots
	for rootIndex, root := range roots {
		indices := []int{}
		for i, group := range groups {
			if group.MountRoot == root.Path || (group.MountRoot == "" && rootIndex == 0) {
				indices = append(indices, i)
			}
		}
		start := 0
		for position, index := range indices {
			if index == m.groupCursor && position >= 7 {
				start = position - 6
			}
		}
		end := min(len(indices), start+8)
		status := "OFFLINE"
		accent := danger
		if root.Mounted {
			status, accent = "ONLINE", lime
		}
		baseStyle := lipgloss.NewStyle().Background(void)
		lines := []string{
			baseStyle.Bold(true).Foreground(accent).Render(strings.ToUpper(filepath.Base(root.Path)) + " NEBULA"),
			baseStyle.Foreground(muted).Render(status + " · " + root.Filesystem),
			"",
		}
		for _, index := range indices[start:end] {
			group := groups[index]
			selected := index == m.groupCursor
			marker := "  "
			if selected {
				marker = "▶ "
			}
			line := fmt.Sprintf("%s%s G%d %s", marker, galaxyGlyph(group.RecoverableBytes, maximum, selected, m.scanPhase), group.GroupID, group.RecoverableHuman)
			if selected {
				line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render(line)
			} else {
				line = baseStyle.Foreground(cyan).Render(line)
			}
			lines = append(lines, line)
		}
		if end < len(indices) {
			lines = append(lines, baseStyle.Foreground(muted).Render(fmt.Sprintf("+%d systems beyond scan", len(indices)-end)))
		}
		if len(indices) == 0 {
			lines = append(lines, baseStyle.Foreground(muted).Render("· clear orbit"))
		}
		panelWidth := max(18, (width-24)/max(1, len(roots)))
		panels = append(panels, lipgloss.NewStyle().Width(panelWidth).Border(lipgloss.RoundedBorder()).BorderForeground(accent).Background(void).Padding(0, 1).Render(strings.Join(lines, "\n")))
	}
	if len(panels) == 0 {
		return "Mount telemetry is unavailable; press G for the list view."
	}
	mapView := lipgloss.JoinHorizontal(lipgloss.Top, panels...)
	return fmt.Sprintf("LIVE ARRAY SCAN %s · recoverable space: · faint  ✦ low  ✦✦ medium  ✦✦✦ high\n\n%s\n\nPage %d/%d · ↑↓ choose · Enter inspect · [/ ] pages · / search · F root · S sort · G list", scan, mapView, m.groupCatalog.Page, max(1, m.groupCatalog.TotalPages))
}

func (m model) storageSetupView(width int) string {
	if m.scanSummaryVisible {
		return m.scanSummaryView(width)
	}
	if m.advancedMode {
		lines := []string{
			lipgloss.NewStyle().Bold(true).Foreground(pink).Render("ADVANCED CONFIGURATION"),
			"Choose a setting and press Enter to edit it. Nothing here moves files.",
			"Use absolute paths. Separate multiple rule paths with a colon (:).",
			"",
		}
		settings := m.advancedSettings()
		for i, setting := range settings {
			cursor := "  "
			if i == m.advancedCursor { cursor = "▶ " }
			value := setting.value
			if value == "" { value = "(none)" }
			line := fmt.Sprintf("%s%-20s %s", cursor, setting.label, compactPath(value, max(20, width-25)))
			style := lipgloss.NewStyle().Foreground(cyan)
			if i == m.advancedCursor { style = style.Bold(true).Foreground(void).Background(purple) }
			lines = append(lines, style.Render(line))
			if i == m.advancedCursor {
				lines = append(lines, "    "+mutedText.Render(setting.help))
			}
		}
		if m.advancedEditing {
			lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render("EDIT VALUE"),
				m.advancedInput+"█", "Enter accepts · Ctrl-G cancels · S saves after editing")
		} else {
			lines = append(lines, "", "↑↓ choose · Enter edit · S save all · E/H/← return to drives")
		}
		if m.setupMessage != "" { lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render(m.setupMessage)) }
		lines = append(lines, "", mutedText.Render("Protected and excluded roots are hard safety rules; preferred roots guide keeper choice."))
		return strings.Join(lines, "\n")
	}
	lines := []string{}
	if m.setupFirstRun {
		lines = append(lines,
			lipgloss.NewStyle().Bold(true).Foreground(pink).Render("WELCOME ABOARD"),
			"Choose the mounted storage roots Archive Keeper may manage.",
			"Setup records configuration only; it never mounts drives or moves files.",
			"",
		)
	}
	if len(m.setupCandidates) == 0 {
		lines = append(lines,
			lipgloss.NewStyle().Bold(true).Foreground(gold).Render("NO STORAGE MOUNTS DETECTED"),
			"Mount a drive under /mnt, /media, or /run/media, then press R to rescan.",
		)
	} else {
		for i, candidate := range m.setupCandidates {
			cursor := "  "
			if i == m.setupCursor {
				cursor = "▶ "
			}
			check := "[ ]"
			if m.setupSelected[candidate.Path] {
				check = "[✓]"
			}
			status := "DETECTED"
			statusColor := lime
			if candidate.Filesystem == "configured" {
				status = "NOT MOUNTED"
				statusColor = danger
			}
			line := fmt.Sprintf("%s%s %-11s %-10s %s", cursor, check, status, candidate.Filesystem, compactPath(candidate.Path, max(18, width-39)))
			style := lipgloss.NewStyle().Foreground(statusColor)
			if i == m.setupCursor {
				style = style.Bold(true).Foreground(void).Background(purple)
			}
			lines = append(lines, style.Render(line))
			if i == m.setupCursor && candidate.Source != "" {
				lines = append(lines, "    "+mutedText.Render("source: "+compactPath(candidate.Source, max(20, width-12))))
			}
		}
	}
	lines = append(lines, "", mutedText.Render("Report: "+compactPath(m.reportPath, max(24, width-10))))
	if m.setupMessage != "" {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render(m.setupMessage))
	}
	if m.scanMessage != "" {
		statusColor := lime
		if m.scanErr != nil {
			statusColor = danger
		}
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(statusColor).Render(m.scanMessage))
	}
	if m.scanRunning {
		elapsed := time.Since(m.scanStartedAt).Round(time.Second)
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("RMLINT SCAN RUNNING "+[]string{"◐", "◓", "◑", "◒"}[m.scanPhase%4]),
			fmt.Sprintf("Elapsed %s · Archive files remain untouched · X/H/← cancel", elapsed))
	} else if m.confirmScan {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render("START RMLINT DUPLICATE SCAN?"),
			"Enter confirms · H/← cancels · existing report is backed up after success")
	}
	if m.configSource != "" {
		lines = append(lines, "", mutedText.Render("Configuration source: "+m.configSource))
	}
	if !m.scanRunning && !m.confirmScan {
		lines = append(lines, "", "↑↓ choose · Space/Enter toggle · A all · N none · R rescan · S save · F scan · E advanced")
	}
	if !m.setupFirstRun && !m.scanRunning {
		lines = append(lines, "H/← return home")
	}
	return strings.Join(lines, "\n")
}

func (m model) scanSummaryView(width int) string {
	status := lipgloss.NewStyle().Bold(true).Foreground(lime).Render("SCAN COMPLETE")
	explanation := "rmlint created a new duplicate report. No files were moved or deleted."
	if m.scanErr != nil {
		status = lipgloss.NewStyle().Bold(true).Foreground(danger).Render("SCAN DID NOT COMPLETE")
		explanation = "The previous report remains active and your files were not changed."
	}
	lines := []string{status, explanation, "", fmt.Sprintf("Duration: %s", m.scanDuration)}
	if len(m.scanRoots) > 0 {
		lines = append(lines, fmt.Sprintf("Storage roots checked: %d", len(m.scanRoots)))
		for _, root := range m.scanRoots {
			lines = append(lines, "  • "+compactPath(root, max(24, width-8)))
		}
	}
	if m.scanErr != nil {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(danger).Render("WHAT HAPPENED"), m.scanErr.Error())
		if detail := strings.TrimSpace(strings.ReplaceAll(m.scanOutput, "\n", " ")); detail != "" {
			lines = append(lines, mutedText.Render("Technical detail: "+compactPath(detail, max(28, width-20))))
		}
		lines = append(lines, "", "R/H/← return to Storage Setup · F can start a new scan after returning")
		return strings.Join(lines, "\n")
	}
	if m.loading {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("READING THE NEW REPORT…"),
			"Archive Keeper is calculating the friendly summary now.")
	} else if m.loadErr != nil {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render("REPORT SAVED, SUMMARY UNAVAILABLE"), m.loadErr.Error())
	} else {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("RESULTS"),
			fmt.Sprintf("Duplicate groups: %d", m.dashboard.Report.Groups),
			fmt.Sprintf("Files charted: %d", m.dashboard.Report.Files),
			fmt.Sprintf("Potentially recoverable: %s", m.dashboard.Report.RecoverableHuman))
		if m.dashboard.Report.Groups == 0 {
			lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(lime).Render("NO DUPLICATES FOUND"),
				"There is nothing to review or quarantine from this scan.")
		}
	}
	if m.scanReportPath != "" {
		lines = append(lines, "", "Active report: "+compactPath(m.scanReportPath, max(24, width-17)))
	}
	if m.scanBackupPath != "" {
		lines = append(lines, "Previous report backup: "+compactPath(m.scanBackupPath, max(24, width-26)))
	} else {
		lines = append(lines, mutedText.Render("No older report needed to be backed up."))
	}
	lines = append(lines, "", "R/H/← return to Storage Setup · 1 Home")
	if !m.loading && m.loadErr == nil && m.dashboard.Report.Groups > 0 {
		lines = append(lines, "Enter/G or 2 opens Duplicate Groups")
	}
	return strings.Join(lines, "\n")
}

func (m *model) rescanSetupCandidates() {
	previous := m.selectedSetupRoots()
	discovered, err := discoverMountCandidates()
	if err != nil {
		m.setupMessage = "Storage rescan failed: " + err.Error()
		return
	}
	m.setupCandidates = mergeConfiguredCandidates(discovered, previous)
	m.setupSelected = map[string]bool{}
	for _, root := range previous {
		m.setupSelected[filepath.Clean(root)] = true
	}
	if m.setupCursor >= len(m.setupCandidates) {
		m.setupCursor = max(0, len(m.setupCandidates)-1)
	}
	m.setupMessage = fmt.Sprintf("Detected %d storage mount(s)", len(discovered))
}

func (m model) selectedSetupRoots() []string {
	roots := []string{}
	for _, candidate := range m.setupCandidates {
		if m.setupSelected[candidate.Path] {
			roots = append(roots, candidate.Path)
		}
	}
	return roots
}

type advancedSetting struct {
	label string
	help  string
	value string
}

func (m model) advancedSettings() []advancedSetting {
	return []advancedSetting{
		{"Report path", "Where rmlint JSON is read and successful scans are saved.", m.reportPath},
		{"Journal database", "Records every applied move so quarantine can be restored.", m.stateDBPath},
		{"Decisions database", "Stores keepers and staged choices; it never contains file data.", m.decisionsDBPath},
		{"Quarantine folder", "One folder name created inside each managed storage root.", m.quarantineName},
		{"Preferred roots", "Keeper preference order; separate multiple absolute paths with a colon.", joinPathSetting(m.preferredRoots)},
		{"Protected roots", "Files beneath these absolute paths must never be quarantined.", joinPathSetting(m.protectedRoots)},
		{"Exclusions", "Trees Archive Keeper should ignore; separate paths with a colon.", joinPathSetting(m.excludedRoots)},
	}
}

func (m *model) setAdvancedSetting(index int, value string) error {
	value = strings.TrimSpace(value)
	switch index {
	case 0:
		if !filepath.IsAbs(value) { return fmt.Errorf("report path must be absolute") }
		m.reportPath = filepath.Clean(value)
	case 1:
		if !filepath.IsAbs(value) { return fmt.Errorf("journal database path must be absolute") }
		m.stateDBPath = filepath.Clean(value)
	case 2:
		if !filepath.IsAbs(value) { return fmt.Errorf("decisions database path must be absolute") }
		m.decisionsDBPath = filepath.Clean(value)
	case 3:
		if value == "" || value == "." || value == ".." || filepath.Base(value) != value { return fmt.Errorf("enter one folder name, without slashes") }
		m.quarantineName = value
	case 4, 5, 6:
		paths, err := normalizeAbsolutePaths(splitPathSetting(value))
		if err != nil { return err }
		if index == 4 { m.preferredRoots = paths }
		if index == 5 { m.protectedRoots = paths }
		if index == 6 { m.excludedRoots = paths }
	default:
		return fmt.Errorf("unknown setting")
	}
	return nil
}

func (m model) currentUIConfig(roots []string) uiConfig {
	return uiConfig{Version: 1, MountRoots: roots, ReportPath: m.reportPath,
		StateDBPath: m.stateDBPath, DecisionsDBPath: m.decisionsDBPath,
		QuarantineName: m.quarantineName, PreferredRoots: m.preferredRoots,
		ProtectedRoots: m.protectedRoots, ExcludedRoots: m.excludedRoots}
}

func (m *model) saveCurrentConfiguration(roots []string) error {
	config := m.currentUIConfig(roots)
	if err := saveUIConfig(config); err != nil { return err }
	applyRootConfiguration(roots)
	applyAdvancedConfiguration(config)
	return nil
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
		"\n\n" + m.mountHealthView(width) + "\n\n" + status + "\n\n" + basicInstructions(home)
	return frame("MISSION CONTROL", "Read-only overview · no files move from this screen", body, width, pink)
}

func historyStatusColor(status string) color.Color {
	switch strings.ToLower(status) {
	case "moved", "restored", "complete":
		return lime
	case "failed", "stale", "blocked", "timeout", "timed-out":
		return danger
	default:
		return gold
	}
}

func historyStatusSummary(counts map[string]int) string {
	if len(counts) == 0 {
		return "no recorded actions"
	}
	keys := make([]string, 0, len(counts))
	for key := range counts { keys = append(keys, key) }
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, key := range keys {
		parts = append(parts, fmt.Sprintf("%s %d", strings.ToUpper(key), counts[key]))
	}
	return strings.Join(parts, " · ")
}

func (m model) historyView(width int) string {
	if !m.historyInspecting {
		lines := []string{fmt.Sprintf("%d journaled runs", m.dashboard.Journal.Runs), ""}
		visible := max(3, min(8, m.height-18))
		start := 0
		if m.historyCursor >= visible {
			start = m.historyCursor-visible+1
		}
		end := min(len(m.dashboard.Journal.LatestRuns), start+visible)
		if start > 0 {
			lines = append(lines, mutedText.Render(fmt.Sprintf("↑ %d earlier runs", start)))
		}
		for i := start; i < end; i++ {
			run := m.dashboard.Journal.LatestRuns[i]
			line := fmt.Sprintf("  ≋ %s  %-8s  %s", compactPath(run.RunID, 28), run.Mode, strings.ToUpper(run.Status))
			if i == m.historyCursor {
				line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render("▶" + line[1:])
			} else {
				line = lipgloss.NewStyle().Foreground(historyStatusColor(run.Status)).Render(line)
			}
			lines = append(lines, line)
		}
		if end < len(m.dashboard.Journal.LatestRuns) {
			lines = append(lines, mutedText.Render(fmt.Sprintf("↓ %d later runs", len(m.dashboard.Journal.LatestRuns)-end)))
		}
		if len(m.dashboard.Journal.LatestRuns) == 0 {
			lines = append(lines, "No journaled runs yet.")
		}
		lines = append(lines, "", "↑↓ select · Enter inspect run · R reload · H/← home",
			"", mutedText.Render("Operational source: journal.sqlite3 (opened read-only)"))
		return strings.Join(lines, "\n")
	}

	if m.historyLoading {
		return lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("OPENING FLIGHT RECORD…") +
			"\nReading the selected run without modifying its journal."
	}
	if m.historyErr != nil {
		return lipgloss.NewStyle().Bold(true).Foreground(danger).Render("HISTORY UNAVAILABLE") +
			"\n" + m.historyErr.Error() + "\n\nR retry · H/← runs"
	}

	detail := m.historyDetail
	if m.confirmRecovery {
		expected := expectedRecoveryConfirmation(m.recoveryKind, m.recoveryResult.ActionID)
		lines := []string{
			lipgloss.NewStyle().Bold(true).Foreground(gold).Render("CONTROLLED RECOVERY GATE"),
			fmt.Sprintf("%s selected action %d only.", strings.ToUpper(m.recoveryKind), m.recoveryResult.ActionID),
			"No overwrite · live verification · journal enabled",
			"",
			"Type exactly:",
			lipgloss.NewStyle().Bold(true).Foreground(pink).Render(expected),
			"",
			"> " + m.recoveryInput,
			"",
			"Enter confirm · ← cancel",
		}
		if m.recoveryErr != nil { lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(danger).Render(m.recoveryErr.Error())) }
		return strings.Join(lines, "\n")
	}
	lines := []string{
		fmt.Sprintf("RUN %s", detail.Run.RunID),
		fmt.Sprintf("%s · %s · %s", detail.Run.CreatedAtHuman, detail.Run.Mode, strings.ToUpper(detail.Run.Status)),
		fmt.Sprintf("%d actions · %s · %s", detail.TotalActions, detail.TotalHuman, historyStatusSummary(detail.StatusCounts)),
		"",
	}
	if len(detail.Actions) == 0 {
		lines = append(lines, "No file actions were recorded for this run.")
	} else {
		visible := max(3, min(7, m.height-22))
		start := 0
		if m.historyActionCursor >= visible { start = m.historyActionCursor-visible+1 }
		end := min(len(detail.Actions), start+visible)
		for i := start; i < end; i++ {
			action := detail.Actions[i]
			line := fmt.Sprintf("  %-9s G%-4d %-9s %s",
				strings.ToUpper(action.Status), action.GroupID, action.SizeHuman,
				compactPath(action.Source, max(16, width-44)))
			if i == m.historyActionCursor {
				line = lipgloss.NewStyle().Bold(true).Foreground(void).Background(purple).Render("▶" + line[1:])
			} else {
				line = lipgloss.NewStyle().Foreground(historyStatusColor(action.Status)).Render(line)
			}
			lines = append(lines, line)
		}
		if end < len(detail.Actions) {
			lines = append(lines, mutedText.Render(fmt.Sprintf("+%d later actions", len(detail.Actions)-end)))
		}
		action := detail.Actions[m.historyActionCursor]
		lines = append(lines, "",
			lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("SOURCE"), compactPath(action.Source, max(24, width-8)),
			lipgloss.NewStyle().Bold(true).Foreground(lime).Render("KEEPER"), compactPath(action.Keeper, max(24, width-8)),
			lipgloss.NewStyle().Bold(true).Foreground(pink).Render("DESTINATION"), compactPath(action.Destination, max(24, width-8)))
		if action.Message != "" {
			lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(gold).Render("MESSAGE"), action.Message)
		}
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(cyan).Render("RECOVERY CONTROL"))
		if m.recoveryRunning {
			lines = append(lines, "VERIFYING SELECTED ACTION…")
		} else if m.recoveryErr != nil {
			lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(danger).Render("BLOCKED · "+m.recoveryErr.Error()))
		} else if m.recoveryResult.ActionID == action.ID {
			label := "PREVIEW READY"
			if m.recoveryResult.Mode == "apply" { label = "RECOVERY COMPLETE" }
			lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(lime).Render(
				fmt.Sprintf("%s · %s · %s → %s", label, strings.ToUpper(m.recoveryResult.Kind),
					strings.ToUpper(m.recoveryResult.BeforeStatus), strings.ToUpper(m.recoveryResult.AfterStatus))))
		}
	}
	lines = append(lines, "", "↑↓ actions · T retry preview · C reconcile preview · A apply preview · R reload · H/← runs")
	return strings.Join(lines, "\n")
}

func basicInstructions(page screen) string {
	header := lipgloss.NewStyle().Bold(true).Foreground(gold).Render("BASIC GUIDE")
	guides := map[screen]string{
		home: "1) Use Storage Setup to choose drives.  2) Run/import an rmlint report.  3) Open Duplicate Groups.\nHome is a read-only overview; it never moves files.",
		groups: "Choose a group and press Enter. Save its keeper first; X stages one copy and B reviews all nonkeepers.\nThis screen saves choices only; it never moves files.",
		decisions: "This is your decision summary. To change a keeper or staged copy, return to Duplicate Groups.\nNothing moves until Quarantine passes its preview and confirmation gates.",
		quarantine: "First press D for the safe dry pilot. If every check passes, press A and type the exact phrase shown.\nOnly the final confirmed A step can move staged files into quarantine; nothing is deleted.",
		restore: "Choose a quarantine run, press Enter to preview it, then A to open the exact-phrase restore gate.\nRestore never overwrites an existing file; collisions are blocked.",
		history: "Choose a run and press Enter to inspect its actions. T previews retry; C previews reconcile; A applies that clean preview.\nBrowsing is read-only. Recovery changes require their own exact confirmation phrase.",
		settings: "Use ↑↓ and Space/Enter to choose mounted roots, then S to save. Press E for explained advanced paths and safety rules. Press F only when you want an rmlint scan.\nA scan reads filenames/content to find duplicates but never runs rmlint's cleanup script or moves files.",
	}
	if guide := guides[page]; guide != "" { return header + "\n" + guide }
	return ""
}

func (m model) pageView(page screen, width int) string {
	spec := map[screen][3]string{
		groups: {"DUPLICATE CONSTELLATIONS", "Browse groups by size, type, location, or confidence", "Group list and side-by-side copy inspector\n\nFilters  / search  ·  Space  potential  ·  Copies  path map\n\nEvery group keeps at least one verified original."},
		decisions: {"KEEPER ORBIT", "Choose what remains and understand why", "★ KEEP      selected original\n◇ QUARANTINE staged duplicate\n? UNDECIDED  requires attention\n\nManual decisions persist in decisions.sqlite3."},
		quarantine: {"QUARANTINE AIRLOCK", "Preview first; mutation always requires explicit confirmation", "1  Inspect the generated plan\n2  Run a bounded dry pilot\n3  Verify source and keeper\n4  Confirm --apply\n\nSafety interlocks remain owned by the Python engine."},
		restore: {"RESTORE BEACON", "Bring a quarantined file home without overwriting data", "Select a run from history, preview destinations, inspect collisions, then confirm restoration.\n\nDifferent-content collisions fail closed."},
		history: {"FLIGHT RECORDER", "Journaled actions, outcomes, retries, and recovery", "Runs will appear here with moved, reconciled, stale, timeout, failed, and restored counts.\n\nOperational source: journal.sqlite3"},
		settings: {"STORAGE ARRAY SETUP", "Choose drives, configure safety rules, and run a safe duplicate scan", ""},
		help: {"GALACTIC FIELD GUIDE", "Navigation and non-negotiable safety rules", "↑↓ or j/k  navigate\nEnter       open / choose keeper\n/           search duplicate paths\nF           filter groups by storage root\nS           change group sort order\n[ and ]     previous / next group page\nX           stage one copy for quarantine\nB           review/stage every nonkeeper\nU           mark undecided\nC           clear staged choice\nD           run bounded dry pilot\nA           open controlled apply gate\nH or ←      back / cancel gate\nG           galaxy / list view\n6           history / run drill-down\n8           storage setup / rmlint scan\nE           advanced setup fields\n1–8         jump to screen\nShift+/ (?) open this guide\nq           quit\n\nBulk staging requires a saved keeper and never stages it. Protected and excluded roots are hard safety rules. A clean dry pilot unlocks apply. Apply moves at most 10 explicitly staged files and requires the exact confirmation phrase. Choices and every move are journaled for recovery."},
	}
	v := spec[page]
	if page == settings {
		v[2] = m.storageSetupView(width)
		v[2] += "\n\n" + basicInstructions(settings)
		return frame(v[0], v[1], v[2], width, pink)
	}
	if m.loadErr == nil && m.dashboard.ProtocolVersion == 1 {
		switch page {
		case groups:
			if m.groupSearch {
				v[2] = "SEARCH FILE PATHS\n\n> " + m.groupSearchInput + "▌\n\nType part of a folder or filename. Enter searches · H/← cancels.\nThis only reads the rmlint report; it does not scan or move files."
				return frame(v[0], v[1], v[2]+"\n\n"+basicInstructions(groups), width, cyan)
			}
			if m.groupLoading {
				v[2] = "Loading this page from the rmlint report…\n\nFiles are being listed only; nothing is moved or changed."
				break
			}
			if m.groupErr != nil {
				v[2] = lipgloss.NewStyle().Bold(true).Foreground(danger).Render("GROUP LIST UNAVAILABLE") + "\n" + m.groupErr.Error() + "\n\nPress 2 to retry · H/← returns to the menu."
				break
			}
			if m.inspecting && m.groupCursor < len(m.groupCatalog.Items) {
				group := m.groupCatalog.Items[m.groupCursor]
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
					} else if pathWithinAny(files[i].Path, m.protectedRoots) {
						hint = "PROTECTED"
					} else if pathWithinAny(files[i].Path, m.excludedRoots) {
						hint = "EXCLUDED"
					} else if action := m.dashboard.Decisions.FileActions[actionKey]; action != "" {
						hint = action
					} else if pathWithinAny(files[i].Path, m.preferredRoots) {
						hint = "PREFERRED"
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
				} else if m.confirmBulk {
					keeper := m.dashboard.Decisions.KeeperPaths[strconv.Itoa(group.GroupID)]
					lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render(
						fmt.Sprintf("KEEP 1 · STAGE %d NONKEEPERS?", max(0, len(files)-1))),
						"Protected keeper: "+compactPath(keeper, max(24, width-24)),
						"Enter/Y confirm · N/H/← cancel · decisions only; no files move")
				} else if m.confirmAction != "" {
					prompt := "STAGE " + m.confirmAction + " FOR THIS COPY?"
					if m.confirmAction == "CLEAR" {
						prompt = "CLEAR THE STAGED DECISION FOR THIS COPY?"
					}
					lines = append(lines, "", lipgloss.NewStyle().Bold(true).Foreground(gold).Render(prompt),
						"Enter/Y confirm · N/H/← cancel · no archive files move")
				} else {
					lines = append(lines, "", fmt.Sprintf("Copy %d of %d · Enter keeper · X one copy · B all nonkeepers · U undecided · C clear · H/← back", m.fileCursor+1, len(files)),
						mutedText.Render("PREFERRED is suggested first; PROTECTED and EXCLUDED copies cannot be staged."))
				}
				if m.statusMessage != "" { lines = append(lines, "", m.statusMessage) }
				return frame(fmt.Sprintf("CONSTELLATION %d", group.GroupID), fmt.Sprintf("%d copies · %s recoverable · keeper decisions enabled", group.Copies, group.RecoverableHuman), strings.Join(lines, "\n")+"\n\n"+basicInstructions(groups), width, cyan)
			}
			if m.galaxyMode {
				v[2] = m.galaxyView(width)
				break
			}
			lines := []string{}
			for i, group := range m.groupCatalog.Items {
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
				lines = append(lines, "No groups match this search and root filter.")
			}
			rootLabel := "all roots"
			if m.groupRoot != "" { rootLabel = filepath.Base(m.groupRoot) }
			queryLabel := "none"
			if m.groupQuery != "" { queryLabel = m.groupQuery }
			controls := fmt.Sprintf("Page %d/%d · %d of %d groups · search: %s · root: %s · sort: %s",
				m.groupCatalog.Page, max(1, m.groupCatalog.TotalPages), m.groupCatalog.FilteredGroups,
				m.groupCatalog.TotalGroups, compactPath(queryLabel, 20), rootLabel, groupSortLabel(m.groupSort))
			v[2] = strings.Join(lines, "\n") + "\n\n" + controls +
				"\n↑↓ choose · Enter inspect · [/] pages · / search · F root · S sort · G galaxy · H/← menu"
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
					if m.dashboard.Mounts.AllReady {
						lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(pink).Render("A controlled apply · typed confirmation required"))
					} else {
						lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(danger).Render("APPLY LOCKED · mount array not ready"))
					}
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
			if m.restorePlan.ReadyFiles > 0 && m.restorePlan.BlockedFiles == 0 && !m.confirmRestore && !m.restoring {
				if m.dashboard.Mounts.AllReady { lines=append(lines,"",lipgloss.NewStyle().Bold(true).Foreground(pink).Render("A controlled restore · typed confirmation required"))
				} else { lines=append(lines,"",lipgloss.NewStyle().Bold(true).Foreground(danger).Render("RESTORE LOCKED · mount array not ready")) }
			}
			lines=append(lines,"","↑↓ inspect · A controlled restore · R reload · H/← runs")
			v[2]=strings.Join(lines,"\n")
		case history:
			v[2] = m.historyView(width)
		}
	}
	if guide := basicInstructions(page); guide != "" { v[2] += "\n\n" + guide }
	return frame(v[0], v[1], v[2], width, cyan)
}

func (m model) View() tea.View {
	contentWidth := max(34, m.width-34)
	content := m.homeView(contentWidth)
	if m.page != home { content = m.pageView(m.page, contentWidth) }
	var rendered string
	if m.compact {
		rendered = logoStyle.Render("✦ ARCHIVE KEEPER · STORAGE GALAXY 2.0") + "\n" +
			mutedText.Render("1 Home · 2 Groups · 3 Keepers · 4 Quarantine · 5 Restore · 6 History · 7 Help · 8 Setup") +
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
		bridgeStatus = "GALAXY MAP · ↑↓ systems · Enter inspect · G list · files untouched"
		if m.inspecting { bridgeStatus = "GROUP INSPECTOR · Enter keeper · X one · B all nonkeepers · decisions only" }
	} else if m.page == quarantine && m.contentFocus {
		bridgeStatus = "QUARANTINE PREVIEW · D dry pilot · R reload · no moves · no journal writes"
		if m.confirmApply {
			bridgeStatus = "FINAL SAFETY GATE · type the exact phrase · ← cancels"
		} else if m.applying {
			bridgeStatus = "CONTROLLED QUARANTINE · bounded apply · journal enabled"
		}
	} else if m.page == settings && m.contentFocus {
		bridgeStatus = "STORAGE SETUP · detection and configuration only · files untouched"
		if m.scanRunning {
			bridgeStatus = "RMLINT SCAN · read-only file inspection · no cleanup script"
		}
	} else if m.page == history && m.contentFocus {
		bridgeStatus = "FLIGHT RECORDER · journal opened read-only"
		if m.historyInspecting { bridgeStatus = "RUN INSPECTOR · ↑↓ actions · R reload · no journal writes" }
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
	if len(os.Args) == 2 && os.Args[1] == "--health-check" {
		fmt.Println("archive-keeper-ui ready")
		return
	}
	p := tea.NewProgram(initialModel())
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "archive-keeper-ui:", err)
		os.Exit(1)
	}
}
