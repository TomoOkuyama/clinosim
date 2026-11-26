"""Issue #3836: a JP Specimen declares JP_Specimen_Common (the JP Core 1.2.0
profile http://jpfhir.jp/fhir/core/StructureDefinition/JP_Specimen_Common) and
carries its Must Support element ``meta.lastUpdated``; US output is unchanged;
the locale check leaves out the types JP Core publishes no profile for."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.types import Cohort
from clinosim.eval.axes.locale import _jp_core_profile_declared
from clinosim.eval.engine import Outcome
from clinosim.modules.output.fhir_r4.builder import _finalize_resource

pytestmark = pytest.mark.unit

_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Specimen_Common"


def _specimen() -> dict:
    return {
        "resourceType": "Specimen",
        "id": "spec-1",
        "status": "available",
        "subject": {"reference": "Patient/p1"},
        "collection": {"collectedDateTime": "2026-01-05T09:30:00+09:00"},
    }


def test_jp_specimen_declares_the_profile_and_last_updated() -> None:
    spec = _specimen()
    _finalize_resource(spec, "JP", {})
    assert spec["meta"]["profile"] == [_PROFILE]
    assert spec["meta"]["lastUpdated"].startswith("2026-01-05T09:30:00")


def test_us_specimen_is_unchanged() -> None:
    spec = _specimen()
    _finalize_resource(spec, "US", {})
    assert "meta" not in spec


def test_jp_companion_specimen_declares_the_profile() -> None:
    obs = {
        "resourceType": "Observation",
        "id": "lab-1",
        "category": [{"coding": [{"code": "laboratory"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "2160-0"}]},
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2026-01-05T09:30:00+09:00",
        "valueQuantity": {"value": 1.0, "unit": "mg/dL"},
    }
    spec = _finalize_resource(obs, "JP", {})
    assert spec is not None
    assert spec["meta"]["profile"] == [_PROFILE]
    assert spec["meta"]["lastUpdated"]


def _cohort(tmp_path: Path, rows: dict[str, list[dict]]) -> Cohort:
    d = tmp_path / "fhir_r4"
    d.mkdir()
    for rt, rs in rows.items():
        (d / f"{rt}.ndjson").write_text("\n".join(json.dumps(r) for r in rs) + "\n")
    return Cohort.open(tmp_path)


_CORE = {"profile": [_PROFILE]}


def test_check_ignores_types_without_a_published_profile(tmp_path: Path) -> None:
    cohort = _cohort(
        tmp_path,
        {
            "Specimen": [{"resourceType": "Specimen", "id": "s", "meta": _CORE}],
            "CareTeam": [{"resourceType": "CareTeam", "id": "c"}],
            "ClinicalImpression": [{"resourceType": "ClinicalImpression", "id": "i"}],
            "Endpoint": [{"resourceType": "Endpoint", "id": "e"}],
            "Composition": [{"resourceType": "Composition", "id": "k"}],
        },
    )
    assert _jp_core_profile_declared(cohort, "").outcome == Outcome.PASS


def test_check_still_flags_a_type_with_a_published_profile(tmp_path: Path) -> None:
    cohort = _cohort(
        tmp_path,
        {
            "Specimen": [{"resourceType": "Specimen", "id": "s"}],
            "Patient": [{"resourceType": "Patient", "id": "p", "meta": _CORE}],
        },
    )
    assert _jp_core_profile_declared(cohort, "").outcome != Outcome.PASS
