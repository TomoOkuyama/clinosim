"""Longitudinal medication events resolve drugs through the catalog (Issue #2292)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import find_drug
from clinosim.modules.longitudinal.med_lookup import resolve_med_name
from clinosim.modules.longitudinal.patterns.event import EventSpec

pytestmark = pytest.mark.unit

_MED_DIR = Path("clinosim/locale/shared/longitudinal/med")


def test_find_drug_by_id_name_or_case_variant() -> None:
    assert find_drug("insulin_glargine").drug_id == "insulin_glargine"
    assert find_drug("Insulin Glargine").drug_id == "insulin_glargine"
    assert find_drug("insulin glargine").drug_id == "insulin_glargine"
    assert find_drug("not_a_drug") is None


def test_insulin_escalation_adds_subcutaneous_basal_insulin() -> None:
    med = resolve_med_name("insulin_glargine")
    assert med.drug_name == "Insulin Glargine"
    assert med.route == "SC"
    assert med.dose
    assert med.drug_name_ja


def test_unknown_emitted_drug_fails_at_load() -> None:
    with pytest.raises(ValueError, match="not in the drug catalog"):
        EventSpec(event_name="x", emits_icd="", emits_meds=["no_such_drug"])


@pytest.mark.parametrize("path", sorted(_MED_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_longitudinal_med_resolves_to_a_chronic_medication(path: Path) -> None:
    body = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for ref in (body.get("emits_meds") or []) + (body.get("removes_meds") or []):
        rec = find_drug(ref)
        assert rec is not None and ref == rec.drug_id, f"{path.name}: {ref!r} must be a catalog drug_id"
        med = resolve_med_name(ref)
        assert med.dose, f"{path.name}: {ref!r} has no chronic_medications entry"
