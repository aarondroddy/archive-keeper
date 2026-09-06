package main

import "testing"

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
