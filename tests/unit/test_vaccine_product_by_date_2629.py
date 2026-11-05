"""Issue #2629: a dose is coded with the vaccine product in use on its date."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.immunization.engine import load_schedule, product_cvx

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("vaccine", "on", "cvx"),
    [
        ("covid19", date(2021, 9, 4), "208"),  # original monovalent
        ("covid19", date(2022, 11, 1), "300"),  # bivalent
        ("covid19", date(2023, 9, 11), "309"),  # 2023-2024 formula onward
        ("influenza", date(2012, 10, 15), "140"),  # trivalent before 2013-14
        ("influenza", date(2018, 10, 15), "150"),  # quadrivalent seasons
        ("influenza", date(2024, 10, 15), "140"),  # trivalent again from 2024-25
        ("pediatric_influenza", date(2018, 10, 15), "158"),
        ("pediatric_influenza", date(2024, 10, 15), "141"),
    ],
)
def test_the_product_in_use_on_the_dose_date(vaccine: str, on: date, cvx: str) -> None:
    assert product_cvx(load_schedule("US")[vaccine], on) == cvx


def test_a_vaccine_without_products_keeps_its_code() -> None:
    tdap = next(v for v in load_schedule("US").values() if str(v["cvx"]) == "115")
    assert product_cvx(tdap, date(2005, 6, 1)) == "115"
