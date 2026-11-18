"""Issue #3333: Conditions are de-duplicated by the full emitted code.

Distinct diagnoses that share a 3-character ICD-10 category (E11.9 /
E11.311 / E11.42) each keep their own Condition (CIF-to-FHIR no-drop). Only
two source codes that map to the SAME emitted code are one diagnosis.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    chronic_condition_id,
    primary_condition_ref,
    primary_condition_ref_from_codes,
)

pytestmark = pytest.mark.unit

_ENC = {
    "encounter_id": "enc-1",
    "encounter_type": "outpatient",
    "admission_datetime": "2026-05-01T10:00:00",
    "discharge_datetime": "2026-05-01T11:00:00",
}


def _codes(conditions: list[dict]) -> list[str]:
    return [c["code"]["coding"][0]["code"] for c in conditions]


def _record(chronic: list[str], primary: str = "", working: list[str] | None = None) -> dict:
    return {
        "clinical_diagnosis": {
            "discharge_diagnosis_code": primary,
            "working_diagnoses": [{"disease_id": w} for w in (working or [])],
        },
        "encounters": [dict(_ENC)],
        "patient": {"chronic_conditions": [{"code": c, "onset_date": "2020-01-01"} for c in chronic]},
    }


def test_us_chronic_codes_sharing_a_category_each_emit_a_condition() -> None:
    conds = _build_conditions(_record(["E11.9", "E11.311", "E11.42"]), "pat-1", "US")
    assert sorted(_codes(conds)) == ["E11.311", "E11.42", "E11.9"]


def test_identical_chronic_code_is_emitted_once() -> None:
    conds = _build_conditions(_record(["E11.9", "E11.9"]), "pat-1", "US")
    assert _codes(conds) == ["E11.9"]


def test_chronic_primary_keeps_every_chronic_of_the_category() -> None:
    """A primary that is one of the chronics merges into that entry only."""
    conds = _build_conditions(_record(["E11.9", "E11.311"], primary="E11.311"), "pat-1", "US")
    assert sorted(_codes(conds)) == ["E11.311", "E11.9"]


def test_specific_primary_does_not_merge_into_other_specific_chronic() -> None:
    """E11.65 (hyperglycaemia) is not the chronic E11.9: both are emitted."""
    conds = _build_conditions(_record(["E11.9"], primary="E11.65"), "pat-1", "US")
    assert sorted(_codes(conds)) == ["E11.65", "E11.9"]
    ref = primary_condition_ref_from_codes("E11.65", ["E11.9"], "pat-1", "enc-1")
    assert ref != chronic_condition_id("pat-1", 0)


def test_specific_primary_merges_into_bare_category_chronic() -> None:
    """Chronic ``I50`` / primary ``I50.9`` is one disease at two granularities."""
    conds = _build_conditions(_record(["I50"], primary="I50.9"), "pat-1", "US")
    assert len(conds) == 1
    assert primary_condition_ref_from_codes("I50.9", ["I50"], "pat-1", "enc-1") == chronic_condition_id("pat-1", 0)


def test_unspecified_primary_merges_into_specific_chronic_of_the_category() -> None:
    """Primary I50.9 (unspecified) is superseded by the chronic I50.5."""
    conds = _build_conditions(_record(["I50.5"], primary="I50.9"), "pat-1", "US")
    assert len(conds) == 1
    assert primary_condition_ref_from_codes("I50.9", ["I50.5"], "pat-1", "enc-1") == chronic_condition_id("pat-1", 0)


def test_acute_primary_of_other_category_is_unaffected() -> None:
    conds = _build_conditions(_record(["E11.311"], primary="J18.9"), "pat-1", "US")
    assert sorted(_codes(conds)) == ["E11.311", "J18.9"]


def test_primary_resolves_to_exact_chronic_not_first_of_category() -> None:
    record = _record(["E11.9", "E11.311"], primary="E11.311")
    assert primary_condition_ref(record, "pat-1", "enc-1") == chronic_condition_id("pat-1", 1)
    assert primary_condition_ref_from_codes("E11.311", ["E11.9", "E11.311"], "pat-1", "enc-1") == chronic_condition_id(
        "pat-1", 1
    )


def test_jp_codes_mapping_to_one_emitted_code_collapse() -> None:
    from clinosim.locale.loaders.demographics import map_diagnosis_code

    # JP maps both CM leaves onto one MHLW code; they are one JP diagnosis.
    a, b = "E11.311", "E11.3"
    assert map_diagnosis_code(a, "JP") == map_diagnosis_code(b, "JP") == "E11.3"
    conds = _build_conditions(_record([a, b]), "pat-1", "JP")
    assert len(conds) == 1


def test_jp_distinct_mapped_codes_both_emit() -> None:
    from clinosim.locale.loaders.demographics import map_diagnosis_code

    assert map_diagnosis_code("E11.9", "JP") != map_diagnosis_code("E11.311", "JP")
    conds = _build_conditions(_record(["E11.9", "E11.311"]), "pat-1", "JP")
    assert len(conds) == 2
