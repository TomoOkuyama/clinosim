"""Integration tests: nursing shift note 3-per-day cadence (α-min-3).

Two layers:
1. Full pipeline (run-beta → FHIR): NURSING_SHIFT_NOTE (34746-8)
   DocumentReference count == 3 × PROGRESS_NOTE (11506-3) count. Both specs
   share frequency semantics (per LOS day, LOS=1 skip, inpatient/icu/rehab
   allowlist), so the daily_3shift cadence makes the ratio exactly 3.
2. Stage 1 → write_cif → Stage 2 TemplateNarrativePass: the neutral shift key
   survives the structural CIF JSON round-trip and renders as distinct
   localized labels (en: night/day/evening, ja: 深夜/日勤/準夜) per AD-65 /
   AD-30 spirit.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate

_LOINC_PROGRESS_NOTE = "11506-3"
_LOINC_NURSING_SHIFT_NOTE = "34746-8"


def _loinc_codes(dref: dict) -> set[str]:
    return {c.get("code") for c in dref.get("type", {}).get("coding", [])}


@pytest.mark.integration
def test_shift_note_count_is_exactly_3x_progress_note_count() -> None:
    """Full pipeline: shift-note DocumentReferences == 3 × progress-note ones."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        assert drefs, "DocumentReference.ndjson is empty — document enricher not firing"
        n_progress = sum(1 for d in drefs if _LOINC_PROGRESS_NOTE in _loinc_codes(d))
        n_shift = sum(1 for d in drefs if _LOINC_NURSING_SHIFT_NOTE in _loinc_codes(d))
        assert n_progress > 0, "No PROGRESS_NOTE DocumentReferences in cohort"
        assert n_shift == 3 * n_progress, (
            f"Expected NURSING_SHIFT_NOTE count == 3 × PROGRESS_NOTE count "
            f"(daily_3shift vs daily, same LOS/skip semantics), "
            f"got shift={n_shift} vs progress={n_progress}"
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
        patient_id="POP-3shift", age=70, sex="F", date_of_birth=date(1956, 1, 1),
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
        path = (
            Path(tmp) / "narratives" / "template" / "documents"
            / enc.encounter_id / f"{stub.document_id}.json"
        )
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
        assert len(set(texts)) >= 3, (
            "The 3 same-day JP shift notes must be pairwise distinct (shift label)"
        )


@pytest.mark.integration
def test_stage2_renders_distinct_en_shift_labels() -> None:
    """US path: night / day / evening labels appear; notes pairwise distinct, no JA chars."""
    with tempfile.TemporaryDirectory() as tmp:
        narratives = _run_stage1_and_stage2(tmp, country="us")
        texts = [n["narrative"]["text"] for n in narratives.values()]
        joined = "\n".join(texts)
        for label in ("night", "day", "evening"):
            assert label in joined.lower(), f"EN shift label {label!r} missing"
        assert len(set(texts)) >= 3, (
            "The 3 same-day EN shift notes must be pairwise distinct (shift label)"
        )
        assert not any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in joined), (
            "US shift notes must be 100% English"
        )
