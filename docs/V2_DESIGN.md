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

The initial shell is deliberately read-only. The next milestone adds the JSON
bridge, real dashboard data, tests for protocol compatibility, and explicit
confirmation flows.
