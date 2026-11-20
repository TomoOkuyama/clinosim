"""Issue #3427: the "X or Y" supportive-detail reduction never mangles an order.

An ordered supportive measure is one concrete instruction. The shared-numeric-tail
rule applies only to "<drug A> or <drug B> <dose>" (B a single name followed by the
dose); every other alternative is written as one instruction in the disease YAML.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.order.engine import supportive_detail_raw
from tests.unit.locale.test_supportive_order_phrases_3398 import _supportive_entries

pytestmark = pytest.mark.unit

_NUM = re.compile(r"\d+(?:\.\d+)?")
_DANGLING = {"per", "to", "of", "with", "for", "the", "a", "and", "or", "until", "at", "on"}


def _pairs() -> list[tuple[str, str]]:
    out = []
    for entry in _supportive_entries():
        for country in ("JP", "US"):
            locale_detail = (entry.get("locale_detail") or {}).get(country.lower())
            raw = str(locale_detail or entry.get("detail", "") or "")
            out.append((raw, supportive_detail_raw(entry, country)))
    return out


def test_inventory_is_not_empty() -> None:
    assert len(_pairs()) > 100


def test_reduced_string_has_no_number_absent_from_the_chosen_alternative_and_shared_dose() -> None:
    bad = []
    for raw, reduced in _pairs():
        if " or " not in raw:
            continue
        primary, tail = raw.split(" or ", 1)
        shared = re.match(r"^[A-Za-z][\w'-]*\s+(\d.*)$", tail.strip())
        allowed = set(_NUM.findall(primary)) | (set(_NUM.findall(shared.group(1))) if shared else set())
        if set(_NUM.findall(reduced)) - allowed:
            bad.append(f"{raw!r} -> {reduced!r}")
    assert not bad, "\n".join(bad)


def test_no_alternative_is_cut_mid_phrase() -> None:
    bad = []
    for raw, reduced in _pairs():
        if " or " not in raw:
            assert reduced == raw
            continue
        primary, tail = raw.split(" or ", 1)
        last = primary.strip().split()[-1].lower()
        if last in _DANGLING or not reduced.startswith(primary.strip()):
            bad.append(f"{raw!r} -> {reduced!r}")
        # a tail that carries a clause (comma / digits) is not a bare alternative
        shared = re.match(r"^[A-Za-z][\w'-]*\s+\d", tail.strip())
        if not shared and (re.search(r"\d", tail) or "," in tail):
            bad.append(f"alternative with its own clause is dropped: {raw!r}")
    assert not bad, "\n".join(bad)


def test_or_inside_a_phrase_is_not_an_alternative() -> None:
    for raw, _ in _pairs():
        assert not re.search(r"\bself or others\b", raw)


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("NS or LR 500-1000mL bolus, then 125-250mL/h", "NS 500-1000mL bolus, then 125-250mL/h"),
        ("NS or LR 100-150 mL/h", "NS 100-150 mL/h"),
        ("NS wide open, titrate to MAP > 65", "NS wide open, titrate to MAP > 65"),
        ("NS or LR wide open, titrate to MAP > 65", "NS"),
        ("Nasal cannula or mask, SpO2 >= 94%", "Nasal cannula"),
        ("Famotidine 20mg IV BID or PPI", "Famotidine 20mg IV BID"),
    ],
)
def test_reduction_examples(detail: str, expected: str) -> None:
    assert supportive_detail_raw({"detail": detail}, "US") == expected
