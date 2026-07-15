"""AD-65 Bug B (Task 12) integration test: nursing docs author = nurse.

Session 27 clinical-integrity review found 23,279 nursing docs (LOINC
34746-8 nursing_shift_note / 78390-2 admission_nursing_assessment /
34745-0 nursing_discharge_summary) had author = attending_physician_id
instead of primary_nurse_id. Generates a small US inpatient-heavy cohort
and verifies every FHIR resource for a nursing LOINC has an author
reference pointing at a nurse staff member, not the attending physician.

Two resource types must be checked: admission_nursing_assessment and
nursing_discharge_summary are format_type=composition (-> Composition),
but nursing_shift_note is format_type=free_text (-> DocumentReference)
per document_type_specs.yaml. Checking only Composition.ndjson would
silently miss the nursing_shift_note regression.

NOTE: an early draft of this task used LOINC 34119-8 for
nursing_discharge_summary. That code was verified-rejected during Task 8
(clinosim/codes/data/loinc.yaml: "Nursing facility Initial evaluation
note" — SNF, not hospital); the correct code, matching
document_type_specs.yaml and clinosim/types/document.py, is 34745-0.

Nurse staff_id format is "NS-<DEPT>-<idx>" (clinosim/modules/staff/engine.py
_add_nurse), distinct from physician "DR-<DEPT>-<idx>" — the check below
looks for the "NS-" prefix on the Practitioner reference, not a
speculative "nurse-"/"RN-" substring.
"""

import json
import subprocess
import sys

import pytest

_NURSING_LOINCS = {"34746-8", "78390-2", "34745-0"}


def _check_ndjson(path, bad_refs):
    """Return (total, nurse_authored) for nursing-LOINC resources in an NDJSON file."""
    total = 0
    nurse_authored = 0
    if not path.exists():
        return total, nurse_authored
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        codings = d.get("type", {}).get("coding", [])
        loincs = {c.get("code") for c in codings}
        if not (loincs & _NURSING_LOINCS):
            continue
        total += 1
        matched = False
        for author in d.get("author", []):
            ref = author.get("reference", "")
            if ref.startswith("Practitioner/NS-"):
                matched = True
                break
        if matched:
            nurse_authored += 1
        else:
            bad_refs.append((path.name, d.get("id", ""), [a.get("reference", "") for a in d.get("author", [])]))
    return total, nurse_authored


@pytest.mark.integration
def test_nursing_docs_author_reference_nurse(tmp_path):
    out = tmp_path / "us500"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "generate",
            "-p",
            "500",
            "--country",
            "US",
            "-o",
            str(out),
            "--format",
            "cif",
            "fhir-r4",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert r.returncode == 0, r.stderr

    fhir_dir = out / "fhir_r4"
    bad_refs: list = []

    comp_total, comp_ok = _check_ndjson(fhir_dir / "Composition.ndjson", bad_refs)
    dref_total, dref_ok = _check_ndjson(fhir_dir / "DocumentReference.ndjson", bad_refs)

    total_nurse_docs = comp_total + dref_total
    nurse_authored = comp_ok + dref_ok

    if total_nurse_docs == 0:
        pytest.skip("cohort produced no nursing docs (p=500 too small)")

    assert nurse_authored == total_nurse_docs, (
        f"{total_nurse_docs - nurse_authored}/{total_nurse_docs} nursing docs "
        f"have non-nurse author; sample bad refs: {bad_refs[:5]}"
    )
