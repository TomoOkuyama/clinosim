"""Prerequisite chronic conditions are defined once, per locale (Issue #2288)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.disease.protocol import _validate_incidence_block

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path", sorted(Path("clinosim/modules/disease/reference_data").glob("*.yaml")), ids=lambda p: p.stem
)
def test_disease_yamls_carry_no_prerequisite(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert "prerequisite_condition" not in (data.get("incidence") or {})


def test_loader_rejects_a_prerequisite_in_the_disease_yaml() -> None:
    with pytest.raises(ValueError, match="demographics.yaml"):
        _validate_incidence_block("x", {"trigger_type": "acute", "prerequisite_condition": "F20"})
