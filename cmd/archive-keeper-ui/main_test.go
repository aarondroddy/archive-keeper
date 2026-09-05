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
