"""A lab panel report reports the results of one Encounter (Issue #3958).

A patient admitted from the emergency department has two FHIR Encounters on the
admission day: the ED bridge (``[admission - admitted_ed_stay(), admission)``)
and the inpatient stay. A panel's same-day members, grouped by panel and day,
used to be reported in one DiagnosticReport on the inpatient Encounter although
some of its results and orders belong to the ED Encounter.
"""

from __future__ import annotations

from datetime import datetime

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports, group_lab_orders
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs
from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import (
    ed_window_of_record,
    reattribute_ed_phase_by_time,
    time_in_ed_window,
)

_IMP = "ENC-IMP-1"
_ADMISSION = "2026-06-27T12:57:00"
# admitted_ed_stay() is 210 minutes: the ED window is 09:27 to 12:57.
_ED_TIMES = ["2026-06-27T09:28:00", "2026-06-27T09:30:00", "2026-06-27T09:31:00"]
_WARD_TIMES = ["2026-06-27T13:04:00", "2026-06-27T13:05:00", "2026-06-27T13:06:00"]


def _record(orders: list[dict], via_ed: bool = True) -> dict:
    return {
        "orders": orders,
        "encounters": [
            {
                "encounter_id": _IMP,
                "encounter_type": "inpatient",
                "admit_source": "emd" if via_ed else "outp",
                "admission_datetime": _ADMISSION,
                "discharge_datetime": "2026-07-02T10:00:00",
            }
        ],
    }


def _lab(lab_name: str, when: str, idx: int, panel_key: str = "") -> dict:
    return {
        "order_id": f"O-{idx}",
        "encounter_id": _IMP,
        "patient_id": "P1",
        "order_type": "lab",
        "order_code": lab_name,
        "display_name": lab_name,
        "urgency": "routine",
        "ordered_datetime": when,
        "ordered_by": "doc1",
        "status": "resulted",
        "panel_key": panel_key,
        "result": {"result_datetime": when, "performed_by": "tech1", "lab_name": lab_name, "value": 6.0, "unit": "u"},
    }


def _cbc_draw(times: list[str], first_idx: int) -> list[dict]:
    return [_lab(name, t, first_idx + i) for i, (name, t) in enumerate(zip(["WBC", "Hb", "Hct"], times, strict=True))]


def _ctx(record: dict) -> BundleContext:
    return BundleContext(
        record=record,
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=_IMP,
        patient_sex="",
    )


def test_same_day_ed_and_ward_members_of_a_panel_are_two_groups() -> None:
    orders = _cbc_draw(_ED_TIMES, 0) + _cbc_draw(_WARD_TIMES, 3)
    window = ed_window_of_record(_record(orders))
    assert window is not None
    groups = [g for g in group_lab_orders(orders, _IMP, window) if g.panel_name == "CBC"]
    assert [g.obs_idxs for g in groups] == [[0, 1, 2], [3, 4, 5]]
    assert groups[0].effective_datetime == _ED_TIMES[-1]
    assert groups[1].effective_datetime == _WARD_TIMES[-1]


def test_a_panel_split_across_the_boundary_is_not_one_report() -> None:
    # CBC: WBC, Hb drawn in the ED, Hct, Plt after admission (the issue's JP case)
    orders = [
        _lab("WBC", _ED_TIMES[0], 0),
        _lab("Hb", _ED_TIMES[1], 1),
        _lab("Hct", _WARD_TIMES[0], 2),
        _lab("Plt", _WARD_TIMES[1], 3),
    ]
    window = ed_window_of_record(_record(orders))
    groups = group_lab_orders(orders, _IMP, window)
    # Neither side reaches the 3-component CBC minimum; no report spans both.
    for g in groups:
        phases = {time_in_ed_window(window, orders[i]["ordered_datetime"]) for i in g.obs_idxs}
        assert len(phases) == 1


def test_without_an_ed_window_the_grouping_is_unchanged() -> None:
    orders = _cbc_draw(_ED_TIMES, 0) + _cbc_draw(_WARD_TIMES, 3)
    merged = [g for g in group_lab_orders(orders, _IMP) if g.panel_name == "CBC"]
    assert len(merged) == 1 and merged[0].obs_idxs == [0, 1, 2]
    assert group_lab_orders(orders, _IMP) == group_lab_orders(orders, _IMP, None)


def test_every_reference_of_a_report_stays_within_one_encounter() -> None:
    record = _record(_cbc_draw(_ED_TIMES, 0) + _cbc_draw(_WARD_TIMES, 3))
    ctx = _ctx(record)
    reports = build_lab_panel_reports(ctx)
    observations = _bb_labs(ctx)
    requests = _bb_service_requests(ctx)
    resources = reports + observations + requests
    for resource in resources:
        reattribute_ed_phase_by_time(resource, ctx)
    encounter_of = {f"{r['resourceType']}/{r['id']}": r["encounter"]["reference"] for r in resources}
    panel_reports = [r for r in reports if r["code"]["coding"][0]["code"] == "58410-2"]
    assert len(panel_reports) == 2
    assert len({r["encounter"]["reference"] for r in panel_reports}) == 2
    for report in reports:
        refs = [x["reference"] for x in report["result"] + report["basedOn"]]
        assert {encounter_of[r] for r in refs} == {report["encounter"]["reference"]}, report["id"]


def test_a_stay_not_admitted_through_the_ed_keeps_its_one_group() -> None:
    record = _record(_cbc_draw(_ED_TIMES, 0) + _cbc_draw(_WARD_TIMES, 3), via_ed=False)
    assert ed_window_of_record(record) is None


def test_time_in_ed_window_is_half_open() -> None:
    window = (datetime(2026, 6, 27, 9, 27), datetime(2026, 6, 27, 12, 57))
    assert time_in_ed_window(window, "2026-06-27T09:27:00")
    assert time_in_ed_window(window, datetime(2026, 6, 27, 12, 56, 59))
    assert not time_in_ed_window(window, "2026-06-27T12:57:00")
    assert not time_in_ed_window(None, "2026-06-27T10:00:00")
