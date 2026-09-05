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

The next milestone adds interactive group inspection and explicit keeper
selection. Mutation stays offline until preview, confirmation, and journaled
operation messages are specified and tested end to end.
