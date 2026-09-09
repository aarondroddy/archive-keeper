# Archive Keeper 2.0 — Storage Galaxy

Storage Galaxy is a Bubble Tea v2 interface layered over Archive Keeper's
existing Python safety engine. The interface may inspect state and propose
commands; filesystem mutation remains behind the established mount validation,
verification, journal, dry-run, and explicit-apply safeguards.

## Visual language

- Near-black violet space with neon magenta, cyan, lime, and gold accents.
- Rounded panels, compact telemetry, playful astronomical language, and strong
  textual status labels.
- Color is never the only carrier of state.
- A responsive compact layout preserves usability over iPad remote terminals.

## Guided dashboard

1. **Home** — safety state, report health, group count, decisions, and potential
   recovery.
2. **Duplicate Groups** — report-wide path search, mount filtering, five sort
   modes, paginated groups, and side-by-side copies.
3. **Keeper Decisions** — explicit keep, quarantine, and undecided state.
4. **Quarantine** — plan, pilot, verification, and confirmation sequence.
5. **Restore** — run selection, preview, collision inspection, and apply.
6. **History** — journal outcomes, retry eligibility, and recovery paths.
7. **Help** — contextual keys and safety explanations.
8. **Storage Setup** — detected mounts, saved roots, and confirmed rmlint scans.

Every workflow screen carries a plain-language basic guide. The guide states
what the screen is for, the next keys to press, and whether the current step is
read-only, decision-only, or capable of a confirmed file move.

## Integration boundary

The Go application will consume a versioned JSON protocol emitted by the Python
package. It will never infer mutation success from prose output. Applied
operations must return structured journal identifiers and terminal states.

The initial shell and dashboard bridge are deliberately read-only. The Go UI
runs `python3 -m archive_keeper.ui_bridge dashboard` asynchronously and accepts
only protocol-versioned JSON. Existing SQLite state is opened with SQLite
`mode=ro` and `query_only`; absent databases are reported but never created.

Optional environment variables let a development build use non-default inputs:

- `ARCHIVE_KEEPER_PYTHON`
- `ARCHIVE_KEEPER_REPORT`
- `ARCHIVE_KEEPER_STATE_DB`
- `ARCHIVE_KEEPER_DECISIONS_DB`
- `ARCHIVE_KEEPER_MOUNT_ROOTS`
- `ARCHIVE_KEEPER_QUARANTINE_NAME`
- `ARCHIVE_KEEPER_VERIFY_TIMEOUT`
- `ARCHIVE_KEEPER_APPLY_LIMIT` (1–10; invalid values fall back to 10)

The largest recoverable groups can be opened in a copy-by-copy inspector.
Keeper selection and quarantine staging write only to `decisions.sqlite3`.
After saving a keeper, the operator may open a group-wide review that previews
the protected keeper and nonkeeper count before atomically staging every other
copy. The bridge rejects a missing or stale keeper and never stages the keeper
path. This bulk operation records decisions only and cannot move archive files.

Controlled quarantine is available only after a clean bounded dry pilot. The
operator must then type the exact phrase shown by the UI. Apply is capped at 10
explicitly staged files, repeats live source/keeper/mount/destination checks
immediately before each move, refuses to overwrite an existing destination,
and journals every attempted move under a restore-compatible run ID. The UI
shows that run ID and its matching restore command after execution.
