"""Protocol entries that name a catalog drug by an alias or a variant
spelling use drug_id; underscores read as spaces (Issue #2415)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import clinosim
from clinosim.codes.drugs import drug_ref

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent

# Names whose text carries administration semantics the emitters still read
# from the name (continuous-infusion detection); remodelled in #2424.
_NAME_CARRIES_SEMANTICS = {"Regular insulin (continuous IV)"}


@pytest.mark.parametrize(
    ("name", "drug_id"),
    [
        ("Calcium_gluconate", "calcium_gluconate"),
        ("Normal_saline", "normal_saline"),
        ("Unfractionated_Heparin", "heparin"),
        ("Sodium_bicarbonate", "sodium_bicarbonate"),
    ],
)
def test_underscore_spellings_resolve(name: str, drug_id: str) -> None:
    assert drug_ref(name) == drug_id


def test_no_resolvable_drug_name_in_protocols() -> None:
    hits: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            name = x.get("drug")
            if isinstance(name, str) and drug_ref(name) and name not in _NAME_CARRIES_SEMANTICS:
                hits.append(name)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for path in (_ROOT / "modules/disease/reference_data").glob("*.yaml"):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert not hits, sorted(set(hits))
