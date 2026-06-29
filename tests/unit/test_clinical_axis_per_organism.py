"""Unit tests for clinosim.audit.axes.clinical per-organism helpers
(PR3b-3 chain completion D1 + D2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import clinical
from clinosim.audit.types import Cohort


def _write(path: Path, country: str, file: str, rows: list[dict]) -> None:
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _mb_org(enc: str, idx: int, organism_snomed: str | None) -> dict:
    """mb-org-* Observation, SNOMED organism or no-growth."""
    obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{idx}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "code": {"coding": [{"code": "600-7"}]},
    }
    if organism_snomed:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}]
        }
    else:
        obs["valueString"] = "No growth"
    return obs


@pytest.mark.unit
def test_organism_per_encounter_basic(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, "3092008"),       # S.aureus
        _mb_org("E2", 0, "112283007"),     # E.coli
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}, "E2": {"112283007"}}


@pytest.mark.unit
def test_organism_per_encounter_multiple_organisms_same_encounter(tmp_path: Path) -> None:
    """A CLABSI encounter with both S.aureus + S.epidermidis blood cultures."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, "3092008"),       # S.aureus
        _mb_org("E1", 1, "11638008"),      # S.epidermidis
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008", "11638008"}}


@pytest.mark.unit
def test_organism_per_encounter_skips_no_growth(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, None),            # no-growth → valueString
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_skips_non_mb_observations(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "lab-E1-0001",  # NOT mb-org-*
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "6690-2"}]},
            "valueQuantity": {"value": 14000},
        },
        {
            "resourceType": "Observation",
            "id": "vs-E1-0001",   # vital signs, also NOT mb-org-*
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "8867-4"}]},
            "valueQuantity": {"value": 88},
        },
        _mb_org("E1", 0, "3092008"),
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}}


@pytest.mark.unit
def test_organism_per_encounter_skips_missing_encounter_ref(tmp_path: Path) -> None:
    """A mb-org-* without encounter ref must be skipped (no enc_id key)."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-orphan-0",
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_empty_observation_file(tmp_path: Path) -> None:
    """No Observation.ndjson at all → empty dict, no crash."""
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_skips_non_snomed_coding(tmp_path: Path) -> None:
    """A mb-org-* whose valueCodeableConcept uses non-SNOMED system is skipped."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://loinc.org", "code": "12345-6"}],
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}
