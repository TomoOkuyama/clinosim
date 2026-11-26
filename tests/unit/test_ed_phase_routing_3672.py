"""Issue #3672: orders, results, doses and procedures dated in the ED window of
a via-ED admission belong to the ED bridge Encounter, not the inpatient one."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import reattribute_ed_phase_by_time
from clinosim.modules.triage.engine import admitted_ed_stay

pytestmark = pytest.mark.unit

_IMP = "ENC-POP-000001-111"
_IMP_REF = f"Encounter/{resolve_encounter_id(_IMP)}"
_ED_REF = f"Encounter/{resolve_encounter_id(f'{_IMP}-ED')}"
_ADM = "2026-03-24T10:37:00"


def _ctx(admit_source: str = "emd"):
    return SimpleNamespace(
        record={"encounters": [{"encounter_id": _IMP, "admit_source": admit_source, "admission_datetime": _ADM}]}
    )


def _in_window() -> str:
    from datetime import datetime

    return (datetime.fromisoformat(_ADM) - admitted_ed_stay() / 2).isoformat() + "Z"


def _resources(t: str) -> list[dict]:
    enc = {"reference": _IMP_REF}
    return [
        {"resourceType": "Observation", "effectiveDateTime": t, "encounter": dict(enc)},
        {"resourceType": "ServiceRequest", "authoredOn": t, "encounter": dict(enc)},
        {"resourceType": "DiagnosticReport", "effectiveDateTime": t, "encounter": dict(enc)},
        {"resourceType": "MedicationRequest", "authoredOn": t, "encounter": dict(enc)},
        # The real builder emits ``context`` (R4 MedicationAdministration), never ``encounter``.
        {"resourceType": "MedicationAdministration", "effectiveDateTime": t, "context": dict(enc)},
        {"resourceType": "ImagingStudy", "started": t, "encounter": dict(enc)},
        {"resourceType": "Procedure", "performedPeriod": {"start": t}, "encounter": dict(enc)},
    ]


def _ref(r: dict) -> str:
    """The Encounter reference a resource carries (``context`` for a MedicationAdministration)."""
    return (r["context"] if r["resourceType"] == "MedicationAdministration" else r["encounter"])["reference"]


def test_ed_window_resources_land_on_the_ed_bridge() -> None:
    ctx = _ctx()
    for r in _resources(_in_window()):
        reattribute_ed_phase_by_time(r, ctx)
        assert _ref(r) == _ED_REF, r["resourceType"]


def test_at_or_after_admission_stays_on_inpatient() -> None:
    ctx = _ctx()
    for t in (_ADM + "+09:00", "2026-03-24T11:00:00Z"):
        for r in _resources(t):
            reattribute_ed_phase_by_time(r, ctx)
            assert _ref(r) == _IMP_REF, r["resourceType"]


def test_direct_admission_untouched() -> None:
    ctx = _ctx("outp")
    for r in _resources(_in_window()):
        reattribute_ed_phase_by_time(r, ctx)
        assert _ref(r) == _IMP_REF


def test_before_the_window_and_unparsable_time_stay() -> None:
    ctx = _ctx()
    for r in _resources("2026-03-20T00:00:00Z"):
        reattribute_ed_phase_by_time(r, ctx)
        assert _ref(r) == _IMP_REF
    r = {"resourceType": "Observation", "encounter": {"reference": _IMP_REF}}
    reattribute_ed_phase_by_time(r, ctx)
    assert r["encounter"]["reference"] == _IMP_REF


def test_documents_are_not_time_routed_and_walker_is_idempotent() -> None:
    ctx = _ctx()
    doc = {"resourceType": "Composition", "date": _in_window(), "encounter": {"reference": _IMP_REF}}
    reattribute_ed_phase_by_time(doc, ctx)
    assert doc["encounter"]["reference"] == _IMP_REF
    obs = _resources(_in_window())[0]
    reattribute_ed_phase_by_time(obs, ctx)
    reattribute_ed_phase_by_time(obs, ctx)
    assert obs["encounter"]["reference"] == _ED_REF


def test_other_encounter_reference_untouched() -> None:
    ctx = _ctx()
    other = f"Encounter/{resolve_encounter_id('OTHER')}"
    r = {"resourceType": "Observation", "effectiveDateTime": _in_window(), "encounter": {"reference": other}}
    reattribute_ed_phase_by_time(r, ctx)
    assert r["encounter"]["reference"] == other


_STUDY_ID = "imgst-ENC-POP-000001-111-0"


def _imaging_ctx(started: str, admit_source: str = "emd"):
    ctx = _ctx(admit_source)
    ctx.record["extensions"] = {"imaging": [{"study_id": _STUDY_ID, "started_datetime": started}]}
    return ctx


def _imaging_report(date: str) -> dict:
    from clinosim.modules.output.fhir_r4.labs.imaging_study import imaging_study_id_for_cif_study_id

    return {
        "resourceType": "Composition",
        "type": {"coding": [{"system": "http://loinc.org", "code": "18748-4"}]},
        "date": date,
        "encounter": {"reference": _IMP_REF},
        "section": [{"entry": [{"reference": f"ImagingStudy/{imaging_study_id_for_cif_study_id(_STUDY_ID)}"}]}],
    }


def test_imaging_report_follows_its_study_not_its_report_time() -> None:
    """The report is issued after admission, but the study it describes ran in the ED."""
    ctx = _imaging_ctx(_in_window().removesuffix("Z"))
    comp = _imaging_report(_ADM + "+01:00")  # report time after admission
    reattribute_ed_phase_by_time(comp, ctx)
    assert comp["encounter"]["reference"] == _ED_REF


def test_imaging_report_of_a_study_after_admission_stays() -> None:
    ctx = _imaging_ctx("2026-03-24T11:00:00")
    comp = _imaging_report(_in_window())  # even a report dated in the window stays with a ward study
    reattribute_ed_phase_by_time(comp, ctx)
    assert comp["encounter"]["reference"] == _IMP_REF


def test_imaging_report_direct_admission_and_unlinked_report_untouched() -> None:
    comp = _imaging_report(_in_window())
    reattribute_ed_phase_by_time(comp, _imaging_ctx(_in_window().removesuffix("Z"), "outp"))
    assert comp["encounter"]["reference"] == _IMP_REF
    comp = _imaging_report(_in_window())
    comp["section"] = []
    reattribute_ed_phase_by_time(comp, _imaging_ctx(_in_window().removesuffix("Z")))
    assert comp["encounter"]["reference"] == _IMP_REF
