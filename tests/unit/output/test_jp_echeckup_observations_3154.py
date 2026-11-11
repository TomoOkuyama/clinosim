"""JP health-checkup results as JP-eCheckup Observations (Issue #3154).

The checkup encounter's lab / vital results are the eCheckup Observations:
one resource per measurement carrying its JLAC10 / LOINC coding and the
MHLW health-checkup item coding (urn:oid:1.2.392.200119.6.1005), declaring
JP_Observation_eCheckupGeneral, and referenced from the results section
(01031) of the health-checkup report. Item codes: MHLW XML用特定健診項目情報
(XMLhc18tab.csv).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

pytestmark = pytest.mark.unit

_ITEM_SYSTEM = "urn:oid:1.2.392.200119.6.1005"
_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Observation_eCheckupGeneral"


def _obs(lab_name: str, value: float, unit: str, intent: str = "health_checkup", country: str = "JP") -> dict:
    order = {"display_name": lab_name, "order_code": lab_name, "clinical_intent": intent, "encounter_id": "CHK-1"}
    result = {"lab_name": lab_name, "value": value, "unit": unit, "result_datetime": "2026-04-01T09:30:00"}
    obs = _build_lab_observation(order, result, "P1", 0, country, encounter_id="CHK-1")
    assert obs is not None
    return obs


@pytest.mark.parametrize(
    ("lab_name", "unit", "item"),
    [
        ("BMI", "kg/m2", "9N011000000000001"),
        ("SBP", "mmHg", "9A751000000000001"),
        ("DBP", "mmHg", "9A761000000000001"),
        ("HbA1c", "%", "3D046000001999902"),
        ("LDL", "mg/dL", "3F077000002391901"),
    ],
)
def test_a_checkup_result_carries_the_item_coding_and_the_profile(lab_name: str, unit: str, item: str) -> None:
    obs = _obs(lab_name, 100.0, unit)
    items = [c for c in obs["code"]["coding"] if c["system"] == _ITEM_SYSTEM]
    assert [c["code"] for c in items] == [item]
    assert items[0]["display"]
    assert _PROFILE in obs["meta"]["profile"]
    # A specimen test keeps its JLAC10 / LOINC coding; a body measurement
    # (BMI, blood pressure) carries the item code alone (Issue #3167).
    assert len(obs["code"]["coding"]) == (1 if lab_name in ("BMI", "SBP", "DBP") else 3)


def test_a_result_outside_the_checkup_is_not_an_echeckup_observation() -> None:
    obs = _obs("HbA1c", 6.0, "%", intent="")
    assert all(c["system"] != _ITEM_SYSTEM for c in obs["code"]["coding"])
    assert _PROFILE not in (obs.get("meta") or {}).get("profile", [])


def test_us_output_has_no_checkup_item_coding() -> None:
    obs = _obs("HbA1c", 6.0, "%", country="US")
    assert all(c["system"] != _ITEM_SYSTEM for c in obs["code"]["coding"])


def test_the_resource_index_buckets_by_declared_profile() -> None:
    from clinosim.modules.output.fhir_r4.documents.composition import _build_encounter_resource_index

    obs = {
        "resourceType": "Observation",
        "id": "lab-1",
        "meta": {"profile": [_PROFILE]},
        "encounter": {"reference": "Encounter/enc-1"},
        "code": {"text": "BMI"},
    }
    other = {"resourceType": "Observation", "id": "anthro-1", "encounter": {"reference": "Encounter/enc-1"}}
    index = _build_encounter_resource_index([{"resource": obs}, {"resource": other}])
    assert [r["reference"] for r in index["enc-1"][f"Observation|{_PROFILE}"]] == ["Observation/lab-1"]
    assert len(index["enc-1"]["Observation"]) == 2


def test_the_results_section_references_the_checkup_observations() -> None:
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = {
        "document_id": "doc-CHK-1-01",
        "loinc_code": "53576-5",
        "format_type": "composition",
        "patient_id": "POP-1",
        "encounter_id": "enc-1",
        "author_practitioner_id": "DR-IM-001",
        "authored_datetime": "2026-04-01T11:00:00",
        "language": "ja",
        "period_start": "2026-04-01T11:00:00",
        "checkup_type": "occupational",
    }
    refs = [{"reference": "Observation/lab-1"}, {"reference": "Observation/lab-2"}]
    # Issue #3163: the results section takes the report Observations by
    # category (laboratory / vital-signs); the questionnaire answers are
    # social-history and none are indexed here.
    index = {
        "enc-1": {
            f"Observation|{_PROFILE}": refs,
            f"Observation|{_PROFILE}|laboratory": refs,
            "Observation": refs + [{"reference": "Observation/a"}],
        }
    }
    sections = {"checkup_lab_results": "検査結果", "checkup_questionnaire": "問診"}
    comp = _build_composition(doc, sections, "ja", encounter_index=index, country="JP")
    by_code = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
    assert by_code["01031"]["entry"] == refs
    assert "entry" not in by_code["01032"]


def test_finishing_keeps_only_what_the_echeckup_profile_allows() -> None:
    from clinosim.modules.output.fhir_r4.builder import _finalize_resource

    obs = _obs("LDL", 120.0, "mg/dL")
    obs["basedOn"] = [{"reference": "ServiceRequest/sr-1"}]
    _finalize_resource(obs, "JP", {})
    assert "basedOn" not in obs
    systems = {i["system"] for i in obs["identifier"]}
    assert systems == {"http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"}


def test_a_lab_observation_outside_the_checkup_keeps_its_links() -> None:
    from clinosim.modules.output.fhir_r4.builder import _finalize_resource

    obs = _obs("LDL", 120.0, "mg/dL", intent="")
    obs["basedOn"] = [{"reference": "ServiceRequest/sr-1"}]
    _finalize_resource(obs, "JP", {})
    assert obs["basedOn"]
    assert len({i["system"] for i in obs["identifier"]}) > 1
