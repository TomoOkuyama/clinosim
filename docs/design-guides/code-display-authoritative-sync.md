# Code display authoritative sync

**Status**: Framework introduced in session 58 Phase 1 (YJ code template).
Migration of remaining code systems tracked in follow-up PRs.

## Why

`clinosim/codes/data/*.yaml` ships curated `(code, en, ja, …)` mappings for
every code the simulator emits. Prior to this framework, drift between the
curated `display` strings and the authoritative source (SNOMED CT
International, WHO ICD-10, MHLW YJ / MEDIS terminology, HL7 / IETF language
tags) was only discovered when the fhir-jp-validator flagged a specific
resource — a reactive, whack-a-mole workflow. The v4 fullset run
(2026-07-18) surfaced ~13,000 display-related errors across 6 code systems,
which motivated a systematic verification framework.

## Principles

1. **Curated data stays authoritative for what clinosim emits.** The Yaml
   files in `clinosim/codes/data/` continue to be the source of truth for
   the exact display strings that ship. Small clinical overrides — e.g.
   emitting `MDD` instead of the WHO preferred `Depressive episode` for
   ICD-10 `F32` — remain possible via a documented allowlist.
2. **Authoritative source is machine-verifiable.** Every ship-time display
   must either match an authoritative preferred term / registered synonym,
   or appear in the override allowlist with a clinical rationale.
3. **Fragment ship stays the norm.** clinosim only ships the codes it
   emits (typically << 200 per system). Authoritative snapshots mirror this
   scope so shipped size stays small.
4. **Silent drift fails CI.** The cross-check test is a hard defense layer.
5. **Refresh is a maintainer workflow, not a runtime concern.** The
   simulator never reaches out to a terminology server at generation time.

## Structure

```
clinosim/codes/
  data/*.yaml                           # curated source of truth
  authoritative/
    README.md                           # index + fetch provenance
    yj_tx_fragment.json                 # ← first framework citizen
    <system>_<source>.json              # snapshots land here per PR
  loader.py                             # lookup() unchanged
tests/unit/codes/
  test_display_matches_authoritative.py # 5th layer of silent-no-op defense
  authoritative_override_allowlist.yaml # clinical shorthand overrides
scripts/
  refresh_authoritative_yj.py           # extraction script (per system)
```

## Snapshot format

Every snapshot is a JSON document with a `metadata` block and a `concept`
list. The concept list contains only the codes clinosim currently emits, in
sorted order (stable diffs):

```json
{
  "metadata": {
    "source_package": "jpfhir-terminology 2.2606.0",
    "source_url": "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code",
    "source_file": "CodeSystem-jp-medicationcodeyj-cs.json",
    "source_content_mode": "fragment",
    "fetched_from": "https://github.com/iryohjoho/fhir-jp-validator tx-server-build/",
    "extracted_at": "2026-07-19",
    "clinosim_codes_total": 165,
    "clinosim_codes_in_fragment": 9,
    "clinosim_codes_missing_from_fragment": ["…"]
  },
  "concept": [{"code": "1149037F1020", "display": "セレコックス錠１００ｍｇ"}]
}
```

The `metadata.clinosim_codes_missing_from_fragment` array records which
clinosim codes fell outside the tx-server's loaded fragment at extraction
time — these are unverifiable (the test SKIPs them) but the record lets a
future refresh decide whether to widen the fetch or accept the gap.

## Cross-check semantics

For each `(system, code)` pair in the curated YAML:

1. If the code has no snapshot entry → **SKIP** (fragment-missing, not a
   verification failure).
2. If the curated display matches the snapshot's `display` OR any of the
   `designation[].value` synonyms → **PASS**.
3. If the curated display matches an allowlist entry whose `clinosim_display`
   equals the curated string, and the allowlist entry has a documented
   `rationale` + `registered_at` → **PASS (allowlisted)**.
4. Otherwise → **FAIL** with a diagnostic listing every drifted code and
   what the authoritative display was.

The test emits per-system counts (`verified` / `allowlisted` /
`unverifiable`) as informational output so maintainers can watch coverage
grow across snapshot refreshes.

## Override allowlist

Every allowlist entry MUST carry:

- `lang`: the display-language field the override applies to (`en` / `ja`).
- `clinosim_display`: exactly what `clinosim/codes/data/<system>.yaml` emits.
- `authoritative_display`: what the snapshot has (for reviewer context).
- `rationale`: free-form clinical or curatorial reason. Cite a guideline,
  a professional-society style guide, or a specific clinical convention.
- `registered_at`: date the override was reviewed (ISO YYYY-MM-DD).

The allowlist is empty at framework launch. First-order fills are expected
when SNOMED CT preferred terms clash with JP clinical shorthand (e.g.
心筋梗塞 vs. Myocardial infarction (disorder)).

## Refresh workflow (maintainer)

1. `git pull` the latest `../fhir-jp-validator/` (or refresh the upstream
   terminology packages the extraction script points at).
2. Run `python scripts/refresh_authoritative_<system>.py` for the code
   systems whose upstream refreshed.
3. `git diff clinosim/codes/authoritative/` — inspect each changed entry.
4. Per-code triage:
   - **New authoritative display now matches curated** → no action; the
     display converged from the other direction. The cross-check test now
     covers a previously-drifting code.
   - **Curated needs updating** → edit `clinosim/codes/data/<system>.yaml`
     and update the display; re-run tests.
   - **Deliberate divergence** (JP clinical shorthand vs upstream preferred
     term) → add an allowlist entry with a clinical rationale.
5. Open a single PR containing the snapshot diff + any curated-data /
   allowlist edits.

## Migration plan

| System        | Source                                          | Migration PR   |
|---------------|-------------------------------------------------|-----------------|
| YJ            | `jpfhir-terminology 2.2606.0` YJ-code CS         | Phase 1 (this) |
| SNOMED CT     | tx-server SNOMED International fragment           | Phase 2         |
| ICD-10 (WHO)  | `codes/data/icd-10.yaml` vs WHO ICD-10 browser    | Phase 2         |
| ICD-10-CM     | `codes/data/icd-10-cm.yaml` vs NLM CM master       | Phase 3         |
| MEDIS keyNo   | `medis-codesystem-diseasekanricodes`              | Phase 3         |
| BCP-47        | HL7 terminology `urn:ietf:bcp:47`                  | Phase 2         |
| LOINC         | Regenstrief LOINC master                          | Phase 3         |
| RxNorm        | NLM RxNorm                                        | Phase 4         |
| MHLW / JLAC10 | JCCLS + MHLW masters                              | Phase 4         |

Phase ordering prioritises code systems with observed v4 drift (SNOMED,
ICD-10, MEDIS, BCP-47 in Phase 2). Every additional system entails: one
`authoritative/<system>_<source>.json`, an entry in
`_SYSTEMS_UNDER_CROSS_CHECK`, and (if the schema differs) a small extension
to `_build_authoritative_display_map`.

## What this framework does NOT do

- **Runtime term resolution.** clinosim does not query a terminology server
  at generation time. Verification runs at test time.
- **Adding new codes.** Adding a code without a `display` in the required
  language is a separate coverage concern
  (`tests/unit/test_diagnosis_code_coverage.py` and siblings). Cross-check
  simply verifies displays that ARE present.
- **Translation quality assurance.** The `ja` translation of a `en`-only
  authoritative source (ICD-10 WHO does not ship Japanese) is a clinosim-
  curated field. Downstream reviewers evaluate translation quality; the
  cross-check does not.
