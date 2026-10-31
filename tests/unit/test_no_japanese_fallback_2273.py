"""Non-JP output never falls back to Japanese (Issue #2273)."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from clinosim.modules.document.narrative import _hedging
from clinosim.modules.document.narrative.renderers.section_builders import discharge_summary
from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name, _localize_rate_adjustment
from clinosim.simulator import daily_loop, discharge_rx

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["FR", "DE", ""])
def test_drug_and_rate_localizers_keep_english_outside_jp(country: str) -> None:
    assert _localize_drug_name("Acetaminophen", country) == "Acetaminophen"
    assert _localize_rate_adjustment("increase rate by 10%", country) == "increase rate by 10%"


def test_drug_localizer_still_translates_for_jp() -> None:
    assert _localize_drug_name("Acetaminophen", "JP") != "Acetaminophen"


def _generator(instructions: dict) -> SimpleNamespace:
    return SimpleNamespace(_resolve_discharge_instructions=lambda ctx: instructions)


def test_discharge_instructions_fall_back_to_english_not_japanese() -> None:
    ctx = SimpleNamespace(target_lang="fr", disease_protocol=None)
    gen = _generator({"diet": {"ja": "減塩食", "en": "Low-salt diet"}, "only_ja": {"ja": "安静"}})
    text, _ = discharge_summary.build_discharge_instructions(gen, ctx)
    assert "Low-salt diet" in text
    assert "減塩食" not in text and "安静" not in text


def test_follow_up_falls_back_to_english_not_japanese() -> None:
    ctx = SimpleNamespace(target_lang="fr", disease_protocol=None)
    text, _ = discharge_summary.build_follow_up(_generator({"follow_up": {"ja": "2週間後", "en": "In 2 weeks"}}), ctx)
    assert text == "In 2 weeks"


def test_hedged_phrase_falls_back_to_english_not_japanese() -> None:
    registry = {"t": {"confirmed": {"ja": ["確定"], "en": ["confirmed"]}}}
    with patch.object(_hedging, "_load_registry", return_value=registry):
        assert _hedging.hedged_phrase("t", "x", confirmed=True, lang="fr") == "confirmed"
        assert _hedging.hedged_phrase("t", "x", confirmed=True) == "confirmed"  # default is English


@pytest.mark.parametrize("func", [daily_loop._run_daily_loop, discharge_rx.build_discharge_rx])
def test_country_key_defaults_to_us(func) -> None:
    assert inspect.signature(func).parameters["country_key"].default == "us"
