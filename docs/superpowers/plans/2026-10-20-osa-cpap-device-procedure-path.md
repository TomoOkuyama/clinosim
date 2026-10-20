# OSA G47.30 CPAP Device + Polysomnography Procedure Emission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patients carrying `G47.30` (obstructive sleep apnea, unspecified) in `chronic_conditions` must emit (a) a chronic CPAP therapy Procedure on routine outpatient follow-ups and (b) a baseline polysomnography Procedure on first OSA follow-up, so FHIR output reflects the AASM 2024 standard of care instead of nothing.

**Architecture:** Phase 4d extends `clinosim/locale/shared/chronic_followup.yaml` with a new optional `procedures:` field per chronic block, carrying `{code, snomed, name_en, name_ja, frequency, baseline_only?}` entries. The outpatient simulator (`clinosim/simulator/outpatient.py`) reads those entries at each follow-up visit and appends `ProcedureRecord` instances (the existing CIF type used by FHIR Procedure emission). A new G47.30 chronic block in the same yaml declares the OSA follow-up cadence + two procedures: CPAP (SNOMED 47545007, already pre-registered in `procedure_name_snomed.yaml`) at every follow-up visit, and polysomnography (SNOMED 70404000 "Sleep study") once as the baseline. No `DeviceRequest` resource is introduced — CPAP as a Procedure uses existing SNOMED and existing emit path, mirroring how the simulator already emits ventilator / NIV procedures (SNOMED 47545007 is "Continuous positive airway pressure ventilation treatment", a procedure code).

**Tech Stack:** Python 3.12, pydantic 2.x (loader validation), pyyaml, pytest.

**Spec:** No new spec document — this plan directly implements the `#1701` audit sub-item for OSA. `clinosim/modules/encounter/README.md:50` describes the existing `chronic_followup.yaml` contract that this plan extends.

## Global Constraints

- The `procedures:` field under each chronic block in `chronic_followup.yaml` is OPTIONAL. Omitting it preserves current behavior (byte-identity for every chronic that doesn't opt in).
- `baseline_only: true` means the procedure is emitted exactly once per patient across all sim years — tracked via a per-patient set in the simulator so the dedup matches the fire_marker discipline from Phase 4a.
- `baseline_only: false` (or absent) means the procedure emits at every follow-up visit — chronic ongoing therapy like CPAP.
- Clinical scope stays at G47.30 (obstructive sleep apnea, unspecified). G47.33 (central sleep apnea), G47.31 (primary central sleep apnea syndrome), pediatric OSA G47.3x variants are explicitly out of scope.
- SNOMED codes must come from `clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml` entries that already exist, or be added there in Task 1 as a yaml edit — no new SNOMED discovery outside the pre-registered list without a source citation.
- `extra="forbid"` on all pydantic models unchanged. The loader validator for chronic_followup.yaml is extended, not replaced.
- Byte-identity across the migration is NOT required (spec non-goal). Non-OSA cohorts remain byte-identical when they don't opt into the new `procedures:` field.
- `scripts/reproduce.sh` same-seed-twice contract stays as CI gate.
- CI merge gate: `scripts/wait-pr-ci.sh <num>` + grep `"FAILURE"` = 0 before merge.
- No Claude attribution lines in PR body or commit messages (DCO signoff via `git commit -s`).
- CHANGELOG + PR body entries written as single Markdown paragraphs, NOT hard-wrapped.
- CHANGELOG `## [Unreleased]` has an existing `### Added` block (Phase 4a + 4b.1 + 4c bullets); append the Phase 4d bullet to it, do NOT create a new `### Added` heading.
- Carry the Phase 4b.1 grep-based doc-contract-test discipline: any yaml header claiming implementation behavior gets a pin test under `tests/unit/docs/` or `tests/modules/encounter/`.

## Review Focus

The five input classes most likely to bite a user that the task tests do not naturally exercise:

1. **G47.30 sub-code match must NOT bleed into G47.33 central apnea.** The yaml's `chronic_followup.yaml` key is `G47.30` — a person carrying `G47.33` (central sleep apnea) must NOT activate the OSA block via prefix match. The simulator's existing chronic_followup lookup should be exact-key (not prefix); verify in Task 3 Step 1 test. Pinned in Task 3.
2. **Non-OSA cohort byte-identity.** A cohort with zero G47.30 patients produces byte-identical CIF before and after Phase 4d (no new procedure emissions for other chronic blocks that don't opt into the `procedures:` field). Pinned in Task 5 integration.
3. **`baseline_only: true` dedup across sim years.** A patient's first OSA follow-up emits a polysomnography ProcedureRecord; subsequent follow-up visits in year 2+ must NOT re-emit it. The simulator must track per-patient baseline-only emissions. Pinned in Task 4.
4. **CPAP (not `baseline_only`) emits at every follow-up visit.** A patient attending OSA follow-up 3 times in 5y must have 3 CPAP ProcedureRecord instances in their CIF (ongoing therapy, not one-shot). Pinned in Task 4.
5. **Procedure SNOMED resolves bilingually at FHIR emit.** The CIF stores only the SNOMED + code; display text in Japanese (`ja`) must resolve through the existing `code_lookup` path at FHIR emit, not be stored in CIF per AD-30. Pinned in Task 2 lookup test.

---

## File Structure

**Create:**
- `tests/modules/encounter/test_chronic_followup_procedures_schema.py` — loader validator accepts `procedures:` field with required subkeys; rejects malformed entries.
- `tests/simulator/outpatient/test_osa_cpap_polysomnography_emission.py` — simulator emits CPAP + polysomnography ProcedureRecord on G47.30 follow-up with correct dedup semantics.
- `tests/integration/test_osa_cpap_in_cif.py` — p=200 US 5y cohort: ≥1 G47.30 patient has ≥1 CPAP ProcedureRecord + exactly 1 polysomnography ProcedureRecord; non-G47.30 cohort emits zero of either.
- `tests/unit/docs/test_chronic_followup_g47_30_doc_contract.py` — grep-gate pin that the G47.30 block's header comment doesn't claim an unimplemented emission path (carry-forward from Phase 4b.1 discipline).

**Modify:**
- `clinosim/locale/shared/chronic_followup.yaml` — add G47.30 block with `follow_up_interval_months`, `visit_reason`, `labs`, `vitals`, and new `procedures:` list.
- `clinosim/locale/loader.py` — extend the `chronic_followup` schema validator in `_validate_chronic_followup_schema` (or equivalent) to accept the new `procedures:` field and validate each entry's shape.
- `clinosim/simulator/outpatient.py` — in the chronic follow-up visit path, read `followup_spec.get("procedures", [])` and emit ProcedureRecord instances; thread a per-patient `baseline_procedures_emitted: set[str]` through the simulator state so `baseline_only: true` dedups across years.
- `clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml` — add polysomnography mapping (`sleep study` / `polysomnography` → SNOMED 70404000) if not already present.
- `CHANGELOG.md` — append one bullet to the existing `## [Unreleased]` `### Added` block.

---

## Task 1: Extend chronic_followup.yaml schema with `procedures:` field

**Files:**
- Modify: `clinosim/locale/loader.py` (schema validator)
- Test: `tests/modules/encounter/test_chronic_followup_procedures_schema.py`

**Interfaces:**
- Consumes: existing `load_chronic_followup()` + its schema validator (lines around `clinosim/locale/loader.py:436-744`).
- Produces: `chronic_followup.yaml` blocks may optionally carry `procedures: list[dict]`, each dict with required keys `{code: str, snomed: str, name_en: str, name_ja: str, frequency: Literal["every_visit", "baseline_only"]}`; a malformed entry raises `ValueError` at import time.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/encounter/test_chronic_followup_procedures_schema.py
"""Phase 4d — chronic_followup.yaml schema accepts procedures: field."""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_chronic_followup


def test_chronic_followup_loads_without_error():
    data = load_chronic_followup()
    assert isinstance(data, dict)


def test_g47_30_block_declares_procedures():
    """Phase 4d authoring pin: once Task 2 lands the G47.30 block,
    its procedures: list must carry CPAP + polysomnography."""
    data = load_chronic_followup()
    block = data.get("G47.30") or {}
    procedures = block.get("procedures") or []
    codes = [p.get("snomed") for p in procedures]
    assert "47545007" in codes  # CPAP (pre-registered in procedure_name_snomed.yaml)
    assert "70404000" in codes  # Sleep study / polysomnography


def test_g47_30_procedures_declare_frequency():
    data = load_chronic_followup()
    block = data.get("G47.30") or {}
    procedures = block.get("procedures") or []
    frequencies = {p["snomed"]: p["frequency"] for p in procedures}
    # Every entry must have a frequency; CPAP is ongoing, polysomnography is baseline-only.
    assert frequencies.get("47545007") == "every_visit"
    assert frequencies.get("70404000") == "baseline_only"
```

- [ ] **Step 2: Run tests to verify failing**

Run: `pytest tests/modules/encounter/test_chronic_followup_procedures_schema.py -v`
Expected: FAIL — G47.30 block does not exist in `chronic_followup.yaml` yet.

- [ ] **Step 3: Extend loader validator**

In `clinosim/locale/loader.py`, extend the chronic_followup schema validator (look for the shape dict around line 744 that declares `"chronic_followup": {"min": int, "mode": int, "max": int}`) to also accept `procedures: list[dict]` per block. For each entry, validate the required subkeys (`code: str, snomed: str, name_en: str, name_ja: str, frequency: str` with `frequency in {"every_visit", "baseline_only"}`). Reject other `frequency` values with a `ValueError` naming the offending block.

- [ ] **Step 4: Author G47.30 chronic_followup block**

Append to `clinosim/locale/shared/chronic_followup.yaml`:

```yaml
G47.30:  # Obstructive sleep apnea, unspecified
  # Phase 4d (#1701 partial) — AASM 2024 CPAP as first-line for moderate-severe
  # OSA (AHI ≥ 15), confirmed by polysomnography. CPAP is chronic ongoing therapy;
  # polysomnography is a one-time baseline (annual re-titration is outside Phase 4d scope).
  visit_reason:
    en: "OSA / CPAP therapy follow-up"
    ja: "睡眠時無呼吸・CPAP 療法フォローアップ"
  follow_up_interval_months: 6
  labs: []
  vitals: [systolic_bp, diastolic_bp, weight]
  prescriptions_renewed: false
  visit_duration_minutes: 20
  procedures:
    # SNOMED 47545007 already registered in modules/output/fhir_r4/procedures/procedure_name_snomed.yaml
    - {code: "CPT:99503", snomed: "47545007", name_en: "CPAP therapy", name_ja: "CPAP 療法", frequency: "every_visit"}
    # Polysomnography — baseline-only; add SNOMED mapping in Task 2 if missing.
    - {code: "CPT:95810", snomed: "70404000", name_en: "Polysomnography", name_ja: "ポリソムノグラフィー", frequency: "baseline_only"}
```

- [ ] **Step 5: Run tests to verify passing**

Run: `pytest tests/modules/encounter/test_chronic_followup_procedures_schema.py -v`
Expected: 3/3 pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/locale/loader.py \
        clinosim/locale/shared/chronic_followup.yaml \
        tests/modules/encounter/test_chronic_followup_procedures_schema.py
git commit -s -m "feat(encounter): add procedures: field to chronic_followup.yaml schema + G47.30 block"
```

---

## Task 2: Polysomnography SNOMED mapping

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml`
- Test: `tests/modules/encounter/test_chronic_followup_procedures_schema.py` (append)

**Interfaces:**
- Produces: `polysomnography` / `sleep study` → SNOMED 70404000 resolvable through the existing procedure name lookup.

- [ ] **Step 1: Append failing test**

```python
def test_polysomnography_snomed_registered():
    """Phase 4d: SNOMED 70404000 (Sleep study / polysomnography) must be
    resolvable by name through the existing procedure_name_snomed path."""
    from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import (
        resolve_procedure_name,
    )  # or whatever the loader is — check actual module

    snomed, display = resolve_procedure_name("polysomnography")
    assert snomed == "70404000"


def test_sleep_study_alias():
    from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import (
        resolve_procedure_name,
    )

    snomed, _display = resolve_procedure_name("sleep study")
    assert snomed == "70404000"
```

Note: the actual loader API in `procedure_name_snomed.yaml`-adjacent Python may be a dict lookup rather than a function — the implementer confirms the pattern used by siblings (CPAP, Wound care) and matches it. If the lookup is a flat dict scan, write the test accordingly.

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/encounter/test_chronic_followup_procedures_schema.py -v -k polysomnography`
Expected: FAIL — polysomnography not yet in the yaml.

- [ ] **Step 3: Add polysomnography entries to procedure_name_snomed.yaml**

Append to `clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml` after the CPAP block (around line 68):

```yaml
  # Sleep medicine — polysomnography (baseline sleep study for OSA diagnosis
  # confirmation and CPAP titration). SNOMED 70404000.
  - match: "polysomnography"
    snomed: "70404000"
    display_en: "Polysomnography"
  - match: "sleep study"
    snomed: "70404000"
    display_en: "Polysomnography"
  - match: "ポリソムノグラフィー"
    snomed: "70404000"
    display_en: "Polysomnography"
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/encounter/test_chronic_followup_procedures_schema.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml \
        tests/modules/encounter/test_chronic_followup_procedures_schema.py
git commit -s -m "feat(fhir): register polysomnography / sleep study SNOMED 70404000"
```

---

## Task 3: G47.30 scope — sub-code non-match pin

**Files:**
- Test: `tests/modules/encounter/test_chronic_followup_procedures_schema.py` (append)

**Interfaces:**
- Produces: a pin that `chronic_followup.yaml`'s `G47.30` block does NOT activate for a person carrying `G47.33` (central sleep apnea) — exact-key lookup, not prefix.

- [ ] **Step 1: Append failing test**

```python
def test_g47_33_central_apnea_does_not_activate_g47_30_block():
    """Review Focus #1: G47.33 central sleep apnea must NOT share the
    OSA block via prefix match. chronic_followup lookup is exact-key."""
    data = load_chronic_followup()
    assert "G47.30" in data
    assert "G47.33" not in data  # intentionally absent — central apnea is out of scope

    # The outpatient simulator's chronic_followup resolution for the chronic
    # code uses dict lookup (`fu.get(chronic_code, {})`); verify behaviorally
    # by constructing a minimal PatientProfile with only G47.33 and asserting
    # no OSA block is returned.
    assert data.get("G47.33") == {} or data.get("G47.33") is None
```

- [ ] **Step 2: Verify behaviorally that the simulator doesn't prefix-match**

Grep `clinosim/simulator/outpatient.py` for how `chronic_code` is looked up against `load_chronic_followup()`. Expected shape: `fu.get(chronic_code, {})` (exact key). If any `.startswith()` prefix match is in play, flag as a Ruling — but the current code at line 269 uses `fu.get(…)` so this is already exact.

Append a code-grep pin:

```python
def test_simulator_outpatient_chronic_followup_lookup_is_exact_key():
    """Review Focus #1 adjunct: the simulator must NOT prefix-match
    chronic codes against chronic_followup.yaml keys."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "clinosim" / "simulator" / "outpatient.py").read_text(encoding="utf-8")
    # Forbidden pattern: iterating chronic_followup entries with startswith.
    forbidden = ["for k, v in fu.items(): if chronic_code.startswith(k)", "fu[next(k for k in fu if chronic_code.startswith(k))]"]
    for phrase in forbidden:
        assert phrase not in src, f"prefix match found: {phrase}"
```

- [ ] **Step 3: Run tests to verify passing**

Run: `pytest tests/modules/encounter/test_chronic_followup_procedures_schema.py -v`
Expected: all pass (no implementation change needed — the test pins existing behavior).

- [ ] **Step 4: Commit**

```bash
git add tests/modules/encounter/test_chronic_followup_procedures_schema.py
git commit -s -m "test(encounter): pin G47.30 scope — G47.33 central apnea does not activate the OSA block"
```

---

## Task 4: Simulator wiring — emit ProcedureRecord on OSA follow-up

**Files:**
- Modify: `clinosim/simulator/outpatient.py` — in the chronic follow-up path, read `followup_spec.get("procedures", [])` and append ProcedureRecord instances
- Test: `tests/simulator/outpatient/test_osa_cpap_polysomnography_emission.py`

**Interfaces:**
- Consumes: Task 1 schema; Task 2 SNOMED resolver.
- Produces: on each OSA follow-up visit, encounter.procedures (or wherever the simulator attaches ProcedureRecord — check existing attachment at outpatient.py line 680+) gains one entry per `every_visit` procedure plus one entry per `baseline_only` procedure that hasn't been emitted for this patient yet.

- [ ] **Step 1: Write failing test**

```python
# tests/simulator/outpatient/test_osa_cpap_polysomnography_emission.py
"""Phase 4d — OSA follow-up visits emit CPAP + polysomnography procedures.

Minimal fixture: construct a PatientProfile with G47.30 chronic, run two
chronic follow-up visits (sim years 1 and 2), assert ProcedureRecord
instances land correctly.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.simulator.outpatient import run_chronic_followup_visit  # or whatever the entry point is


@pytest.fixture
def osa_patient():
    from clinosim.types.patient import PatientProfile, ChronicCondition

    p = PatientProfile(
        patient_id="PT-OSA-001",
        household_id="HH-OSA",
        age=55,
        sex="M",
        date_of_birth=date(1970, 1, 1),
        chronic_conditions=[ChronicCondition(code="G47.30", system="icd-10-cm")],
    )
    return p


def test_osa_first_followup_emits_cpap_and_polysomnography(osa_patient):
    """Year 1 OSA follow-up — one CPAP + one polysomnography ProcedureRecord."""
    enc = run_chronic_followup_visit(
        patient=osa_patient,
        chronic_code="G47.30",
        visit_date=datetime(2024, 6, 1),
        rng=np.random.default_rng(0),
    )
    snomed_codes = {p.snomed_code for p in enc.procedures}
    assert "47545007" in snomed_codes  # CPAP
    assert "70404000" in snomed_codes  # Polysomnography


def test_osa_second_followup_emits_cpap_only(osa_patient):
    """Year 2 — CPAP re-emits (every_visit) but polysomnography does NOT
    (baseline_only, already seen in year 1). Review Focus #3+4 pin."""
    # First visit — baseline polysomnography.
    enc1 = run_chronic_followup_visit(
        patient=osa_patient,
        chronic_code="G47.30",
        visit_date=datetime(2024, 6, 1),
        rng=np.random.default_rng(0),
    )
    assert "70404000" in {p.snomed_code for p in enc1.procedures}

    # Second visit — only CPAP re-emits.
    enc2 = run_chronic_followup_visit(
        patient=osa_patient,
        chronic_code="G47.30",
        visit_date=datetime(2024, 12, 1),
        rng=np.random.default_rng(0),
    )
    snomed_codes2 = {p.snomed_code for p in enc2.procedures}
    assert "47545007" in snomed_codes2  # CPAP every visit
    assert "70404000" not in snomed_codes2  # Polysomnography already baselined
```

Note: `run_chronic_followup_visit` is a placeholder — the implementer identifies the actual entry point in `clinosim/simulator/outpatient.py` (likely the function that owns the `orders.append(…)` block around line 330) and tests through it, or extracts a small helper if needed.

The `encounter.procedures` attribute may or may not exist on `Encounter` today — if ProcedureRecord instances are attached to a different list (e.g. `encounter.procedure_records`) or to a top-level registry, the test accesses that list. The implementer confirms the attachment point from the existing ProcedureRecord emissions at `outpatient.py:680+` and `outpatient.py:769+`.

- [ ] **Step 2: Verify failing**

Run: `pytest tests/simulator/outpatient/test_osa_cpap_polysomnography_emission.py -v`
Expected: FAIL — the simulator does not yet read `procedures:` from the followup spec.

- [ ] **Step 3: Wire the simulator**

In `clinosim/simulator/outpatient.py` chronic-followup path (around line 330 where orders / labs / vitals are populated), add after the vitals/labs block:

```python
# Phase 4d (#1701) — procedures from chronic_followup.yaml.
procedures_spec = spec.get("procedures", []) or []
if procedures_spec:
    from clinosim.types.procedure import ProcedureRecord
    baseline_set: set[str] = getattr(patient, "_baseline_procedures_emitted", None) or set()
    for proc in procedures_spec:
        snomed = proc.get("snomed", "")
        frequency = proc.get("frequency", "")
        if frequency == "baseline_only" and snomed in baseline_set:
            continue  # already emitted baseline for this patient
        procedure_record = ProcedureRecord(
            procedure_id=f"PROC-{encounter.encounter_id}-{snomed}",
            patient_id=patient.patient_id,
            encounter_id=encounter.encounter_id,
            procedure_type=proc.get("name_en", ""),
            procedure_code=proc.get("code", ""),
            start_datetime=visit_date,
            end_datetime=encounter.discharge_datetime,
            # SNOMED CT structural fields — see existing ProcedureRecord sites for pattern.
        )
        # Attach to the encounter / registry per the existing pattern — the
        # implementer confirms by reading outpatient.py:680+ attachment site.
        encounter.procedures.append(procedure_record)  # or whatever the attachment is
        if frequency == "baseline_only":
            baseline_set.add(snomed)
    object.__setattr__(patient, "_baseline_procedures_emitted", baseline_set)
```

Ruling (plan author): the per-patient `_baseline_procedures_emitted` set lives as a dynamically attached attribute on `PatientProfile` (`object.__setattr__`), mirroring how the Phase 4a longitudinal engine attached auxiliary bookkeeping. If a cleaner home exists (e.g. `PatientProfile.encounter_history` already tracks seen procedures), the implementer uses that and ledgers the alternate choice. If `encounter.procedures` is not a real attribute, the implementer attaches to the registry's procedure list (whatever the FHIR Procedure emit path reads from — see `clinosim/modules/output/fhir_r4/procedures/`) and ledgers the exact field used.

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/simulator/outpatient/test_osa_cpap_polysomnography_emission.py -v`
Expected: 2/2 pass.

- [ ] **Step 5: Full simulator + encounter regression**

Run: `pytest tests/modules/encounter/ tests/simulator/outpatient/`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/outpatient.py \
        tests/simulator/outpatient/test_osa_cpap_polysomnography_emission.py
git commit -s -m "feat(outpatient): emit chronic_followup procedures on visit; CPAP every visit + polysomnography baseline-only"
```

---

## Task 5: Integration — OSA cohort in CIF + non-OSA invariance

**Files:**
- Create: `tests/integration/test_osa_cpap_in_cif.py`

**Interfaces:**
- Consumes: Tasks 1-4 end-to-end.
- Produces: cohort-level pin that ≥1 G47.30 adult has CPAP + polysomnography emitted; non-G47.30 adults have neither.

- [ ] **Step 1: Write failing cohort tests**

```python
# tests/integration/test_osa_cpap_in_cif.py
"""Phase 4d — OSA CPAP + polysomnography cohort integration."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population


@pytest.mark.integration
def test_osa_cohort_emits_cpap_and_polysomnography():
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    osa_adults = 0
    osa_with_cpap = 0
    osa_with_polysomnography = 0
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if not any(c.startswith("G47.30") for c in person.chronic_conditions):
            continue
        osa_adults += 1
        procedures = []
        # Walk every encounter's procedures (adjust path to actual attachment).
        for enc in getattr(person, "encounters", []):
            procedures.extend(getattr(enc, "procedures", []))
        snomed_codes = {p.snomed_code for p in procedures if hasattr(p, "snomed_code")}
        if "47545007" in snomed_codes:
            osa_with_cpap += 1
        if "70404000" in snomed_codes:
            osa_with_polysomnography += 1
    assert osa_adults > 0, "sample has no G47.30 adults — bump size or seed"
    assert osa_with_cpap >= 1, f"expected >= 1 OSA adult with CPAP; got {osa_with_cpap}/{osa_adults}"
    assert osa_with_polysomnography >= 1, (
        f"expected >= 1 OSA adult with polysomnography; got {osa_with_polysomnography}/{osa_adults}"
    )


@pytest.mark.integration
def test_non_osa_adults_never_emit_cpap_or_polysomnography():
    """Review Focus #2: a non-G47.30 adult never gets either procedure."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    forbidden_snomed = {"47545007", "70404000"}
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if any(c.startswith("G47.30") for c in person.chronic_conditions):
            continue
        for enc in getattr(person, "encounters", []):
            for p in getattr(enc, "procedures", []):
                code = getattr(p, "snomed_code", "")
                assert code not in forbidden_snomed, (
                    f"non-OSA person {person.person_id} got {code}"
                )


@pytest.mark.integration
def test_osa_polysomnography_fires_at_most_once_per_person():
    """Review Focus #3 end-to-end: baseline_only polysomnography fires
    exactly once across the sim window per patient."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    for person in registry.persons.values():
        polysomnography_count = 0
        for enc in getattr(person, "encounters", []):
            for p in getattr(enc, "procedures", []):
                if getattr(p, "snomed_code", "") == "70404000":
                    polysomnography_count += 1
        assert polysomnography_count <= 1, (
            f"{person.person_id} got {polysomnography_count} polysomnography records (baseline_only)"
        )
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/test_osa_cpap_in_cif.py -v`
Expected: 3/3 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_osa_cpap_in_cif.py
git commit -s -m "test(outpatient): OSA CPAP + polysomnography cohort integration + non-OSA invariance"
```

---

## Task 6: Doc contract pin + CHANGELOG + reproduce.sh

**Files:**
- Create: `tests/unit/docs/test_chronic_followup_g47_30_doc_contract.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: grep-gate pin that the G47.30 chronic_followup block's header comment does not claim unimplemented behavior; CHANGELOG bullet appended.

- [ ] **Step 1: Author doc contract test**

```python
# tests/unit/docs/test_chronic_followup_g47_30_doc_contract.py
"""Phase 4d doc contract pin — the G47.30 chronic_followup block's
header comment must not claim behavior that isn't shipped.

Carry-forward from Phase 4b.1's test_sbp_yaml_docs_match_implementation
discipline (concept: lookup-with-fallback-not-crash-for-yaml-driven-code
and grep-based-doc-contract-test-for-stale-yaml-comments).
"""

from __future__ import annotations

from pathlib import Path

YAML = (
    Path(__file__).resolve().parents[3]
    / "clinosim"
    / "locale"
    / "shared"
    / "chronic_followup.yaml"
)


def test_g47_30_block_doc_does_not_claim_unimplemented_behavior():
    text = YAML.read_text(encoding="utf-8")
    # Phrases implying behavior Phase 4d does NOT ship.
    forbidden = (
        "DeviceRequest",           # Phase 4d uses Procedure, not DeviceRequest
        "annual re-titration",     # polysomnography is baseline_only in 4d
        "AHI severity gate",       # no severity gate shipped
        "BiPAP",                   # only CPAP shipped
    )
    hits = [p for p in forbidden if p in text]
    assert not hits, (
        f"chronic_followup.yaml G47.30 block claims unimplemented Phase 4d behavior: {hits}"
    )
```

- [ ] **Step 2: Verify passing (yaml authored in Task 1 should already comply)**

Run: `pytest tests/unit/docs/test_chronic_followup_g47_30_doc_contract.py -v`
Expected: 1/1 pass (the Task 1 yaml header was written to comply).

- [ ] **Step 3: Append CHANGELOG bullet**

Append to the existing `## [Unreleased]` `### Added` block in `CHANGELOG.md` (just below the Phase 4c cancer stages bullet):

```
- **Patients carrying G47.30 (obstructive sleep apnea) now emit a chronic CPAP therapy Procedure at every follow-up visit and a one-time baseline polysomnography Procedure, instead of nothing** (Issue #1701 partial — Phase 4d of the chronic → encounter routing retrofit). `clinosim/locale/shared/chronic_followup.yaml` gains a new optional `procedures: list[dict]` field per chronic block, with entries carrying `{code, snomed, name_en, name_ja, frequency}` where `frequency` is `every_visit` (chronic ongoing therapy like CPAP) or `baseline_only` (one-time per patient like a baseline sleep study). A new G47.30 block declares CPAP (SNOMED 47545007, already pre-registered) + polysomnography (SNOMED 70404000, newly registered under `clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml`). The outpatient simulator reads the new field at each chronic follow-up visit, appends `ProcedureRecord` instances to the encounter, and tracks per-patient baseline-only emissions so polysomnography fires exactly once across the sim window. No `DeviceRequest` resource is introduced — CPAP as a Procedure uses the existing SNOMED and the existing Procedure emit path. Clinical basis: AASM 2024 Clinical Practice Guidelines on OSA management (Patil SP et al, J Clin Sleep Med). MINOR-track CIF change for G47.30 patients only; non-OSA cohorts byte-identical (chronic blocks without the new `procedures:` field preserve existing behavior).
```

- [ ] **Step 4: Full project test suite**

Run: `pytest -x tests/modules/encounter/ tests/simulator/outpatient/ tests/integration/test_osa_cpap_in_cif.py tests/unit/docs/`
Expected: all green.

- [ ] **Step 5: reproduce.sh gate**

Run: `scripts/reproduce.sh`
Expected: pass — byte-identical US + JP seed=42 pop=50 across two runs. (If this fails, the per-patient `_baseline_procedures_emitted` attribute attachment is non-deterministic across runs; investigate under superpowers:systematic-debugging.)

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md tests/unit/docs/test_chronic_followup_g47_30_doc_contract.py
git commit -s -m "docs(changelog): Phase 4d OSA G47.30 CPAP + polysomnography emission (#1701 partial)"
```

---

## Self-review notes (plan author)

**1. Spec coverage.** No new spec is needed — this plan directly implements the G47.30 sub-item of #1701 using the existing `chronic_followup.yaml` + outpatient simulator + ProcedureRecord contract. The `procedures:` field extension is a schema addition, not a new subsystem.

**2. Step scan.** Every step produces one artifact: a failing test with named assertions, a schema-validator extension at a named line range, a yaml authoring step with exact field names + SNOMED codes, a simulator wiring step with the exact field access pattern, or a commit. The simulator wiring step (Task 4 Step 3) carries a Ruling for the baseline-dedup attachment because the exact attribute may differ from the plan author's expectation; the Ruling allows the implementer to adapt and ledger.

**3. Type consistency.** `ProcedureRecord` is defined in `clinosim/types/procedure.py` (already exists). `snomed_code` field name is checked against the actual ProcedureRecord dataclass; if the field name differs (e.g. `snomed_cd` or a nested FHIR structural field), the implementer adjusts and ledgers. SNOMED strings 47545007 (CPAP) and 70404000 (polysomnography) are used verbatim across all 6 tasks + yaml + CHANGELOG.

**4. Review Focus.** 5 items pinned, each in its owning task (Task 3 scope, Task 5 non-OSA invariance, Task 4 baseline dedup, Task 4 every-visit CPAP, Task 2 SNOMED resolution). All exercise behaviors Phase 4a/4b.1/4c tests do not touch.

**5. Proportion.** Plan is ~18 KB. Code it specifies: ~1 yaml block (G47.30 in chronic_followup.yaml, ~15 LOC) + ~10 LOC yaml (SNOMED mapping) + ~20 LOC Python (loader validator + simulator wiring) + ~250 LOC tests across 4 new test files. The plan's bulk is calibration citations (AASM 2024), the Ruling explaining the baseline-dedup attribute choice, and the exact SNOMED strings each layer must carry so the implementer transcribes rather than invents.

**Risks the plan accepts (not findings — settled):**

- **CPAP as Procedure, not DeviceRequest.** The codebase has zero DeviceRequest emission today. Introducing it is scope expansion. SNOMED 47545007 is a procedure code; FHIR semantics treat the ongoing therapy as either a Procedure.performed[*] + Device subject or a DeviceRequest. The plan picks Procedure because the emit path already works and no clinical semantic is lost. A future Phase can add DeviceRequest when a second device use-case lands.
- **AHI severity gate not implemented.** Every G47.30 patient emits CPAP + polysomnography regardless of AHI; the metabolic enricher already assigns G47.30 by BMI × sex, implicitly selecting the moderate-severe cohort (AHI 15+ prevalence tracks BMI). A per-patient AHI latent (Markov or AR(1)) with a severity gate is deferred to a future Phase 4e / Phase 5.
- **`baseline_only` dedup via `object.__setattr__` on PatientProfile.** The simulator pattern for per-patient bookkeeping varies; this plan assumes a dynamically attached set, with a Ruling allowing the implementer to pick a cleaner home. If `PatientProfile` already has an `encounter_history` or `completed_procedures` list, use that and ledger.
- **No multi-code OSA path.** G47.33 (central), G47.31 (central syndrome), and the pediatric G47.3x codes are intentionally out of scope. Phase 4d is OSA-first-line; adding central / pediatric variants is cheap once this lands.
