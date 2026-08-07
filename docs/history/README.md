# Historical documentation

Documents preserved for traceability but no longer describing the current
system state. New contributors should NOT start here — see [the docs
root](../index.md) and [`docs/getting-started/`](../getting-started/).

## Contents

- [`spec-2026-04.md`](spec-2026-04.md) — Original full-system spec written in
  April 2026 (「医療ダミーデータ生成システム 仕様書 v0.3」). Superseded by
  [`DESIGN.md`](../../DESIGN.md) (architecture + ADR table) and
  [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md)
  (FHIR output spec).
- [`des-migration-audit.md`](des-migration-audit.md) — Pre-migration cleanup
  audit for the discrete-event engine split. The described refactor is
  complete (`simulator.py` split into `simulator/{engine,inpatient,
  outpatient,emergency,helpers,cli}.py`, `simulator/des_engine.py` in place).
  Retained for design continuity.
- [`session-prompts/`](session-prompts/) — Per-session resume prompts for
  the maintainer's long-running development context. See the sub-README.
- [`scratchpad-archive/`](scratchpad-archive/) — Per-PR byte-diff scripts
  and Data-Quality Review reports from past investigation chains.

Files moved into this directory as part of the session 82 repo-hygiene
series (PRs A-G).
