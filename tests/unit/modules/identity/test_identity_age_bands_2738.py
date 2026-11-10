"""Issue #2738: the JP identity age bands go through the shared age-band helper."""

from __future__ import annotations

import pytest

from clinosim.age_bands import parse_age_band
from clinosim.countries.jp.identity_provider import _rate_for_age, _rate_table_for_age
from clinosim.datafiles import load_data_yaml

pytestmark = pytest.mark.unit

_TABLES = ("card_holding_rate", "mynumber_insurance_rate", "insurance_category_distribution")


def _identity() -> dict:
    from pathlib import Path

    return load_data_yaml(Path(__file__).resolve().parents[4] / "clinosim/locale/jp/identity.yaml")


@pytest.mark.parametrize("table", _TABLES)
def test_every_band_key_is_a_shared_age_band(table: str) -> None:
    for key in _identity()[table]:
        parse_age_band(key)


def test_open_ended_band_covers_the_oldest() -> None:
    cfg = _identity()
    assert _rate_for_age(cfg["card_holding_rate"], 95) == cfg["card_holding_rate"]["80+"]
    assert _rate_for_age(cfg["card_holding_rate"], 79) == cfg["card_holding_rate"]["70-79"]
    assert _rate_table_for_age(cfg["insurance_category_distribution"], 80) == {}
