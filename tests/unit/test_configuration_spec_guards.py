"""Guards of docs/design-guides/configuration-and-reference-data-spec.md (Issue #2732)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"


def _modules_with_reference_yaml() -> list[Path]:
    return sorted(d.parent for d in (_PKG / "modules").glob("*/reference_data") if any(d.glob("*.yaml")))


def _has_model(module: Path) -> bool:
    return any(re.search(r"\(BaseModel\)|model_validate", p.read_text(encoding="utf-8")) for p in module.rglob("*.py"))


def test_module_reference_yaml_has_a_model() -> None:
    """Spec §1: every module's reference YAML is validated by a Pydantic model
    (the former ratchet emptied with the population model)."""
    missing = {m.name for m in _modules_with_reference_yaml() if not _has_model(m)}
    assert not missing, f"reference YAML without a Pydantic model: {sorted(missing)}"


def test_no_ad_hoc_age_band_parsing() -> None:
    """Age-band keys are parsed only by clinosim/age_bands.py."""
    pattern = re.compile(r'key\.partition\("-"\)|band\w*\.endswith\("\+"\)|band\w*\.split\("-"\)')
    offenders = [
        f"{p.relative_to(_PKG)}:{i}"
        for p in sorted(_PKG.rglob("*.py"))
        if p.name != "age_bands.py"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, offenders
