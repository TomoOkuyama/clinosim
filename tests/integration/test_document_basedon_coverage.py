"""Integration: subject / encounter ref integrity for document-chain resources.

Silent-no-op gate: if builders silently omit references, these asserts fire
immediately rather than requiring visual audit of the NDJSON output.

PR-90 / PR1 LAB Task 10 lesson: fail-loud BEFORE iterate.
Each test asserts that the NDJSON file is non-empty and that the target
reference key is present on at least one resource BEFORE iterating to check
every resolution.  An empty NDJSON would otherwise silently pass all
resolution checks (iterating over zero elements is vacuously true).

Checks:
- Every DocumentReference.subject → Patient resolves
- Every DocumentReference.context.encounter[0] → Encounter resolves
- Every Composition.subject → Patient resolves
- Every Composition.encounter → Encounter resolves (where present)
- Every ClinicalImpression.subject → Patient resolves
- Every ClinicalImpression.encounter → Encounter resolves (where present)
- Every AllergyIntolerance.patient → Patient resolves
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


def _ids(resources: list[dict]) -> set[str]:
    return {r["id"] for r in resources}


@pytest.mark.integration
def test_document_reference_subject_and_encounter_refs_resolve() -> None:
    """Every DocumentReference.subject resolves to Patient, and encounter to Encounter."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        patient_ids = _ids(load_ndjson(find_ndjson(out, "Patient.ndjson")))
        encounter_ids = _ids(load_ndjson(find_ndjson(out, "Encounter.ndjson")))
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))

        # Fail-loud BEFORE iterate (PR-90 / PR1 LAB Task 10 lesson)
        assert drefs, (
            "DocumentReference.ndjson is empty — cannot verify subject/encounter refs. "
            "Document enricher may not be firing (silent-no-op)."
        )
        assert any(d.get("subject") for d in drefs), (
            "No DocumentReference has a subject field — silent-no-op in builder"
        )

        dangling_subject: list[str] = []
        dangling_encounter: list[str] = []
        for dr in drefs:
            dr_id = dr.get("id", "?")
            subj = dr.get("subject", {}).get("reference", "")
            assert subj.startswith("Patient/"), (
                f"DocumentReference/{dr_id} subject must start with 'Patient/': {subj!r}"
            )
            pid = subj.removeprefix("Patient/")
            if pid not in patient_ids:
                dangling_subject.append(f"DocumentReference/{dr_id} -> Patient/{pid}")

            ctx_enc = (
                dr.get("context", {}).get("encounter", [{}])[0].get("reference", "")
                if dr.get("context")
                else ""
            )
            if ctx_enc:
                assert ctx_enc.startswith("Encounter/"), (
                    f"DocumentReference/{dr_id} context.encounter must start with 'Encounter/': "
                    f"{ctx_enc!r}"
                )
                eid = ctx_enc.removeprefix("Encounter/")
                if eid not in encounter_ids:
                    dangling_encounter.append(f"DocumentReference/{dr_id} -> Encounter/{eid}")

        assert not dangling_subject, (
            f"{len(dangling_subject)} dangling DocumentReference.subject refs:\n"
            + "\n".join(dangling_subject[:10])
        )
        assert not dangling_encounter, (
            f"{len(dangling_encounter)} dangling DocumentReference encounter refs:\n"
            + "\n".join(dangling_encounter[:10])
        )


@pytest.mark.integration
def test_composition_subject_and_encounter_refs_resolve() -> None:
    """Every Composition.subject resolves to Patient; encounter ref resolves where present."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        patient_ids = _ids(load_ndjson(find_ndjson(out, "Patient.ndjson")))
        encounter_ids = _ids(load_ndjson(find_ndjson(out, "Encounter.ndjson")))
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))

        # Fail-loud BEFORE iterate
        assert comps, (
            "Composition.ndjson is empty — cannot verify subject/encounter refs. "
            "Document enricher may not be firing (silent-no-op)."
        )
        assert any(c.get("subject") for c in comps), (
            "No Composition has a subject field — silent-no-op in builder"
        )

        dangling_subject: list[str] = []
        dangling_encounter: list[str] = []
        for comp in comps:
            comp_id = comp.get("id", "?")
            subj = comp.get("subject", {}).get("reference", "")
            assert subj.startswith("Patient/"), (
                f"Composition/{comp_id} subject must start with 'Patient/': {subj!r}"
            )
            pid = subj.removeprefix("Patient/")
            if pid not in patient_ids:
                dangling_subject.append(f"Composition/{comp_id} -> Patient/{pid}")

            enc_ref = comp.get("encounter", {}).get("reference", "") if comp.get("encounter") else ""
            if enc_ref:
                assert enc_ref.startswith("Encounter/"), (
                    f"Composition/{comp_id} encounter must start with 'Encounter/': {enc_ref!r}"
                )
                eid = enc_ref.removeprefix("Encounter/")
                if eid not in encounter_ids:
                    dangling_encounter.append(f"Composition/{comp_id} -> Encounter/{eid}")

        assert not dangling_subject, (
            f"{len(dangling_subject)} dangling Composition.subject refs:\n"
            + "\n".join(dangling_subject[:10])
        )
        assert not dangling_encounter, (
            f"{len(dangling_encounter)} dangling Composition encounter refs:\n"
            + "\n".join(dangling_encounter[:10])
        )


@pytest.mark.integration
def test_clinical_impression_subject_and_encounter_refs_resolve() -> None:
    """Every ClinicalImpression.subject resolves to Patient; encounter ref resolves."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        patient_ids = _ids(load_ndjson(find_ndjson(out, "Patient.ndjson")))
        encounter_ids = _ids(load_ndjson(find_ndjson(out, "Encounter.ndjson")))
        impressions = load_ndjson(find_ndjson(out, "ClinicalImpression.ndjson"))

        # Fail-loud BEFORE iterate
        assert impressions, (
            "ClinicalImpression.ndjson is empty — cannot verify subject/encounter refs. "
            "Document enricher may not be firing (silent-no-op)."
        )
        assert any(ci.get("subject") for ci in impressions), (
            "No ClinicalImpression has a subject field — silent-no-op in builder"
        )

        dangling_subject: list[str] = []
        dangling_encounter: list[str] = []
        for ci in impressions:
            ci_id = ci.get("id", "?")
            subj = ci.get("subject", {}).get("reference", "")
            assert subj.startswith("Patient/"), (
                f"ClinicalImpression/{ci_id} subject must start with 'Patient/': {subj!r}"
            )
            pid = subj.removeprefix("Patient/")
            if pid not in patient_ids:
                dangling_subject.append(f"ClinicalImpression/{ci_id} -> Patient/{pid}")

            enc_ref = ci.get("encounter", {}).get("reference", "") if ci.get("encounter") else ""
            if enc_ref:
                assert enc_ref.startswith("Encounter/"), (
                    f"ClinicalImpression/{ci_id} encounter must start with 'Encounter/': {enc_ref!r}"
                )
                eid = enc_ref.removeprefix("Encounter/")
                if eid not in encounter_ids:
                    dangling_encounter.append(f"ClinicalImpression/{ci_id} -> Encounter/{eid}")

        assert not dangling_subject, (
            f"{len(dangling_subject)} dangling ClinicalImpression.subject refs:\n"
            + "\n".join(dangling_subject[:10])
        )
        assert not dangling_encounter, (
            f"{len(dangling_encounter)} dangling ClinicalImpression encounter refs:\n"
            + "\n".join(dangling_encounter[:10])
        )


@pytest.mark.integration
def test_allergy_intolerance_patient_ref_resolves() -> None:
    """Every AllergyIntolerance.patient resolves to Patient.ndjson."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        patient_ids = _ids(load_ndjson(find_ndjson(out, "Patient.ndjson")))
        allergies = load_ndjson(find_ndjson(out, "AllergyIntolerance.ndjson"))

        # Fail-loud BEFORE iterate
        assert allergies, (
            "AllergyIntolerance.ndjson is empty — cannot verify patient refs. "
            "Allergy enricher or builder may not be firing (silent-no-op)."
        )
        assert any(a.get("patient") for a in allergies), (
            "No AllergyIntolerance has a patient field — silent-no-op in builder"
        )

        dangling: list[str] = []
        for ai in allergies:
            ai_id = ai.get("id", "?")
            pat_ref = ai.get("patient", {}).get("reference", "")
            assert pat_ref.startswith("Patient/"), (
                f"AllergyIntolerance/{ai_id} patient must start with 'Patient/': {pat_ref!r}"
            )
            pid = pat_ref.removeprefix("Patient/")
            if pid not in patient_ids:
                dangling.append(f"AllergyIntolerance/{ai_id} -> Patient/{pid}")

        assert not dangling, (
            f"{len(dangling)} dangling AllergyIntolerance.patient refs:\n"
            + "\n".join(dangling[:10])
        )


@pytest.mark.integration
def test_all_document_refs_have_required_fields() -> None:
    """Each DocumentReference must have id, status, type, subject, content fields."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        if not drefs:
            pytest.skip("No DocumentReference resources emitted for n=100 cohort")
        for dr in drefs:
            dr_id = dr.get("id", "?")
            assert dr.get("status") == "current", (
                f"DocumentReference/{dr_id} expected status='current', "
                f"got {dr.get('status')!r}"
            )
            assert dr.get("type"), f"DocumentReference/{dr_id} missing type"
            assert dr.get("subject"), f"DocumentReference/{dr_id} missing subject"
            content = dr.get("content", [])
            assert content, f"DocumentReference/{dr_id} missing content"
            assert content[0].get("attachment", {}).get("data"), (
                f"DocumentReference/{dr_id} attachment.data is empty "
                "(base64 text must be present)"
            )
