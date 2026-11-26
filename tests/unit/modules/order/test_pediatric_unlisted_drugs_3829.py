"""Drugs absent from the pediatric table no longer keep an adult dose (Issue #3829).

Methylprednisolone, azithromycin, amoxicillin/clavulanate and loperamide are
dosed by weight from their labels; cyclobenzaprine and butylscopolamine, with
no pediatric dose read, are withheld below an age. A guard keeps the set of
mg-dosed drugs a child can still get at an adult dose from growing.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import drug_key
from clinosim.modules.order.engine import enrich_medication_order
from clinosim.modules.order.pediatric_dose import (
    _table,
    pediatric_dose_text,
    pediatric_order_name,
    redose_order_for_child,
)
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit

_FIVE_YEARS = 60
_REPO = Path(__file__).resolve().parents[4]


def test_methylprednisolone_is_redosed_by_weight() -> None:
    assert (
        pediatric_order_name("Methylprednisolone 125mg", _FIVE_YEARS, 20.0, country="US") == "Methylprednisolone 10mg"
    )


def test_methylprednisolone_never_exceeds_the_cap_for_a_large_child() -> None:
    assert pediatric_order_name("Methylprednisolone 125mg", 17 * 12, 90.0, country="US") == "Methylprednisolone 45mg"


def test_azithromycin_is_10_mg_per_kg_with_a_500_mg_cap() -> None:
    assert pediatric_order_name("Azithromycin 500mg IV", _FIVE_YEARS, 23.9, country="US") == "Azithromycin 239mg IV"
    assert pediatric_order_name("Azithromycin 500mg IV", 16 * 12, 70.0, country="US") == "Azithromycin 500mg IV"


def test_azithromycin_is_not_given_below_six_months() -> None:
    assert pediatric_order_name("Azithromycin 250mg", 4, 6.0, country="US") is None


def test_amoxicillin_clavulanate_keeps_its_two_ingredient_ratio() -> None:
    # 13 mg/kg of amoxicillin per dose; the clavulanate share of the adult tablet follows.
    assert (
        pediatric_order_name("Amoxicillin/clavulanate 875/125mg", _FIVE_YEARS, 21.5, country="US")
        == "Amoxicillin/clavulanate 280/40mg"
    )


def test_amoxicillin_clavulanate_in_a_discharge_dose_text() -> None:
    assert (
        pediatric_dose_text("Amoxicillin/Clavulanate", "875/125mg PO BID", _FIVE_YEARS, 21.5, "US") == "280/40mg PO BID"
    )


def test_amoxicillin_clavulanate_inpatient_order_is_redosed_in_its_name_too() -> None:
    name = "Amoxicillin/Clavulanate 875/125mg PO BID"
    o = Order(order_id="O1", order_type=OrderType.MEDICATION, display_name=name, drug_id="amoxicillin_clavulanate")
    enrich_medication_order(o, dose_str="875/125mg PO BID")
    redose_order_for_child(o, _FIVE_YEARS, 21.5, country="US")
    assert (o.dose_quantity, o.dose_unit) == (280.0, "mg")
    assert o.display_name == "Amoxicillin/Clavulanate 280/40mg PO BID"


def test_trimethoprim_sulfamethoxazole_combination_is_no_longer_garbled() -> None:
    # 5 mg/kg of trimethoprim; the sulfamethoxazole share keeps the 1:5 tablet ratio.
    assert (
        pediatric_order_name("Trimethoprim/sulfamethoxazole 160/800mg", _FIVE_YEARS, 20.0, country="US")
        == "Trimethoprim/sulfamethoxazole 100/500mg"
    )


def test_loperamide_is_0_1_mg_per_kg_from_two_years() -> None:
    assert pediatric_order_name("Loperamide 2mg", 36, 15.5, country="US") == "Loperamide 1.6mg"
    assert pediatric_order_name("Loperamide 2mg", 20, 11.0, country="US") is None


@pytest.mark.parametrize(
    ("name", "age_months", "given"),
    [
        ("Cyclobenzaprine 5mg", 24, False),
        ("Cyclobenzaprine 10mg", 14 * 12, False),
        ("Cyclobenzaprine 10mg", 15 * 12, True),
        ("Buscopan 20mg IV", 7 * 12, False),
        ("Buscopan 20mg IV", 17 * 12, False),
        ("Buscopan 20mg IV", 18 * 12, True),
    ],
)
def test_drugs_without_a_pediatric_dose_are_withheld_below_their_age(name: str, age_months: int, given: bool) -> None:
    out = pediatric_order_name(name, age_months, 30.0, country="US")
    assert (out == name) is given and (out is not None) is given


def _unhandled_child_drugs() -> set[str]:
    """Drug keys of mg-dosed ED treatments and take-home scripts reachable by a
    child (protocol ``min_age`` < 18, spec ``min_age_years`` < 18) that the
    pediatric table neither doses nor withholds."""
    table = _table()
    handled = set(table["drugs"]) | set(table["neonatal_drugs"]) | set(table.get("withheld_below_age_months") or {})
    for overrides in (table.get("country_overrides") or {}).values():
        handled |= set(overrides)
    gaps: set[str] = set()
    for path in glob.glob(str(_REPO / "clinosim/modules/encounter/reference_data/*.yaml")):
        proto = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(proto, dict) or int(proto.get("min_age") or 0) >= 18:
            continue
        for block in ("treatment", "discharge_prescriptions"):
            for spec in proto.get(block) or []:
                if not isinstance(spec, dict) or int(spec.get("min_age_years") or 0) >= 18:
                    continue
                names = [spec.get("name") or spec.get("drug"), *(spec.get("locale_name") or {}).values()]
                for name in filter(None, names):
                    if re.search(r"\d\s*(mg|g|mcg)\b", name, re.IGNORECASE) and drug_key(name) not in handled:
                        gaps.add(drug_key(name))
    return gaps


# Drugs a child can still be given at the written adult dose: no pediatric dose
# or age limit read yet. The set must only shrink; add a drug to the table (or
# to withheld_below_age_months) and remove it here.
_KNOWN_GAPS = frozenset(
    {
        "albuterol",
        "betahistine",
        "cefcapene_pivoxil",
        "cephalexin",
        "dextromethorphan",
        "eperisone",
        "hydroxyzine",
        "ipratropium",
        "lorazepam",
        "meclizine",
        "morphine",
        "naproxen",
        "nitrofurantoin",
        "oxycodone",
        "phenazopyridine",
        "sumatriptan",
        "tamsulosin",
        "foreign body removal with 25g needle",
    }
)


def test_no_new_drug_reaches_a_child_at_an_adult_dose() -> None:
    new = _unhandled_child_drugs() - _KNOWN_GAPS
    assert not new, f"mg-dosed drugs a child can get with no pediatric rule: {sorted(new)}"


def test_the_issue_drugs_are_covered() -> None:
    gaps = _unhandled_child_drugs()
    for drug in (
        "methylprednisolone",
        "azithromycin",
        "amoxicillin_clavulanate",
        "butylscopolamine",
        "cyclobenzaprine",
        "loperamide",
    ):
        assert drug not in gaps


def test_known_gaps_do_not_list_handled_drugs() -> None:
    assert _KNOWN_GAPS <= _unhandled_child_drugs()
