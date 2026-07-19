# Authoritative code system snapshots

Machine-readable snapshots of authoritative code system displays used to
verify `clinosim/codes/data/*.yaml` against the original terminology sources.
These are **verification references**, not the source of truth — the source
of truth for what clinosim emits stays in `clinosim/codes/data/*.yaml`,
which allows small, deliberate clinical overrides (registered in the
allowlist below).

Companion documentation: [`docs/design-guides/code-display-authoritative-sync.md`](../../../docs/design-guides/code-display-authoritative-sync.md).

## Files

| File | Source | Fetched | Notes |
|---|---|---|---|
| `yj_tx_fragment.json` | `jpfhir-terminology 2.2606.0` / `CodeSystem-jp-medicationcodeyj-cs.json` (`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code`) | 2026-07-19 | Fragment (2000 concepts on the tx-server), filtered to the 9 codes clinosim currently emits. |
| `loinc_2_82_tx.json` | LOINC 2.82 official master (`Loinc_2.82/LoincTable/Loinc.csv`) via `tx-server-build/loinc-src/` | 2026-07-19 | 167 codes clinosim emits; includes `display` (LONG_COMMON_NAME) + `short_display` (SHORTNAME) + `status`. Full display cross-check enabled in Issue #270 (Phase 3-b) — 75 legitimate shorthand + 17 tracked semantic-mismatch overrides registered in the allowlist. |

Follow-on snapshots (SNOMED / ICD-10 / MEDIS / BCP-47 / LOINC etc.) are
tracked in the design guide and land in subsequent PRs as each Chain migrates
to the framework.

## Content mode: `fragment`

Every snapshot inherits its source CodeSystem's `content` semantics. When
`content == "fragment"`, codes NOT in the snapshot **may still be valid**
per the source terminology — the tx-server's loaded partial listing simply
doesn't have them. The cross-check test treats missing codes as *unable to
verify* (SKIP), not *invalid* (FAIL). The `metadata.clinosim_codes_missing_from_fragment`
field records exactly which clinosim codes are outside the fragment so a
future snapshot refresh can decide whether to widen the fetch.

## Cross-check semantics

For every `(system, code)` pair with an entry in the authoritative snapshot,
the cross-check test asserts that the clinosim-curated display matches
either:

- the authoritative `display` (preferred term), OR
- one of the authoritative `designation[].value` entries (synonyms), OR
- an entry in the override allowlist with a documented clinical rationale.

A drift (curated display ≠ authoritative AND not in allowlist) fails CI.
This is the 5th layer of the silent-no-op defense.

## Refresh workflow

1. Pull the latest `../fhir-jp-validator/tx-server-build/` (or the upstream
   terminology package).
2. Re-run the extraction script (per-code-system script in `scripts/`,
   TBD as each system migrates in).
3. Inspect the diff in the snapshot files.
4. For every changed entry:
   - Match now → curated data was already correct, no clinosim change needed.
   - Match now, curated stale → update `clinosim/codes/data/*.yaml`.
   - Deliberate divergence (clinical shorthand override) → add to allowlist
     with a clinical rationale.
5. PR: snapshot diff + allowlist / YAML edit + cross-check test refresh.

## What does NOT belong here

- Full CodeSystem definitions (structure, filters, hierarchies) — those live
  on the tx-server, not in clinosim.
- Locale translations that the authoritative source does not carry — those
  live in `clinosim/codes/data/*.yaml` under the `ja` / other-language keys
  and are considered clinosim-curated (not verifiable against upstream).
- Codes clinosim never emits — the fragment is intentionally scoped to
  clinosim's emit surface so the shipped snapshots stay small.
