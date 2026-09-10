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

Storage Setup has a guided Advanced Configuration screen opened with `E`.
It edits the report, journal, decisions, quarantine folder, keeper-preference,
protection, and exclusion settings without moving files. Paths are validated
as absolute, the quarantine destination is restricted to one folder name, and
the complete configuration is saved with owner-only permissions.

After each confirmed rmlint scan, Storage Setup becomes a post-scan summary
before the operator enters the report. It reports duration and scanned roots,
then group count, file count, recoverable space, and active/backup report
locations. Zero-result and failed scans receive explicit explanations; a
failure keeps the previous report active. Successful non-empty results link
directly to Duplicate Groups. This state is informational and never moves or
deletes files.

Every workflow screen carries a plain-language basic guide. The guide states
what the screen is for, the next keys to press, and whether the current step is
read-only, decision-only, or capable of a confirmed file move.

## Combined installation

Archive Keeper is distributed as one platform-specific package containing the
Python safety engine and a prebuilt Storage Galaxy executable. The existing
`archive-keeper` entry point retains every command-line workflow and adds
`archive-keeper ui` as the stable graphical-terminal launcher. End users do not
need Go; maintainers compile and embed the UI while building the release. A
health-check mode verifies the packaged executable without entering alternate
screen mode.

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
- `ARCHIVE_KEEPER_PREFERRED_ROOTS`
- `ARCHIVE_KEEPER_PROTECTED_ROOTS`
- `ARCHIVE_KEEPER_EXCLUDED_ROOTS`
- `ARCHIVE_KEEPER_VERIFY_TIMEOUT`
- `ARCHIVE_KEEPER_APPLY_LIMIT` (1–10; invalid values fall back to 10)

The largest recoverable groups can be opened in a copy-by-copy inspector.
Keeper selection and quarantine staging write only to `decisions.sqlite3`.
After saving a keeper, the operator may open a group-wide review that previews
the protected keeper and nonkeeper count before atomically staging every other
copy. The bridge rejects a missing or stale keeper and never stages the keeper
path. This bulk operation records decisions only and cannot move archive files.

Preferred roots influence presentation rather than silently changing a manual
decision: the inspector selects and labels the first matching copy. Protected
and excluded roots are enforced as hard, boundary-safe path rules by the Python
bridge. They are checked when a single decision is staged, before an atomic
bulk decision is committed, when the quarantine plan is built, during the dry
pilot, and again for controlled apply. Rechecking at every boundary prevents a
stale decision created before a rule change from being moved later.

Controlled quarantine is available only after a clean bounded dry pilot. The
operator must then type the exact phrase shown by the UI. Apply is capped at 10
explicitly staged files, repeats live source/keeper/mount/destination checks
immediately before each move, refuses to overwrite an existing destination,
and journals every attempted move under a restore-compatible run ID. The UI
shows that run ID and its matching restore command after execution.
