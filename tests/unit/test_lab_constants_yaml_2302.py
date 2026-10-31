"""Issue #2302: per-lab constants live in lab_constants.yaml and the
validator checks lab plausibility against the generator's limits."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clinosim.modules.observation import engine
from clinosim.modules.validator.consistency import ConsistencyReport, _check_lab_ranges

pytestmark = pytest.mark.unit

_YAML = Path(engine.__file__).parent / "reference_data" / "lab_constants.yaml"


def test_engine_tables_are_the_yaml_sections() -> None:
    data = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    assert engine.BIOLOGICAL_CV == data["biological_cv"]
    assert engine.ANALYTICAL_CV == data["analytical_cv"]
    assert engine.PRECISION == data["precision"]
    assert engine.LAB_UNITS == data["units"]
    assert engine.BASELINE_LAB_NORMALS == data["baseline_normals"]
    assert {k: list(v) for k, v in engine.PHYSIOLOGIC_LIMITS.items()} == data["physiologic_limits"]
    assert {k: list(v) for k, v in engine._PANIC_THRESHOLDS.items()} == data["panic_thresholds"]


def test_every_limited_lab_has_a_unit() -> None:
    for lab in (*engine.PHYSIOLOGIC_LIMITS, *engine._PANIC_THRESHOLDS, *engine.PRECISION):
        assert lab in engine.LAB_UNITS, lab


def _issues(lab_name: str, value: float) -> list:
    report = ConsistencyReport()
    record = SimpleNamespace(lab_results=[SimpleNamespace(lab_name=lab_name, value=value)])
    _check_lab_ranges(record, "p1", report)  # type: ignore[arg-type]
    return [i for i in report.issues if i.check_name == "lab_range"]


def test_validator_uses_the_generator_units() -> None:
    # Platelets are reported in 10*3/uL: 250 is normal, 5000 is not plausible.
    assert not _issues("Plt", 250)
    assert _issues("Plt", 5000)


def test_validator_matches_canonical_names_not_substrings() -> None:
    # "HbA1c" is not haemoglobin: an HbA1c of 7.0 % is not checked against the Hb range.
    assert not _issues("HbA1c", 7.0)
    assert _issues("Hb", 30.0)
