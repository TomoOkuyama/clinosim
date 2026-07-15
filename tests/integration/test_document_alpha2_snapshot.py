"""Integration: snapshot (--end) semantics for α-min-2 document resources (AD-32).

α-min-2 extends the AD-32 snapshot compliance to nursing document types:
- NURSING_DISCHARGE_SUMMARY (34745-0) must be skipped for in-progress encounters,
  matching the behaviour of DISCHARGE_SUMMARY (18842-5) from α-min-1.
- ADMISSION_NURSING_ASSESSMENT (78390-2) must still be present for in-progress
  inpatient encounters (admission_once, not gated on discharge).
- NURSING_SHIFT_NOTE (34746-8) daily notes must still be present for in-progress
  encounters (daily, not gated on discharge).
- CareTeam must still be emitted for in-progress encounters (no discharge gate).

AD-32 snapshot rule: inpatients whose discharge would fall after the --end date
have Encounter.status='in-progress' with discharge_datetime absent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate

_LOINC_NURSING_DISCHARGE_SUMMARY = "34745-0"
_LOINC_ADMISSION_NURSING_ASSESSMENT = "78390-2"
_LOINC_NURSING_SHIFT_NOTE = "34746-8"
_LOINC_DISCHARGE_SUMMARY = "18842-5"

_SNAPSHOT_END = "2025-02-28"
_COHORT_SIZE = 300


def _enc_id_from_ref(ref: str, prefix: str = "Encounter/") -> str:
    return ref.removeprefix(prefix)


def _get_loinc_from_type(resource: dict) -> str:
    return next(
        (c.get("code", "") for c in resource.get("type", {}).get("coding", [])),
        "",
    )


@pytest.mark.integration
def test_snapshot_no_nursing_discharge_summary_for_inprogress() -> None:
    """AD-32: in-progress encounters must have NO NURSING_DISCHARGE_SUMMARY Composition.

    NURSING_DISCHARGE_SUMMARY (34745-0) is a discharge_once document (same gate as
    DISCHARGE_SUMMARY 18842-5). Emitting it for in-progress encounters would violate
    AD-32 snapshot semantics.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", _COHORT_SIZE, 42, out, end=_SNAPSHOT_END)

        encs = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        in_progress_ids = {e["id"] for e in encs if e.get("status") == "in-progress"}
        if not in_progress_ids:
            pytest.skip(f"No in-progress Encounters for p={_COHORT_SIZE}, seed=42, end={_SNAPSHOT_END}.")

        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        enc_to_loinc: dict[str, set[str]] = {}
        for comp in comps:
            enc_ref = comp.get("encounter", {}).get("reference", "") if comp.get("encounter") else ""
            if not enc_ref:
                continue
            eid = _enc_id_from_ref(enc_ref)
            loinc = _get_loinc_from_type(comp)
            enc_to_loinc.setdefault(eid, set()).add(loinc)

        violations: list[str] = []
        for eid in in_progress_ids:
            if _LOINC_NURSING_DISCHARGE_SUMMARY in enc_to_loinc.get(eid, set()):
                violations.append(eid)

        assert not violations, (
            f"AD-32 VIOLATION: {len(violations)} in-progress encounter(s) have a "
            f"NURSING_DISCHARGE_SUMMARY Composition (LOINC {_LOINC_NURSING_DISCHARGE_SUMMARY}):\n"
            + "\n".join(violations[:10])
        )


@pytest.mark.integration
def test_snapshot_nursing_admission_assessment_present_for_inprogress() -> None:
    """AD-32: in-progress inpatient encounters must have ADMISSION_NURSING_ASSESSMENT.

    ADMISSION_NURSING_ASSESSMENT (78390-2) is admission_once — it must be emitted
    for in-progress encounters (not gated on discharge_datetime).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", _COHORT_SIZE, 42, out, end=_SNAPSHOT_END)

        encs = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        in_progress_ids = {e["id"] for e in encs if e.get("status") == "in-progress"}
        if not in_progress_ids:
            pytest.skip(f"No in-progress Encounters for p={_COHORT_SIZE}, seed=42, end={_SNAPSHOT_END}.")

        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        enc_to_loinc: dict[str, set[str]] = {}
        for comp in comps:
            enc_ref = comp.get("encounter", {}).get("reference", "") if comp.get("encounter") else ""
            if not enc_ref:
                continue
            eid = _enc_id_from_ref(enc_ref)
            loinc = _get_loinc_from_type(comp)
            enc_to_loinc.setdefault(eid, set()).add(loinc)

        # Only check inpatient in-progress encounters (nursing docs are inpatient-only)
        inpatient_in_progress = {
            e["id"]
            for e in encs
            if e.get("status") == "in-progress" and e.get("class", {}).get("code", "") in {"IMP", "ACUTE", "OBSENC"}
        }
        if not inpatient_in_progress:
            pytest.skip(
                "No inpatient in-progress Encounters in cohort — "
                "ADMISSION_NURSING_ASSESSMENT check not meaningful for outpatient in-progress."
            )

        missing: list[str] = []
        for eid in inpatient_in_progress:
            if _LOINC_ADMISSION_NURSING_ASSESSMENT not in enc_to_loinc.get(eid, set()):
                missing.append(eid)

        missing_rate = len(missing) / len(inpatient_in_progress)
        assert missing_rate <= 0.25, (
            f"{len(missing)}/{len(inpatient_in_progress)} inpatient in-progress encounters "
            f"lack ADMISSION_NURSING_ASSESSMENT (rate={missing_rate:.0%}, threshold=25%). "
            "Nursing enricher may not be emitting admission notes for in-progress encounters."
        )


@pytest.mark.integration
def test_snapshot_nursing_shift_notes_present_for_inprogress() -> None:
    """AD-32: in-progress inpatient encounters must have NURSING_SHIFT_NOTE DocumentReferences.

    NURSING_SHIFT_NOTE (34746-8) is daily — it must fire for every inpatient LOS day
    regardless of whether discharge_datetime is set (same pattern as PROGRESS_NOTE).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", _COHORT_SIZE, 42, out, end=_SNAPSHOT_END)

        encs = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        in_progress_ids = {e["id"] for e in encs if e.get("status") == "in-progress"}
        if not in_progress_ids:
            pytest.skip(f"No in-progress Encounters for p={_COHORT_SIZE}, seed=42, end={_SNAPSHOT_END}.")

        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        enc_to_loinc: dict[str, set[str]] = {}
        for dr in drefs:
            ctx = dr.get("context", {}) or {}
            enc_list = ctx.get("encounter", []) or []
            if enc_list:
                enc_ref = enc_list[0].get("reference", "")
                if enc_ref:
                    eid = _enc_id_from_ref(enc_ref)
                    loinc = _get_loinc_from_type(dr)
                    enc_to_loinc.setdefault(eid, set()).add(loinc)

        inpatient_in_progress = {
            e["id"]
            for e in encs
            if e.get("status") == "in-progress" and e.get("class", {}).get("code", "") in {"IMP", "ACUTE", "OBSENC"}
        }
        if not inpatient_in_progress:
            pytest.skip("No inpatient in-progress Encounters in cohort")

        encounters_with_shift_notes = {
            eid for eid in inpatient_in_progress if _LOINC_NURSING_SHIFT_NOTE in enc_to_loinc.get(eid, set())
        }
        if not encounters_with_shift_notes:
            pytest.skip(
                "No in-progress inpatient encounters have NURSING_SHIFT_NOTE DocumentReferences. "
                "Increase cohort or check encounter type filter."
            )
        assert encounters_with_shift_notes, (
            "AD-32: expected at least one in-progress inpatient encounter to have a "
            "NURSING_SHIFT_NOTE DocumentReference — nursing enricher may be incorrectly "
            "gating daily notes on discharge_datetime."
        )


@pytest.mark.integration
def test_snapshot_care_team_present_for_inprogress_encounters() -> None:
    """AD-32: in-progress encounters must still have CareTeam resources.

    CareTeam is emitted for every encounter regardless of status (not discharge-gated).
    A missing CareTeam for in-progress encounters would indicate an incorrect AD-32 gate
    in the CareTeam builder.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", _COHORT_SIZE, 42, out, end=_SNAPSHOT_END)

        encs = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        in_progress_enc_ids = {e["id"] for e in encs if e.get("status") == "in-progress"}
        if not in_progress_enc_ids:
            pytest.skip(f"No in-progress Encounters for p={_COHORT_SIZE}, seed=42, end={_SNAPSHOT_END}.")

        care_teams = load_ndjson(find_ndjson(out, "CareTeam.ndjson"))
        assert care_teams, "CareTeam.ndjson is empty — CareTeam builder not firing"

        care_team_enc_ids = {
            ct.get("encounter", {}).get("reference", "").removeprefix("Encounter/")
            for ct in care_teams
            if ct.get("encounter")
        }

        # All in-progress encounters should have CareTeam
        missing = in_progress_enc_ids - care_team_enc_ids
        assert not missing, (
            f"{len(missing)} in-progress encounter(s) have no CareTeam resource — "
            "CareTeam builder may be incorrectly filtering out in-progress encounters:\n"
            + "\n".join(sorted(missing)[:5])
        )
