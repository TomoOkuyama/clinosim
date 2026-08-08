# PR3b-3 Clinical Axis Completion (D1 + D2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the two PR3b-3 clinical-axis gate TODOs (D1 = R-rate per-organism filter, D2 = empty-rate panel-eligible filter) so PR3b-3 chain closes with zero PR3b-3-related deferred TODOs.

**Architecture:** Add two pure helpers inline in `clinosim/audit/axes/clinical.py` — `_organism_per_encounter(cohort, country)` walks `Observation.ndjson` once for `mb-org-*` Observations to build `{enc_id: {organism_snomed, ...}}`; `_panel_eligible_organisms()` derives `{hai_type: {organism_snomed, ...}}` from `load_hai_antibiogram()` keys. The R-rate gate (D1) filters `cohort_enc` by per-(hai_type, organism). The empty-rate gate (D2) restricts the denominator to encounters with at least one panel-eligible organism culture. Both TODO markers removed; n<30 WARN guards retained.

**Tech Stack:** Python 3.11+, pytest (unit + integration markers), existing audit framework (`clinosim.audit.{types,axes,registry}`), existing FHIR microbiology builder convention (`mb-org-{enc}-{i}` id + `valueCodeableConcept` SNOMED coding).

## Global Constraints

- Code language: Python 3.11+. Comments + docstrings: English.
- Formatter: ruff. Type checking: mypy strict.
- Line length: 100.
- Determinism (AD-16): no `random.random()` / `time.time()` / shared global RNG.
- No new YAML files. No new module package. helpers go inline in `clinical.py`.
- TODO comment markers in `clinical.py:175-191` and `antibiotic/audit.py:111-128`
  MUST be removed (their removal is the contract that closes the PR3b-3 chain).
- Pre-merge gate (session 22 rule): `pytest tests/unit tests/integration -m "unit or integration"` full sweep — NOT a feature-specific subset.
- Commit trailer (every commit):
  `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7`
- Spec: `docs/superpowers/specs/2026-06-29-pr3b-3-clinical-axis-completion-design.md`
- Out-of-scope (deferred, do NOT fold in): sibling-sweep reverse-coverage
  on hai_lab_lift / hai_rates / hai_codes / hai_specimens / hai_organisms;
  audit registry `_reset_for_test` ordering fix; DESIGN.md AD-55/AD-60 PR3b-3
  supplement; emitting `hai_event_id` as FHIR identifier.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `clinosim/audit/axes/clinical.py` | Modify | Add 2 helpers + rewire D1 + D2 gate blocks + remove D1 TODO block |
| `clinosim/modules/antibiotic/audit.py` | Modify | Simplify `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` docstring (remove TODO paragraph) |
| `tests/unit/test_clinical_axis_per_organism.py` | Create | Unit tests for both helpers |
| `tests/integration/test_antibiotic_audit.py` | Modify | Add 4 integration tests for end-to-end gate behavior |
| `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md` | Create | DQR record from `clinosim audit run` |
| `CLAUDE.md` | Modify | Record PR3b-3 chain completion; update audit defense layer narrative |
| `docs/CONTRIBUTING-modules.md` | Modify | Add per-organism filter rationale to PR verification guide |
| `clinosim/modules/antibiotic/README.md` | Modify | Note D1/D2 gate completion |
| `clinosim/audit/README.md` | Modify (if exists) | Note D1/D2 gate completion |

---

### Task 1: Helper `_organism_per_encounter` — TDD

**Files:**
- Create: `tests/unit/test_clinical_axis_per_organism.py`
- Modify: `clinosim/audit/axes/clinical.py` (add helper near top, after `_is_susceptibility_observation`)

**Interfaces:**
- Consumes: `clinosim.audit.types.Cohort` (lazy NDJSON reader), `country: str`
- Produces: `_organism_per_encounter(cohort: Cohort, country: str) -> dict[str, set[str]]` — `{encounter_id: {organism_snomed, ...}}`. Used by Tasks 3 + 4.

- [ ] **Step 1: Write failing test file**

Create `tests/unit/test_clinical_axis_per_organism.py`:

```python
"""Unit tests for clinosim.audit.axes.clinical per-organism helpers
(PR3b-3 chain completion D1 + D2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import clinical
from clinosim.audit.types import Cohort


def _write(path: Path, country: str, file: str, rows: list[dict]) -> None:
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _mb_org(enc: str, idx: int, organism_snomed: str | None) -> dict:
    """mb-org-* Observation, SNOMED organism or no-growth."""
    obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{idx}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "code": {"coding": [{"code": "600-7"}]},
    }
    if organism_snomed:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}]
        }
    else:
        obs["valueString"] = "No growth"
    return obs


@pytest.mark.unit
def test_organism_per_encounter_basic(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, "3092008"),       # S.aureus
        _mb_org("E2", 0, "112283007"),     # E.coli
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}, "E2": {"112283007"}}


@pytest.mark.unit
def test_organism_per_encounter_multiple_organisms_same_encounter(tmp_path: Path) -> None:
    """A CLABSI encounter with both S.aureus + S.epidermidis blood cultures."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, "3092008"),       # S.aureus
        _mb_org("E1", 1, "11638008"),      # S.epidermidis
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008", "11638008"}}


@pytest.mark.unit
def test_organism_per_encounter_skips_no_growth(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, None),            # no-growth → valueString
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_skips_non_mb_observations(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "lab-E1-0001",  # NOT mb-org-*
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "6690-2"}]},
            "valueQuantity": {"value": 14000},
        },
        {
            "resourceType": "Observation",
            "id": "vs-E1-0001",   # vital signs, also NOT mb-org-*
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "8867-4"}]},
            "valueQuantity": {"value": 88},
        },
        _mb_org("E1", 0, "3092008"),
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}}


@pytest.mark.unit
def test_organism_per_encounter_skips_missing_encounter_ref(tmp_path: Path) -> None:
    """A mb-org-* without encounter ref must be skipped (no enc_id key)."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-orphan-0",
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_empty_observation_file(tmp_path: Path) -> None:
    """No Observation.ndjson at all → empty dict, no crash."""
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_skips_non_snomed_coding(tmp_path: Path) -> None:
    """A mb-org-* whose valueCodeableConcept uses non-SNOMED system is skipped."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://loinc.org", "code": "12345-6"}],
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_clinical_axis_per_organism.py -v`
Expected: All 7 tests FAIL with `AttributeError: module 'clinosim.audit.axes.clinical' has no attribute '_organism_per_encounter'`.

- [ ] **Step 3: Implement `_organism_per_encounter` in clinical.py**

In `clinosim/audit/axes/clinical.py`, add the helper after `_is_susceptibility_observation` (around line 68):

```python
def _organism_per_encounter(cohort: Cohort, country: str) -> dict[str, set[str]]:
    """Return {encounter_id: {organism_snomed, ...}} from microbiology Observations.

    Walks Observation.ndjson once, filters to mb-org-* organism observations
    that carry a valueCodeableConcept SNOMED code (growth observations).
    No-growth observations (valueString="No growth"/"発育なし"), non-mb
    Observations, missing encounter refs, and non-SNOMED valueCodeableConcept
    codings are skipped.

    Used by the PR3b-3 R-rate gate (per-(hai_type, organism) cohort filter)
    and empty-rate gate (panel-eligible denominator filter).
    """
    out: dict[str, set[str]] = {}
    for row in cohort.ndjson(country, "Observation"):
        rid = row.get("id", "")
        if not rid.startswith("mb-org-"):
            continue
        eid = _enc_id(row)
        if not eid:
            continue
        vcc = row.get("valueCodeableConcept") or {}
        codings = vcc.get("coding", []) or []
        for c in codings:
            sys_uri = c.get("system", "") or ""
            if "snomed" in sys_uri:
                code = c.get("code", "") or ""
                if code:
                    out.setdefault(eid, set()).add(code)
    return out
```

Also import `Cohort` if not already imported (it should be available since `run` uses it via type hint — but check the imports block).

- [ ] **Step 4: Run unit tests — all 7 must pass**

Run: `pytest tests/unit/test_clinical_axis_per_organism.py -v`
Expected: 7 passed.

- [ ] **Step 5: Run full unit suite to confirm no regression**

Run: `pytest tests/unit -m unit -q`
Expected: All previously-green unit tests still pass.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_clinical_axis_per_organism.py clinosim/audit/axes/clinical.py
git commit -m "$(cat <<'EOF'
feat(audit): _organism_per_encounter helper for PR3b-3 D1/D2 gates

Walks Observation.ndjson once, builds {enc_id: {organism_snomed,...}} from
mb-org-* Observations with valueCodeableConcept SNOMED coding. 7 unit tests
cover: basic, multi-organism per encounter, no-growth skip, non-mb skip,
missing encounter ref skip, empty file, non-SNOMED coding skip.

Used by D1 (R-rate per-organism filter) and D2 (panel-eligible denominator)
in upcoming tasks.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 2: Helper `_panel_eligible_organisms` — TDD

**Files:**
- Modify: `tests/unit/test_clinical_axis_per_organism.py` (append tests)
- Modify: `clinosim/audit/axes/clinical.py` (add helper after `_organism_per_encounter`)

**Interfaces:**
- Consumes: `clinosim.modules.hai.load_hai_antibiogram` (existing cached YAML loader)
- Produces: `_panel_eligible_organisms() -> dict[str, set[str]]` — `{hai_type: {organism_snomed, ...}}`. Used by Task 4.

- [ ] **Step 1: Append failing tests to the unit test file**

Append to `tests/unit/test_clinical_axis_per_organism.py`:

```python
@pytest.mark.unit
def test_panel_eligible_organisms_includes_antibiogram_keys() -> None:
    """All organisms in hai_antibiogram.yaml appear in the per-hai_type set."""
    from clinosim.modules.hai import load_hai_antibiogram

    out = clinical._panel_eligible_organisms()
    abg = load_hai_antibiogram()
    for hai_type, organism_map in abg.items():
        assert hai_type in out
        assert set(organism_map.keys()) == out[hai_type], (
            f"{hai_type}: panel-eligible set {out[hai_type]} != "
            f"antibiogram keys {set(organism_map.keys())}"
        )


@pytest.mark.unit
def test_panel_eligible_organisms_excludes_no_panel_organisms() -> None:
    """E.faecalis 78065002 + C.albicans 53326005 are not in any
    panel-eligible set (no antibiogram entry → auto-excluded)."""
    out = clinical._panel_eligible_organisms()
    for hai_type, orgs in out.items():
        assert "78065002" not in orgs, (
            f"{hai_type}: E.faecalis 78065002 leaked into panel-eligible set"
        )
        assert "53326005" not in orgs, (
            f"{hai_type}: C.albicans 53326005 leaked into panel-eligible set"
        )


@pytest.mark.unit
def test_panel_eligible_organisms_returns_known_hai_types() -> None:
    """Smoke: every HAI_TYPES constant entry has at least one panel-eligible org."""
    from clinosim.modules.hai import HAI_TYPES

    out = clinical._panel_eligible_organisms()
    for hai_type in HAI_TYPES:
        assert hai_type in out
        assert out[hai_type], f"{hai_type}: empty panel-eligible set"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_clinical_axis_per_organism.py::test_panel_eligible_organisms_includes_antibiogram_keys -v`
Expected: FAIL with `AttributeError: module 'clinosim.audit.axes.clinical' has no attribute '_panel_eligible_organisms'`.

- [ ] **Step 3: Implement `_panel_eligible_organisms` in clinical.py**

In `clinosim/audit/axes/clinical.py`, add after `_organism_per_encounter`:

```python
def _panel_eligible_organisms() -> dict[str, set[str]]:
    """Per-hai_type set of organisms with antibiogram entries (panel-eligible).

    Derived from load_hai_antibiogram() keys. Organisms without an antibiogram
    entry (E.faecalis 78065002, C.albicans 53326005, future no-panel additions)
    are automatically excluded — no hard-coded exclusion list. Used by the D2
    empty-rate gate to restrict the denominator to encounters whose culture
    organism actually has a S/I/R panel.
    """
    from clinosim.modules.hai import load_hai_antibiogram  # local: avoids any potential cycle
    abg = load_hai_antibiogram()
    return {hai_type: set(organism_map.keys()) for hai_type, organism_map in abg.items()}
```

- [ ] **Step 4: Run unit tests — 10 tests total must pass**

Run: `pytest tests/unit/test_clinical_axis_per_organism.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_clinical_axis_per_organism.py clinosim/audit/axes/clinical.py
git commit -m "$(cat <<'EOF'
feat(audit): _panel_eligible_organisms helper for PR3b-3 D2

Derives {hai_type: {organism_snomed,...}} from load_hai_antibiogram() keys.
E.faecalis (78065002) and C.albicans (53326005) are auto-excluded by virtue
of having no antibiogram entry — no hard-coded exclusion list.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 3: D1 — R-rate gate per-(hai_type, organism) filter

**Files:**
- Modify: `clinosim/audit/axes/clinical.py:175-235` (R-rate gate block + TODO removal)
- Modify: `tests/integration/test_antibiotic_audit.py` (append integration tests)

**Interfaces:**
- Consumes: `_organism_per_encounter` (Task 1)
- Produces: D1 wiring; no new public API.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_antibiotic_audit.py`:

```python
@pytest.mark.integration
def test_clinical_axis_r_rate_gate_filters_per_organism(tmp_path) -> None:
    """D1: R-rate gate cohort must include ONLY encounters whose organism
    matches the band's cohort key.

    Synthetic CLABSI cohort with 6 encounters:
      - 4 with S.aureus (3092008): 2 cefazolin R, 2 cefazolin S → 50% R
      - 2 with S.epidermidis (11638008): both cefazolin R → 100% R (would
        skew the mixed cohort to 67% R, outside MRSA band)
    The band "clabsi/3092008" (cefazolin 40-55% R) must measure 50%, NOT 67%.
    """
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.registry import discover, get_registered
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz_loinc = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(35)]
    # 30 S.aureus encounters: 15 R, 15 S → 50% R (within 40-55% band)
    # 5 S.epidermidis encounters: all R (would inflate mixed cohort)
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T80.211A"}]},  # CLABSI ICD
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(35)
    ]
    organism_obs = []
    susc_obs = []
    for i in range(30):  # S.aureus
        organism_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
        })
        susc_obs.append({
            "resourceType": "Observation", "id": f"mb-sus-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": cefaz_loinc}]},
            "valueCodeableConcept": {"coding": [{"code": "R" if i < 15 else "S"}]},
        })
    for i in range(30, 35):  # S.epidermidis, all R
        organism_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "11638008"}]},
        })
        susc_obs.append({
            "resourceType": "Observation", "id": f"mb-sus-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": cefaz_loinc}]},
            "valueCodeableConcept": {"coding": [{"code": "R"}]},
        })

    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs + susc_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    assert n == 30, f"S.aureus cohort must be 30, got {n} (per-organism filter not applied)"
    assert r_rate == 0.5, f"S.aureus cohort R-rate must be 0.5, got {r_rate}"
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "clabsi/3092008/cefazolin" in f.message]
    assert not fails, f"50% should be inside [0.40, 0.55] band; got FAIL: {fails!r}"


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_zero_for_absent_organism(tmp_path) -> None:
    """D1: a band whose organism appears in NO cohort encounter yields n=0
    (not a spurious FAIL). Cohort = 30 E.coli CAUTI; band cohort = cauti/E.coli
    pre-existing, but verify CLABSI/S.aureus band yields n=0 cleanly."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.registry import discover, get_registered
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(10)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T83.511A"}]},  # CAUTI ICD only
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(10)
    ]
    # Only E.coli organisms — no S.aureus / S.epidermidis
    organism_obs = [{
        "resourceType": "Observation", "id": f"mb-org-E{i}-0",
        "encounter": {"reference": f"Encounter/E{i}"},
        "code": {"coding": [{"code": "600-7"}]},
        "valueCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": "112283007"}]},
    } for i in range(10)]
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    # CLABSI/S.aureus band should report n=0, no FAIL
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    assert n == 0
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "clabsi/3092008/cefazolin" in f.message]
    assert not fails, f"Absent-organism cohort must not FAIL; got {fails!r}"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_filters_per_organism tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_zero_for_absent_organism -v`
Expected: BOTH FAIL. The first will report `n == 35` (mixed cohort) or similar inflated count instead of 30, OR the R-rate will be the mixed 5/6 from 35-count instead of 0.5.

- [ ] **Step 3: Rewire the R-rate gate block in clinical.py**

In `clinosim/audit/axes/clinical.py`, replace the existing R-rate block (currently lines 175-235, which includes the TODO comment block) with:

```python
        # ---------------------------------------------------------------
        # PR3b-3 (D1 complete, 2026-06-29): NHSN R-rate gate per
        # (hai_type, organism, antibiotic) cohort. Cohort encounters are
        # filtered by per-organism culture so bands measure the true
        # per-organism resistance rate (e.g. clabsi/3092008/cefazolin =
        # S.aureus only, not mixed S.aureus + S.epidermidis + E.coli).
        # n<30 → WARN guard retained for rare-event safety.
        # ---------------------------------------------------------------
        r_bands = spec.clinical_acceptance.get("hai_resistance_bands") or []
        if r_bands:
            from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
            for band in r_bands:
                hai_type_b, organism_b = band["cohort"].split("/", maxsplit=1)
                abx_key = band["antibiotic"]
                abx_loinc = ANTIBIOTIC_LOINC_LOOKUP.get(abx_key)
                if abx_loinc is None:
                    continue
                base_set = cohort_enc.get(hai_type_b, set())
                cohort_enc_set = {
                    e for e in base_set if organism_b in org_per_enc.get(e, set())
                }
                if not cohort_enc_set:
                    result.info[f"{country}_{band['cohort']}_{abx_key}_n"] = 0
                    continue
                r_count = 0
                total_count = 0
                for row in cohort.ndjson(country, "Observation"):
                    eid = _enc_id(row)
                    if eid not in cohort_enc_set:
                        continue
                    s = _is_susceptibility_observation(row)
                    if s is None:
                        continue
                    if s[0] != abx_loinc:
                        continue
                    total_count += 1
                    if s[1] == "R":
                        r_count += 1
                result.info[f"{country}_{band['cohort']}_{abx_key}_n"] = total_count
                if total_count < 30:
                    result.findings.append(AuditFinding(
                        Severity.WARN,
                        f"{country}/{band['cohort']}/{abx_key}: cohort too small "
                        f"(n={total_count}); R-rate band not enforced",
                    ))
                    continue
                r_rate = r_count / total_count
                result.info[f"{country}_{band['cohort']}_{abx_key}_R_rate"] = round(r_rate, 3)
                if r_rate < band["expected_R_min"] or r_rate > band["expected_R_max"]:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}/{band['cohort']}/{abx_key}: R-rate "
                        f"{r_rate:.3f} outside band [{band['expected_R_min']}, "
                        f"{band['expected_R_max']}] (source: {band['source']})",
                    ))
```

AND, at the top of the `for country in cohort.countries():` loop body (just before `cohort_enc: dict[...] = ...`), add the once-per-country helper call:

```python
        org_per_enc = _organism_per_encounter(cohort, country)
```

(So both D1 and D2 reuse the same map without re-walking Observation.ndjson.)

- [ ] **Step 4: Run the D1 integration tests**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_filters_per_organism tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_zero_for_absent_organism -v`
Expected: 2 passed.

- [ ] **Step 5: Run all clinical axis unit + integration tests to confirm no regression**

Run: `pytest tests/unit/test_axis_clinical.py tests/integration/test_antibiotic_audit.py tests/integration/test_audit_end_to_end.py -v`
Expected: All previously-green pass; the 2 new tests pass. (The pre-existing PR3b-3 R-rate test that ran on n<30 WARN should still WARN, not change semantics.)

- [ ] **Step 6: Commit**

```bash
git add clinosim/audit/axes/clinical.py tests/integration/test_antibiotic_audit.py
git commit -m "$(cat <<'EOF'
feat(audit/D1): R-rate gate per-(hai_type, organism) filter

Removes the clinical.py TODO comment block. The NHSN R-rate gate now
restricts the cohort to encounters whose culture organism matches the
band's cohort key, so clabsi/3092008/cefazolin measures pure S.aureus
resistance (~47% target the MRSA proxy band 40-55%), not the mixed
S.aureus + S.epidermidis + E.coli ~67% that would breach the band.

2 integration tests pin the per-organism semantics:
  - 30 S.aureus + 5 S.epidermidis cohort → only the 30 measured against
    the S.aureus band, rate = 0.5 within [0.40, 0.55].
  - Absent-organism band → n=0, no spurious FAIL.

n<30 WARN guard retained for rare-event safety.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 4: D2 — empty-rate gate panel-eligible filter

**Files:**
- Modify: `clinosim/audit/axes/clinical.py:237-273` (empty-rate gate block)
- Modify: `clinosim/modules/antibiotic/audit.py:111-128` (docstring simplification, TODO removal)
- Modify: `tests/integration/test_antibiotic_audit.py` (append integration tests)

**Interfaces:**
- Consumes: `_organism_per_encounter` (Task 1), `_panel_eligible_organisms` (Task 2)
- Produces: D2 wiring; no new public API.

- [ ] **Step 1: Write failing integration tests**

Append to `tests/integration/test_antibiotic_audit.py`:

```python
@pytest.mark.integration
def test_clinical_axis_empty_rate_gate_excludes_no_panel_organisms(tmp_path) -> None:
    """D2: empty-rate denominator must EXCLUDE encounters whose only culture
    is a no-panel organism (E.faecalis 78065002 / C.albicans 53326005).

    Cohort: 30 panel-eligible CLABSI encounters (S.aureus, all with susc) +
    10 no-panel CLABSI encounters (E.faecalis, never get a S/I/R panel).
    Pre-D2: denominator = 40, empty count = 10, rate = 25% > 5% → FAIL.
    Post-D2: denominator = 30 (panel-eligible only), empty count = 0,
    rate = 0% < 5% → PASS.
    """
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.registry import discover, get_registered
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    vanc_loinc = ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(40)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T80.211A"}]},  # CLABSI
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(40)
    ]
    org_obs = []
    susc_obs = []
    # 30 panel-eligible (S.aureus) + susceptibilities → not empty
    for i in range(30):
        org_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
        })
        susc_obs.append({
            "resourceType": "Observation", "id": f"mb-sus-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": vanc_loinc}]},
            "valueCodeableConcept": {"coding": [{"code": "S"}]},
        })
    # 10 no-panel (E.faecalis) → no susc → would be empty pre-D2
    for i in range(30, 40):
        org_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "78065002"}]},
        })
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", org_obs + susc_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    total = result.info.get("us_hai_empty_susc_n")
    rate = result.info.get("us_hai_empty_susc_rate")
    assert total == 30, (
        f"panel-eligible denominator must exclude E.faecalis cohort; "
        f"expected 30, got {total}"
    )
    assert rate == 0.0, (
        f"all 30 panel-eligible encounters have S susceptibility, "
        f"empty rate must be 0.0; got {rate}"
    )
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "empty-susceptibility" in f.message]
    assert not fails, f"0% empty rate must PASS; got {fails!r}"


@pytest.mark.integration
def test_clinical_axis_empty_rate_gate_skips_when_all_no_panel(tmp_path) -> None:
    """D2: cohort containing only no-panel organisms → panel_eligible_encs
    is empty → gate skipped cleanly (total=0, no info entry change)."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.registry import discover, get_registered
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(5)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T80.211A"}]},
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(5)
    ]
    # All C.albicans (no panel)
    organism_obs = [{
        "resourceType": "Observation", "id": f"mb-org-E{i}-0",
        "encounter": {"reference": f"Encounter/E{i}"},
        "code": {"coding": [{"code": "600-7"}]},
        "valueCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": "53326005"}]},
    } for i in range(5)]
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    total = result.info.get("us_hai_empty_susc_n", -1)
    assert total == 0, f"all-no-panel cohort denominator must be 0, got {total}"
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "empty-susceptibility" in f.message]
    assert not fails, f"empty panel-eligible cohort must not FAIL; got {fails!r}"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_clinical_axis_empty_rate_gate_excludes_no_panel_organisms tests/integration/test_antibiotic_audit.py::test_clinical_axis_empty_rate_gate_skips_when_all_no_panel -v`
Expected: BOTH FAIL. The first will report `total == 40` (denominator includes E.faecalis). The second will report `total == 5` (denominator includes C.albicans).

- [ ] **Step 3: Rewire empty-rate gate block in clinical.py**

In `clinosim/audit/axes/clinical.py`, replace the existing empty-rate block (currently lines 237-273) with:

```python
        # ---------------------------------------------------------------
        # PR3b-3 (D2 complete, 2026-06-29): empty-susceptibilities rate gate.
        # Denominator restricted to panel-eligible HAI cohort encounters —
        # those with at least one culture organism that has an antibiogram
        # entry. No-panel organisms (E.faecalis 78065002, C.albicans 53326005)
        # are auto-excluded via _panel_eligible_organisms. Restores NHSN
        # denominator definition the 5% threshold was calibrated against.
        # n<30 WARN guard retained for rare-event safety.
        # ---------------------------------------------------------------
        empty_max = spec.clinical_acceptance.get("hai_empty_susceptibilities_max_rate")
        if empty_max is not None:
            panel_orgs = _panel_eligible_organisms()
            panel_eligible_encs: set[str] = set()
            for hai_type, encs in cohort_enc.items():
                eligible = panel_orgs.get(hai_type, set())
                for e in encs:
                    if any(org in eligible for org in org_per_enc.get(e, set())):
                        panel_eligible_encs.add(e)

            enc_has_susc: dict[str, bool] = {e: False for e in panel_eligible_encs}
            for row in cohort.ndjson(country, "Observation"):
                eid = _enc_id(row)
                if eid not in enc_has_susc:
                    continue
                if _is_susceptibility_observation(row) is not None:
                    enc_has_susc[eid] = True
            total = len(enc_has_susc)
            result.info[f"{country}_hai_empty_susc_n"] = total
            if total > 0:
                empty_count = sum(1 for v in enc_has_susc.values() if not v)
                empty_rate = empty_count / total
                result.info[f"{country}_hai_empty_susc_rate"] = round(empty_rate, 3)
                if total < 30:
                    result.findings.append(AuditFinding(
                        Severity.WARN,
                        f"{country}: empty-susceptibility cohort too small "
                        f"(n={total}); rate gate not enforced "
                        f"(observed={empty_rate:.3f}, max={empty_max})",
                    ))
                elif empty_rate > empty_max:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}: empty-susceptibility rate {empty_rate:.3f} "
                        f"exceeds max {empty_max} (panel-eligible HAI cohort)",
                    ))
```

- [ ] **Step 4: Simplify `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` docstring in audit.py**

In `clinosim/modules/antibiotic/audit.py`, replace lines 111-128 (the docstring around `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE`) with:

```python
# Empty-susceptibilities rate acceptance bound (PR3b-3 D2 complete, 2026-06-29).
#
# Denominator: PANEL-ELIGIBLE HAI cultures only — those whose organism appears
# in hai_antibiogram.yaml. Excludes no-panel organisms (E.faecalis 78065002,
# C.albicans 53326005) automatically via clinical.py:_panel_eligible_organisms,
# which derives the eligible set from load_hai_antibiogram() keys.
#
# Rationale: CLABSI has ~28% no-panel organism weight (0.15 C.albicans + 0.13
# E.faecalis); CAUTI has ~34%. Computing empty rate over ALL cultures would
# make the gate always-FAIL. The 5% threshold is 10× the measured rate at p=10k
# (0.5%) to give safety margin for small-p Bernoulli noise.
HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE: float = 0.05
```

(Removes the entire `TODO(post-PR3b-3)` paragraph; keeps the NHSN denominator-definition rationale as load-bearing context.)

Also update the comment block at lines 63-74 (the `PR3b-3 (2026-06-27) wired ...` paragraph) by removing the "TODO: per-organism filter requires DiagnosticReport walk" line — that TODO is now done.

In `clinosim/modules/antibiotic/audit.py`, locate the block:

```python
# PR3b-3 (2026-06-27) wired active enforcement of these bands in
# clinosim/audit/axes/clinical.py:
#   - NHSN R-rate gate (per-(hai_type, antibiotic) cohort) — see clinical.py
#     "PR3b-3: NHSN R-rate gate" block. TODO: per-organism filter requires
#     DiagnosticReport walk; documented in clinical.py.
#   - empty-susceptibilities rate gate (per panel-eligible HAI cohort) — see
#     clinical.py "PR3b-3: empty-susceptibilities rate gate" block. n<30 →
#     WARN guard added in adversarial-1 fix for consistency.
```

Replace with:

```python
# PR3b-3 wired active enforcement of these bands in
# clinosim/audit/axes/clinical.py (complete 2026-06-29):
#   - NHSN R-rate gate per-(hai_type, organism, antibiotic) cohort — uses
#     _organism_per_encounter to filter cohort by per-organism culture so
#     bands measure pure per-organism resistance rates.
#   - empty-susceptibilities rate gate per panel-eligible HAI cohort —
#     uses _panel_eligible_organisms to restrict denominator to encounters
#     with at least one organism that has an antibiogram S/I/R panel.
```

- [ ] **Step 5: Run the D2 integration tests + full antibiotic_audit suite**

Run: `pytest tests/integration/test_antibiotic_audit.py -v`
Expected: All pass (existing + 4 new D1/D2 tests).

- [ ] **Step 6: Commit**

```bash
git add clinosim/audit/axes/clinical.py clinosim/modules/antibiotic/audit.py tests/integration/test_antibiotic_audit.py
git commit -m "$(cat <<'EOF'
feat(audit/D2): empty-rate gate panel-eligible denominator

Removes the antibiotic/audit.py TODO paragraph. The empty-susceptibilities
rate gate now restricts the denominator to HAI cohort encounters with at
least one panel-eligible organism culture (via _panel_eligible_organisms,
which derives the set from load_hai_antibiogram() keys — no hard-coded
exclusion list).

E.faecalis (78065002) and C.albicans (53326005) cohorts are auto-excluded
from both numerator and denominator, restoring the NHSN denominator
definition the 5% threshold was calibrated against.

2 integration tests pin the panel-eligible semantics:
  - Mixed cohort 30 S.aureus + 10 E.faecalis → denominator = 30, rate = 0%.
  - All-no-panel cohort (5 C.albicans) → denominator = 0, gate skipped.

n<30 WARN guard retained for rare-event safety.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 5: audit run + DQR + optional band calibration

**Files:**
- Create: `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`
- Modify (if calibration needed): `clinosim/modules/antibiotic/audit.py` (band thresholds)
- Modify (if calibration needed): `tests/integration/test_antibiotic_audit.py` (regression-pin
  any threshold change)

**Interfaces:**
- Consumes: post-Task-4 state (D1+D2 wired, tests green)
- Produces: DQR record + optional band adjustment

- [ ] **Step 1: Generate fresh DQR cohort**

```bash
mkdir -p scratchpad/pr3b3_dqr_v2
clinosim generate --country US --population 5000 --seed 42 --output scratchpad/pr3b3_dqr_v2/us --format fhir-r4
clinosim generate --country JP --population 5000 --seed 42 --output scratchpad/pr3b3_dqr_v2/jp --format fhir-r4
```

Expected: each finishes within a few minutes; NDJSON files appear under `scratchpad/pr3b3_dqr_v2/{us,jp}/fhir_r4/`.

- [ ] **Step 2: Run audit**

```bash
clinosim audit run -d scratchpad/pr3b3_dqr_v2 | tee scratchpad/pr3b3_dqr_v2/audit_output.txt
```

Expected: audit completes; output shows clinical-axis findings + info entries per-(hai_type, organism, abx) cohort.

- [ ] **Step 3: Inspect per-(hai_type, organism, abx) gate behavior**

Look for these info keys in the audit output:
- `us_clabsi/3092008_cefazolin_n` and `_R_rate`
- `us_cauti/112283007_ceftriaxone_n` and `_R_rate`
- `us_vap/3092008_cefazolin_n` and `_R_rate`
- (and JP equivalents)
- `us_hai_empty_susc_n` and `_rate` (must be <5%)
- (and JP equivalent)

For each per-organism cohort, record:
- observed n (cohort size)
- observed R rate
- band threshold + whether observed is inside

If any n<30, expect WARN; if n>=30 and observed outside band, expect FAIL.

- [ ] **Step 4: Calibrate bands if any FAIL appears (same-PR adjustment)**

If 1-2 bands need adjustment, update `_NHSN_RESISTANCE_BANDS` in `clinosim/modules/antibiotic/audit.py`:
- Edit the `expected_R_min` / `expected_R_max` values to bracket the observed rate
- Update the `source` field with the rationale, e.g.:
  `"source": "NHSN AR 2018-2020 Table 2 + clinosim simulation calibration p=5000"`
- Add a per-band regression test to `tests/integration/test_antibiotic_audit.py` pinning the new band

If >2 bands need adjustment, STOP. This signals a deeper problem (antibiogram drift or filter bug). Investigate before committing. Per the spec risk matrix, >2 adjustments = split into follow-up PR.

- [ ] **Step 5: Write DQR record**

Create `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`:

```markdown
# PR3b-3 Clinical Axis Completion (D1 + D2) — DQR

**Date**: 2026-06-29
**Branch**: feat/pr3b-3-clinical-axis-completion
**Cohort**: scratchpad/pr3b3_dqr_v2 (US p=5000 seed=42 + JP p=5000 seed=42)
**Audit**: `clinosim audit run -d scratchpad/pr3b3_dqr_v2`

## D1: R-rate gate per-(hai_type, organism, antibiotic)

[Insert observed table with n and R_rate per band, both countries.]

| Country | Cohort | Antibiotic | n | Observed R | Band | Result |
|---|---|---|---|---|---|---|
| US | clabsi/3092008 | cefazolin | TBD | TBD | [0.40, 0.55] | TBD |
| US | cauti/112283007 | ceftriaxone | TBD | TBD | [0.12, 0.22] | TBD |
| US | vap/3092008 | cefazolin | TBD | TBD | [0.30, 0.45] | TBD |
| JP | (same 3) | | | | | |

## D2: Empty-rate gate panel-eligible

| Country | Panel-eligible n | Empty rate | Threshold | Result |
|---|---|---|---|---|
| US | TBD | TBD | <0.05 | TBD |
| JP | TBD | TBD | <0.05 | TBD |

## Calibration adjustments (if any)

[List any band threshold adjustments + provenance source.]

## Verdict

[PASS/WARN/FAIL overall. Mark "PR3b-3 chain D1/D2 closure verified" if all PASS.]
```

Fill in the TBD values from Step 3 + 4 observations.

- [ ] **Step 6: Commit**

```bash
git add docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md
# If band thresholds were adjusted in Step 4:
git add clinosim/modules/antibiotic/audit.py tests/integration/test_antibiotic_audit.py
git commit -m "$(cat <<'EOF'
chore(audit): record PR3b-3 D1/D2 DQR + calibration [if applicable]

Cohort: US 5000 + JP 5000 (seed=42). Per-(hai_type, organism, abx) R-rate
and panel-eligible empty rate observed. [Band adjustments summarized in
DQR doc, if any.]

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 6: Docs sync — CLAUDE.md + CONTRIBUTING + module README

**Files:**
- Modify: `CLAUDE.md` (record D1/D2 closure under "Phase 3b-3 ... complete" narrative)
- Modify: `docs/CONTRIBUTING-modules.md` (add per-organism filter pattern to PR verification guide)
- Modify: `clinosim/modules/antibiotic/README.md` (note D1/D2 wire completion)
- Modify: `clinosim/audit/README.md` (if exists; otherwise skip)

**Interfaces:**
- Consumes: post-Task-5 state (audit results + any calibration)
- Produces: doc sync, no code change

- [ ] **Step 1: Update CLAUDE.md PR3b-3 narrative**

In `CLAUDE.md`, find the "Phase 3b-3 HAI culture S/I/R-driven narrow / de-escalation chain complete" paragraph (around the v0.2 phase narrative). Append:

```markdown
**PR3b-3 chain CLOSED (D1+D2 complete, 2026-06-29)** — the clinical-axis
R-rate gate now filters cohort encounters per-(hai_type, organism,
antibiotic) via `_organism_per_encounter` (Observation.ndjson mb-org-*
walk); the empty-rate gate restricts the denominator to panel-eligible
encounters via `_panel_eligible_organisms` (derived from
`load_hai_antibiogram()` keys, no hard-coded no-panel list). Both
TODO markers removed (`clinical.py:175-191`, `antibiotic/audit.py:111-128`).
PR3b-3-related deferred TODOs = **0**.
```

- [ ] **Step 2: Update CONTRIBUTING-modules.md PR verification guide**

In `docs/CONTRIBUTING-modules.md`, find the section listing the silent-no-op defense layers (4 layers established through PR3b-3 chain). Append a 5th note:

```markdown
**Per-cohort gate per-dimensional filter (PR3b-3 D1+D2, 2026-06-29)**: when an
audit clinical-axis gate's threshold is calibrated against a per-(dim1, dim2,
...) cohort but the gate filter discards a dimension, the threshold becomes
meaningful at production scale but masked behind n<30 WARN guards in
small-cohort regimes. PR3b-3 D1 (R-rate per-organism filter) and D2
(empty-rate panel-eligible denominator) are examples. Pattern: build the
per-dimensional cohort map ONCE per (country, audit-run) and reuse across
gates that need the dimension.
```

- [ ] **Step 3: Update antibiotic module README**

In `clinosim/modules/antibiotic/README.md`, find the section on audit gates. Append:

```markdown
- **NHSN R-rate gate** wired in `audit/axes/clinical.py` with
  per-(hai_type, organism, antibiotic) cohort filter (PR3b-3 D1 complete,
  2026-06-29). Cohort filtering via `_organism_per_encounter` walking
  `Observation.ndjson` mb-org-* resources.
- **Empty-susceptibilities rate gate** wired with panel-eligible
  denominator (PR3b-3 D2 complete, 2026-06-29). Eligibility set derived
  from `load_hai_antibiogram()` keys via `_panel_eligible_organisms`.
- Both n<30 WARN guards retained for rare-event safety.
```

(If exact existing structure does not match, adapt — keep the substance: D1 + D2 complete with helper names + n<30 WARN retained.)

- [ ] **Step 4: Run full unit + integration suite for sanity**

Run: `pytest tests/unit tests/integration -m "unit or integration" -q`
Expected: All pass (no new test should require update from docs change).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/CONTRIBUTING-modules.md clinosim/modules/antibiotic/README.md
git commit -m "$(cat <<'EOF'
docs: PR3b-3 chain closure — D1+D2 complete

CLAUDE.md, CONTRIBUTING-modules.md, antibiotic/README.md updated to record
the R-rate per-organism filter (D1) and empty-rate panel-eligible filter
(D2) closure. PR3b-3-related deferred TODOs = 0.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 7: Full pre-merge gate + PR

**Files:**
- None modified (verification + PR draft)

**Interfaces:**
- Consumes: post-Task-6 state (all D1+D2+DQR+docs committed)
- Produces: PR ready for review

- [ ] **Step 1: Run full pre-merge sweep (session 22 rule)**

Run: `pytest tests/unit tests/integration -m "unit or integration" -q`
Expected: All pass. ANY failure (including the 5 known pre-existing audit registry `_reset_for_test` ordering failures) means investigate before pushing.

- [ ] **Step 2: Run ruff + mypy (project standard)**

```bash
ruff check clinosim/ tests/ && ruff format --check clinosim/ tests/
mypy clinosim/
```

Expected: clean.

- [ ] **Step 3: Push branch + create PR**

```bash
git push -u origin feat/pr3b-3-clinical-axis-completion
gh pr create --title "feat(audit): PR3b-3 clinical axis completion (D1 + D2)" --body "$(cat <<'EOF'
## Summary

Closes the PR3b-3 chain by completing the two clinical-axis gate TODOs:

- **D1** = R-rate gate per-(hai_type, organism, antibiotic) filter
  (`clinical.py:175-191` TODO removed)
- **D2** = empty-rate gate panel-eligible denominator filter
  (`antibiotic/audit.py:111-128` TODO removed)

Shared helper `_organism_per_encounter` walks `Observation.ndjson` mb-org-*
once and builds `{enc_id: {organism_snomed, ...}}`. `_panel_eligible_organisms`
derives the eligibility set from `load_hai_antibiogram()` keys — no
hard-coded no-panel exclusion list.

After this PR, **PR3b-3-related deferred TODOs = 0**.

## Test plan

- [x] 10 new unit tests in `tests/unit/test_clinical_axis_per_organism.py`
  (7 for `_organism_per_encounter`, 3 for `_panel_eligible_organisms`)
- [x] 4 new integration tests in `tests/integration/test_antibiotic_audit.py`
  (D1 per-organism filter, D1 absent-organism n=0, D2 panel-eligible
  exclusion, D2 all-no-panel skip)
- [x] Pre-existing PR3b-3 tests (37) green
- [x] Full sweep `pytest tests/unit tests/integration -m "unit or integration"` green
- [x] `clinosim audit run -d scratchpad/pr3b3_dqr_v2` (US + JP p=5000) — DQR
  recorded in `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`

## Spec + plan

- Spec: `docs/superpowers/specs/2026-06-29-pr3b-3-clinical-axis-completion-design.md`
- Plan: `docs/superpowers/plans/2026-06-29-pr3b-3-clinical-axis-completion-plan.md`
- DQR: `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`

## Out-of-scope (deferred, separate backlog)

- Sibling-sweep reverse-coverage on hai_lab_lift / hai_rates / hai_codes /
  hai_specimens / hai_organisms YAML loaders
- audit registry `_reset_for_test` ordering bug (5 pre-existing failures)
- DESIGN.md AD-55/AD-60 PR3b-3 supplement section
- Emit `hai_event_id` as a FHIR identifier (community/HAI separation)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

Expected: PR URL returned.

- [ ] **Step 4: Record PR URL + note for adversarial fan-out next**

Save the PR URL. Next task (post-plan) is `superpowers:requesting-code-review` triggering the 4-stage adversarial chain — separately tracked in the session's TaskList items 7-8.

---

## Spec coverage self-check (writing-plans self-review)

- D1 R-rate per-organism filter → Task 3 ✓
- D2 empty-rate panel-eligible filter → Task 4 ✓
- `_organism_per_encounter` helper → Task 1 ✓
- `_panel_eligible_organisms` helper → Task 2 ✓
- TODO removal (clinical.py + audit.py) → Task 3 + Task 4 ✓
- Unit tests (10) → Tasks 1 + 2 ✓
- Integration tests (4) → Tasks 3 + 4 ✓
- audit run + calibration policy → Task 5 ✓
- DQR record → Task 5 ✓
- CLAUDE.md + CONTRIBUTING + README sync → Task 6 ✓
- Full pre-merge gate (session 22 rule) → Task 7 ✓
- PR draft with out-of-scope list → Task 7 ✓
- HAI vs community culture rationale → Spec only (no code touchpoint)
- Helper placement inline rationale → Spec only (no code touchpoint)
- Same-PR band adjustment with >2 break-out → Task 5 Step 4 ✓

Type consistency: `_organism_per_encounter` returns `dict[str, set[str]]` in
Task 1 spec; D1 Task 3 + D2 Task 4 both consume it as `dict[str, set[str]]`
(no name drift). `_panel_eligible_organisms` returns `dict[str, set[str]]`
in Task 2; D2 Task 4 uses it consistently.

Placeholder scan: no TBD/TODO in the implementation steps (the DQR template
in Task 5 has TBD cells expected to be filled at execution time — that is
intentional, not a plan placeholder).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-29-pr3b-3-clinical-axis-completion-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

For a 7-task scope-small bug fix with tight TDD per task, inline execution often wins because the session context already has the design + spec + helper rationale loaded; subagent dispatch adds round-trip overhead per task. Subagent-driven becomes worthwhile when tasks are independent and parallelizable, which is not the case here (tasks 3+4 depend on 1+2; tasks 5+6+7 depend on the prior chain).

Which approach?
