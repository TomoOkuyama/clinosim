# Code display authoritative sync

**Status**: Active. The display cross-check covers YJ, ICD-10 (WHO,
English), ICD-10 (MHLW, Japanese) and LOINC (see "Migration plan");
the remaining code systems migrate in follow-up PRs.

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
    yj_tx_fragment.json                 # YJ (first framework citizen)
    icd10_who_tx.json                   # ICD-10 WHO, English displays
    icd10_mhlw_2013_ja.json             # ICD-10 MHLW, Japanese displays
    loinc_2_83_tx.json                  # LOINC
    icd10cm_2027_cms.json               # ICD-10-CM (CMS)
    snomed_ct_tx.json                   # SNOMED CT International
    JP_MedicationCodeYJ_CS_full.json    # YJ (full CodeSystem)
    <system>_<source>.json              # further snapshots (index in README.md)
  loader.py                             # lookup() unchanged
tests/unit/codes/
  test_display_matches_authoritative.py # 5th layer of silent-no-op defense
  authoritative_override_allowlist.yaml # clinical shorthand overrides
scripts/
  refresh_authoritative_yj.py           # extraction scripts (per system)
  refresh_authoritative_yj_full.py
  refresh_authoritative_loinc.py
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

The allowlist was empty at framework launch. Its entries today are LOINC
displays that keep clinical shorthand instead of the LOINC long common name
(plus tracked semantic mismatches). Further fills are expected when SNOMED
CT preferred terms clash with JP clinical shorthand (e.g. 心筋梗塞 vs.
Myocardial infarction (disorder)).

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

| System        | Source                                          | Phase   | Status |
|---------------|-------------------------------------------------|---------|--------|
| YJ            | full YJ-code CS (`JP_MedicationCodeYJ_CS_full.json`; fragment `yj_tx_fragment.json` before Issue #3127) | Phase 1 | cross-checked |
| ICD-10 (WHO)  | `fhir.tx.support.r4` ICD-10 CS (`icd10_who_tx.json`), `en` displays | Phase 2 | cross-checked |
| ICD-10 (MHLW) | MHLW 基本分類表 2013 (`icd10_mhlw_2013_ja.json`), `ja` displays | — | cross-checked |
| LOINC         | LOINC 2.83 via tx.fhir.org (`loinc_2_83_tx.json`) | Phase 3 | cross-checked |
| SNOMED CT     | SNOMED CT International via tx.fhir.org (`snomed_ct_tx.json`) | Phase 2 | cross-checked (Issue #3127) |
| BCP-47        | HL7 terminology `urn:ietf:bcp:47`                  | Phase 2 | planned |
| ICD-10-CM     | CMS FY2027 code descriptions (`icd10cm_2027_cms.json`) | Phase 3 | cross-checked (Issue #3127) |
| MEDIS keyNo   | `medis-codesystem-diseasekanricodes`              | Phase 3 | planned |
| RxNorm        | NLM RxNorm                                        | Phase 4 | planned |
| MHLW / JLAC10 | JCCLS + MHLW masters                              | Phase 4 | planned |

"Cross-checked" means the system is registered in
`_SYSTEMS_UNDER_CROSS_CHECK` (`tests/unit/codes/test_display_matches_authoritative.py`).
Other snapshots in `clinosim/codes/authoritative/` (RxNorm, the MHLW YJ
master, the full YJ CodeSystem, the 医科診療行為 master) are read by their
own code-system tests, not by this cross-check.

Phase ordering prioritises code systems with observed v4 drift (SNOMED,
ICD-10, MEDIS, BCP-47). Every additional system entails: one
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
