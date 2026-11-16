"""Issue #3276: a narrative's ``generated_at`` is the document's own time.

The narrative pass used to stamp every document with 2020-01-01 plus
``rng_seed`` seconds, years before the encounter it describes. The stamp is
now the stub's ``authored_datetime`` (else its ``period_end``, else the
encounter's discharge time) with the country's timezone suffix, the same
representation FHIR ``DocumentReference.date`` uses. It stays deterministic
for identical inputs and no longer depends on ``rng_seed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _write(tmp_path: Path, document: dict[str, Any], encounter_extra: dict[str, Any] | None = None) -> None:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    encounter = {
        "encounter_id": "ENC-1",
        "encounter_type": {"value": "inpatient"},
        "attending_physician_id": "DR-1",
        "admission_diagnosis_code": "I21.4",
        "admission_datetime": "2026-01-09T09:00:00",
    }
    encounter.update(encounter_extra or {})
    payload = {
        "patient": {"patient_id": "POP-000001", "age": 65, "sex": "M", "chronic_conditions": []},
        "encounters": [encounter],
        "documents": [
            {
                "document_id": "doc-1",
                "task_type": "admission_hp",
                "loinc_code": "34117-2",
                "narrative": None,
                "format_type": "composition",
                **document,
            }
        ],
        "vitals": [],
        "lab_results": [],
        "medications": [],
        "diagnoses": [],
        "procedures": [],
        "allergies": [],
    }
    (structural / "ENC-1.json").write_text(json.dumps(payload, ensure_ascii=False))


def _generated_at(tmp_path: Path, country: str = "US", rng_seed: int = 42) -> str:
    TemplateNarrativePass(cif_dir=str(tmp_path), country=country, rng_seed=rng_seed).run()
    payload = json.loads((tmp_path / "narratives/template/documents/ENC-1/doc-1.json").read_text())
    return payload["narrative"]["generated_at"]


@pytest.mark.unit
def test_generated_at_is_authored_datetime_us(tmp_path: Path) -> None:
    _write(tmp_path, {"authored_datetime": "2026-01-09T10:30:00", "period_end": "2026-01-09T11:00:00"})
    assert _generated_at(tmp_path, "US") == "2026-01-09T10:30:00Z"


@pytest.mark.unit
def test_generated_at_carries_the_country_timezone_jp(tmp_path: Path) -> None:
    _write(tmp_path, {"authored_datetime": "2026-01-09T10:30:00"})
    assert _generated_at(tmp_path, "JP") == "2026-01-09T10:30:00+09:00"


@pytest.mark.unit
def test_generated_at_falls_back_to_period_end(tmp_path: Path) -> None:
    _write(tmp_path, {"period_start": "2026-01-09T08:00:00", "period_end": "2026-01-09T09:15:00"})
    assert _generated_at(tmp_path, "US") == "2026-01-09T09:15:00Z"


@pytest.mark.unit
def test_generated_at_falls_back_to_encounter_discharge(tmp_path: Path) -> None:
    _write(tmp_path, {}, {"discharge_datetime": "2026-01-14T11:00:00"})
    assert _generated_at(tmp_path, "US") == "2026-01-14T11:00:00Z"


@pytest.mark.unit
def test_generated_at_empty_when_no_document_time(tmp_path: Path) -> None:
    """No time on the stub or the encounter end: left empty, never invented."""
    _write(tmp_path, {})
    assert _generated_at(tmp_path, "US") == ""


@pytest.mark.unit
def test_generated_at_does_not_depend_on_rng_seed(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    other = tmp_path_factory.mktemp("other_seed")
    for d in (tmp_path, other):
        _write(d, {"authored_datetime": "2026-01-09T10:30:00"})
    assert _generated_at(tmp_path, "US", rng_seed=1) == _generated_at(other, "US", rng_seed=500)


@pytest.mark.unit
def test_generated_at_keeps_an_explicit_offset(tmp_path: Path) -> None:
    _write(tmp_path, {"authored_datetime": "2026-01-09T10:30:00+09:00"})
    assert _generated_at(tmp_path, "JP") == "2026-01-09T10:30:00+09:00"
