# PR3b-5 Attribution Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the PR3b-3 D1 R-rate gate's encounter-level susceptibility attribution approximation (~15-20% mis-attribution at p=5000) by joining susc → specimen → organism, with HAI / community separation via a new FHIR `Observation.identifier` carrying `MicrobiologyResult.hai_event_id`.

**Architecture:** Two pure inline helpers in `clinosim/audit/axes/clinical.py` walk Observation.ndjson once each: `_organism_per_specimen` builds `{specimen_id: organism_snomed}` from mb-org-* with valueCodeableConcept SNOMED; `_hai_specimens` returns the set of specimen_ids whose mb-org-* carries a `HAI_EVENT_ID_SYSTEM` identifier. The FHIR microbiology builder (`_fhir_microbiology.py`) emits `MicrobiologyResult.hai_event_id` as `identifier` on Specimen + mb-org-* + mb-sus-* + DiagnosticReport when non-empty. D1 R-rate gate switches from encounter-level susc-cohort match to specimen-based join + HAI-only filter; D2 stays encounter-level.

**Tech Stack:** Python 3.11+, pytest (unit + integration markers), FHIR R4 (`Observation.identifier` per HL7 R4 §5.4.7), existing PR3b-3 + PR3b-2 infrastructure (`MicrobiologyResult.hai_event_id` already CIF-side; `Observation.specimen.reference` already emitted).

## Global Constraints

- Code language: Python 3.11+. Comments + docstrings: English.
- Formatter: ruff. Type checking: mypy strict.
- Line length: 100.
- Determinism (AD-16): no `random.random()` / `time.time()` / shared global RNG.
- No new YAML files. No new module package. helpers + constants go inline.
- `HAI_EVENT_ID_SYSTEM = "http://clinosim/identifier/hai-event-id"` is the canonical URI; reader + writer MUST import this exact constant (silent-no-op defense layer pattern from PR #113 C4 + PR #114 F3).
- Byte-diff invariant intentionally broken (new identifier field on HAI resources). audit run is primary gate. Community cultures (`hai_event_id == ""`) MUST remain byte-identical to pre-PR3b-5 output.
- Pre-merge gate (session 22 rule): `pytest tests/unit tests/integration -m "unit or integration"` full sweep — NOT a feature-specific subset.
- Commit trailer (every commit):
  `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7`
- Spec: `docs/superpowers/specs/2026-06-29-pr3b-5-attribution-refinement-design.md`
- Out-of-scope items (DO NOT fold in): sibling YAML sweep, PR3b-4 WBC/CRP decay, audit registry `_reset_for_test` ordering, audit Phase 2, NHSN clinical-accuracy verification, I1 WARN UX, unused MB_*_PREFIX cleanup, DESIGN.md AD-55/AD-60 extended ADR. Each gets a TODO.md formal entry in Task 7.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `clinosim/modules/output/_fhir_microbiology.py` | Modify | Add `HAI_EVENT_ID_SYSTEM` constant + emit `identifier` on 4 resource types when `hai_event_id` set |
| `clinosim/audit/axes/clinical.py` | Modify | Add 2 helpers + rewire D1 R-rate gate (susc → specimen → organism + HAI-only filter) |
| `tests/unit/test_clinical_axis_per_organism.py` | Modify | Add unit tests for `_organism_per_specimen`, `_hai_specimens`, canonical constant contract |
| `tests/integration/test_antibiotic_audit.py` | Modify | Add C1 + C2 resolution integration tests + builder-side identifier emission test |
| `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md` | Create | DQR — audit run results, C1+C2 resolution evidence, RESOLVED stamp on prior DQR cross-link |
| `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md` | Modify | Update §"Known approximation" with **RESOLVED via PR3b-5** cross-link |
| `CLAUDE.md` | Modify | Append PR3b-5 chain note under PR3b-3 supplement; update silent-no-op defense layer enumeration (now 7 layers with HAI_EVENT_ID_SYSTEM canonical) |
| `TODO.md` | Modify | Strike PR3b-5 entry; add formal out-of-scope items per the spec table |
| `docs/CONTRIBUTING-modules.md` | Modify | Add "Cross-module canonical URI constants" subsection citing HAI_EVENT_ID_SYSTEM precedent |
| `clinosim/modules/antibiotic/README.md` | Modify | Note D1 gate now per-(hai_type, organism, antibiotic) via specimen-based join |
| `clinosim/modules/hai/README.md` | Modify | Note `hai_event_id` now emitted as FHIR Observation.identifier |

---

### Task 1: `HAI_EVENT_ID_SYSTEM` canonical constant + FHIR identifier emission

**Files:**
- Modify: `clinosim/modules/output/_fhir_microbiology.py`
- Modify: `tests/integration/test_antibiotic_audit.py` (append builder-side test)

**Interfaces:**
- Consumes: existing `MicrobiologyResult.hai_event_id` (CIF field, PR3b-2)
- Produces: `HAI_EVENT_ID_SYSTEM: str = "http://clinosim/identifier/hai-event-id"` (importable by audit reader). FHIR Specimen / mb-org-*/mb-sus-* Observation / DiagnosticReport carry `identifier = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]` when `hai_event_id` non-empty; no identifier field emitted when empty.

- [ ] **Step 1: Write the failing integration test for FHIR identifier emission**

Append to `tests/integration/test_antibiotic_audit.py`:

```python
@pytest.mark.integration
def test_fhir_microbiology_emits_hai_event_id_identifier() -> None:
    """PR3b-5 Task 1: MicrobiologyResult.hai_event_id non-empty → FHIR
    Specimen / mb-org-* Observation / mb-sus-* Observation /
    DiagnosticReport all carry identifier[].system == HAI_EVENT_ID_SYSTEM
    with value == hai_event_id. Empty hai_event_id → no identifier field."""
    from clinosim.modules.output._fhir_common import BundleContext
    from clinosim.modules.output._fhir_microbiology import (
        HAI_EVENT_ID_SYSTEM,
        _bb_microbiology,
    )

    # HAI culture: hai_event_id set
    hai_mb = {
        "specimen": "blood",
        "specimen_snomed": "119297000",
        "test_loinc": "600-7",
        "collected_datetime": "2026-01-10T08:00:00",
        "reported_datetime": "2026-01-12T08:00:00",
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [
            {"antibiotic_loinc": "10-9", "interpretation": "S"},
        ],
        "hai_event_id": "hai-clabsi-E1-1",
    }
    # Community culture: hai_event_id empty
    comm_mb = {
        "specimen": "urine",
        "specimen_snomed": "122575003",
        "test_loinc": "630-4",
        "collected_datetime": "2026-01-10T08:00:00",
        "reported_datetime": "2026-01-12T08:00:00",
        "growth": True,
        "organism_snomed": "112283007",
        "susceptibilities": [],
        "hai_event_id": "",
    }
    ctx = BundleContext(
        record={"microbiology": [hai_mb, comm_mb]},
        patient_id="p1",
        primary_enc_id="E1",
        country="US",
    )
    resources = _bb_microbiology(ctx)

    # Index by id prefix for assertions
    spec_hai = [r for r in resources if r["resourceType"] == "Specimen"
                and r["id"] == "spec-E1-0"][0]
    spec_comm = [r for r in resources if r["resourceType"] == "Specimen"
                 and r["id"] == "spec-E1-1"][0]
    org_hai = [r for r in resources if r["id"] == "mb-org-E1-0"][0]
    org_comm = [r for r in resources if r["id"] == "mb-org-E1-1"][0]
    sus_hai = [r for r in resources if r["id"] == "mb-sus-E1-0-0"][0]
    dr_hai = [r for r in resources if r["id"] == "dr-mb-E1-0"][0]
    dr_comm = [r for r in resources if r["id"] == "dr-mb-E1-1"][0]

    # HAI side: identifier present, system + value correct
    for res in (spec_hai, org_hai, sus_hai, dr_hai):
        ident = res.get("identifier") or []
        assert len(ident) == 1, f"{res['id']}: expected 1 identifier, got {ident}"
        assert ident[0]["system"] == HAI_EVENT_ID_SYSTEM, (
            f"{res['id']}: identifier.system mismatch"
        )
        assert ident[0]["value"] == "hai-clabsi-E1-1", (
            f"{res['id']}: identifier.value mismatch"
        )

    # Community side: no identifier field at all (byte-identical pre-PR3b-5)
    for res in (spec_comm, org_comm, dr_comm):
        assert "identifier" not in res, (
            f"{res['id']}: community culture must NOT emit identifier "
            f"(byte-identical invariant), got {res.get('identifier')!r}"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_fhir_microbiology_emits_hai_event_id_identifier -v`
Expected: FAIL with `ImportError: cannot import name 'HAI_EVENT_ID_SYSTEM' from 'clinosim.modules.output._fhir_microbiology'`.

- [ ] **Step 3: Add constant + emission logic in `_fhir_microbiology.py`**

At the top of `clinosim/modules/output/_fhir_microbiology.py`, near the existing `MB_*_ID_PREFIX` constants, add:

```python
# Canonical URI for HAI event cross-reference identifiers (PR3b-5,
# 2026-06-29). Emitted on Specimen + mb-org-*/mb-sus-* Observation +
# DiagnosticReport when MicrobiologyResult.hai_event_id is non-empty.
# Internal-only — clinosim simulator cross-reference, not registered in
# JP Core / US Core / HL7 IGs. Audit reader (clinosim.audit.axes.clinical)
# imports this same constant; a rename here triggers ImportError downstream
# rather than a silent gate skip (same defense pattern as MB_ORG_ID_PREFIX
# and ABX_ORDER_ID_PREFIX).
HAI_EVENT_ID_SYSTEM = "http://clinosim/identifier/hai-event-id"
```

In `_bb_microbiology`, just after `base = f"..."` and before `spec_id = ...`, add:

```python
        # PR3b-5: build identifier list once per culture; empty when not HAI.
        hai_event_id = mb.get("hai_event_id", "")
        hai_identifier = (
            [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]
            if hai_event_id else []
        )
```

Then, for each of the four resources (Specimen, organism Observation, susceptibility Observation, DiagnosticReport), add an `if hai_identifier: res["identifier"] = hai_identifier` block. Concretely:

After `specimen: dict[str, Any] = {"resourceType": "Specimen", "id": spec_id, "subject": subject}`:

```python
        if hai_identifier:
            specimen["identifier"] = hai_identifier
```

After `org_obs: dict[str, Any] = {...}` (the existing org_obs dict literal), before the conditional updates:

```python
        if hai_identifier:
            org_obs["identifier"] = hai_identifier
```

Inside the `for j, sus in enumerate(...)` loop, after `sus_obs: dict[str, Any] = {...}`:

```python
            if hai_identifier:
                sus_obs["identifier"] = hai_identifier
```

After `report: dict[str, Any] = {...}` (the DR dict literal), before the conditional updates:

```python
        if hai_identifier:
            report["identifier"] = hai_identifier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_fhir_microbiology_emits_hai_event_id_identifier -v`
Expected: 1 passed.

- [ ] **Step 5: Run full PR3b-3 + adjacent integration suites to confirm no regression**

Run: `pytest tests/integration/test_antibiotic_audit.py tests/integration/test_audit_end_to_end.py tests/integration/test_clinical_pipeline.py -q`
Expected: all green. The community-culture branch (no `identifier` field) is byte-identical, so existing e2e snapshot tests pass without modification.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/output/_fhir_microbiology.py tests/integration/test_antibiotic_audit.py
git commit -m "$(cat <<'EOF'
feat(fhir/pr3b-5): emit hai_event_id as Observation/Specimen/DR identifier

Adds HAI_EVENT_ID_SYSTEM canonical URI constant + emits identifier on
the 4 microbiology FHIR resources (Specimen, mb-org-* Observation,
mb-sus-* Observation, DiagnosticReport) when
MicrobiologyResult.hai_event_id is non-empty. Community cultures
(hai_event_id == "") remain byte-identical — no identifier field
emitted.

Sets up the writer side of the PR3b-5 audit reader's HAI-only filter
(_hai_specimens helper, Task 2). HAI_EVENT_ID_SYSTEM constant is
shared between writer and reader to defend against rename silent-no-op
(same pattern as MB_ORG_ID_PREFIX + ABX_ORDER_ID_PREFIX from prior
PR3b-3 chain).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 2: `_organism_per_specimen` + `_hai_specimens` helpers — TDD

**Files:**
- Modify: `clinosim/audit/axes/clinical.py`
- Modify: `tests/unit/test_clinical_axis_per_organism.py`

**Interfaces:**
- Consumes: `Cohort`, `HAI_EVENT_ID_SYSTEM` (from Task 1), `MB_ORG_ID_PREFIX` (from PR #113), `_SNOMED_URI` (from PR #113), `_enc_id` (existing)
- Produces:
  - `_organism_per_specimen(cohort: Cohort, country: str) -> dict[str, str]` → `{specimen_id: organism_snomed}`
  - `_hai_specimens(cohort: Cohort, country: str) -> set[str]` → set of HAI-derived specimen_ids
  Used by Task 3 (D1 rewire).

- [ ] **Step 1: Write failing unit tests**

Append to `tests/unit/test_clinical_axis_per_organism.py`:

```python
# ----------------------------------------------------------------------------
# PR3b-5 specimen-based helpers
# ----------------------------------------------------------------------------


def _mb_org_with_specimen(
    enc: str, idx: int, organism_snomed: str | None,
    spec_id: str | None = None, hai_event_id: str = "",
) -> dict:
    """mb-org-* Observation with explicit specimen reference + optional HAI
    identifier. PR3b-5 helpers join susc → specimen → organism so the
    specimen ref is the load-bearing field, not the encounter ref."""
    obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{idx}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "code": {"coding": [{"code": "600-7"}]},
    }
    if spec_id is not None:
        obs["specimen"] = {"reference": f"Specimen/{spec_id}"}
    if organism_snomed:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}]
        }
    else:
        obs["valueString"] = "No growth"
    if hai_event_id:
        from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
        obs["identifier"] = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]
    return obs


@pytest.mark.unit
def test_organism_per_specimen_basic(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008", spec_id="spec-E1-0"),
        _mb_org_with_specimen("E2", 0, "112283007", spec_id="spec-E2-0"),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {"spec-E1-0": "3092008", "spec-E2-0": "112283007"}


@pytest.mark.unit
def test_organism_per_specimen_multi_specimen_same_encounter(tmp_path: Path) -> None:
    """C1 resolution precondition: an encounter with 2 specimens (S.aureus +
    S.epidermidis) → 2 distinct specimen_id → organism mappings, not 1
    encounter → organism set. This is the load-bearing difference from
    _organism_per_encounter."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008",  spec_id="spec-E1-0"),
        _mb_org_with_specimen("E1", 1, "60875001", spec_id="spec-E1-1"),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {"spec-E1-0": "3092008", "spec-E1-1": "60875001"}


@pytest.mark.unit
def test_organism_per_specimen_skips_no_growth(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, None, spec_id="spec-E1-0"),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_skips_missing_specimen_ref(tmp_path: Path) -> None:
    """mb-org-* without specimen reference cannot be joined → skip."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008", spec_id=None),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_skips_non_canonical_snomed(tmp_path: Path) -> None:
    """Canonical SNOMED URI equality from PR #113 C3 fix: non-canonical
    system URIs are rejected, not substring-matched."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "urn:oid:2.16.840.1.113883.6.96",
                            "code": "3092008"}],
            },
        },
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_skips_non_mb_observations(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "lab-E1-0001",
            "specimen": {"reference": "Specimen/spec-E1-X"},
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "6690-2"}]},
            "valueQuantity": {"value": 14000},
        },
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_empty_file(tmp_path: Path) -> None:
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_hai_specimens_includes_hai_identifier(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008",
                              spec_id="spec-E1-0",
                              hai_event_id="hai-clabsi-1"),
        _mb_org_with_specimen("E2", 0, "112283007",
                              spec_id="spec-E2-0"),  # community, no identifier
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == {"spec-E1-0"}


@pytest.mark.unit
def test_hai_specimens_rejects_wrong_system(tmp_path: Path) -> None:
    """Canonical equality on HAI_EVENT_ID_SYSTEM — same defense pattern
    as canonical SNOMED URI from PR #113 C3."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            "identifier": [{"system": "http://other/system",
                            "value": "hai-clabsi-1"}],
        },
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_specimens_rejects_empty_value(tmp_path: Path) -> None:
    """Identifier with correct system but empty value is not a HAI marker."""
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            "identifier": [{"system": HAI_EVENT_ID_SYSTEM, "value": ""}],
        },
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_specimens_empty_file(tmp_path: Path) -> None:
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_event_id_system_canonical_constant_shared() -> None:
    """Canonical-constant contract: writer (_fhir_microbiology) and reader
    (clinical) import the same HAI_EVENT_ID_SYSTEM. Renaming triggers
    ImportError downstream, not a silent gate skip."""
    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM

    assert HAI_EVENT_ID_SYSTEM == "http://clinosim/identifier/hai-event-id"
    assert clinical_axis.HAI_EVENT_ID_SYSTEM is HAI_EVENT_ID_SYSTEM
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_clinical_axis_per_organism.py::test_organism_per_specimen_basic tests/unit/test_clinical_axis_per_organism.py::test_hai_specimens_includes_hai_identifier -v`
Expected: BOTH FAIL with `AttributeError: module 'clinosim.audit.axes.clinical' has no attribute '_organism_per_specimen'` / `_hai_specimens`.

- [ ] **Step 3: Implement the two helpers + import the constant**

In `clinosim/audit/axes/clinical.py`, update the import block at the top:

```python
from clinosim.codes import get_system_uri
from clinosim.modules.antibiotic.engine import ABX_NARROW_SUFFIX, ABX_ORDER_ID_PREFIX
from clinosim.modules.output._fhir_microbiology import (
    HAI_EVENT_ID_SYSTEM,
    MB_ORG_ID_PREFIX,
)
```

Add the two helpers after `_panel_eligible_organisms`:

```python
def _organism_per_specimen(cohort: Cohort, country: str) -> dict[str, str]:
    """Return {specimen_id: organism_snomed} from microbiology Observations.

    PR3b-5: walks Observation.ndjson, filters to mb-org-* with both a
    Specimen reference AND a valueCodeableConcept SNOMED coding (growth).
    Used by the PR3b-5 D1 R-rate gate for true per-organism susc
    attribution (replaces the encounter-level approximation from
    PR3b-3 / _organism_per_encounter).

    No-growth observations, missing specimen ref, missing encounter,
    non-mb-org ids, and non-canonical SNOMED URIs are skipped.
    """
    out: dict[str, str] = {}
    for row in cohort.ndjson(country, "Observation"):
        rid = row.get("id", "")
        if not rid.startswith(MB_ORG_ID_PREFIX):
            continue
        spec_ref = (row.get("specimen") or {}).get("reference", "") or ""
        spec_id = spec_ref.split("/")[-1] if spec_ref else ""
        if not spec_id:
            continue
        vcc = row.get("valueCodeableConcept") or {}
        codings = vcc.get("coding", []) or []
        for c in codings:
            sys_uri = c.get("system", "") or ""
            if sys_uri == _SNOMED_URI:
                code = c.get("code", "") or ""
                if code:
                    out[spec_id] = code
                    break
    return out


def _hai_specimens(cohort: Cohort, country: str) -> set[str]:
    """Return set of specimen_ids that are HAI-derived.

    PR3b-5: walks Observation.ndjson, filters to mb-org-* with a non-empty
    identifier carrying the canonical HAI_EVENT_ID_SYSTEM URI. Used by the
    PR3b-5 D1 R-rate gate to exclude community-acquired culture
    susceptibilities that share an encounter with a HAI event (C2
    resolution).
    """
    hai_specs: set[str] = set()
    for row in cohort.ndjson(country, "Observation"):
        rid = row.get("id", "")
        if not rid.startswith(MB_ORG_ID_PREFIX):
            continue
        identifiers = row.get("identifier") or []
        is_hai = any(
            i.get("system") == HAI_EVENT_ID_SYSTEM and i.get("value")
            for i in identifiers
        )
        if not is_hai:
            continue
        spec_ref = (row.get("specimen") or {}).get("reference", "") or ""
        spec_id = spec_ref.split("/")[-1] if spec_ref else ""
        if spec_id:
            hai_specs.add(spec_id)
    return hai_specs
```

- [ ] **Step 4: Run unit tests — all 12 PR3b-5 unit tests must pass**

Run: `pytest tests/unit/test_clinical_axis_per_organism.py -v`
Expected: all pass (existing 13 from PR3b-3 + 12 new = 25). If `test_hai_event_id_system_canonical_constant_shared` fails with `clinical_axis.HAI_EVENT_ID_SYSTEM` not defined, the import block above was not applied — re-run Step 3.

- [ ] **Step 5: Full unit suite regression check**

Run: `pytest tests/unit -m unit -q`
Expected: all previously-green pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/audit/axes/clinical.py tests/unit/test_clinical_axis_per_organism.py
git commit -m "$(cat <<'EOF'
feat(audit/pr3b-5): _organism_per_specimen + _hai_specimens helpers

Two pure inline helpers for the PR3b-5 D1 R-rate gate refactor:

  _organism_per_specimen(cohort, country) -> {specimen_id: organism_snomed}
  _hai_specimens(cohort, country) -> set[specimen_id]

The first replaces the encounter-level _organism_per_encounter join
with a true specimen-based join (C1 resolution). The second filters out
community-acquired specimens via the new FHIR HAI_EVENT_ID_SYSTEM
identifier (C2 resolution).

12 new unit tests cover both helpers + canonical-constant contract.
HAI_EVENT_ID_SYSTEM is now imported by both writer (_fhir_microbiology)
and reader (clinical.py) — rename triggers ImportError downstream, same
defense pattern as MB_ORG_ID_PREFIX + ABX_ORDER_ID_PREFIX.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 3: D1 R-rate gate rewire — susc → specimen → organism + HAI-only filter

**Files:**
- Modify: `clinosim/audit/axes/clinical.py:175-235` (R-rate gate block)
- Modify: `tests/integration/test_antibiotic_audit.py` (append C1 + C2 resolution tests)

**Interfaces:**
- Consumes: `_organism_per_specimen` (Task 2), `_hai_specimens` (Task 2)
- Produces: D1 wiring; no new public API. `_organism_per_encounter` from PR #112 is retained for D2 only — comment its docstring with "D2-only after PR3b-5".

- [ ] **Step 1: Write failing C1 + C2 integration tests**

Append to `tests/integration/test_antibiotic_audit.py`:

```python
def _write_obs_with_specimen(
    tmp_path, country: str, enc: str, spec_id: str,
    organism_snomed: str, abx_loinc: str, interpretation: str,
    hai_event_id: str = "",
) -> list[dict]:
    """Build a triple (Specimen, mb-org-*, mb-sus-*) wired with the same
    specimen reference, optionally with HAI identifier. Returns the list
    of rows for caller-side _write inclusion."""
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
    rows: list[dict] = []
    spec: dict = {"resourceType": "Specimen", "id": spec_id}
    org_obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{spec_id[-1]}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "specimen": {"reference": f"Specimen/{spec_id}"},
        "code": {"coding": [{"code": "600-7"}]},
        "valueCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}],
        },
    }
    sus_obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-sus-{enc}-{spec_id[-1]}-0",
        "encounter": {"reference": f"Encounter/{enc}"},
        "specimen": {"reference": f"Specimen/{spec_id}"},
        "code": {"coding": [{"code": abx_loinc}]},
        "valueCodeableConcept": {"coding": [{"code": interpretation}]},
    }
    if hai_event_id:
        ident = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]
        spec["identifier"] = ident
        org_obs["identifier"] = ident
        sus_obs["identifier"] = ident
    rows.append(spec)
    rows.append(org_obs)
    rows.append(sus_obs)
    return rows


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_no_double_count_multi_organism_encounter(
    tmp_path,
) -> None:
    """C1 resolution: CLABSI encounter with 2 specimens (S.aureus +
    S.epidermidis), each with its own cefazolin susc. The S.aureus band
    counts ONLY the S.aureus-specimen susc (not the S.epidermidis-specimen
    susc). PR3b-3 encounter-level join double-counted; PR3b-5 specimen-based
    join attributes correctly."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(file: str, rows: list[dict]) -> None:
        p = tmp_path / "us" / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]
    # 30 CLABSI encounters: each has a S.aureus specimen (HAI, cefazolin R)
    # AND a S.epidermidis specimen (HAI, cefazolin S). Pre-PR3b-5: both
    # counted under S.aureus band → R-rate = 0.5 (false). Post-PR3b-5:
    # only S.aureus-specimen counted → R-rate = 1.0 (true, S.aureus only).
    enc_rows: list[dict] = []
    cond_rows: list[dict] = []
    obs_rows: list[dict] = []
    for i in range(30):
        eid = f"E{i}"
        enc_rows.append({"resourceType": "Encounter", "id": eid,
                         "class": {"code": "IMP"}})
        cond_rows.append({"resourceType": "Condition", "id": f"c{i}",
                          "code": {"coding": [{"code": "T80.211A"}]},
                          "encounter": {"reference": f"Encounter/{eid}"}})
        # S.aureus specimen — cefazolin R
        obs_rows.extend(_write_obs_with_specimen(
            tmp_path, "us", eid, f"spec-{eid}-0",
            organism_snomed="3092008", abx_loinc=cefaz, interpretation="R",
            hai_event_id=f"hai-{eid}-sa",
        ))
        # S.epidermidis specimen — cefazolin S (would inflate S.aureus band)
        obs_rows.extend(_write_obs_with_specimen(
            tmp_path, "us", eid, f"spec-{eid}-1",
            organism_snomed="60875001", abx_loinc=cefaz, interpretation="S",
            hai_event_id=f"hai-{eid}-se",
        ))
    _w("Encounter.ndjson", enc_rows)
    _w("Condition.ndjson", cond_rows)
    _w("Observation.ndjson", obs_rows)
    # Specimen.ndjson too (kept for FHIR consistency, even though gate
    # reads via Observation.specimen.reference)
    _w("Specimen.ndjson", [r for r in obs_rows if r["resourceType"] == "Specimen"])

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    # PR3b-5: 30 S.aureus-specimen susc, all R → rate = 1.0, n = 30.
    # (S.epidermidis-specimen susc NOT counted under S.aureus band.)
    assert n == 30, (
        f"S.aureus band cohort must be 30 (S.aureus specimens only); "
        f"got {n}. Pre-PR3b-5 encounter-level join would yield 60."
    )
    assert r_rate == 1.0, (
        f"S.aureus band R-rate must be 1.0 (true per-specimen rate); "
        f"got {r_rate}. Pre-PR3b-5 would yield 0.5 (false, mixed)."
    )


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_excludes_community_culture(tmp_path) -> None:
    """C2 resolution: CLABSI encounter with HAI S.aureus specimen + community
    E.coli specimen (no HAI identifier). The S.aureus band must NOT count
    the E.coli susc rows (different organism + different specimen, but pre-
    PR3b-5 encounter-level join would count E.coli susc if they happened to
    be cefazolin). PR3b-5 HAI-only filter excludes community specimens
    entirely."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(file: str, rows: list[dict]) -> None:
        p = tmp_path / "us" / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]
    enc_rows: list[dict] = []
    cond_rows: list[dict] = []
    obs_rows: list[dict] = []
    for i in range(30):
        eid = f"E{i}"
        enc_rows.append({"resourceType": "Encounter", "id": eid,
                         "class": {"code": "IMP"}})
        cond_rows.append({"resourceType": "Condition", "id": f"c{i}",
                          "code": {"coding": [{"code": "T80.211A"}]},
                          "encounter": {"reference": f"Encounter/{eid}"}})
        # HAI S.aureus specimen — cefazolin R (true HAI MRSA)
        obs_rows.extend(_write_obs_with_specimen(
            tmp_path, "us", eid, f"spec-{eid}-0",
            organism_snomed="3092008", abx_loinc=cefaz, interpretation="R",
            hai_event_id=f"hai-{eid}-sa",
        ))
        # Community S.aureus specimen — cefazolin S (would inflate via
        # encounter-level join in pre-PR3b-5; same organism but no HAI marker)
        obs_rows.extend(_write_obs_with_specimen(
            tmp_path, "us", eid, f"spec-{eid}-1",
            organism_snomed="3092008", abx_loinc=cefaz, interpretation="S",
            hai_event_id="",  # community
        ))
    _w("Encounter.ndjson", enc_rows)
    _w("Condition.ndjson", cond_rows)
    _w("Observation.ndjson", obs_rows)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    # PR3b-5: only HAI-derived S.aureus specimens count. 30 HAI S.aureus
    # specimens, all R → rate = 1.0, n = 30. (Community S.aureus excluded.)
    assert n == 30, (
        f"HAI-only filter must exclude community specimens; got n={n}. "
        f"Pre-PR3b-5 would yield 60 (HAI + community mixed)."
    )
    assert r_rate == 1.0, (
        f"HAI-only R-rate must be 1.0 (pure HAI); got {r_rate}. "
        f"Pre-PR3b-5 would yield 0.5 (HAI + community mixed)."
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_no_double_count_multi_organism_encounter tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_excludes_community_culture -v`
Expected: BOTH FAIL. The first will likely show `n == 60` and `r_rate == 0.5` (encounter-level mixed S.aureus + S.epidermidis). The second will show `n == 60` and `r_rate == 0.5` (HAI + community).

- [ ] **Step 3: Rewire D1 R-rate gate in clinical.py**

In `clinosim/audit/axes/clinical.py`, find the existing `for country in cohort.countries():` loop's helper hoist (added in PR #112). Update it to compute both per-specimen and HAI maps:

```python
    for country in cohort.countries():
        # PR3b-5 D1 (2026-06-29): per-country per-specimen organism map +
        # HAI-only specimen set. Both built ONCE and reused by the R-rate
        # gate (susc → specimen → organism join, HAI-only filter). D2
        # empty-rate gate continues to use _organism_per_encounter
        # (encounter-level panel-eligibility semantics unchanged).
        org_per_enc = _organism_per_encounter(cohort, country)
        org_per_specimen = _organism_per_specimen(cohort, country)
        hai_specimens = _hai_specimens(cohort, country)
```

Then replace the R-rate gate block (currently at lines 175-235 region, post-PR #112 D1 wiring) with the specimen-based join version:

```python
        # ---------------------------------------------------------------
        # PR3b-5 D1 (2026-06-29): NHSN R-rate gate per (hai_type, organism,
        # antibiotic) cohort. Resolves the PR3b-3 encounter-level
        # approximation by joining susc → specimen → organism via
        # Observation.specimen.reference, and filtering to HAI-derived
        # specimens via the new HAI_EVENT_ID_SYSTEM identifier.
        # - C1 fix: multi-organism encounter no longer double-counts.
        # - C2 fix: community-acquired culture susceptibilities are
        #   excluded from HAI bands.
        # n<30 → WARN guard retained for rare-event safety.
        # Cohort encounter pre-filter retained as defense-in-depth
        # (re-verify the susc's encounter is in the HAI cohort).
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
                cohort_enc_set = cohort_enc.get(hai_type_b, set())
                if not cohort_enc_set:
                    result.info[f"{country}_{band['cohort']}_{abx_key}_n"] = 0
                    continue
                r_count = 0
                total_count = 0
                for row in cohort.ndjson(country, "Observation"):
                    s = _is_susceptibility_observation(row)
                    if s is None:
                        continue
                    if s[0] != abx_loinc:
                        continue
                    # PR3b-5: specimen-based join
                    spec_ref = (row.get("specimen") or {}).get("reference", "") or ""
                    spec_id = spec_ref.split("/")[-1] if spec_ref else ""
                    if not spec_id:
                        continue
                    # PR3b-5: HAI-only filter
                    if spec_id not in hai_specimens:
                        continue
                    # PR3b-5: per-organism match
                    if org_per_specimen.get(spec_id) != organism_b:
                        continue
                    # Defense in depth: re-verify encounter is in HAI cohort
                    eid = _enc_id(row)
                    if eid and eid not in cohort_enc_set:
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

Update the `_organism_per_encounter` docstring (still used by D2):

```python
def _organism_per_encounter(cohort: Cohort, country: str) -> dict[str, set[str]]:
    """Return {encounter_id: {organism_snomed, ...}} from microbiology Observations.

    [existing body unchanged]

    Used by the PR3b-5 D2 empty-rate gate (panel-eligible denominator
    filter via _panel_eligible_organisms). The PR3b-5 D1 R-rate gate
    uses _organism_per_specimen + _hai_specimens for specimen-based
    per-organism attribution.
    """
```

- [ ] **Step 4: Run the new C1 + C2 integration tests**

Run: `pytest tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_no_double_count_multi_organism_encounter tests/integration/test_antibiotic_audit.py::test_clinical_axis_r_rate_gate_excludes_community_culture -v`
Expected: BOTH PASS.

- [ ] **Step 5: Run all clinical-axis + antibiotic-audit suites for regression**

Run: `pytest tests/unit/test_axis_clinical.py tests/unit/test_clinical_axis_per_organism.py tests/integration/test_antibiotic_audit.py tests/integration/test_audit_end_to_end.py -q`
Expected: all green. Existing D1 tests from PR #112 use single-organism / single-specimen fixtures (no multi-specimen), so they continue to pass under the specimen-based join.

- [ ] **Step 6: Commit**

```bash
git add clinosim/audit/axes/clinical.py tests/integration/test_antibiotic_audit.py
git commit -m "$(cat <<'EOF'
feat(audit/D1 pr3b-5): susc → specimen → organism join + HAI-only filter

Resolves the PR3b-3 D1 R-rate gate's encounter-level susceptibility
attribution approximation.

C1 (multi-organism encounter double-count): a CLABSI encounter with both
S.aureus + S.epidermidis specimens no longer double-counts cefazolin susc
under both organism bands. The gate now reads
Observation.specimen.reference and joins to _organism_per_specimen[spec_id].

C2 (community + HAI culture co-occurrence): a CLABSI encounter with a HAI
S.aureus specimen + a community S.aureus specimen no longer mixes community
susceptibilities into the HAI MRSA band. The gate filters susc by
spec_id in _hai_specimens (set of HAI-derived specimens via the new
HAI_EVENT_ID_SYSTEM identifier from Task 1).

Cohort encounter pre-filter retained as defense in depth. n<30 WARN guard
retained for rare-event safety. D2 empty-rate gate unchanged
(_organism_per_encounter still used; encounter-level panel-eligibility
semantics).

2 new integration tests verify C1 + C2 resolution.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 4: audit run + DQR + PR3b-3 DQR §"Known approximation" RESOLVED cross-link

**Files:**
- Create: `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`
- Modify: `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`

**Interfaces:**
- Consumes: post-Task-3 state (D1 specimen-based join wired, tests green)
- Produces: DQR documentation, no code change

- [ ] **Step 1: Generate fresh DQR cohort**

```bash
mkdir -p scratchpad/pr3b5_dqr
.venv/bin/clinosim generate --country US --population 5000 --seed 42 --output scratchpad/pr3b5_dqr/us --format fhir-r4
.venv/bin/clinosim generate --country JP --population 5000 --seed 42 --output scratchpad/pr3b5_dqr/jp --format fhir-r4
```

Expected: each finishes within a few minutes; NDJSON appears under `scratchpad/pr3b5_dqr/{us,jp}/fhir_r4/`. Spot-check: `grep -l hai-event-id scratchpad/pr3b5_dqr/us/fhir_r4/Observation.ndjson` should match the HAI-derived mb-org-* / mb-sus-* rows.

- [ ] **Step 2: Run audit + capture output**

```bash
.venv/bin/clinosim audit run -d scratchpad/pr3b5_dqr | tee scratchpad/pr3b5_dqr/audit_output.txt
```

Expected: audit completes; per-(hai_type, organism, abx) info entries surface; n<30 WARN guards fire at p=5000 cohort scale (same as PR #112 DQR baseline).

- [ ] **Step 3: Spot-check HAI identifier emission in cohort**

```bash
.venv/bin/python - <<'PY'
import json
hai = 0
comm = 0
for ln in open("scratchpad/pr3b5_dqr/us/fhir_r4/Observation.ndjson"):
    r = json.loads(ln)
    if not r["id"].startswith("mb-org-"):
        continue
    idents = r.get("identifier", [])
    if any(i.get("system") == "http://clinosim/identifier/hai-event-id" for i in idents):
        hai += 1
    else:
        comm += 1
print(f"HAI mb-org count: {hai}")
print(f"Community mb-org count: {comm}")
PY
```

Expected: `hai > 0` (some HAI cultures in cohort), `comm > 0` (community cultures present without identifier). Record both numbers in the DQR.

- [ ] **Step 4: Write PR3b-5 DQR**

Create `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`:

```markdown
# PR3b-5 Attribution Refinement — Data Quality Review

**Date**: 2026-06-29
**Branch**: feat/pr3b-5-attribution-refinement
**Cohort**: scratchpad/pr3b5_dqr (US p=5000 seed=42 + JP p=5000 seed=42)
**Audit**: `clinosim audit run -d scratchpad/pr3b5_dqr`

## Summary

**PR3b-3 D1+D2 approximation RESOLVED.** D1 R-rate gate now joins
susceptibilities to specimens (via Observation.specimen.reference) and
filters to HAI-derived specimens (via the new HAI_EVENT_ID_SYSTEM
canonical identifier). The two attribution defects documented in
PR3b-3 DQR §"Known approximation" (C1 multi-organism encounter
double-count, C2 community + HAI culture co-occurrence) are now both
mechanically excluded by the gate.

## Cohort-side HAI identifier emission

| Country | mb-org-* HAI count | mb-org-* community count |
|---|---|---|
| US | [from Step 3] | [from Step 3] |
| JP | [from Step 3] | [from Step 3] |

Community mb-org-* rows carry no `identifier` field (byte-identical to
pre-PR3b-5 output for community cultures). HAI rows carry
`identifier[0].system == HAI_EVENT_ID_SYSTEM` with value matching the
emitter's `MicrobiologyResult.hai_event_id`.

## D1 R-rate gate at production scale

At p=5000 the per-(hai_type, organism, abx) cohorts continue to hit the
n<30 WARN guard (same as PR #112 baseline). The gate semantics are now
**correct at any cohort scale** — adding more patients would surface a
true per-organism per-HAI R-rate against the NHSN band.

## C1 + C2 resolution evidence

- **C1**: Integration test
  `test_clinical_axis_r_rate_gate_no_double_count_multi_organism_encounter`
  builds 30 CLABSI encounters with both S.aureus + S.epidermidis
  specimens and confirms the S.aureus band counts only 30 susc rows
  (pre-PR3b-5 would yield 60).
- **C2**: Integration test
  `test_clinical_axis_r_rate_gate_excludes_community_culture` builds 30
  encounters with both HAI S.aureus + community S.aureus specimens and
  confirms only 30 HAI susc rows are counted (pre-PR3b-5 would yield 60).

## Verdict

**PR3b-5 attribution refinement: VERIFIED. PR3b-3 D1+D2 approximation =
RESOLVED.**

The "Known approximation" section in the PR3b-3 DQR is updated to
reference this PR's resolution.
```

Fill in the actual HAI / community counts from Step 3 output.

- [ ] **Step 5: Update PR3b-3 DQR with RESOLVED cross-link**

In `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`, find the `## Known approximation (deferred refinement)` section. Add at the top, just under the heading:

```markdown
> **RESOLVED via PR3b-5** (2026-06-29). The specimen-based susc → organism
> join + HAI_EVENT_ID_SYSTEM identifier filter eliminate both C1
> (multi-organism encounter double-count) and C2 (community + HAI
> culture co-occurrence) attribution defects documented below.
> See `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`.
>
> The original approximation text is retained for historical context.
```

- [ ] **Step 6: Commit**

```bash
git add docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md
git commit -m "$(cat <<'EOF'
chore(audit): PR3b-5 DQR + PR3b-3 DQR §"Known approximation" RESOLVED

PR3b-5 DQR records the specimen-based join + HAI-only filter
resolution evidence (C1 + C2 integration tests + cohort-side identifier
emission counts). PR3b-3 DQR §"Known approximation" updated with the
"RESOLVED via PR3b-5" cross-link at the top of the section while
preserving the original historical text below.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 5: Out-of-scope items → TODO.md formal entries

**Files:**
- Modify: `TODO.md`

**Interfaces:**
- Consumes: spec's Out-of-scope table
- Produces: TODO.md entries for every deferred item, sufficient for a fresh contributor to pick up

- [ ] **Step 1: Identify the Phase 3b backlog block in TODO.md**

Run: `grep -n "Phase 3b backlog\|PR3b-4\|PR3b-5" TODO.md | head -10`

Find the existing Phase 3b backlog section (created by PR #115 with the PR3b-5 entry).

- [ ] **Step 2: Strike the PR3b-5 entry + add the 8 deferred items**

Modify the existing Phase 3b backlog section. Find:

```markdown
- **PR3b-5**: specimen-organism susceptibility attribution refinement. PR3b-3 D1
  filters cohort encounters per-organism via `_organism_per_encounter`, but the
  ...
```

Replace with:

```markdown
- ~~PR3b-5~~: ✓ done 2026-06-29 (this PR, attribution refinement) — specimen-
  based susc → organism join + FHIR HAI_EVENT_ID_SYSTEM identifier emission
  resolved the PR3b-3 D1 encounter-level attribution approximation. C1
  (multi-organism encounter double-count) and C2 (community + HAI culture
  co-occurrence) both mechanically excluded. See
  `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`.

Out-of-scope items deferred from PR3b-5 (formal tracking — each one
required so the chain closure can honestly claim "no half-finished state
remains"):

- PR3b-4: WBC/CRP forward-delta decay coupled with antibiotic-day count.
  Sibling to the Phase 3a HAI lift pattern; antibiotic start_day initiates
  a forward decay on WBC + CRP observed values mirroring the lift profile.
  Independent of PR3b-3 / PR3b-5 — purely new realism work.
- Sibling YAML loader sweep (hai_lab_lift / hai_rates / hai_codes /
  hai_specimens / hai_organisms additional reverse-coverage): apply the
  6-layer silent-no-op defense pattern established by PR3b-3 chain to all
  remaining hai_*.yaml loaders. Scope-tiny, pattern application. This is
  the next user-declared breakpoint after PR3b-5.
- audit registry `_reset_for_test` ordering bug: 10 fail master baseline
  (production code healthy, test isolation issue only). Tests that call
  `discover()` end up with empty registry after another test's
  `_reset_for_test`. Fix candidate: autouse fixture in conftest that
  re-discovers before each integration test.
- audit clinical axis Phase 2 (per-event observed-vs-theoretical
  enforcement): new axis-level enforcement walking CIF state_history per
  event for closed-form delta verification. Currently the silent_no_op
  axis lift_firing_proof covers this at synthetic-fixture level; Phase 2
  would enforce per-real-event at audit run time.
- NHSN clinical-accuracy band verification (CoNS / K.pneumoniae VAP /
  A.baumannii VAP exempt entries): adv-2 Agent 1 flagged that NHSN AR
  2018-2020 may publish stable population bands for organisms currently
  in `_NHSN_REVERSE_COVERAGE_EXEMPT`. Verify against the NHSN tables and
  either ADD a band (preferred) or tighten the exempt rationale.
- I1 WARN per-country diagnostic improvement: current WARN message fires
  per country with identical wording; symptom (antibiogram corruption /
  mb-org drift / SNOMED URI drift) is global. Improve by probing
  individual root cause and emitting one global WARN with specific
  dispatch.
- Unused MB_*_PREFIX cleanup (MB_SUS / MB_SPECIMEN / MB_DR): extracted
  in PR #113 for consistency but currently no reader imports them.
  YAGNI cleanup once a reader appears (or remove if no reader added by
  the next refactor).
- DESIGN.md AD-55 / AD-60 PR3b-3 supplement extended ADR text: brief
  closure note already in AD-60. A longer ADR-quality narrative covering
  the 6-layer + 7-layer silent-no-op defense pattern and the AD-55
  near-essential clinical cascade extension is a documentation polish
  item.
```

- [ ] **Step 3: Verify no other section in TODO.md mentions PR3b-5 as pending**

Run: `grep -n "PR3b-5" TODO.md`
Expected: only the ~~PR3b-5~~ done-entry above + at most a backreference.

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git commit -m "$(cat <<'EOF'
docs(todo): strike PR3b-5 done + record 8 deferred items formally

PR3b-5 attribution refinement closed (this PR). All out-of-scope items
the spec deferred are now formal TODO.md entries with sufficient
context for a fresh contributor to pick up:

  - PR3b-4 WBC/CRP forward-delta decay (Phase 3b backlog)
  - Sibling YAML loader sweep (NEXT user-declared breakpoint)
  - audit registry _reset_for_test ordering bug
  - audit clinical axis Phase 2 (per-event observed-vs-theoretical)
  - NHSN clinical-accuracy band verification
  - I1 WARN per-country diagnostic improvement
  - Unused MB_*_PREFIX cleanup
  - DESIGN.md AD-55/AD-60 extended ADR text

Honest closure: "no half-finished state remains" — every deferred
item has a written home.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 6: Docs sync — CLAUDE.md + DESIGN.md + READMEs + CONTRIBUTING

**Files:**
- Modify: `CLAUDE.md` (PR3b-5 chain CLOSED narrative + 7th defense layer enumeration)
- Modify: `docs/CONTRIBUTING-modules.md` (Cross-module canonical URI constants subsection)
- Modify: `clinosim/modules/antibiotic/README.md` (D1 specimen-based join note)
- Modify: `clinosim/modules/hai/README.md` (hai_event_id FHIR identifier emission note)

**Interfaces:**
- Consumes: post-Task-5 state (TODO.md formal entries, code + DQR committed)
- Produces: documentation, no code change

- [ ] **Step 1: CLAUDE.md PR3b-3 + PR3b-5 narrative**

In `CLAUDE.md`, find the existing PR3b-3 CLOSED supplement paragraph (added in PR #112, extended through #115). Append a new paragraph after it:

```markdown
  **PR3b-5 attribution refinement CLOSED (2026-06-29, this chain)** — D1
  R-rate gate now joins susceptibilities to specimens (via
  `Observation.specimen.reference`) and filters to HAI-derived specimens
  (via the new `HAI_EVENT_ID_SYSTEM` canonical URI identifier). C1
  (multi-organism encounter double-count) and C2 (community + HAI culture
  co-occurrence) attribution defects are mechanically excluded. New
  helpers: `_organism_per_specimen`, `_hai_specimens` (inline in
  `clinosim/audit/axes/clinical.py`). FHIR identifier emission added to
  `clinosim/modules/output/_fhir_microbiology.py` on Specimen + mb-org-* /
  mb-sus-* Observation + DiagnosticReport when
  `MicrobiologyResult.hai_event_id` is non-empty (community cultures
  byte-identical). PR3b-3 DQR §"Known approximation" carries a RESOLVED
  cross-link. **Silent-no-op defense layer 7**: `HAI_EVENT_ID_SYSTEM`
  canonical URI shared between writer (`_fhir_microbiology.py`) and reader
  (`audit/axes/clinical.py`) per the precedent established by
  `MB_ORG_ID_PREFIX` + `ABX_ORDER_ID_PREFIX`.
```

- [ ] **Step 2: CONTRIBUTING-modules.md — Cross-module canonical URI subsection**

In `docs/CONTRIBUTING-modules.md`, find the "Validator ordering & reverse-staleness" subsection added in PR #115. Append a new subsection just after it:

```markdown
### Cross-module canonical URI constants(PR3b-5, 2026-06-29)

FHIR builder と audit reader が共有する canonical URI(system / identifier
URI 等)を hard-coded literal で書かないこと。**writer 側 module(`clinosim/modules/output/_fhir_*.py`)に module-level 定数として定義 + reader 側がそれを import する pattern**を踏襲。rename 時に reader 側で ImportError が triggered され、silent-no-op skip を防御する(同パターン:`MB_ORG_ID_PREFIX` PR #113 / `ABX_ORDER_ID_PREFIX` PR #114 / `HAI_EVENT_ID_SYSTEM` PR3b-5)。

定数命名規約:
- ID prefix:`<BUILDER_PREFIX>_<RESOURCE>_ID_PREFIX = "..."`(例 `MB_ORG_ID_PREFIX`)
- system URI(canonical):`<DOMAIN>_<CONCEPT>_SYSTEM = "..."`(例 `HAI_EVENT_ID_SYSTEM`)
- 内部 URI には `http://clinosim/identifier/<purpose>` または `http://clinosim/<resource>/<purpose>` を使用(JP Core / US Core / HL7 IG に登録ない概念のみ)

contract test pattern:`assert clinical_axis.CONSTANT is mb_builder.CONSTANT`(同一 object identity 確認、import path 一致を pin)。先例 `tests/unit/test_clinical_axis_per_organism.py:test_hai_event_id_system_canonical_constant_shared`。
```

- [ ] **Step 3: antibiotic README**

In `clinosim/modules/antibiotic/README.md`, find the section describing the D1 R-rate gate (added/updated in PR #112). Update the per-(hai_type, organism, antibiotic) cohort line to reflect specimen-based join:

```markdown
1. **NHSN R-rate** per (hai_type, **organism**, antibiotic) cohort — `_NHSN_RESISTANCE_BANDS` 配線、MRSA / ESBL+ / etc. の population-level R-rate を NHSN AR 2018-2020 band で gate。**PR3b-5 D1 完成 (2026-06-29)** で specimen-based join に refinement:`_organism_per_specimen` が `Observation.specimen.reference` を joining key にし、`_hai_specimens` が `HAI_EVENT_ID_SYSTEM` identifier で HAI-derived specimens を filter(community culture exclude、C1+C2 attribution defect 解消)
```

- [ ] **Step 4: hai README — `hai_event_id` FHIR emission**

In `clinosim/modules/hai/README.md`, find the section describing `MicrobiologyResult.hai_event_id` (PR3b-2 narrative). Append a note about FHIR emission:

```markdown
**PR3b-5 (2026-06-29)**: `MicrobiologyResult.hai_event_id` is now emitted as
`Observation.identifier[].system = HAI_EVENT_ID_SYSTEM` + matching value on
Specimen / mb-org-* / mb-sus-* / DiagnosticReport FHIR resources (when
non-empty — community cultures unchanged). The audit clinical axis D1
R-rate gate consumes this identifier via `_hai_specimens` to filter
community-acquired culture susceptibilities out of HAI-specific
per-(organism, antibiotic) bands.
```

- [ ] **Step 5: Run full unit + integration suite for sanity**

Run: `pytest tests/unit tests/integration -m "unit or integration" -q`
Expected: previously-green tests all pass. Test cascade failure count = baseline + new tests' inheritance (at most +3-4). Documented in PR body.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/CONTRIBUTING-modules.md clinosim/modules/antibiotic/README.md clinosim/modules/hai/README.md
git commit -m "$(cat <<'EOF'
docs(pr3b-5): record attribution refinement chain closure

CLAUDE.md: append PR3b-5 CLOSED supplement to PR3b-3 narrative + silent-
no-op defense layer 7 (HAI_EVENT_ID_SYSTEM canonical URI shared between
writer and reader).
CONTRIBUTING-modules.md: add "Cross-module canonical URI constants"
subsection codifying the writer-side-module + reader-import pattern.
antibiotic/README.md: D1 R-rate gate description updated for specimen-
based join + HAI-only filter.
hai/README.md: note hai_event_id FHIR identifier emission + audit
clinical axis consumer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 7: Pre-merge gate + PR

**Files:**
- None modified (verification + PR draft)

**Interfaces:**
- Consumes: post-Task-6 state (helpers + FHIR emit + D1 rewire + DQR + TODO.md + docs all committed)
- Produces: PR ready for review

- [ ] **Step 1: Run full pre-merge sweep (session 22 rule)**

Run: `pytest tests/unit tests/integration -m "unit or integration" -q`
Expected: failure count = 10 pre-existing `_reset_for_test` ordering ± up to 3-4 new tests inheriting the cascade. Note exact count for PR body.

- [ ] **Step 2: Confirm tests pass in isolation**

Run: `pytest tests/integration/test_antibiotic_audit.py tests/unit/test_clinical_axis_per_organism.py -v`
Expected: every test passes in isolation. Total new tests added by PR3b-5: ~15 (12 unit + 3 integration).

- [ ] **Step 3: Push branch + create PR**

```bash
git push -u origin feat/pr3b-5-attribution-refinement
gh pr create --title "feat(audit): PR3b-5 attribution refinement (specimen-based join + hai_event_id emit)" --body "$(cat <<'EOF'
## Summary

Resolves the PR3b-3 D1 R-rate gate's encounter-level susceptibility attribution approximation (~15-20% mixing at p=5000 per PR3b-3 DQR §"Known approximation").

- **C1 multi-organism encounter double-count** → fixed by joining susc → specimen → organism via `Observation.specimen.reference`.
- **C2 community + HAI culture co-occurrence** → fixed by filtering to HAI-derived specimens via the new `HAI_EVENT_ID_SYSTEM` canonical URI identifier.

PR3b-3 D1+D2 chain DQR §"Known approximation" carries a **RESOLVED via PR3b-5** cross-link.

## Test plan

- [x] ~12 new unit tests for `_organism_per_specimen` + `_hai_specimens` + canonical constant contract
- [x] 3 new integration tests for FHIR builder identifier emission + C1 resolution + C2 resolution
- [x] All 31 existing PR3b-3 D1+D2 + canonical-constants tests green
- [x] Full sweep `pytest tests/unit tests/integration -m "unit or integration"` — failure count = master baseline + new tests inheriting `_reset_for_test` cascade (registry isolation, out-of-scope, separately tracked)
- [x] `clinosim audit run -d scratchpad/pr3b5_dqr` (US + JP p=5000) — DQR `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`

## Silent-no-op defense layer 7

`HAI_EVENT_ID_SYSTEM` canonical URI is defined in `_fhir_microbiology.py` and imported by `clinosim/audit/axes/clinical.py`. A rename triggers ImportError downstream, not a silent gate skip. Same defense pattern as `MB_ORG_ID_PREFIX` (PR #113) and `ABX_ORDER_ID_PREFIX` (PR #114).

## Out-of-scope (deferred, formal TODO.md entries)

Per the spec's explicit deferral policy ("no half-finished state remains"), 8 items are formally tracked in `TODO.md`:

- PR3b-4 WBC/CRP forward-delta decay
- Sibling YAML loader sweep (NEXT user-declared breakpoint)
- audit registry `_reset_for_test` ordering bug
- audit clinical axis Phase 2 (per-event observed-vs-theoretical)
- NHSN clinical-accuracy band verification
- I1 WARN per-country diagnostic improvement
- Unused MB_*_PREFIX cleanup
- DESIGN.md AD-55/AD-60 extended ADR text

## Related

- Spec: `docs/superpowers/specs/2026-06-29-pr3b-5-attribution-refinement-design.md`
- Plan: `docs/superpowers/plans/2026-06-29-pr3b-5-attribution-refinement-plan.md`
- DQR: `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`
- PR3b-3 chain (closed): PR #112 + #113 + #114 + #115 + #116

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

Expected: PR URL returned. Record for the post-merge adversarial fan-out (separate task in the session's task list).

---

## Spec coverage self-check

- HAI_EVENT_ID_SYSTEM canonical URI constant → Task 1 ✓
- FHIR identifier emission on 4 resource types → Task 1 ✓
- `_organism_per_specimen` helper → Task 2 ✓
- `_hai_specimens` helper → Task 2 ✓
- Canonical-constant import contract (writer ↔ reader) → Task 2 Step 1 + Task 1 ✓
- D1 R-rate gate susc → specimen → organism join → Task 3 ✓
- D1 HAI-only filter → Task 3 ✓
- D2 unchanged → Task 3 (no code change to D2 block) ✓
- D1 cohort encounter pre-filter retained → Task 3 ✓
- Unit tests (12 new) → Task 2 ✓
- Integration tests (3 new: FHIR emit + C1 + C2) → Task 1 + Task 3 ✓
- audit run + DQR → Task 4 ✓
- PR3b-3 DQR §"Known approximation" RESOLVED cross-link → Task 4 Step 5 ✓
- TODO.md out-of-scope formal entries (all 8 deferred items) → Task 5 ✓
- CLAUDE.md + CONTRIBUTING-modules.md + READMEs sync → Task 6 ✓
- Pre-merge gate (session 22 rule) → Task 7 ✓
- PR draft with out-of-scope list → Task 7 ✓
- Byte-diff invariant intentionally broken (HAI resources only) → Task 1 Step 3 ✓
- Determinism (AD-16) — no new RNG → Task 1 + 2 + 3 (pure walks / pure field write) ✓
- 7th silent-no-op defense layer (HAI_EVENT_ID_SYSTEM shared constant) → Task 6 CLAUDE.md ✓

## Type consistency

- `_organism_per_specimen(cohort, country) -> dict[str, str]` — Task 2, consumed in Task 3
- `_hai_specimens(cohort, country) -> set[str]` — Task 2, consumed in Task 3
- `HAI_EVENT_ID_SYSTEM: str` — Task 1, imported in Task 2 + Task 3 + tests

All signatures consistent across tasks.

## Placeholder scan

No TBD / TODO / "fill in" placeholders in implementation steps. The DQR template in Task 4 has bracketed `[from Step 3]` placeholders — these are expected to be filled at execution time, not plan-time TBDs.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-29-pr3b-5-attribution-refinement-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task with review between tasks.

**2. Inline Execution** — execute tasks in this session with checkpoints.

For this 7-task scope-medium PR with strict dependency chain (Task 1 → 2 → 3 → 4 → 5 → 6 → 7, parallelism limited), inline execution often wins because spec + plan context is already loaded. Subagent-driven becomes worthwhile when tasks can branch independently; PR3b-5 cannot.

Which approach?
