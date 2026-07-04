# JP microbiology culture code JLAC10 mapping — design spec

Date: 2026-07-04
Status: approved (brainstorming), pending implementation plan

## Problem

`clinosim/modules/observation/reference_data/microbiology.yaml`'s `specimens` dict
(`blood`/`urine`/`sputum`/`wound`) carries a single `test_loinc` value baked in at
generation time (`clinosim/modules/observation/microbiology.py:199`,
`MicrobiologyResult.test_loinc`). This value is emitted verbatim as the culture
Observation's `code.coding[].system`/`code` in `_fhir_microbiology.py::_bb_microbiology`
regardless of `ctx.country` — so JP output emits a US LOINC code for the culture test
type, violating the project's JP JLAC10 principle (CLAUDE.md "Code is the truth" +
AD-26). This is the same class of gap that chemistry labs (`WBC`/`Glucose`/etc.) had
until a prior DQR cycle added country-gated `code_mapping_lab.yaml` resolution
(`_fhir_observations.py::_build_lab_observation`) — microbiology culture tests were
missed from that sweep.

Scope explicitly excludes (per user decision during brainstorming):
- Antibiotic susceptibility test codes (`SusceptibilityResult.antibiotic_loinc`, 10
  drugs) — JLAC10's structure for susceptibility results may not mirror LOINC's
  per-drug-per-test-code model; needs its own research pass. Filed as a TODO.md
  follow-up, not blocked on by this fix.
- Organism identification codes (SNOMED CT) — already locale-independent by design
  (matches the existing HAI-organism convention); no change.
- CSV adapter (`csv_adapter.py`) — dumps `MicrobiologyResult.test_loinc` as a raw code
  column, not a `display`/`text` field, so it isn't covered by CLAUDE.md's JP
  localization requirement (which targets FHIR display/text fields). Filed as an
  optional TODO.md follow-up for future JP-CSV consistency, not required now.

## Why this fix generalizes to HAI-derived cultures for free

`MicrobiologyResult.specimen` (`"blood"|"urine"|"sputum"|"wound"`) is a country-neutral
internal key already present on every culture record, both community-acquired
(`observation/microbiology.py`) and HAI-derived (`hai/enricher.py:206`, populated from
`hai_specimens.yaml`'s `spec_cfg["specimen"]`). Resolving the FHIR code purely from this
key at output time — rather than from the pre-baked `test_loinc` — means a single change
in `_fhir_microbiology.py` covers both culture sources. No changes needed to
`hai/engine.py`, `hai/enricher.py`, `hai_specimens.yaml`, or the `MicrobiologyResult`
dataclass itself (`test_loinc` stays as the CIF field and US/default fallback value —
removing it would ripple into `csv_adapter.py` / `antibiotic/audit.py` test fixtures /
several unit tests for no benefit, out of scope per the narrow-scope decision).

## Architecture

Mirrors the existing chemistry-lab country-gated resolution pattern
(`_fhir_observations.py::_build_lab_observation`):

```
MicrobiologyResult.specimen ("blood" | "urine" | "sputum" | "wound")
        |
        v
_bb_microbiology() in _fhir_microbiology.py:
    country_code = "JP" if is_jp(ctx.country) else "US"
    code_map = load_code_mapping("microbiology", country_code)   # {} for US (no file)
    code_system_key = system_key_for("microbiology", country_code)  # "jlac10" | "loinc"
    code_value = code_map.get(specimen_key) or mb.get("test_loinc", "")
    lang = resolve_lang(country_code)  # already computed above in the function
    culture_code = {"coding": [_micro_coding(code_system_key, code_value, lang)]} if code_value else {"text": "Culture"}
```

### New files / changes

1. **`clinosim/locale/jp/code_mapping_microbiology.yaml`** (new file, new domain,
   mirrors `code_mapping_lab.yaml`'s header/sourcing conventions): maps specimen key →
   JLAC10 analyte code, populated only for specimens where an authoritative code is
   found (see Verification below). Header must cite the same JSLM master source
   (`137jlac10_1.xlsx` v137, per `reference_jlac10_source` memory) — no fabricated
   codes (AD-57).

2. **`clinosim/codes/loader.py`**: add `"microbiology"` to `_COUNTRY_SYSTEM_KEYS`:
   `{"default": "loinc", "jp": "jlac10"}` (same shape as the existing `"lab"` entry).
   Update `system_key_for`'s docstring (`kind: one of "lab", "diagnosis", "drug",
   "procedure"`) to include `"microbiology"`.

3. **`clinosim/codes/data/jlac10.yaml`**: add entries for whichever specimen codes are
   found and verified (en + ja per existing convention).

4. **`_fhir_microbiology.py::_bb_microbiology`**: replace the direct
   `culture_loinc = mb.get("test_loinc", "")` line with the country-gated resolution
   shown above. `culture_code` is reused for both the organism Observation and the
   DiagnosticReport (both already read the same `culture_code` variable — no other
   change needed there).

No change to `MicrobiologyResult`, `hai/engine.py`, `hai/enricher.py`,
`hai_specimens.yaml`, `csv_adapter.py`, or `antibiotic/audit.py`.

## Verification approach (no fabrication — AD-57)

For each of the 4 specimens (blood / urine / sputum / wound culture, i.e. "bacteria
identified by culture in <specimen>"), query the JSLM JLAC10 master
(`137jlac10_1.xlsx`, sheet 「分析物コード」) per the `reference_jlac10_source` memory
workflow, optionally cross-checking jpfhir.jp JP-CLINS CodeSystem if the code falls in
its 648-concept core-lab range. Two possible outcomes per specimen:

- **Match found**: a discrete JLAC10 analyte code exists representing "culture
  identification" for that specimen type (analogous to how JLAC10 has discrete codes
  for other qualitative/microbiology-adjacent tests). Add it to
  `code_mapping_microbiology.yaml` + `jlac10.yaml`.
- **No clean match**: JLAC10 represents microbiology culture differently (e.g. via a
  materials/method code combination rather than a single analyte code, or the
  4-specimen granularity doesn't map 1:1 to JLAC10's categorization). Leave that
  specimen unmapped (falls through to the existing LOINC fallback, so JP output for
  that specimen is unchanged from today — no regression) and document the finding
  (what was checked, why no match) in a TODO.md entry.

Partial coverage (some specimens mapped, others still falling back to LOINC) is an
accepted, documented outcome per the user's explicit decision — not a partial/half-done
implementation, since the fallback path is the pre-existing, correct-for-US behavior.

## Testing

- Unit test in `tests/unit/` (colocated with existing `_fhir_microbiology.py` tests, or
  a new `test_fhir_microbiology.py` if none exists) exercising `_bb_microbiology` for
  both US and JP `ctx.country`, asserting:
  - US: culture Observation code system/value unchanged (still LOINC from
    `test_loinc`).
  - JP, mapped specimen: code system = jlac10 URI, code = the verified JLAC10 value,
    display resolved via `code_lookup`.
  - JP, unmapped specimen (if any remain after verification): falls back to LOINC
    (matches current behavior — regression guard for the fallback path).
  - A synthetic HAI-derived `MicrobiologyResult` (constructed the same way
    `hai/enricher.py` does, i.e. only `specimen` + `test_loinc` set, no other JP-only
    fields) resolves identically to a community-acquired one with the same
    `specimen` — proving the single change point covers both sources.
- Run existing `tests/unit/test_microbiology.py`,
  `tests/integration/test_antibiotic_audit.py`, `tests/integration/test_narrow_enricher.py`
  (all reference `test_loinc` today) to confirm no regression.
- `pytest -m unit` and `-m integration` before considering done (per CLAUDE.md testing
  rules).
- Optional manual spot-check: run `clinosim` CIF+FHIR generation for a small JP cohort
  and inspect a culture Observation's `code.coding[]` to confirm JLAC10 appears for
  mapped specimens.

## Out-of-scope items to file in TODO.md at completion

- Antibiotic susceptibility JLAC10 mapping (10 drugs) — separate research question,
  deferred.
- CSV adapter JP/JLAC10 consistency for the `test_loinc` column — deferred, optional.
- Any specimen where no authoritative JLAC10 match was found — document the specific
  finding (what was searched, why no match) so a future session doesn't re-research
  from scratch.
