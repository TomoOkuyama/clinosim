"""Integration tests: nursing shift note 3-per-day cadence (α-min-3).

Two layers:
1. Full pipeline (run-beta → FHIR): per-encounter DocumentReference count
   invariant for PROGRESS_NOTE (11506-3, freq=daily) vs NURSING_SHIFT_NOTE
   (34746-8, freq=daily_3shift). Since Issue #337 (session 62) the two
   frequencies have ASYMMETRIC LOS/skip semantics:

     LOS == 1: progress=1, shift=0
       - daily emits at LOS=1 (Issue #337, eDS Composition
         hospitalCourseSection.entry min=1 target を確保)
       - daily_3shift は LOS=1 skip (3-per-day cadence を保つため)
     LOS >= 2: progress=LOS, shift=3*LOS

   したがって cohort-level の単純な "shift == 3 × progress" は成立
   しない(LOS=1 encounter を持つ cohort で必ず崩れる)。encounter 単位で
   LOS-conditional に check する必要がある。この test はその per-encounter
   invariant を pin する。
2. Stage 1 → write_cif → Stage 2 TemplateNarrativePass: the neutral shift key
   survives the structural CIF JSON round-trip and renders as distinct
   localized labels (en: night/day/evening, ja: 深夜/日勤/準夜) per AD-65 /
   AD-30 spirit.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate

_LOINC_PROGRESS_NOTE = "11506-3"
_LOINC_NURSING_SHIFT_NOTE = "34746-8"


def _loinc_codes(dref: dict) -> set[str]:
    return {c.get("code") for c in dref.get("type", {}).get("coding", [])}


def _dref_encounter_id(dref: dict) -> str:
    """FHIR DocumentReference.context.encounter[0].reference の末尾 id."""
    ctx = dref.get("context") or {}
    enc_list = ctx.get("encounter") or []
    ref = enc_list[0].get("reference", "") if enc_list else ""
    if not ref:
        ref = (dref.get("encounter") or {}).get("reference", "")
    return ref.rsplit("/", 1)[-1]


@pytest.mark.integration
def test_progress_and_shift_note_per_encounter_los_invariant() -> None:
    """Per-encounter PROGRESS_NOTE / NURSING_SHIFT_NOTE counts must match the
    LOS-conditional formula documented in ``document/engine.py`` (Issue #337).

    Uses ``_compute_los_days`` from the implementation so the test's LOS
    definition can never drift from the emit-side logic.
    """
    # Import the implementation's LOS calculator — never re-implement it
    # test-side. This keeps the assertion tied to whatever definition the
    # emit path actually uses.
    from clinosim.modules.document.engine import _compute_los_days

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)

        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        encounters = {e["id"]: e for e in load_ndjson(find_ndjson(out, "Encounter.ndjson"))}
        assert drefs, "DocumentReference.ndjson is empty — document enricher not firing"
        assert encounters, "Encounter.ndjson is empty"

        # Collect per-encounter progress + shift note counts. An encounter
        # that emits NEITHER is silently absent (allowlist mismatch or the
        # non-inpatient path); we only assert on encounters that fired at
        # least one of the two specs (i.e. those in the allowlist —
        # inpatient / icu / rehab_inpatient).
        per_enc: dict[str, dict[str, int]] = defaultdict(lambda: {"progress": 0, "shift": 0})
        for d in drefs:
            codes = _loinc_codes(d)
            eid = _dref_encounter_id(d)
            if not eid:
                continue
            if _LOINC_PROGRESS_NOTE in codes:
                per_enc[eid]["progress"] += 1
            if _LOINC_NURSING_SHIFT_NOTE in codes:
                per_enc[eid]["shift"] += 1

        assert per_enc, "No PROGRESS_NOTE or NURSING_SHIFT_NOTE emitted in any encounter"

        # For each encounter that emitted at least one relevant note,
        # look up its Encounter.period → LOS and assert the invariant.
        # In-progress encounters (Encounter.period.end absent — AD-32
        # snapshot truncation) compute LOS from `physiological_states`,
        # which is not FHIR-visible; those cannot be verified from FHIR
        # output alone and are scoped out of this test.
        checked_los1 = 0
        checked_los_ge_2 = 0
        skipped_in_progress = 0
        for eid, cnt in per_enc.items():
            enc = encounters.get(eid)
            if enc is None:
                pytest.fail(f"DocumentReference references unknown encounter {eid!r}")
            period = enc.get("period") or {}
            admit_s = period.get("start", "")
            disch_s = period.get("end", "")
            assert admit_s, f"{eid}: Encounter.period.start missing"
            if not disch_s:
                # In-progress: LOS = f(physiological_states) which is not
                # emitted to FHIR. This test cannot recompute the LOS the
                # emitter used, so skip. Completed encounters cover the
                # invariant we care about.
                skipped_in_progress += 1
                continue
            admit_dt = datetime.fromisoformat(admit_s.replace("Z", "+00:00"))
            disch_dt = datetime.fromisoformat(disch_s.replace("Z", "+00:00"))
            # `physiological_states=[]` is safe on the completed-encounter
            # code path: the discharge branch returns
            # `max(1, (disch.date - admit.date).days)` without touching the
            # empty list. Feeding [] on the in-progress branch would silently
            # return 1, which is why we filter in-progress out above.
            los = _compute_los_days(admit_dt, disch_dt, [])

            if los == 1:
                # Issue #337 asymmetry: daily emits at LOS=1, daily_3shift skips.
                assert cnt["progress"] == 1, (
                    f"{eid} LOS=1: expected 1 PROGRESS_NOTE (Issue #337), got {cnt['progress']}"
                )
                assert cnt["shift"] == 0, (
                    f"{eid} LOS=1: expected 0 NURSING_SHIFT_NOTE "
                    f"(daily_3shift skips LOS<=1 to preserve 3-per-day cadence), "
                    f"got {cnt['shift']}"
                )
                checked_los1 += 1
            elif los >= 2:
                assert cnt["progress"] == los, (
                    f"{eid} LOS={los}: expected {los} PROGRESS_NOTE (1 per LOS day), "
                    f"got {cnt['progress']}"
                )
                assert cnt["shift"] == 3 * los, (
                    f"{eid} LOS={los}: expected {3 * los} NURSING_SHIFT_NOTE "
                    f"(3 per LOS day: night 00:00 / day 08:00 / evening 16:00), "
                    f"got {cnt['shift']}"
                )
                checked_los_ge_2 += 1
            else:
                # `_compute_los_days` floors at 1 for both discharged and
                # in-progress encounters, so los in {0} should not appear.
                pytest.fail(
                    f"{eid}: unexpected LOS={los} "
                    f"(_compute_los_days floors at 1; check whether the implementation changed)"
                )

        # At least one LOS>=2 encounter must be present or the invariant
        # for daily_3shift is untested by this cohort. LOS=1 encounters are
        # optional (cohort-dependent) but when present must satisfy the
        # asymmetry assertion above.
        assert checked_los_ge_2 > 0, (
            f"No LOS>=2 encounters in cohort — the 3× shift invariant is untested. "
            f"Grow the population or seed to include multi-day admissions."
        )


def _run_stage1_and_stage2(tmp: str, country: str) -> dict[str, dict]:
    """document_enricher → write_cif → TemplateNarrativePass; return narrative payloads.

    Returns {document_id: narrative_json} for the nursing_shift_note stubs only.
    """
    from clinosim.modules.document.engine import document_enricher
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType
    from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    enc = Encounter(
        encounter_id="ENC-3shift-1",
        patient_id="POP-3shift",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.COMPLETED,
        attending_physician_id="DR-3shift",
        admission_datetime=datetime(2026, 7, 1, 14, 30),
        discharge_datetime=datetime(2026, 7, 3, 11, 0),
    )
    enc.primary_nurse_id = "NS-3shift"
    patient = PatientProfile(
        patient_id="POP-3shift",
        age=70,
        sex="F",
        date_of_birth=date(1956, 1, 1),
    )
    record = CIFPatientRecord(patient=patient, encounters=[enc])

    ctx = SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country=country),
    )
    document_enricher(ctx)

    shift_stubs = [d for d in record.documents if d.task_type == "nursing_shift_note"]
    assert len(shift_stubs) == 6, (  # LOS=2 days × 3 shifts
        f"Expected 6 shift-note stubs for LOS=2, got {len(shift_stubs)}"
    )

    dataset = CIFDataset(
        metadata=CIFMetadata(
            clinosim_version="0.2",
            generation_timestamp=datetime(2026, 7, 3, 12, 0),
            random_seed=42,
            country=country.upper(),
            hospital_scale="medium",
            total_patients_generated=1,
        ),
        patients=[record],
        hospital_roster=[],
        hospital_config={},
    )
    write_cif(dataset, tmp)
    TemplateNarrativePass(cif_dir=tmp, country=country.upper(), rng_seed=42).run()

    narratives: dict[str, dict] = {}
    for stub in shift_stubs:
        path = Path(tmp) / "narratives" / "template" / "documents" / enc.encounter_id / f"{stub.document_id}.json"
        assert path.is_file(), f"Stage 2 did not write narrative for {stub.document_id}"
        narratives[stub.document_id] = json.loads(path.read_text())
    return narratives


@pytest.mark.integration
def test_stage2_renders_distinct_ja_shift_labels() -> None:
    """JP path: 深夜 / 日勤 / 準夜 all appear; per-day 3 notes are pairwise distinct."""
    with tempfile.TemporaryDirectory() as tmp:
        narratives = _run_stage1_and_stage2(tmp, country="jp")
        texts = [n["narrative"]["text"] for n in narratives.values()]
        joined = "\n".join(texts)
        for label in ("深夜", "日勤", "準夜"):
            assert label in joined, f"JP shift label {label} missing from narratives"
        assert len(set(texts)) >= 3, "The 3 same-day JP shift notes must be pairwise distinct (shift label)"


@pytest.mark.integration
def test_stage2_renders_distinct_en_shift_labels() -> None:
    """US path: night / day / evening labels appear; notes pairwise distinct, no JA chars."""
    with tempfile.TemporaryDirectory() as tmp:
        narratives = _run_stage1_and_stage2(tmp, country="us")
        texts = [n["narrative"]["text"] for n in narratives.values()]
        joined = "\n".join(texts)
        for label in ("night", "day", "evening"):
            assert label in joined.lower(), f"EN shift label {label!r} missing"
        assert len(set(texts)) >= 3, "The 3 same-day EN shift notes must be pairwise distinct (shift label)"
        assert not any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in joined), "US shift notes must be 100% English"
