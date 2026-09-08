"""MedicationRequest emit-time dedup (Issue #1177).

247 (patient, authoredOn) buckets in the JP p=10000 sample emit
≥2 MedicationRequests whose drug + dose + route are byte-identical
because multiple CIF order sources (chronic list + episode-specific
+ inpatient add-on) converge on the same effective order. The
post-build dedup drops later duplicates by (drug text, authoredOn
date, first-dosage text, first-route code).
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.lib.inline_bb import _dedup_medication_requests


def _mk_mr(drug: str, day: str, dose: str = "", route_code: str = "", mr_id: str = "") -> dict:
    di: dict = {"text": dose} if dose else {}
    if route_code:
        di["route"] = {"coding": [{"code": route_code}]}
    mr = {
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {"text": drug},
        "authoredOn": day,
        "dosageInstruction": [di],
    }
    if mr_id:
        mr["id"] = mr_id
    return mr


def test_no_duplicates_returns_list_unchanged() -> None:
    mrs = [
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg 経口 1日1回", "26643006"),
        _mk_mr("メトホルミン", "2025-11-17", "500mg 経口 1日2回", "26643006"),
    ]
    assert len(_dedup_medication_requests(mrs)) == 2


def test_exact_duplicate_dropped() -> None:
    mrs = [
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg 経口 1日1回", "26643006", mr_id="mr-a"),
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg 経口 1日1回", "26643006", mr_id="mr-b"),
    ]
    result = _dedup_medication_requests(mrs)
    assert len(result) == 1
    # First occurrence kept
    assert result[0]["id"] == "mr-a"


def test_different_dose_kept() -> None:
    # IV loading + PO maintenance = legitimate two-order case.
    mrs = [
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg 経口 1日1回", "26643006"),
        _mk_mr("プレドニゾロン", "2025-11-17", "60mg 静注 1日1回", "47625008"),
    ]
    assert len(_dedup_medication_requests(mrs)) == 2


def test_different_day_kept() -> None:
    mrs = [
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg 経口 1日1回", "26643006"),
        _mk_mr("プレドニゾロン", "2025-11-18", "40mg 経口 1日1回", "26643006"),
    ]
    assert len(_dedup_medication_requests(mrs)) == 2


def test_different_route_kept() -> None:
    mrs = [
        _mk_mr("メトホルミン", "2025-11-17", "500mg 1日2回", "26643006"),
        _mk_mr("メトホルミン", "2025-11-17", "500mg 1日2回", "47625008"),
    ]
    assert len(_dedup_medication_requests(mrs)) == 2


def test_case_insensitive_drug_match() -> None:
    mrs = [
        _mk_mr("Prednisolone", "2025-11-17", "40 mg PO daily", "26643006"),
        _mk_mr("prednisolone", "2025-11-17", "40 mg po daily", "26643006"),
    ]
    assert len(_dedup_medication_requests(mrs)) == 1


def test_authored_on_with_time_and_tz_normalizes_to_date() -> None:
    # authoredOn may be a datetime with TZ; the key should compare on
    # date-precision only.
    mrs = [
        _mk_mr("プレドニゾロン", "2025-11-17T09:00:00+09:00", "40mg", "26643006"),
        _mk_mr("プレドニゾロン", "2025-11-17T17:30:00+09:00", "40mg", "26643006"),
    ]
    assert len(_dedup_medication_requests(mrs)) == 1


def test_empty_drug_text_row_passes_through() -> None:
    # Cannot dedup without a drug identity — those rows pass through.
    mr_empty = {
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {"text": ""},
        "authoredOn": "2025-11-17",
        "dosageInstruction": [{"text": "40mg"}],
    }
    mrs = [mr_empty, mr_empty]  # even a "duplicate" empty stays
    assert len(_dedup_medication_requests(mrs)) == 2


def test_three_way_duplicate_collapses_to_one() -> None:
    mrs = [
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg", "26643006", mr_id="mr-a"),
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg", "26643006", mr_id="mr-b"),
        _mk_mr("プレドニゾロン", "2025-11-17", "40mg", "26643006", mr_id="mr-c"),
    ]
    result = _dedup_medication_requests(mrs)
    assert len(result) == 1
    assert result[0]["id"] == "mr-a"
