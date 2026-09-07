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
2. **Duplicate Groups** — searchable groups and side-by-side copies.
3. **Keeper Decisions** — explicit keep, quarantine, and undecided state.
4. **Quarantine** — plan, pilot, verification, and confirmation sequence.
5. **Restore** — run selection, preview, collision inspection, and apply.
6. **History** — journal outcomes, retry eligibility, and recovery paths.
7. **Help** — contextual keys and safety explanations.
8. **Storage Setup** — discover mounted storage, persist managed roots, and launch
   a JSON-only rmlint duplicate scan.

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
- `ARCHIVE_KEEPER_RESTORE_LIMIT` (1–10; invalid values fall back to 10)

The largest recoverable groups can be opened in a copy-by-copy inspector.
Keeper selection and quarantine staging write only to `decisions.sqlite3`.

Controlled quarantine is available only after a clean bounded dry pilot. The
operator must then type the exact phrase shown by the UI. Apply is capped at 10
explicitly staged files, repeats live source/keeper/mount/destination checks
immediately before each move, refuses to overwrite an existing destination,
and journals every attempted move under a restore-compatible run ID. The UI
shows that run ID and its matching restore command after execution.

The Restore screen lists journal runs that still contain `moved` actions and
opens each run in a live, read-only preview. A file is eligible only when its
quarantine copy is a regular file, its original path is absent, and both paths
are on the same configured mounted root. Any existing original path is a hard
collision; the UI does not overwrite or reconcile it. After the exact bounded
confirmation phrase is entered, the engine repeats its checks, performs a
no-replace move, journals the result, and displays `RESTORE VERIFIED` with
restored, failed, and remaining counts.

## Mount array health

The dashboard reads `/proc/self/mountinfo` and reports every configured storage
root with an explicit ONLINE or OFFLINE state, filesystem type, and mounted
source. Reading mount metadata does not traverse the NAS. Controlled quarantine
and restore remain locked unless every configured root is an actual mount; the
Python engine repeats its own live checks before moving anything.

## Interactive galaxy map

Duplicate Groups opens in Galaxy view. Each configured mount is rendered as a
drive region, and the largest recoverable duplicate groups appear as selectable
star systems within that region. Star intensity is proportional to recoverable
bytes, the selected system pulses during the live scan, arrow keys move between
systems, and Enter opens the existing copy inspector. Press `G` to switch
between Galaxy and the compact list fallback.


## Portable storage setup and scanning

On first launch without `ARCHIVE_KEEPER_MOUNT_ROOTS`, the UI opens Storage
Setup. It discovers real mounts beneath `/mnt`, `/media`, and `/run/media`
from kernel mount metadata. The operator explicitly selects the roots Archive
Keeper may manage and presses `S` to save them. Setup is also available later
with `8`.

The selection and active report path are stored in
`~/.config/archive-keeper/ui.json` with owner-only permissions. Environment
variables still take precedence, so scripted and advanced deployments remain
fully configurable. Storage Setup never mounts or unmounts a filesystem.

Pressing `F` in Storage Setup opens a confirmation gate for a duplicate-only
rmlint scan. The UI invokes rmlint directly with only the JSON formatter:

`rmlint <selected roots> - -T duplicates -o json:<temporary report>`

Specifying `-o json` overrides rmlint's default outputs, so this workflow does
not create or execute `rmlint.sh`. The scan only reads archive files. Its JSON
is written to a temporary file in the report directory; only a successful,
non-empty scan becomes the active report. An existing report is first retained
under a timestamped `.previous-...` name. The dashboard reloads after success.
Press `X`, `H`, or Left Arrow to cancel a long-running scan. Quarantine
remains a separate, explicitly staged and confirmed operation.
