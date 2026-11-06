"""Guards of docs/design-guides/configuration-and-reference-data-spec.md (Issue #2732)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"

# Spec §5: modules whose reference YAML is not validated by a Pydantic model
# yet. This list may only shrink: a module that gains a model is removed, and a
# new module with reference data needs a model.
_NO_MODEL_YET = frozenset(
    {
        "antibiotic",
        "diagnosis",
        "drug_safety",
        "llm_service",
        "monitoring",
        "physiology",
        "population",
    }
)


def _modules_with_reference_yaml() -> list[Path]:
    return sorted(d.parent for d in (_PKG / "modules").glob("*/reference_data") if any(d.glob("*.yaml")))


def _has_model(module: Path) -> bool:
    return any(re.search(r"\(BaseModel\)|model_validate", p.read_text(encoding="utf-8")) for p in module.rglob("*.py"))


def test_module_reference_yaml_has_a_model() -> None:
    missing = {m.name for m in _modules_with_reference_yaml() if not _has_model(m)}
    assert missing <= _NO_MODEL_YET, f"reference YAML without a Pydantic model: {sorted(missing - _NO_MODEL_YET)}"


def test_no_model_yet_list_only_shrinks() -> None:
    modelled = {m.name for m in _modules_with_reference_yaml() if _has_model(m)}
    assert not (modelled & _NO_MODEL_YET), f"remove from _NO_MODEL_YET: {sorted(modelled & _NO_MODEL_YET)}"


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
