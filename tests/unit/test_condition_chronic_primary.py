"""Chronic-primary Condition merge semantics.

When an outpatient encounter's primary (encounter) diagnosis is a chronic
condition the patient already carries (e.g. a diabetes follow-up visit
coding E11.9), NO separate `cond-{enc}-primary` Condition is emitted —
the chronic `cond-chronic-{patient}-{i:02d}` Condition already models the
ongoing disease, and `Encounter.diagnosis[].use=DD` (emitted by the
encounter builder) conveys the encounter-role.

Acute primaries (a base code that doesn't match any chronic) still emit a
fresh `cond-{enc}-primary` Condition, resolved on outpatient discharge.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

pytestmark = pytest.mark.unit


def _by_id_suffix(conditions: list[dict], needle: str) -> dict | None:
    """Issue #854 Bucket B (PR-condition): Condition.id is now opaque
    (`cond-<12hex>`), so substring matching on the id no longer works.
    Look the resource up via the pre-#854 structural key that the writer
    now carries on `identifier[]` under `CONDITION_KEY_SYSTEM`. Callers
    still pass the pre-#854 id-body substring (e.g. `chronic-pat-1-00`
    or `enc-1-primary`) — the leading `cond-` prefix on the needle is
    stripped so both old-shape needles (`cond-chronic-...`) and new
    structural-key needles (`chronic-...`) resolve identically."""
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import CONDITION_KEY_SYSTEM

    key_needle = needle.removeprefix("cond-")
    for c in conditions:
        idents = c.get("identifier") or []
        for i in idents:
            if i.get("system") == CONDITION_KEY_SYSTEM and key_needle in i.get("value", ""):
                return c
    return None


def _status(cond: dict) -> str:
    return cond["clinicalStatus"]["coding"][0]["code"]


def test_outpatient_chronic_primary_merges_into_chronic_condition() -> None:
    """Chronic-primary encounter: no `-primary` Condition; chronic entry
    represents the disease with its own onsetDateTime, active status."""
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "E11.9"},
        "encounters": [
            {
                "encounter_id": "enc-1",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-05-01T10:00:00",
                "discharge_datetime": "2026-05-01T11:00:00",
            }
        ],
        "patient": {"chronic_conditions": [{"code": "E11.9", "onset_date": "2020-03-15"}]},
    }
    conds = _build_conditions(record, "pat-1", "US")
    # No encounter-primary Condition emitted.
    assert _by_id_suffix(conds, "enc-1-primary") is None
    # Exactly one chronic Condition emitted for E11.9.
    chronic = _by_id_suffix(conds, "cond-chronic-pat-1-00")
    assert chronic is not None
    assert _status(chronic) == "active"
    assert chronic["onsetDateTime"] == "2020-03-15"
    # category stays problem-list-item — the encounter-role is expressed by
    # `Encounter.diagnosis[].use=DD` (see encounter builder), not by adding
    # a second category coding on the Condition itself.
    cat_code = chronic["category"][0]["coding"][0]["code"]
    assert cat_code == "problem-list-item"


def test_outpatient_acute_primary_stays_resolved_with_visit_onset() -> None:
    """Acute-primary encounter (base doesn't match any chronic): still emits
    `cond-{enc}-primary`, resolved on outpatient discharge."""
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "J06.9"},  # acute URI
        "encounters": [
            {
                "encounter_id": "enc-2",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-05-01T10:00:00",
                "discharge_datetime": "2026-05-01T11:00:00",
            }
        ],
        "patient": {"chronic_conditions": [{"code": "E11.9", "onset_date": "2020-03-15"}]},
    }
    conds = _build_conditions(record, "pat-2", "US")
    primary = _by_id_suffix(conds, "enc-2-primary")
    assert primary is not None
    assert _status(primary) == "resolved"
    # Issue #821 (N-7): encounter-diagnosis onset/recordedDate now carry the
    # full admission datetime (was date-only, breaking time-series sort).
    # Builder appends JST as its default; post-process rewrites per country.
    assert primary["onsetDateTime"] == "2026-05-01T10:00:00+09:00"
    assert primary["recordedDate"] == "2026-05-01T10:00:00+09:00"


def test_chronic_primary_with_finer_encounter_code_still_merges() -> None:
    """Encounter dx `I50.9` (specific) matches chronic `I50` (base). Base
    match wins — merge into chronic (no separate primary emit)."""
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "I50.9"},
        "encounters": [
            {
                "encounter_id": "enc-hf",
                "encounter_type": "inpatient",
                "admission_datetime": "2026-05-01T10:00:00",
            }
        ],
        "patient": {"chronic_conditions": [{"code": "I50", "onset_date": "2010-12-04"}]},
    }
    conds = _build_conditions(record, "pat-3", "JP")
    assert _by_id_suffix(conds, "enc-hf-primary") is None
    chronic = _by_id_suffix(conds, "cond-chronic-pat-3-00")
    assert chronic is not None
    # Chronic keeps its own 3-char code (ICD granularity harmonisation is
    # deferred — this PR only removes the duplicate row). JP mapping is
    # identity so I50 stays I50; US would map I50 → I50.9 via
    # code_mapping_diagnosis.
    assert chronic["code"]["coding"][0]["code"] == "I50"


def test_admission_condition_suppressed_when_mapping_collapses_admit_and_primary_1341() -> None:
    """Issue #1341: admit_dx and discharge_dx are raw-distinct but both
    collapse to the same code under ``map_diagnosis_code``. Prior to the
    fix, the raw-view of ``needs_admission_diagnosis_condition`` said "admit
    is orphaned" (raw admit != raw primary), while the mapped-view said
    "admit is covered" (mapped admit == mapped primary). The OR combining
    the two views emitted a second Condition carrying the same mapped code
    as the primary — 10 dup pairs on JP p=500 seed=356 (mostly hip-fracture
    S72.0 collapses and JP 99999999 placeholder-code collapses).

    Scenario: JP hip fracture — discharge_dx=S72.00 (raw variant),
    admit_dx=S72.0 (raw root). Both map to S72.0 in JP. The encounter
    should carry exactly ONE S72.0 Condition (the principal), not two.
    """
    record = {
        "clinical_diagnosis": {
            "discharge_diagnosis_code": "S72.00",
            "admission_diagnosis_code": "S72.0",
        },
        "encounters": [
            {
                "encounter_id": "enc-hip",
                "encounter_type": "inpatient",
                "admission_datetime": "2026-07-21T09:58:00",
                "discharge_datetime": "2026-07-28T14:00:00",
            }
        ],
        "patient": {"chronic_conditions": []},
    }
    conds = _build_conditions(record, "pat-hip", "JP")
    # Collect S72.0 Conditions attached to this encounter.
    s72_conds = [c for c in conds if any((cod.get("code") == "S72.0") for cod in c.get("code", {}).get("coding", []))]
    assert len(s72_conds) == 1, (
        f"admission Condition must not duplicate the primary when both admit "
        f"and discharge dx collapse to the same mapped code (S72.0); got "
        f"{len(s72_conds)} S72.0 Conditions"
    )
