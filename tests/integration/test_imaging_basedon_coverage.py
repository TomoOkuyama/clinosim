"""Integration: basedOn / endpoint ref integrity for imaging resources.

Silent-no-op gate: if builders silently omit references, these asserts fire
immediately rather than requiring visual audit of the NDJSON output.

Checks:
- Every ImagingStudy.basedOn → ServiceRequest resolves
- Every ImagingStudy.endpoint → Endpoint resolves
- Every radiology DiagnosticReport.basedOn → ServiceRequest resolves
- Every radiology DiagnosticReport.imagingStudy → ImagingStudy resolves
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


def _ids(resources: list[dict]) -> set[str]:
    return {r["id"] for r in resources}


@pytest.mark.integration
def test_every_imaging_study_basedon_resolves() -> None:
    """ImagingStudy.basedOn[ServiceRequest] must resolve within ServiceRequest.ndjson."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        sr_ids = _ids(load_ndjson(find_ndjson(out, "ServiceRequest.ndjson")))
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted — cannot verify basedOn")
        dangling: list[str] = []
        for study in studies:
            assert study.get("basedOn"), (
                f"ImagingStudy/{study.get('id')} missing basedOn ref (silent-no-op)"
            )
            for ref in study["basedOn"]:
                sr_id = ref["reference"].removeprefix("ServiceRequest/")
                if sr_id not in sr_ids:
                    dangling.append(f"ImagingStudy/{study['id']} -> ServiceRequest/{sr_id}")
        assert not dangling, (
            f"{len(dangling)} dangling ImagingStudy.basedOn references:\n"
            + "\n".join(dangling[:10])
        )


@pytest.mark.integration
def test_every_imaging_study_endpoint_resolves() -> None:
    """ImagingStudy.endpoint[Endpoint] must resolve within Endpoint.ndjson."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        endpoint_ids = _ids(load_ndjson(find_ndjson(out, "Endpoint.ndjson")))
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted — cannot verify endpoint refs")
        dangling: list[str] = []
        for study in studies:
            assert study.get("endpoint"), (
                f"ImagingStudy/{study.get('id')} missing endpoint ref (silent-no-op)"
            )
            for ref in study["endpoint"]:
                ep_id = ref["reference"].removeprefix("Endpoint/")
                if ep_id not in endpoint_ids:
                    dangling.append(f"ImagingStudy/{study['id']} -> Endpoint/{ep_id}")
        assert not dangling, (
            f"{len(dangling)} dangling ImagingStudy.endpoint references:\n"
            + "\n".join(dangling[:10])
        )


@pytest.mark.integration
def test_every_radiology_dr_basedon_resolves() -> None:
    """Radiology DR.basedOn[ServiceRequest] must resolve within ServiceRequest.ndjson."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        sr_ids = _ids(load_ndjson(find_ndjson(out, "ServiceRequest.ndjson")))
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        if not rad_drs:
            pytest.skip("No radiology DiagnosticReport resources emitted")
        dangling: list[str] = []
        for dr in rad_drs:
            assert dr.get("basedOn"), (
                f"DiagnosticReport/{dr['id']} missing basedOn ref (silent-no-op)"
            )
            for ref in dr["basedOn"]:
                sr_id = ref["reference"].removeprefix("ServiceRequest/")
                if sr_id not in sr_ids:
                    dangling.append(f"DiagnosticReport/{dr['id']} -> ServiceRequest/{sr_id}")
        assert not dangling, (
            f"{len(dangling)} dangling radiology DR.basedOn references:\n"
            + "\n".join(dangling[:10])
        )


@pytest.mark.integration
def test_every_radiology_dr_imagingstudy_resolves() -> None:
    """Radiology DR.imagingStudy[ImagingStudy] must resolve within ImagingStudy.ndjson."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        study_ids = _ids(load_ndjson(find_ndjson(out, "ImagingStudy.ndjson")))
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        if not rad_drs:
            pytest.skip("No radiology DiagnosticReport resources emitted")
        dangling: list[str] = []
        for dr in rad_drs:
            assert dr.get("imagingStudy"), (
                f"DiagnosticReport/{dr['id']} missing imagingStudy ref (silent-no-op)"
            )
            for ref in dr["imagingStudy"]:
                st_id = ref["reference"].removeprefix("ImagingStudy/")
                if st_id not in study_ids:
                    dangling.append(f"DiagnosticReport/{dr['id']} -> ImagingStudy/{st_id}")
        assert not dangling, (
            f"{len(dangling)} dangling radiology DR.imagingStudy references:\n"
            + "\n".join(dangling[:10])
        )


@pytest.mark.integration
def test_imaging_study_outgoing_patient_encounter_refs_resolve() -> None:
    """ImagingStudy.subject + encounter refs must resolve within their NDJSON files."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        patient_ids = _ids(load_ndjson(find_ndjson(out, "Patient.ndjson")))
        encounter_ids = _ids(load_ndjson(find_ndjson(out, "Encounter.ndjson")))
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted — cannot verify outgoing refs")
        for study in studies:
            study_id = study.get("id", "?")
            subj = study.get("subject", {}).get("reference", "")
            assert subj.startswith("Patient/"), (
                f"ImagingStudy/{study_id} subject must start with 'Patient/': {subj!r}"
            )
            pid = subj.removeprefix("Patient/")
            assert pid in patient_ids, (
                f"ImagingStudy/{study_id} dangling Patient ref Patient/{pid}"
            )
            enc = study.get("encounter", {}).get("reference", "")
            assert enc.startswith("Encounter/"), (
                f"ImagingStudy/{study_id} encounter must start with 'Encounter/': {enc!r}"
            )
            eid = enc.removeprefix("Encounter/")
            assert eid in encounter_ids, (
                f"ImagingStudy/{study_id} dangling Encounter ref Encounter/{eid}"
            )
