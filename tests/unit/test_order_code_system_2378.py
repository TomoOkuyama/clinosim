"""Medication orders record the code system of order_code, and the legacy
name-only chronic entries use drug_id (Issue #2378)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import clinosim
from clinosim.codes import code_exists
from clinosim.codes.drugs import get_drug
from clinosim.modules.order.engine import protocol_drug_order_code, protocol_drug_order_code_system

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent


def _drug_specs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("drug"), str):
                out.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for path in sorted((_ROOT / "modules/disease/reference_data").glob("*.yaml")):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    return out


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_protocol_drug_code_is_registered_in_its_system(country: str) -> None:
    bad = []
    for spec in _drug_specs():
        code = protocol_drug_order_code(spec, country)
        system = protocol_drug_order_code_system(spec, country)
        if not code:
            assert system == ""
            continue
        if not code_exists(system, code, exact=True):
            bad.append((spec.get("drug"), system, code))
    assert not bad, bad[:20]


def test_chronic_entries_reference_the_catalog() -> None:
    data = yaml.safe_load((_ROOT / "locale/shared/chronic_medications.yaml").read_text(encoding="utf-8"))
    names: list[str] = []
    ids: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if "drug_class" in x:
                if "drug" in x:
                    names.append(str(x["drug"]))
                ids.append(str(x.get("drug_id") or ""))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    assert not names, names
    assert all(get_drug(i) is not None for i in ids)


@pytest.mark.parametrize(
    ("name", "rxcui"),
    [
        ("Labetalol", "6185"),  # the inline code 6135 was ketoconazole
        ("Magnesium Sulfate", "6585"),  # 6475 was loxapine
        ("Nicardipine", "7396"),  # 7417 was nifedipine
        ("Ketorolac", "35827"),  # 6739 does not exist
    ],
)
def test_us_order_code_is_the_catalog_rxcui(name: str, rxcui: str) -> None:
    spec = {"drug": name}
    assert protocol_drug_order_code(spec, "US") == rxcui
    assert protocol_drug_order_code_system(spec, "US") == "rxnorm"
