package main

import (
	"fmt"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

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
	m.dashboard.Report.LargestGroups = append(m.dashboard.Report.LargestGroups, struct {
		GroupID          int    `json:"group_id"`
		Copies           int    `json:"copies"`
		RecoverableBytes int64  `json:"recoverable_bytes"`
		RecoverableHuman string `json:"recoverable_human"`
		SamplePath       string `json:"sample_path"`
		MountRoot        string `json:"mount_root"`
		Files            []struct {
			Path         string `json:"path"`
			SizeHuman    string `json:"size_human"`
			OriginalHint bool   `json:"original_hint"`
			Checksum     string `json:"checksum"`
		} `json:"files"`
	}{GroupID: 42, Copies: 2, RecoverableBytes: 4096, RecoverableHuman: "4.00 KiB", MountRoot: "/mnt/MyCloud1"})
	got := m.galaxyView(120)
	if !strings.Contains(got, "MYCLOUD1 NEBULA") || !strings.Contains(got, "G42") {
		t.Fatalf("galaxy view did not render mount region and group: %q", got)
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

func TestUIConfigRoundTrip(t *testing.T) {
	configPath := filepath.Join(t.TempDir(), "archive-keeper", "ui.json")
	t.Setenv("ARCHIVE_KEEPER_UI_CONFIG", configPath)
	want := uiConfig{
		Version: 1,
		MountRoots: []string{"/mnt/Zeta", "/mnt/Alpha", "/mnt/Zeta"},
		ReportPath: filepath.Join(t.TempDir(), "rmlint.json"),
	}
	if err := saveUIConfig(want); err != nil {
		t.Fatalf("saveUIConfig: %v", err)
	}
	got, err := loadUIConfig()
	if err != nil {
		t.Fatalf("loadUIConfig: %v", err)
	}
	if got.Version != 1 || got.ReportPath != want.ReportPath {
		t.Fatalf("unexpected saved config: %#v", got)
	}
	if !reflect.DeepEqual(got.MountRoots, []string{"/mnt/Alpha", "/mnt/Zeta"}) {
		t.Fatalf("mount roots were not normalized and sorted: %#v", got.MountRoots)
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

func TestRmlintScanArgsProduceJSONOnly(t *testing.T) {
	got := rmlintScanArgs([]string{"/mnt/One", "/mnt/Two"}, "/tmp/report.json")
	want := []string{"/mnt/One", "/mnt/Two", "-", "-T", "duplicates", "-o", "json:/tmp/report.json"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unexpected rmlint arguments: %#v", got)
	}
	for _, arg := range got {
		if strings.Contains(arg, "rmlint.sh") || arg == "sh" {
			t.Fatalf("scan arguments must not produce or run a cleanup script: %#v", got)
		}
	}
}
