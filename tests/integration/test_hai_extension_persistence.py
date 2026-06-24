"""Integration: HAIEvent serializable; CIF extensions round-trip (PR-B)."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from clinosim.types.hai import HAIEvent
from clinosim.types.output import CIFPatientRecord


pytestmark = pytest.mark.integration


def test_hai_event_serializable_via_asdict():
    ev = HAIEvent(
        hai_id="hai-e1-clabsi-0", encounter_id="e1",
        hai_type="clabsi", source_device_id="dev-e1-cvc-0",
        icd10_code="T80.211A", snomed_code="736442006",
        onset_date="2026-01-04", organism_snomed="112283007",
        culture_specimen_id="spec-hai-hai-e1-clabsi-0",
    )
    d = asdict(ev)
    assert d["hai_id"] == "hai-e1-clabsi-0"
    assert d["onset_date"] == "2026-01-04"


def test_cif_patient_record_extensions_round_trip(tmp_path):
    rec = CIFPatientRecord()
    rec.extensions["hai"] = [
        HAIEvent(
            hai_id="hai-e1-cauti-0", encounter_id="e1",
            hai_type="cauti", source_device_id="dev-e1-cath-0",
            icd10_code="T83.511A", snomed_code="68566005",
            onset_date="2026-01-04", organism_snomed="112283007",
            culture_specimen_id="spec-hai-hai-e1-cauti-0",
        ),
    ]
    serialised = {"extensions": {"hai": [asdict(h) for h in rec.extensions["hai"]]}}
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(serialised))
    loaded = json.loads(path.read_text())
    assert loaded["extensions"]["hai"][0]["hai_type"] == "cauti"
    assert loaded["extensions"]["hai"][0]["organism_snomed"] == "112283007"
