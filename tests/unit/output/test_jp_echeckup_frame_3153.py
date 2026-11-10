"""JP health-checkup Composition frame and resolvable references (Issue #3153).

JP-eCheckup 1.7.0 JP_Composition_eCheckupGeneral requires: the
composition-clinicaldocument-versionNumber extension, meta.lastUpdated,
type = doc-typecodes 53576-5 only (display 検診・健診報告書), a category
from checkup-report-category, event.code from checkup-programService-code,
event.period.start, and section titles equal to the fixed values. The
Composition's author, Encounter location and department must resolve.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

pytestmark = pytest.mark.unit

_REPORT_CATEGORY = "urn:oid:1.2.392.200119.6.1001"
_PROGRAM_SERVICE = "urn:oid:1.2.392.200119.6.1002"
_DOC_TYPECODES = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_VERSION_EXT = "http://hl7.org/fhir/StructureDefinition/composition-clinicaldocument-versionNumber"


def _doc(checkup_type: str = "occupational") -> dict:
    return {
        "document_id": "doc-CHK-1-01",
        "loinc_code": "53576-5",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": "CHK-POP-000001-001",
        "author_practitioner_id": "DR-IM-001",
        "authored_datetime": "2026-04-15T11:00:00",
        "language": "ja",
        "period_start": "2026-04-15T11:00:00",
        "period_end": "2026-04-15T11:00:00",
        "checkup_type": checkup_type,
    }


def _comp(checkup_type: str = "occupational") -> dict:
    sections = {"checkup_lab_results": "検査結果", "checkup_questionnaire": "問診結果"}
    return _build_composition(_doc(checkup_type), sections, "ja")


def test_version_extension_and_last_updated() -> None:
    comp = _comp()
    assert {"url": _VERSION_EXT, "valueString": "1"} in comp["extension"]
    assert comp["meta"]["lastUpdated"]


def test_type_is_the_single_doc_typecodes_coding() -> None:
    assert _comp()["type"]["coding"] == [{"system": _DOC_TYPECODES, "code": "53576-5", "display": "検診・健診報告書"}]


@pytest.mark.parametrize(
    ("checkup_type", "category", "service"),
    [("occupational", "41", "030"), ("specific", "10", "010"), ("regional_union", "80", "020")],
)
def test_category_and_event_code_follow_the_checkup_type(checkup_type: str, category: str, service: str) -> None:
    comp = _comp(checkup_type)
    assert [c["coding"][0]["system"] for c in comp["category"]] == [_REPORT_CATEGORY]
    assert comp["category"][0]["coding"][0]["code"] == category
    assert len(comp["category"][0]["coding"]) == 1
    event = comp["event"][0]
    assert event["code"][0]["coding"][0]["system"] == _PROGRAM_SERVICE
    assert event["code"][0]["coding"][0]["code"] == service
    assert event["period"]["start"]


def test_section_titles_are_the_fixed_values() -> None:
    assert [s["title"] for s in _comp()["section"]] == ["事業者健診検査結果セクション", "事業者健診問診結果セクション"]


def test_the_facility_has_the_health_checkup_department() -> None:
    from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle
    from clinosim.simulator._setup import _load_hospital_ops as load_hospital_ops

    ids = {e["resource"]["id"] for e in _build_facility_bundle(load_hospital_ops(None), "JP")["entry"]}
    assert {"dept-health-checkup", "loc-dept-health-checkup"} <= ids


def test_the_health_checkup_department_has_no_physicians_of_its_own() -> None:
    import numpy as np

    from clinosim.modules.staff.engine import generate_roster
    from clinosim.simulator._setup import _load_hospital_ops as load_hospital_ops

    roster = generate_roster("medium", "JP", np.random.default_rng(1), hospital_config=load_hospital_ops(None))
    assert not [m for m in roster.members if m.department == "health_checkup"]


def test_the_checkup_has_a_real_attending_physician() -> None:
    import numpy as np

    from clinosim.modules.health_checkup.engine import _patient_selected, enrich_health_checkup
    from clinosim.modules.staff.engine import generate_roster
    from clinosim.simulator._setup import _load_hospital_ops as load_hospital_ops
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.config import SimulatorConfig
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    pid = next(f"POP-{i:06d}" for i in range(200) if _patient_selected(f"POP-{i:06d}"))
    roster = generate_roster("medium", "JP", np.random.default_rng(1), hospital_config=load_hospital_ops(None))
    record = CIFPatientRecord(patient=PatientProfile(patient_id=pid, age=50, sex="M"))
    ctx = EnricherContext(
        config=SimulatorConfig(country="JP", modules={"health_checkup": True}),
        master_seed=42,
        records=[record],
        roster=roster,
    )
    enrich_health_checkup(ctx)
    checkup = ctx.records[1]
    physicians = {m.staff_id: m for m in roster.members if m.role == "physician"}
    attending = checkup.encounters[0].attending_physician_id
    assert attending in physicians
    assert checkup.documents[0].author_practitioner_id == attending
