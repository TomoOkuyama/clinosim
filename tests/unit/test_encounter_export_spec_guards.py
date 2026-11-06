"""Guards of docs/design-guides/encounter-lifecycle-and-export-spec.md (Issue #2730)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"
_ENCOUNTER_SIMULATORS = ("emergency.py", "inpatient.py", "outpatient.py", "perinatal.py", "unknown_condition.py")
# The per-resource finishing passes run only inside builder._finalize_resource.
_FINISH_PASSES = (
    "_apply_jp_core_profile",
    "_apply_jp_clins_profile",
    "_apply_us_core_profile",
    "_normalize_jp_observation_category",
    "_populate_jp_medication_dosage_ecs_fields",
    "_strip_forbidden_observation_reference_range_extensions",
)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    return [
        (i, line)
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if not line.lstrip().startswith("#")
    ]


@pytest.mark.parametrize("name", _ENCOUNTER_SIMULATORS)
def test_every_encounter_simulator_builds_its_diagnosis_through_encounter_setup(name: str) -> None:
    assert "encounter_diagnosis(" in (_PKG / "simulator" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", _ENCOUNTER_SIMULATORS)
def test_every_encounter_simulator_links_its_orders_through_encounter_setup(name: str) -> None:
    assert "attach_orders(" in (_PKG / "simulator" / name).read_text(encoding="utf-8")


def test_clinical_diagnosis_is_constructed_only_in_encounter_setup() -> None:
    offenders = [
        f"{p.name}:{i}"
        for p in sorted((_PKG / "simulator").rglob("*.py"))
        if p.name != "encounter_setup.py"
        for i, line in _code_lines(p)
        if "ClinicalDiagnosis(" in line
    ]
    assert not offenders, offenders


def test_condition_resources_start_from_the_skeleton() -> None:
    offenders = [
        f"{p.relative_to(_PKG)}:{i}"
        for p in sorted((_PKG / "modules/output/fhir_r4").rglob("*.py"))
        if p.name != "conditions.py"
        for i, line in _code_lines(p)
        if re.search(r'"resourceType":\s*"Condition"', line)
    ]
    assert not offenders, offenders


def test_finishing_passes_run_only_in_finalize_resource() -> None:
    text = (_PKG / "modules/output/fhir_r4/builder.py").read_text(encoding="utf-8")
    start = text.index("def _finalize_resource(")
    end = text.index("\ndef ", start + 1)
    outside = text[:start] + text[end:]
    calls = [p for p in _FINISH_PASSES if re.search(rf"\b{p}\(", outside)]
    assert not calls, calls
