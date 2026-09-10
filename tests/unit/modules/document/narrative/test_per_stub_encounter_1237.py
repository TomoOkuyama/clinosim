"""Issue #1237: narrative pass binds each stub to its OWN encounter context.

Before this fix, `_run_unit` in `passes.py` used `encounters[0]` for every
stub in a patient, so companion vaccination encounters (`ENC-VAX-*`,
S104 PR #1214) and synth ED-bridge encounters got the parent IMP
encounter's `chief_complaint` / `clinical_course_archetype` /
`admission_datetime` leaked into their narrative content — the emitted
document's `encounter_id` was even overwritten with the primary
encounter id (a data-quality regression above the content one).

S105 final v3 audit (US p=10k s=329) surfaced 5,521 VAX narrative files
where the subjective section said things like "76-year-old male with
sudden weakness / speech difficulty" (a stroke narrative) on a
Vaccination visit encounter. This test pins the fix.

Approach: exercise `_run_unit` behavior by constructing a two-encounter
patient (primary IMP + companion VAX), stubbing `_build_context` to
record which encounter it was called with, and asserting the pass
produces one result per stub, each anchored to its stub's own encounter
id.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _mk_patient_with_vax_encounter() -> dict[str, Any]:
    return {
        "patient": {
            "patient_id": "POP-000001",
            "sex": "F",
            "date_of_birth": "1970-01-15",
        },
        "encounters": [
            {
                "encounter_id": "ENC-POP-000001-imp",
                "encounter_type": "inpatient",
                "status": "finished",
                "admission_datetime": "2025-10-05T08:00:00",
                "discharge_datetime": "2025-10-15T12:00:00",
                "chief_complaint": "Chest pain",
                "chief_complaint_ja": "胸痛",
                "clinical_course_archetype": "uncomplicated_improvement",
                "severity": "moderate",
            },
            {
                "encounter_id": "ENC-VAX-POP-000001-abcd1234",
                "encounter_type": "outpatient",
                "status": "finished",
                "admission_datetime": "2026-03-01T10:00:00",
                "discharge_datetime": "2026-03-01T10:30:00",
                "chief_complaint": "Vaccination visit",
                "chief_complaint_ja": "予防接種",
                "admission_diagnosis_code": "Z23",
                "admission_diagnosis_system": "icd-10-cm",
            },
        ],
        "documents": [
            {
                "document_id": "doc-imp-1",
                "task_type": "outpatient_soap",
                "loinc_code": "34131-3",
                "patient_id": "POP-000001",
                "encounter_id": "ENC-POP-000001-imp",
                "authored_datetime": "2025-10-05T08:00:00",
                "period_start": "2025-10-05T08:00:00",
                "period_end": "2025-10-05T08:30:00",
                "language": "en",
                "format_type": "composition",
            },
            {
                "document_id": "doc-vax-1",
                "task_type": "outpatient_soap",
                "loinc_code": "34131-3",
                "patient_id": "POP-000001",
                "encounter_id": "ENC-VAX-POP-000001-abcd1234",
                "authored_datetime": "2026-03-01T10:00:00",
                "period_start": "2026-03-01T10:00:00",
                "period_end": "2026-03-01T10:30:00",
                "language": "en",
                "format_type": "composition",
            },
        ],
        "orders": [],
        "medication_administrations": [],
        "physiological_states": [],
        "vital_signs": [],
    }


def test_per_stub_encounter_binding_via_run_unit(monkeypatch) -> None:
    """Each stub must be rendered with its OWN encounter context.

    Records the encounter_id argument to `_build_context` (via monkeypatch)
    and verifies both encounter contexts get built (parent IMP + VAX
    companion). Also monkeypatches `_write` to a no-op so we exercise
    the pass logic without touching serialization details.
    """
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    patient = _mk_patient_with_vax_encounter()

    build_ctx_calls: list[str] = []
    written_encounter_ids: list[str] = []

    def _fake_build_context(self, patient_dict, encounter_dict, spec, language):
        _eid = encounter_dict.get("encounter_id", "__none__")
        build_ctx_calls.append(_eid)
        return SimpleNamespace(shift="", day_index=0, related_procedure_id="", _enc=_eid)

    def _fake_generate(self, ctx, spec):
        return SimpleNamespace(sections={"subjective": f"for {ctx._enc}"})

    def _fake_output_to_wrapper(self, output, generator):
        return SimpleNamespace(sections=output.sections, generator=generator, generator_metadata={})

    def _fake_write(self, narrative_dir, encounter_id, stub, wrapper, spec):
        written_encounter_ids.append(encounter_id)

    monkeypatch.setattr(TemplateNarrativePass, "_build_context", _fake_build_context)
    monkeypatch.setattr(TemplateNarrativePass, "_generate", _fake_generate)
    monkeypatch.setattr(TemplateNarrativePass, "_output_to_wrapper", _fake_output_to_wrapper)
    monkeypatch.setattr(TemplateNarrativePass, "_write", _fake_write)

    with tempfile.TemporaryDirectory() as tmp:
        structural_dir = os.path.join(tmp, "structural", "patients")
        os.makedirs(structural_dir, exist_ok=True)
        with open(os.path.join(structural_dir, "POP-000001.json"), "w") as f:
            json.dump(patient, f)
        os.makedirs(os.path.join(tmp, "narratives"), exist_ok=True)

        pass_ = TemplateNarrativePass(cif_dir=tmp, version_id="test-1237")
        pass_.run()

    # `_build_context` was called with BOTH encounter ids (cache dedups
    # within an encounter, so the set — not the list length — is the
    # regression check).
    assert set(build_ctx_calls) == {
        "ENC-POP-000001-imp",
        "ENC-VAX-POP-000001-abcd1234",
    }, f"expected both encounter contexts to be built, got {build_ctx_calls}"

    # Written narrative files carry each stub's OWN encounter_id (was:
    # both stubs got the primary IMP id — VAX narrative was mis-filed).
    assert set(written_encounter_ids) == {
        "ENC-POP-000001-imp",
        "ENC-VAX-POP-000001-abcd1234",
    }, f"expected per-stub encounter_id on written narratives, got {written_encounter_ids}"
