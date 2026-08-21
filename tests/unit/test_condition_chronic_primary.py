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
    for c in conditions:
        if needle in c["id"]:
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
