# Safety Model

Archive Keeper is designed around planning, quarantine, journaling, and restore
rather than immediate deletion.

Before any real operation:

```bash
findmnt /mnt/MyCloud1
findmnt /mnt/MyCloud2
findmnt /mnt/MyCloud3
```

Do not continue if a mount path is merely an empty local directory.

Recommended rollout:

1. Analyze the report.
2. Inspect the plan.
3. Review keeper choices.
4. Run a 25-file dry run.
5. Run a real verified 25-file pilot.
6. Inspect quarantine.
7. Restore the pilot.
8. Only then increase scope.

Quarantine is not a backup.


## Collision reconciliation

Archive Keeper 1.6.5 fails closed on path collisions. When a quarantine destination or restore destination already exists, Archive Keeper compares the relevant files with SHA-256 before taking any cleanup action. Identical collisions may be reconciled; different-content collisions are left untouched for manual review. Restore reconciliation removes only the redundant quarantine copy after confirming the existing original is identical.


## Visible quarantine directories (1.6.6)

New runs default to `ArchiveKeeper Quarantine` on each configured NAS root. Existing runs keep using the directory recorded by their journal, including legacy `.ArchiveKeeper` trees. Archive Keeper never renames or migrates an existing quarantine automatically. Use `--quarantine-name` only when starting a new run if a custom directory name is desired.
