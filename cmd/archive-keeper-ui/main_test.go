package main

import (
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
	if got := galaxyGlyph(100, 100, false, 1); got != "✹" {
		t.Fatalf("largest system should be a bright star: %q", got)
	}
	if got := galaxyGlyph(30, 100, false, 1); got != "✦" {
		t.Fatalf("medium system should be a star: %q", got)
	}
	if got := galaxyGlyph(5, 100, false, 1); got != "·" {
		t.Fatalf("small system should be a point: %q", got)
	}
	if got := galaxyGlyph(5, 100, true, 2); got != "◉" {
		t.Fatalf("selected system should pulse: %q", got)
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
