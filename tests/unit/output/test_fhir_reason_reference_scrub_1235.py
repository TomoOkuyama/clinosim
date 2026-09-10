"""Issue #1235: `_scrub_refs_one_pass` also cleans MR/MA/Procedure.reasonReference[].

The scrubber pass (`_scrub_refs_one_pass`, PR #1226) covered Composition
section entries, DiagnosticReport.result, MR/SR.basedOn, MA.request
cascade, and DocumentReference.context.related. PR #1232 added Encounter
diagnosis[] + reasonReference. Missed: MR / MA / Procedure own
``reasonReference`` list.

S105 final audit v3 (p=10k s=329, 2025-09-10 → 2026-09-10) surfaced 118
JP + 31 US dangling reasonReference refs — in-hospital-death case where
the target Condition drops via `_dt_fields` gate (recordedDate > dod)
but MR / MA / Procedure themselves are event-timestamped ≤ dod (they
were prescribed / administered / performed on the day of death), so they
survive and end up with dangling reasonReference. Adding the three
resource types to `_SCRUB_LIST_REF_FIELDS_BY_TYPE` closes the gap
(symmetric with existing scrubbable list fields).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import _drop_entries_after_death

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"resource": resource}


def _post_mortem_condition() -> dict:
    return {
        "resourceType": "Condition",
        "id": "cond-postmortem",
        "recordedDate": "2025-10-25T10:00:00",
    }


def _live_condition() -> dict:
    return {
        "resourceType": "Condition",
        "id": "cond-alive",
        "recordedDate": "2025-10-21T08:00:00",
    }


def test_medication_request_reason_reference_scrubbed() -> None:
    mr = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "authoredOn": "2025-10-22T08:00:00",
        "reasonReference": [
            {"reference": "Condition/cond-postmortem"},
            {"reference": "Condition/cond-alive"},
        ],
    }
    kept = _drop_entries_after_death(
        [_entry(_post_mortem_condition()), _entry(mr), _entry(_live_condition())],
        "2025-10-22",
    )
    mr_res = next(e["resource"] for e in kept if e["resource"]["id"] == "mr-1")
    refs = [r["reference"] for r in mr_res.get("reasonReference", [])]
    assert refs == ["Condition/cond-alive"]


def test_medication_administration_reason_reference_scrubbed() -> None:
    ma = {
        "resourceType": "MedicationAdministration",
        "id": "ma-1",
        "effectivePeriod": {"start": "2025-10-22T08:00:00"},
        "reasonReference": [
            {"reference": "Condition/cond-postmortem"},
            {"reference": "Condition/cond-alive"},
        ],
    }
    kept = _drop_entries_after_death(
        [_entry(_post_mortem_condition()), _entry(ma), _entry(_live_condition())],
        "2025-10-22",
    )
    ma_res = next(e["resource"] for e in kept if e["resource"]["id"] == "ma-1")
    refs = [r["reference"] for r in ma_res.get("reasonReference", [])]
    assert refs == ["Condition/cond-alive"]


def test_procedure_reason_reference_scrubbed() -> None:
    proc = {
        "resourceType": "Procedure",
        "id": "proc-1",
        "performedDateTime": "2025-10-22T09:00:00",
        "reasonReference": [
            {"reference": "Condition/cond-postmortem"},
            {"reference": "Condition/cond-alive"},
        ],
    }
    kept = _drop_entries_after_death(
        [_entry(_post_mortem_condition()), _entry(proc), _entry(_live_condition())],
        "2025-10-22",
    )
    proc_res = next(e["resource"] for e in kept if e["resource"]["id"] == "proc-1")
    refs = [r["reference"] for r in proc_res.get("reasonReference", [])]
    assert refs == ["Condition/cond-alive"]


def test_mr_basedon_still_scrubbed_after_1235() -> None:
    """Regression guard: pre-existing MR.basedOn scrub still works."""
    canceled_sr = {
        "resourceType": "ServiceRequest",
        "id": "sr-canceled",
        "authoredOn": "2025-10-25",
    }
    mr = {
        "resourceType": "MedicationRequest",
        "id": "mr-basedon",
        "authoredOn": "2025-10-22T08:00:00",
        "basedOn": [{"reference": "ServiceRequest/sr-canceled"}],
    }
    kept = _drop_entries_after_death([_entry(canceled_sr), _entry(mr)], "2025-10-22")
    mr_res = next(e["resource"] for e in kept if e["resource"]["id"] == "mr-basedon")
    assert mr_res.get("basedOn", []) == []


def test_procedure_report_still_scrubbed_after_1235() -> None:
    """Regression guard: pre-existing Procedure.report scrub still works."""
    postmortem_dr = {
        "resourceType": "DiagnosticReport",
        "id": "dr-postmortem",
        "issued": "2025-10-25",
    }
    proc = {
        "resourceType": "Procedure",
        "id": "proc-with-report",
        "performedDateTime": "2025-10-22T09:00:00",
        "report": [{"reference": "DiagnosticReport/dr-postmortem"}],
    }
    kept = _drop_entries_after_death([_entry(postmortem_dr), _entry(proc)], "2025-10-22")
    proc_res = next(e["resource"] for e in kept if e["resource"]["id"] == "proc-with-report")
    assert proc_res.get("report", []) == []
