# JP Microbiology Culture Code JLAC10 Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JP-country FHIR output for microbiology culture Observations must emit a JLAC10
code (not a US LOINC code) for the culture test type, matching the project's existing
JP JLAC10 convention for chemistry labs.

**Architecture:** Mirror the existing country-gated code resolution pattern used for
chemistry labs (`_fhir_observations.py::_build_lab_observation`): resolve the FHIR
`code.coding[].system`/`code` for a microbiology culture at FHIR-build time from the
country-neutral `MicrobiologyResult.specimen` key ("blood"/"urine"/"sputum"/"wound"),
via a new JP-only `code_mapping_microbiology.yaml` + a new `"microbiology"` kind in
`system_key_for`. Falls back to the existing `test_loinc` value when no JP mapping
applies (US, or an unmapped specimen) — same fallback shape as
`code_map.get(lab_name, order.get("order_code", ""))` in the chemistry-lab builder.

**Tech Stack:** Python 3.11+, pytest, PyYAML. No new dependencies.

## Global Constraints

- **No fabricated codes (AD-57).** The JLAC10 code used in this plan (`6B010`) was
  looked up live against the authoritative JSLM JLAC10 master
  (`https://www.jslm.org/committees/code/137jlac10_1.xlsx`, sheet「分析物コード」,
  header row 5, columns C=code/D=Japanese name/F=English name) during design research
  on 2026-07-04. Category `6B` = 微生物学的検査/培養同定検査 (Microbiology /
  culture-identification tests). The ONLY entry in that category for general bacterial
  culture is `6B010` = 培養同定(一般細菌) / "culture and identification (common
  bacteria)" — a single generic code, NOT specimen-specific (JLAC10 puts the
  specimen-type distinction in the separate 17-digit full code's 材料コード
  (material/specimen code) segment, not in the 5-character analyte code clinosim
  stores). This means all 4 specimens (blood/urine/sputum/wound) map to the *same*
  JLAC10 code — this is a verified finding, not a partial/incomplete mapping.
- Code comments and docstrings: English (CLAUDE.md). Module READMEs: N/A (no README
  changes in this plan).
- Line length 100, ruff formatting, mypy strict — run `ruff check` / existing project
  lint conventions if the repo has a pre-commit hook; otherwise match surrounding style.
- Run `pytest -m unit` before every commit in this plan; run `pytest -m integration`
  before the final commit (Task 4).
- Out of scope (per approved spec, do NOT touch): `SusceptibilityResult.antibiotic_loinc`
  / the `antibiotics` dict in `microbiology.yaml`, `csv_adapter.py`,
  `MicrobiologyResult` dataclass fields, `hai/engine.py`, `hai/enricher.py`,
  `hai_specimens.yaml`.

---

### Task 1: Register JLAC10 code 6B010 + JP microbiology code mapping

**Files:**
- Modify: `clinosim/codes/data/jlac10.yaml` (append new entry)
- Create: `clinosim/locale/jp/code_mapping_microbiology.yaml`
- Modify: `tests/unit/test_codes_jlac10.py` (add microbiology coverage, same pattern as
  the existing `code_mapping_lab.yaml` checks in this file)

**Interfaces:**
- Produces: `clinosim.codes.lookup("jlac10", "6B010", lang)` resolves to
  `"culture and identification (common bacteria)"` (en) / `"培養同定(一般細菌)"` (ja).
  `clinosim/locale/jp/code_mapping_microbiology.yaml` is a `dict[str, str]` keyed by
  specimen (`"blood"`/`"urine"`/`"sputum"`/`"wound"`), all four values `"6B010"`. Task 3
  consumes this file via `load_code_mapping("microbiology", "JP")`.

- [ ] **Step 1: Write the failing test**

Open `tests/unit/test_codes_jlac10.py` and add a new test class at the end of the file
(after the existing `TestJLAC10Integrity` class), plus a new module-level constant for
the microbiology map:

```python
_JP_MICRO_MAP = yaml.safe_load(
    (_ROOT / "locale/jp/code_mapping_microbiology.yaml").read_text()
)


@pytest.mark.unit
class TestMicrobiologyJLAC10Integrity:
    def test_every_mapped_code_exists(self):
        missing = {
            specimen: code for specimen, code in _JP_MICRO_MAP.items()
            if code not in _JLAC10
        }
        assert not missing, f"JP microbiology codes absent from jlac10.yaml: {missing}"

    def test_all_four_specimens_mapped(self):
        assert set(_JP_MICRO_MAP) == {"blood", "urine", "sputum", "wound"}

    def test_verified_code(self):
        """JLAC10 has one generic culture-identification analyte code (6B010),
        not per-specimen codes — the specimen distinction lives in the 17-digit
        full code's material segment, which clinosim does not model. Verified
        against JSLM JLAC10 master v137, category 6B (微生物学的検査/培養同定検査),
        2026-07-04."""
        assert all(code == "6B010" for code in _JP_MICRO_MAP.values())

    def test_display_resolves(self):
        assert lookup("jlac10", "6B010", "en") == "culture and identification (common bacteria)"
        assert lookup("jlac10", "6B010", "ja") == "培養同定(一般細菌)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_codes_jlac10.py::TestMicrobiologyJLAC10Integrity -v`
Expected: FAIL — `FileNotFoundError` (module-level `yaml.safe_load` for
`code_mapping_microbiology.yaml` fails at collection time since the file doesn't exist
yet).

- [ ] **Step 3: Add the JLAC10 code entry**

In `clinosim/codes/data/jlac10.yaml`, after the last entry (`5C215` / Procalcitonin,
currently the last 3 lines of the file), append:

```yaml
  # --- Microbiology culture (6B) ---
  6B010:
    en: Culture and identification (common bacteria)
    ja: 培養同定(一般細菌)
```

- [ ] **Step 4: Create the JP code mapping file**

Create `clinosim/locale/jp/code_mapping_microbiology.yaml`:

```yaml
# Internal specimen key → JLAC10 analyte code (分析物コード) mapping for
# microbiology culture tests.
#
# AUTHORITATIVE SOURCE — verified against the official JLAC10 master:
#   日本臨床検査医学会 (JSLM) 検査項目コード委員会
#   "JLAC10コード表_臨床検査" v137 (2026-06): https://www.jslm.org/committees/code/
#   (137jlac10_1.xlsx, sheet「分析物コード」)
# Display text lives in clinosim/codes/data/jlac10.yaml. Never fabricate a code (AD-57).
#
# NOTE: unlike code_mapping_lab.yaml, all four specimens share the same code.
# JLAC10 category 6B (微生物学的検査/培養同定検査) has a single generic analyte
# code for "culture and identification (common bacteria)" — 6B010 — with no
# per-specimen variants at the analyte-code level. Specimen type is
# distinguished elsewhere in clinosim's FHIR output via the Specimen resource
# (specimen_snomed), not via the test code, which matches how JLAC10 itself
# represents specimen type (in the 17-digit full code's material segment, not
# the 5-character analyte code clinosim stores).
blood: "6B010"
urine: "6B010"
sputum: "6B010"
wound: "6B010"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_codes_jlac10.py -v`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 6: Commit**

```bash
git add clinosim/codes/data/jlac10.yaml clinosim/locale/jp/code_mapping_microbiology.yaml tests/unit/test_codes_jlac10.py
git commit -m "feat(jlac10): register 6B010 culture-identification code + JP microbiology code mapping"
```

---

### Task 2: Add "microbiology" kind to system_key_for

**Files:**
- Modify: `clinosim/codes/loader.py:121-147`
- Test: Create `tests/unit/test_codes_loader.py`

**Interfaces:**
- Consumes: nothing new (pure addition to the existing `_COUNTRY_SYSTEM_KEYS` dict).
- Produces: `system_key_for("microbiology", "JP")` → `"jlac10"`;
  `system_key_for("microbiology", "US")` → `"loinc"`. Task 3 consumes this.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_codes_loader.py`:

```python
"""Unit tests for clinosim.codes.loader's system_key_for (kind -> code-system-key)."""

from __future__ import annotations

import pytest

from clinosim.codes import system_key_for


@pytest.mark.unit
class TestSystemKeyFor:
    def test_microbiology_jp(self):
        assert system_key_for("microbiology", "JP") == "jlac10"

    def test_microbiology_us(self):
        assert system_key_for("microbiology", "US") == "loinc"

    def test_microbiology_case_insensitive(self):
        assert system_key_for("microbiology", "jp") == "jlac10"

    def test_unknown_kind_raises(self):
        with pytest.raises(KeyError):
            system_key_for("not_a_real_kind", "JP")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_codes_loader.py -v`
Expected: FAIL on `test_microbiology_jp` / `test_microbiology_us` /
`test_microbiology_case_insensitive` with `KeyError: "system_key_for: unknown kind
'microbiology'; ..."` (the `test_unknown_kind_raises` test passes already, since that
behavior already exists).

- [ ] **Step 3: Add the "microbiology" kind**

In `clinosim/codes/loader.py`, change:

```python
_COUNTRY_SYSTEM_KEYS: dict[str, dict[str, str]] = {
    "lab": {"jp": "jlac10", "default": "loinc"},
    "diagnosis": {"jp": "icd-10", "default": "icd-10-cm"},
    "drug": {"jp": "yj", "default": "rxnorm"},
    "procedure": {"jp": "k-codes", "default": "cpt"},
}
```

to:

```python
_COUNTRY_SYSTEM_KEYS: dict[str, dict[str, str]] = {
    "lab": {"jp": "jlac10", "default": "loinc"},
    "diagnosis": {"jp": "icd-10", "default": "icd-10-cm"},
    "drug": {"jp": "yj", "default": "rxnorm"},
    "procedure": {"jp": "k-codes", "default": "cpt"},
    "microbiology": {"jp": "jlac10", "default": "loinc"},
}
```

And update the `system_key_for` docstring's `Args: kind:` line from:

```python
        kind: one of ``"lab"``, ``"diagnosis"``, ``"drug"``, ``"procedure"``.
```

to:

```python
        kind: one of ``"lab"``, ``"diagnosis"``, ``"drug"``, ``"procedure"``,
            ``"microbiology"``.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_codes_loader.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add clinosim/codes/loader.py tests/unit/test_codes_loader.py
git commit -m "feat(codes): add microbiology kind to system_key_for (jlac10/loinc)"
```

---

### Task 3: Country-gated code resolution in the microbiology FHIR builder

**Files:**
- Modify: `clinosim/modules/output/_fhir_microbiology.py:10-22` (imports) and `:79-81`
  (culture code resolution)
- Test: Modify `tests/unit/test_microbiology.py` (`TestFhirBuilder` class)

**Interfaces:**
- Consumes: `load_code_mapping("microbiology", country)` (Task 1's YAML, via the
  existing `clinosim.locale.loader.load_code_mapping` function — same one
  `_build_lab_observation` already uses), `system_key_for("microbiology", country)`
  (Task 2), `MicrobiologyResult.specimen` (already exists, no change).
- Produces: `_bb_microbiology(ctx)` unchanged signature; JP output now emits
  `code.coding[].system == get_system_uri("jlac10")` /
  `code.coding[].code == "6B010"` for culture Observations + the DiagnosticReport;
  US output unchanged (still LOINC from `test_loinc`).

- [ ] **Step 1: Write the failing tests**

Open `tests/unit/test_microbiology.py`. Add `get_system_uri` to the existing
`from clinosim.codes import lookup as code_lookup` import line, i.e. change:

```python
from clinosim.codes import lookup as code_lookup
```

to:

```python
from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
```

Then add three new test methods to the existing `TestFhirBuilder` class (after
`test_no_growth_uses_value_string`):

```python
    def test_jp_culture_uses_jlac10_code(self):
        bundle, mb = self._bundle("urinary_tract_infection", country="JP")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("jlac10")
        assert coding["code"] == "6B010"

    def test_us_culture_still_uses_loinc(self):
        bundle, mb = self._bundle("urinary_tract_infection", country="US")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("loinc")
        assert coding["code"] == mb[0].test_loinc

    def test_hai_derived_culture_resolves_same_as_community(self):
        # Mimics the MicrobiologyResult shape hai/enricher.py builds (only
        # specimen / specimen_snomed / test_loinc / growth / organism_snomed /
        # hai_event_id set) — proves the single change point in
        # _fhir_microbiology.py covers HAI-derived cultures too, since both
        # sources carry the same country-neutral `specimen` key.
        hai_culture = {
            "encounter_id": "ENC-HAI",
            "specimen": "blood",
            "specimen_snomed": "119297000",
            "test_loinc": "600-7",
            "growth": True,
            "organism_snomed": "3092008",
            "quantitation": "",
            "susceptibilities": [],
            "hai_event_id": "HAI-1",
        }
        rec = {
            "patient": {"patient_id": "P-HAI", "sex": "F"},
            "encounters": [{"encounter_id": "ENC-HAI"}],
            "clinical_diagnosis": {},
            "microbiology": [hai_culture],
        }
        bundle = fhir._build_bundle(rec, "JP")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("jlac10")
        assert coding["code"] == "6B010"

    def test_jp_unmapped_specimen_falls_back_to_test_loinc(self):
        # Defensive regression guard for the fallback branch itself: today all 4
        # real specimens (blood/urine/sputum/wound) are mapped, so this branch is
        # unreachable with real data — but the `.get(specimen, fallback)` code
        # path must still behave correctly if a future specimen is added to
        # microbiology.yaml before code_mapping_microbiology.yaml is updated for it.
        unmapped_culture = {
            "encounter_id": "ENC-UNMAPPED",
            "specimen": "csf",  # not a key in code_mapping_microbiology.yaml
            "specimen_snomed": "258450006",
            "test_loinc": "6463-4",
            "growth": True,
            "organism_snomed": "9861002",
            "quantitation": "",
            "susceptibilities": [],
            "hai_event_id": "",
        }
        rec = {
            "patient": {"patient_id": "P-UNMAPPED", "sex": "M"},
            "encounters": [{"encounter_id": "ENC-UNMAPPED"}],
            "clinical_diagnosis": {},
            "microbiology": [unmapped_culture],
        }
        bundle = fhir._build_bundle(rec, "JP")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("loinc")
        assert coding["code"] == "6463-4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_microbiology.py::TestFhirBuilder -v`
Expected: `test_jp_culture_uses_jlac10_code` and
`test_hai_derived_culture_resolves_same_as_community` FAIL (current code emits LOINC
`600-7`/`630-4`/`619-7`/`634-6`, not `6B010`, for JP). `test_us_culture_still_uses_loinc`
and `test_jp_unmapped_specimen_falls_back_to_test_loinc` PASS already (no behavior
change for US, and the unmapped-specimen case already falls back to `test_loinc` today
since no country-gating exists yet) — that's fine, they're regression guards for the
next step, not new-behavior tests.

- [ ] **Step 3: Implement the country-gated resolution**

In `clinosim/modules/output/_fhir_microbiology.py`, change the imports from:

```python
from clinosim.codes import get_system_uri
from clinosim.modules._shared import resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _micro_coding
```

to:

```python
from clinosim.codes import get_system_uri, system_key_for
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _micro_coding
```

Then, inside `_bb_microbiology`, right after the existing line
`lang = resolve_lang(ctx.country)` (currently line 52), add the country-gated lookup
setup (computed once per call, not per culture):

```python
    lang = resolve_lang(ctx.country)
    country_code = "JP" if is_jp(ctx.country) else "US"
    culture_code_system = system_key_for("microbiology", country_code)
    culture_code_map = load_code_mapping("microbiology", country_code)
```

Then replace the existing lines (currently lines 79-81):

```python
        culture_loinc = mb.get("test_loinc", "")
        culture_code = ({"coding": [_micro_coding("loinc", culture_loinc, lang)]}
                        if culture_loinc else {"text": "Culture"})
```

with:

```python
        culture_code_value = culture_code_map.get(
            mb.get("specimen", ""), mb.get("test_loinc", "")
        )
        culture_code = ({"coding": [_micro_coding(culture_code_system, culture_code_value, lang)]}
                        if culture_code_value else {"text": "Culture"})
```

(`culture_code` is used unchanged further down for the organism Observation's `code`
field and the DiagnosticReport's `code` field — no other lines in this function
change.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_microbiology.py -v`
Expected: PASS (all tests in the file, including the 3 new ones and all pre-existing
ones — `TestGenerator`, `TestCodesResolve`, `TestFhirBuilder`).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/_fhir_microbiology.py tests/unit/test_microbiology.py
git commit -m "fix(fhir): resolve microbiology culture code via country-gated JLAC10/LOINC lookup"
```

---

### Task 4: Full-suite verification + TODO.md documentation

**Files:**
- Modify: `TODO.md` (add a new bullet under the existing `### Single items (ride along
  with related chains)` heading)

**Interfaces:** None (verification + documentation task, no code changes).

- [ ] **Step 1: Run the full unit test suite**

Run: `pytest -m unit -q`
Expected: all tests pass (no regressions in `test_hai_yaml_validators.py`,
`test_sdoh_codes.py`, `test_microbiology.py`, `test_hai_codes_coverage.py`,
`observation/test_microbiology_validation.py` — all reference `test_loinc` today and
must be unaffected, since `MicrobiologyResult.test_loinc` and `microbiology.yaml` are
untouched by this plan).

- [ ] **Step 2: Run the integration test suite**

Run: `pytest -m integration -q`
Expected: all tests pass, in particular `tests/integration/test_antibiotic_audit.py`
and `tests/integration/test_narrow_enricher.py` (both construct `MicrobiologyResult`
fixtures referencing `test_loinc` — must be unaffected since that field is untouched).

- [ ] **Step 3: Manual spot-check (optional but recommended)**

Run a small JP cohort and inspect a culture Observation's coding. Output lands at
`<output-dir>/fhir_r4/Observation.ndjson` (AD-31 bulk-data layout, one NDJSON per
resource type):

```bash
clinosim generate -o /tmp/jp_micro_check -p 500 -s 42 --country JP --format fhir-r4
python3 -c "
import json
with open('/tmp/jp_micro_check/fhir_r4/Observation.ndjson') as f:
    for line in f:
        r = json.loads(line)
        if r['id'].startswith('mb-org-'):
            print(r['code']['coding'][0])
"
```

Expected: at least one line printed, each showing
`{'system': 'urn:oid:1.2.392.200119.4.1005', 'code': '6B010', 'display': '培養同定(一般細菌)'}`.
If no `mb-org-*` lines appear at all, rerun with a larger `-p` (microbiology cultures
only occur for infection-associated diseases — sepsis/pneumonia/UTI/cellulitis/
aspiration — so a small cohort may draw zero). This step is a confirmation, not a
blocking gate, since Task 3's unit tests already prove this behavior directly.

- [ ] **Step 4: Document scope decisions in TODO.md**

Open `TODO.md`, find the `### Single items (ride along with related chains)` section
(currently ending after the "Allergy/imaging display locale-freeze" bullet). Add a new
bullet at the end of that section:

```markdown
- JP microbiology culture codes now use JLAC10 (`6B010`, session 35, 2026-07-04) —
  `_fhir_microbiology.py` resolves the culture Observation/DiagnosticReport code via
  `code_mapping_microbiology.yaml` + `system_key_for("microbiology", ...)`, covering
  both community-acquired and HAI-derived cultures (both carry the same country-neutral
  `MicrobiologyResult.specimen` key). Verified against JSLM JLAC10 master v137: category
  6B (微生物学的検査/培養同定検査) has one generic culture-identification analyte code
  (no per-specimen variants at the analyte-code level — specimen type lives in the
  17-digit full code's material segment, which clinosim doesn't model), so all 4
  specimens map to the same `6B010`. Deferred, not required for this fix: (a) antibiotic
  susceptibility JLAC10 mapping (`SusceptibilityResult.antibiotic_loinc`, 10 drugs) —
  JLAC10's susceptibility-result structure may not mirror LOINC's per-drug-per-test-code
  model, needs its own research pass; (b) CSV adapter (`csv_adapter.py`) still dumps the
  raw `test_loinc` CIF field for JP — acceptable since it's a raw code column, not a
  `display`/`text` field (CLAUDE.md's JP-must-be-Japanese rule targets FHIR
  display/text), but could be revisited for JP output consistency later.
```

- [ ] **Step 5: Commit**

```bash
git add TODO.md
git commit -m "docs: record JP microbiology JLAC10 mapping completion + deferred follow-ups"
```
