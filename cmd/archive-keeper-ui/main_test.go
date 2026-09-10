package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestStructuredErrorLogIsJSONLinesAndOwnerOnly(t *testing.T) {
	path := filepath.Join(t.TempDir(), "logs", "ui-errors.jsonl")
	t.Setenv("ARCHIVE_KEEPER_UI_LOG", path)
	loggedPath, err := writeStructuredLog("error", "python_bridge", "dashboard", fmt.Errorf("bridge unavailable"), map[string]any{"attempt": 2})
	if err != nil {
		t.Fatalf("write structured log: %v", err)
	}
	if loggedPath != path {
		t.Fatalf("unexpected log path: %q", loggedPath)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat structured log: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("structured log mode = %o, want 600", info.Mode().Perm())
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read structured log: %v", err)
	}
	var event structuredLogEvent
	if err := json.Unmarshal(data, &event); err != nil {
		t.Fatalf("log is not one JSON object: %v", err)
	}
	if event.Level != "error" || event.Component != "python_bridge" || event.Operation != "dashboard" || event.Message != "bridge unavailable" {
		t.Fatalf("unexpected structured event: %#v", event)
	}
	if event.Details["attempt"] != float64(2) {
		t.Fatalf("structured details missing attempt: %#v", event.Details)
	}
}

func TestCompactPathLeavesShortPathsAlone(t *testing.T) {
	path := "/mnt/MyCloud1/movie.mp4"
	if got := compactPath(path, 80); got != path {
		t.Fatalf("compactPath changed a short path: %q", got)
	}
}

func TestCompactPathKeepsBothEnds(t *testing.T) {
	got := compactPath("/mnt/MyCloud1/a/very/long/folder/movie.mp4", 24)
	if got != "/mnt/MyClou…er/movie.mp4" {
		t.Fatalf("unexpected compact path: %q", got)
	}
}

func TestControlledApplyConfirmationUsesBoundedLimit(t *testing.T) {
	t.Setenv("ARCHIVE_KEEPER_APPLY_LIMIT", "3")
	if got := controlledApplyLimit(); got != 3 {
		t.Fatalf("unexpected controlled apply limit: %d", got)
	}
	if got := expectedApplyConfirmation(); got != "QUARANTINE UP TO 3 FILES" {
		t.Fatalf("unexpected confirmation phrase: %q", got)
	}
}

func TestControlledApplyLimitRejectsUnsafeOverride(t *testing.T) {
	t.Setenv("ARCHIVE_KEEPER_APPLY_LIMIT", "999")
	if got := controlledApplyLimit(); got != 10 {
		t.Fatalf("unsafe limit override escaped the hard cap: %d", got)
	}
}

func TestApplyConfirmationInputAcceptsNamedSpaceKey(t *testing.T) {
	got := appendApplyConfirmationInput("QUARANTINE", "space")
	got = appendApplyConfirmationInput(got, "u")
	if got != "QUARANTINE U" {
		t.Fatalf("space key was not added to confirmation input: %q", got)
	}
}

func TestControlledRestoreConfirmationUsesBoundedLimit(t *testing.T) {
	t.Setenv("ARCHIVE_KEEPER_RESTORE_LIMIT", "2")
	if got := controlledRestoreLimit(); got != 2 { t.Fatalf("unexpected restore limit: %d", got) }
	if got := expectedRestoreConfirmation(); got != "RESTORE UP TO 2 FILES" { t.Fatalf("unexpected restore phrase: %q", got) }
}

func TestGalaxyGlyphEncodesDensityAndSelectionPulse(t *testing.T) {
	if got := galaxyGlyph(100, 100, false, 1); got != "✦✦✦" {
		t.Fatalf("largest system should have three stars: %q", got)
	}
	if got := galaxyGlyph(30, 100, false, 1); got != "✦✦ " {
		t.Fatalf("medium system should have two stars: %q", got)
	}
	if got := galaxyGlyph(12, 100, false, 1); got != "✦  " {
		t.Fatalf("low system should have one star: %q", got)
	}
	if got := galaxyGlyph(5, 100, false, 1); got != "·  " {
		t.Fatalf("faint system should be a point: %q", got)
	}
	if got := galaxyGlyph(30, 100, true, 2); got != "✹✹ " {
		t.Fatalf("selected system should pulse without losing its tier: %q", got)
	}
}

func TestGalaxyViewUsesMountRegions(t *testing.T) {
	var m model
	m.width = 160
	m.galaxyMode = true
	m.dashboard.Mounts.AllReady = false
	m.dashboard.Mounts.Roots = append(m.dashboard.Mounts.Roots, struct {
		Path       string `json:"path"`
		Mounted    bool   `json:"mounted"`
		Filesystem string `json:"filesystem"`
		Source     string `json:"source"`
		Status     string `json:"status"`
	}{Path: "/mnt/MyCloud1", Mounted: true, Filesystem: "cifs", Source: "//nas/MyCloud1", Status: "online"})
	m.groupCatalog.Page = 1
	m.groupCatalog.TotalPages = 1
	m.groupCatalog.Items = append(m.groupCatalog.Items, duplicateGroup{
		GroupID: 42, Copies: 2, RecoverableBytes: 4096,
		RecoverableHuman: "4.00 KiB", MountRoot: "/mnt/MyCloud1",
	})
	got := m.galaxyView(120)
	if !strings.Contains(got, "MYCLOUD1 NEBULA") || !strings.Contains(got, "G42") {
		t.Fatalf("galaxy view did not render mount region and group: %q", got)
	}
}

func TestGroupSortCyclesThroughEveryMode(t *testing.T) {
	mode := "space-desc"
	want := []string{"space-asc", "copies-desc", "path-asc", "group-asc", "space-desc"}
	for _, expected := range want {
		mode = nextGroupSort(mode)
		if mode != expected { t.Fatalf("next sort = %q, want %q", mode, expected) }
	}
}

func TestEveryPrimaryScreenHasBasicGuidance(t *testing.T) {
	for _, page := range []screen{home, groups, decisions, quarantine, restore, history, settings} {
		if guide := basicInstructions(page); !strings.Contains(guide, "BASIC GUIDE") {
			t.Fatalf("screen %d has no basic guide: %q", page, guide)
		}
	}
}

func TestBulkStageResultIsDecisionOnly(t *testing.T) {
	result := bulkStageResult{ProtocolVersion: 1, OK: true, GroupID: 7, Staged: 3, KeeperPath: "/keeper"}
	if !result.OK || result.Staged != 3 || result.KeeperPath == "" {
		t.Fatalf("unexpected bulk stage result: %#v", result)
	}
}


func TestParseMountCandidatesFiltersPseudoAndDecodesPaths(t *testing.T) {
	mountInfo := strings.Join([]string{
		"31 20 0:45 / /mnt/MyCloud1 rw,relatime - cifs //nas/MyCloud1 rw",
		"32 20 0:46 / /mnt/Photo\\040Vault rw,relatime - nfs4 nas:/photos rw",
		"33 20 0:47 / /proc rw,nosuid - proc proc rw",
		"34 20 0:48 / /tmp rw,nosuid - tmpfs tmpfs rw",
	}, "\n")
	got := parseMountCandidates(mountInfo)
	wantPaths := []string{"/mnt/MyCloud1", "/mnt/Photo Vault"}
	if len(got) != len(wantPaths) {
		t.Fatalf("expected %d storage mounts, got %#v", len(wantPaths), got)
	}
	for i, want := range wantPaths {
		if got[i].Path != want {
			t.Fatalf("candidate %d path = %q, want %q", i, got[i].Path, want)
		}
	}
}

func TestParseMountCandidatesCoversSupportedStorageKinds(t *testing.T) {
	mountInfo := strings.Join([]string{
		"41 20 8:1 / /mnt/LocalDisk rw,relatime - ext4 /dev/sdb1 rw",
		"42 20 0:51 / /mnt/TeamShare rw,relatime - cifs //server/share rw",
		"43 20 0:52 / /mnt/Research rw,relatime - nfs4 server:/exports/research rw",
		"44 20 8:17 / /media/aaron/USB\040ARCHIVE rw,nosuid - exfat /dev/sdc1 rw",
	}, "\n")

	got := parseMountCandidates(mountInfo)
	want := []mountCandidate{
		{Path: "/media/aaron/USB ARCHIVE", Filesystem: "exfat", Source: "/dev/sdc1"},
		{Path: "/mnt/LocalDisk", Filesystem: "ext4", Source: "/dev/sdb1"},
		{Path: "/mnt/Research", Filesystem: "nfs4", Source: "server:/exports/research"},
		{Path: "/mnt/TeamShare", Filesystem: "cifs", Source: "//server/share"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("storage matrix mismatch:\n got: %#v\nwant: %#v", got, want)
	}

	merged := mergeConfiguredCandidates(got, []string{"/mnt/TeamShare", "/mnt/OfflineVault"})
	foundOffline := false
	for _, candidate := range merged {
		if candidate.Path == "/mnt/OfflineVault" {
			foundOffline = candidate.Filesystem == "configured"
		}
	}
	if !foundOffline {
		t.Fatalf("configured offline storage was not retained: %#v", merged)
	}
}

func TestThemeColorSupportsLowAndNoColorModes(t *testing.T) {
	t.Setenv("NO_COLOR", "1")
	if _, ok := themeColor("#FFFFFF", 15).(lipgloss.NoColor); !ok {
		t.Fatalf("NO_COLOR did not disable color")
	}

	t.Setenv("NO_COLOR", "")
	t.Setenv("ARCHIVE_KEEPER_LOW_COLOR", "1")
	if reflect.TypeOf(themeColor("#FFFFFF", 15)) != reflect.TypeOf(lipgloss.ANSIColor(15)) {
		t.Fatalf("low-color mode did not select an ANSI indexed color")
	}
}

func TestUIConfigRoundTrip(t *testing.T) {
	configPath := filepath.Join(t.TempDir(), "archive-keeper", "ui.json")
	t.Setenv("ARCHIVE_KEEPER_UI_CONFIG", configPath)
	want := uiConfig{
		Version: 1,
		MountRoots: []string{"/mnt/Zeta", "/mnt/Alpha", "/mnt/Zeta"},
		ReportPath: filepath.Join(t.TempDir(), "rmlint.json"),
		StateDBPath: filepath.Join(t.TempDir(), "journal.sqlite3"),
		DecisionsDBPath: filepath.Join(t.TempDir(), "decisions.sqlite3"),
		QuarantineName: "ArchiveKeeper Safe Hold",
		PreferredRoots: []string{"/mnt/Zeta/Favorites"},
		ProtectedRoots: []string{"/mnt/Alpha/Originals"},
		ExcludedRoots: []string{"/mnt/Alpha/Cache"},
	}
	if err := saveUIConfig(want); err != nil {
		t.Fatalf("saveUIConfig: %v", err)
	}
	got, err := loadUIConfig()
	if err != nil {
		t.Fatalf("loadUIConfig: %v", err)
	}
	if got.Version != 1 || got.ReportPath != want.ReportPath ||
		got.StateDBPath != want.StateDBPath || got.DecisionsDBPath != want.DecisionsDBPath ||
		got.QuarantineName != want.QuarantineName {
		t.Fatalf("unexpected saved config: %#v", got)
	}
	if !reflect.DeepEqual(got.MountRoots, []string{"/mnt/Alpha", "/mnt/Zeta"}) {
		t.Fatalf("mount roots were not normalized and sorted: %#v", got.MountRoots)
	}
	if !reflect.DeepEqual(got.PreferredRoots, want.PreferredRoots) ||
		!reflect.DeepEqual(got.ProtectedRoots, want.ProtectedRoots) ||
		!reflect.DeepEqual(got.ExcludedRoots, want.ExcludedRoots) {
		t.Fatalf("advanced path rules were not preserved: %#v", got)
	}
}

func TestAdvancedSettingValidationAndPreferredCursor(t *testing.T) {
	var m model
	if err := m.setAdvancedSetting(3, "nested/folder"); err == nil {
		t.Fatal("quarantine folder accepted a path instead of one folder name")
	}
	if err := m.setAdvancedSetting(5, "relative/path"); err == nil {
		t.Fatal("protected roots accepted a relative path")
	}
	if err := m.setAdvancedSetting(5, "/mnt/Protected:/mnt/Protected"); err != nil {
		t.Fatalf("valid protected roots rejected: %v", err)
	}
	if !reflect.DeepEqual(m.protectedRoots, []string{"/mnt/Protected"}) {
		t.Fatalf("protected roots were not normalized: %#v", m.protectedRoots)
	}
	m.preferredRoots = []string{"/mnt/Favorite"}
	group := duplicateGroup{Files: []duplicateFile{
		{Path: "/mnt/Other/copy.bin"},
		{Path: "/mnt/Favorite/keeper.bin"},
	}}
	if got := m.preferredFileCursor(group); got != 1 {
		t.Fatalf("preferred file cursor = %d, want 1", got)
	}
}

func TestPathWithinAnyUsesPathBoundaries(t *testing.T) {
	if !pathWithinAny("/mnt/Protected/child/file.bin", []string{"/mnt/Protected"}) {
		t.Fatal("child path was not recognized as protected")
	}
	if pathWithinAny("/mnt/Protected-ish/file.bin", []string{"/mnt/Protected"}) {
		t.Fatal("similar path escaped boundary-safe matching")
	}
}

func TestHistoryStatusSummaryIsDeterministic(t *testing.T) {
	got := historyStatusSummary(map[string]int{"restored": 2, "failed": 1, "moved": 3})
	want := "FAILED 1 · MOVED 3 · RESTORED 2"
	if got != want {
		t.Fatalf("unexpected history summary: %q", got)
	}
}

func TestHistoryRunListShowsSelectionAndReadOnlyControls(t *testing.T) {
	var m model
	m.historyCursor = 0
	m.dashboard.Journal.Runs = 1
	m.dashboard.Journal.LatestRuns = append(m.dashboard.Journal.LatestRuns, struct {
		RunID  string `json:"run_id"`
		Mode   string `json:"mode"`
		Status string `json:"status"`
	}{RunID: "ui-history-test", Mode: "apply", Status: "restored"})
	got := m.historyView(100)
	for _, want := range []string{"ui-history-test", "RESTORED", "Enter inspect run", "opened read-only"} {
		if !strings.Contains(got, want) {
			t.Fatalf("history list missing %q: %q", want, got)
		}
	}
}

func TestHistoryRunListScrollsWithSelection(t *testing.T) {
	var m model
	m.height = 24
	m.dashboard.Journal.Runs = 12
	for i := 0; i < 12; i++ {
		m.dashboard.Journal.LatestRuns = append(m.dashboard.Journal.LatestRuns, struct {
			RunID  string `json:"run_id"`
			Mode   string `json:"mode"`
			Status string `json:"status"`
		}{RunID: fmt.Sprintf("run-%02d", i), Mode: "apply", Status: "complete"})
	}
	m.historyCursor = 9
	got := m.historyView(100)
	for _, want := range []string{"run-09", "↑ 4 earlier runs", "↓ 2 later runs"} {
		if !strings.Contains(got, want) {
			t.Fatalf("scrolled history list missing %q: %q", want, got)
		}
	}
	if strings.Contains(got, "run-00") {
		t.Fatalf("history viewport should not render off-screen runs: %q", got)
	}
}

func TestRecoveryConfirmationIsActionScoped(t *testing.T) {
	if got := expectedRecoveryConfirmation("retry", 17); got != "RETRY ACTION 17" {
		t.Fatalf("unexpected retry confirmation: %q", got)
	}
	if got := expectedRecoveryConfirmation("reconcile", 22); got != "RECONCILE ACTION 22" {
		t.Fatalf("unexpected reconcile confirmation: %q", got)
	}
}

func TestRecoveryConfirmationInputAcceptsNamedSpaceKey(t *testing.T) {
	got := appendApplyConfirmationInput("RETRY", "space")
	got = appendApplyConfirmationInput(got, "a")
	if got != "RETRY A" {
		t.Fatalf("space key was not added to recovery confirmation: %q", got)
	}
}

func TestRmlintScanArgsProduceJSONOnly(t *testing.T) {
	got := rmlintScanArgs([]string{"/mnt/One", "/mnt/Two"}, "/tmp/report.json")
	want := []string{"/mnt/One", "/mnt/Two", "-", "-T", "duplicates", "-g", "-o", "json:/tmp/report.json"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unexpected rmlint arguments: %#v", got)
	}
	for _, arg := range got {
		if strings.Contains(arg, "rmlint.sh") || arg == "sh" {
			t.Fatalf("scan arguments must not produce or run a cleanup script: %#v", got)
		}
	}
}

func TestParseScanProgressRecognizesRmlintPhasesAndExactPercent(t *testing.T) {
	progress, ok := parseScanProgress("\x1b[32mMatching (1 dupes of 2 originals; ETA: 3s) 42%\x1b[0m")
	if !ok || progress.phase != "MATCHING CONTENT" || !progress.known || progress.percent != 42 {
		t.Fatalf("unexpected matching progress: %#v, ok=%v", progress, ok)
	}

	progress, ok = parseScanProgress("Traversing (17 usable files / 2 ignored files / folders)")
	if !ok || progress.phase != "DISCOVERING FILES" || progress.known {
		t.Fatalf("unexpected traversal progress: %#v, ok=%v", progress, ok)
	}

	progress, ok = parseScanProgress("Merging files into directories")
	if !ok || progress.phase != "FINALIZING RESULTS" {
		t.Fatalf("unexpected finalizing progress: %#v, ok=%v", progress, ok)
	}
}

func TestScanProgressBarClampsInput(t *testing.T) {
	if got := scanProgressBar(50, 4); got != "[██··]" {
		t.Fatalf("unexpected progress bar: %q", got)
	}
	if got := scanProgressBar(150, 2); got != "[██]" {
		t.Fatalf("progress bar did not clamp: %q", got)
	}
}

func TestPostScanSummaryExplainsSuccessfulResultsAndNextSteps(t *testing.T) {
	var m model
	m.scanSummaryVisible = true
	m.scanDuration = 2 * time.Second
	m.scanRoots = []string{"/tmp/Orion", "/tmp/Lyra"}
	m.scanReportPath = "/tmp/rmlint.json"
	m.scanBackupPath = "/tmp/rmlint.json.previous"
	m.dashboard.Report.Groups = 4
	m.dashboard.Report.Files = 8
	m.dashboard.Report.RecoverableHuman = "1.50 MiB"

	got := m.scanSummaryView(100)
	for _, want := range []string{
		"SCAN COMPLETE",
		"No files were moved or deleted",
		"Duration: 2s",
		"Storage roots checked: 2",
		"Duplicate groups: 4",
		"Files charted: 8",
		"Potentially recoverable: 1.50 MiB",
		"Active report: /tmp/rmlint.json",
		"Previous report backup: /tmp/rmlint.json.previous",
		"Enter/G or 2 opens Duplicate Groups",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("successful scan summary missing %q: %q", want, got)
		}
	}
}

func TestPostScanSummaryClearlyReportsNoDuplicates(t *testing.T) {
	var m model
	m.scanDuration = time.Second
	m.scanRoots = []string{"/tmp/Orion"}
	m.scanReportPath = "/tmp/rmlint.json"
	m.dashboard.Report.RecoverableHuman = "0.00 B"

	got := m.scanSummaryView(100)
	for _, want := range []string{"SCAN COMPLETE", "Duplicate groups: 0", "NO DUPLICATES FOUND", "nothing to review or quarantine"} {
		if !strings.Contains(got, want) {
			t.Fatalf("empty scan summary missing %q: %q", want, got)
		}
	}
	if strings.Contains(got, "opens Duplicate Groups") {
		t.Fatalf("empty scan summary must not offer an unavailable results action: %q", got)
	}
}

func TestPostScanSummaryExplainsFailureAndPreservesPriorReport(t *testing.T) {
	var m model
	m.scanDuration = 3 * time.Second
	m.scanRoots = []string{"/tmp/Orion"}
	m.scanErr = fmt.Errorf("rmlint scan failed")
	m.scanOutput = "permission denied\nexit status 1"

	got := m.scanSummaryView(100)
	for _, want := range []string{
		"SCAN DID NOT COMPLETE",
		"previous report remains active",
		"files were not changed",
		"WHAT HAPPENED",
		"rmlint scan failed",
		"Technical detail: permission denied exit status 1",
		"return to Storage Setup",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("failed scan summary missing %q: %q", want, got)
		}
	}
}
