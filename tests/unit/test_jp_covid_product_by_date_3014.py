"""Issue #3014: a Japanese COVID-19 dose is coded with the product in use in
Japan on its date (従来型 1価 → オミクロン株対応 2価 → XBB.1.5 / 季節性), with
the product's 0.3 mL dose."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.immunization.engine import load_schedule, product_cvx, vaccine_administration

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("on", "cvx"),
    [
        (date(2021, 12, 29), "208"),  # 従来型 1価 (初回接種・3回目)
        (date(2022, 9, 19), "208"),  # the day before the 2価 rollout
        (date(2022, 9, 20), "300"),  # オミクロン株対応 2価 (令和4年秋開始接種)
        (date(2023, 9, 19), "300"),
        (date(2023, 9, 20), "309"),  # XBB.1.5 対応 1価 (令和5年秋開始接種)
        (date(2025, 10, 15), "309"),  # 定期接種 (B類) from 2024-25
    ],
)
def test_a_jp_covid_dose_is_the_product_of_its_date(on: date, cvx: str) -> None:
    assert product_cvx(load_schedule("JP")["covid19"], on) == cvx


@pytest.mark.parametrize("cvx", ["208", "300", "309"])
def test_every_jp_covid_product_is_an_intramuscular_0_3_ml_dose(cvx: str) -> None:
    admin = vaccine_administration("JP", cvx, 600)
    assert admin is not None and admin.dose_ml == 0.3
