"""SimulatorConfig rejects unknown fields (Issue #2206)."""

from __future__ import annotations

import pydantic
import pytest

from clinosim.types.config import SimulatorConfig

pytestmark = pytest.mark.unit


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError, match="population"):
        SimulatorConfig(population=1000)


def test_known_fields_still_validate() -> None:
    cfg = SimulatorConfig(catchment_population=1000, random_seed=7, country="JP")
    assert (cfg.catchment_population, cfg.random_seed, cfg.country) == (1000, 7, "JP")


@pytest.mark.parametrize("name", ["japan_medium", "japan_small", "japan_large", "us_medium"])
def test_every_preset_validates(name: str) -> None:
    assert SimulatorConfig.preset(name).catchment_population
