"""P2-13 PR2a Task 3: JP discharge summary narrative render.

Uses the AD-66 canonical JP inpatient fixture (bacterial pneumonia) to
drive the full run_forced pipeline and confirm the discharge summary
ClinicalDocument gets the 5 JP-CLINS section keys populated by the
template narrative pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def jp_bacterial_pneumonia_documents():
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.modules.output.cif_reader import CIFReader
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import SimulatorConfig, load_patient_profile
    import tempfile
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    profile_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "patient_profiles"
        / "jp_inpatient_bacterial_pneumonia.yaml"
    )
    profile = load_patient_profile(str(profile_path))
    scenario = profile.to_forced_scenario()
    scenario = scenario.__class__(**{**scenario.__dict__, "count": 3})
    config = SimulatorConfig(
        random_seed=profile.random_seed,
        country=profile.country,
        hospital_scale=profile.hospital_scale,
        catchment_population=3,
    )
    dataset = run_forced(scenario, config)

    tmproot = tempfile.mkdtemp(prefix="jp-clins-narr-")
    cif_dir = Path(tmproot) / "cif"
    write_cif(dataset, str(cif_dir))
    # Run the Stage 2 template narrative pass to populate narrative subtree.
    TemplateNarrativePass(cif_dir=str(cif_dir), country=profile.country).run()
    reader = CIFReader(str(cif_dir), narrative_version="current")
    docs = []
    for record in reader.iter_patients():
        for doc in record.get("documents", []) or []:
            if doc.get("loinc_code") == "18842-5":
                docs.append(doc)
    return docs


@pytest.mark.unit
def test_jp_discharge_summary_has_5_required_sections(jp_bacterial_pneumonia_documents):
    assert jp_bacterial_pneumonia_documents, (
        "expected at least one JP discharge summary in the fixture cohort"
    )
    expected = {
        "admission_reason",
        "admission_details",
        "admission_diagnoses",
        "chief_complaint",
        "present_illness",
    }
    for doc in jp_bacterial_pneumonia_documents:
        narr = doc.get("narrative") or {}
        secs = narr.get("sections") or {}
        assert set(secs.keys()) == expected, (
            f"unexpected JP DS section keys for {doc.get('document_id')}: "
            f"{sorted(secs.keys())}"
        )


@pytest.mark.unit
def test_jp_discharge_summary_sections_have_content(jp_bacterial_pneumonia_documents):
    for doc in jp_bacterial_pneumonia_documents:
        narr = doc.get("narrative") or {}
        secs = narr.get("sections") or {}
        for key, text in secs.items():
            assert text and text.strip(), (
                f"empty section {key!r} on {doc.get('document_id')}"
            )
