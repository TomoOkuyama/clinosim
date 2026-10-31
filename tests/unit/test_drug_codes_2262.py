"""Issue #2262: drug codes come from the catalog / mapping through shared
accessors, conflicts resolve to the verified code, and drug-system URIs come
from the registry."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.codes import get_system_uri
from clinosim.codes.drugs import drug_system_key, drug_system_uri, is_verified_yj, jp_drug_system_key
from clinosim.locale.loader import drug_code

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


@pytest.mark.parametrize(
    ("code", "key"),
    [("1234567", "hot7"), ("123456789", "hot9"), ("1234567890123", "hot13"), ("3999401A1200", "yj"), ("abc", "hot9")],
)
def test_jp_system_by_code_format(code: str, key: str) -> None:
    assert jp_drug_system_key(code) == key
    assert drug_system_uri(code, "JP") == get_system_uri(key)


def test_us_drug_codes_are_rxnorm() -> None:
    assert drug_system_key("588250", "US") == "rxnorm"


@pytest.mark.parametrize(
    ("drug", "country", "expected"),
    [
        ("milnacipran", "US", ("rxnorm", "588250")),  # IN, not the PIN 30003 (RxNav)
        ("elcatonin", "JP", ("yj", "3999401A3024")),  # MHLW YJ master; 20S matches the 20-unit dose (#2347)
        ("nafamostat", "JP", ("yj", "3999407D1181")),
    ],
)
def test_conflicts_resolve_to_the_verified_code(drug: str, country: str, expected: tuple[str, str]) -> None:
    assert drug_code(drug, country) == expected
    if expected[0] == "yj":
        assert is_verified_yj(expected[1])


def test_no_drug_system_uri_literal_outside_codes() -> None:
    uris = [get_system_uri(k) for k in ("rxnorm", "yj", "hot7", "hot9", "hot13", "medication-nocoded")]
    offenders = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("codes/") or rel == "audit/axes/jp_language.py":
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{rel}: {u}" for u in uris if re.search(rf'"{re.escape(u)}"', text)]
    assert not offenders, offenders
