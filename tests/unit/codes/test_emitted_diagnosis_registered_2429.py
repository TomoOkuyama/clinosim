"""Diagnosis codes the generator emits are registered with displays (Issue #2429)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.codes.icd10 import icd10_display

pytestmark = pytest.mark.unit

_LOCALE = Path(clinosim.__file__).parent / "locale"


def _leaves(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in _leaves(v)]
    return []


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_mapping_target_is_registered(country: str) -> None:
    mapping = yaml.safe_load((_LOCALE / country.lower() / "code_mapping_diagnosis.yaml").read_text(encoding="utf-8"))
    targets = {t for v in mapping.values() for t in ([v] if isinstance(v, str) else _leaves(v))}
    missing = sorted(t for t in targets if not icd10_display(t, country, "en"))
    assert not missing, missing


def test_single_gene_disease_codes_are_registered() -> None:
    data = yaml.safe_load((_LOCALE / "shared" / "single_gene_diseases.yaml").read_text(encoding="utf-8"))
    codes = list(data["single_gene_diseases"])
    assert "D55.0" in codes
    for country in ("US", "JP"):
        assert not [c for c in codes if not icd10_display(c, country, "en")], country


def test_g6pd_and_metabolic_syndrome_displays() -> None:
    assert icd10_display("D55.0", "JP", "ja") == "グルコース-６-リン＜燐＞酸脱水素酵素［G6PD］欠損による貧血"
    assert icd10_display("E88.810", "US", "en") == "Metabolic syndrome"
    assert icd10_display("E88.8", "JP", "ja") == "その他の明示された代謝障害"
