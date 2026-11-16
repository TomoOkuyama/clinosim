"""Minor-burn ED visits are coded by site and depth (Issue #3279).

The protocol's chief complaint is a partial-thickness burn of the hand or
arm, so the ED diagnosis is a second-degree burn of the hand (T23.2) or of
the forearm (T22.2) in the country's diagnosis system, never T30.0 (burn of
unspecified body region, unspecified degree).
"""

from __future__ import annotations

import copy
from collections import Counter
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clinosim.codes.loader import display, system_key_for
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_assessment
from clinosim.modules.encounter.protocol import EncounterConditionProtocol, load_encounter_condition
from clinosim.simulator.emergency import ed_diagnosis_code

pytestmark = pytest.mark.unit

_US_CODES = {"T23.201A", "T23.202A", "T22.211A", "T22.212A"}
_JP_CODES = {"T23.2", "T22.2"}


def _patient() -> SimpleNamespace:
    return SimpleNamespace(chronic_conditions=[])


def _codes(country: str, n: int = 400) -> list[str]:
    spec = load_encounter_condition("minor_burn")
    return [ed_diagnosis_code(spec, _patient(), country=country, encounter_id=f"ENC-{i}") for i in range(n)]


def test_minor_burn_protocol_no_longer_codes_t30() -> None:
    spec = load_encounter_condition("minor_burn")
    assert "T30" not in str(spec.get("icd10_code", ""))
    assert all("T30" not in code for v in spec["diagnosis_variants"] for code in v["codes"].values())


@pytest.mark.parametrize(("country", "expected"), [("US", _US_CODES), ("JP", _JP_CODES)])
def test_minor_burn_gets_a_second_degree_hand_or_forearm_code(country: str, expected: set[str]) -> None:
    codes = _codes(country)
    assert set(codes) == expected
    # hand 0.6 / forearm 0.4 of the variants' weight
    hand = sum(1 for c in codes if c.startswith("T23")) / len(codes)
    assert 0.5 < hand < 0.7


def test_variant_is_deterministic_per_encounter_and_country_consistent() -> None:
    spec = load_encounter_condition("minor_burn")
    us = ed_diagnosis_code(spec, _patient(), country="US", encounter_id="ENC-X-1")
    assert us == ed_diagnosis_code(spec, _patient(), country="US", encounter_id="ENC-X-1")
    jp = ed_diagnosis_code(spec, _patient(), country="JP", encounter_id="ENC-X-1")
    # the same draw picks the same site in both countries
    assert us[:3] == jp[:3]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_variant_code_has_a_display_naming_site_and_depth(country: str) -> None:
    system = system_key_for("diagnosis", country)
    for code in set(_codes(country)):
        en = display(system, code, "en") or ""
        assert "second degree" in en and ("hand" in en or "forearm" in en or "upper limb" in en), (code, en)
    if country == "JP":
        for code in _JP_CODES:
            ja = display(system, code, "ja") or ""
            assert "第２度熱傷" in ja and ("手" in ja or "上肢" in ja), (code, ja)


@pytest.mark.parametrize(
    ("country", "lang", "site_words", "depth_word"),
    [("US", "en", ("hand", "forearm"), "second degree"), ("JP", "ja", ("手", "上肢"), "第２度")],
)
def test_ed_assessment_names_site_and_depth(country: str, lang: str, site_words: tuple, depth_word: str) -> None:
    spec = load_encounter_condition("minor_burn")
    system = system_key_for("diagnosis", country)
    for i in range(20):
        code = ed_diagnosis_code(spec, _patient(), country=country, encounter_id=f"ENC-A-{i}")
        ctx = SimpleNamespace(
            target_lang=lang,
            diagnoses=[SimpleNamespace(admission_diagnosis_code=code, admission_diagnosis_system=system)],
            encounter=SimpleNamespace(**{f"chief_complaint_{lang}": spec["chief_complaint"][lang]}),
        )
        text, _ = build_ed_assessment(None, ctx)  # type: ignore[arg-type]
        assert depth_word in text and any(w in text for w in site_words), text
        assert "部位不明" not in text and "unspecified body region" not in text


def test_variant_choice_matches_weights_without_rng() -> None:
    counts = Counter(c[:5] for c in _codes("JP", 2000))
    assert set(counts) == {"T23.2", "T22.2"}
    assert abs(counts["T23.2"] / 2000 - 0.6) < 0.05


def _base() -> dict:
    return copy.deepcopy(load_encounter_condition("minor_burn"))


def test_validator_requires_a_code_for_every_country() -> None:
    data = _base()
    del data["diagnosis_variants"][0]["codes"]["jp"]
    with pytest.raises(ValidationError, match="jp"):
        EncounterConditionProtocol.model_validate(data)


def test_validator_rejects_a_non_positive_weight() -> None:
    data = _base()
    data["diagnosis_variants"][0]["weight"] = 0
    with pytest.raises(ValidationError):
        EncounterConditionProtocol.model_validate(data)


def test_validator_takes_exactly_one_of_code_or_variants() -> None:
    both = _base()
    both["icd10_code"] = "T23.201A"
    with pytest.raises(ValidationError, match="exactly one"):
        EncounterConditionProtocol.model_validate(both)
    neither = _base()
    del neither["diagnosis_variants"]
    with pytest.raises(ValidationError, match="exactly one"):
        EncounterConditionProtocol.model_validate(neither)


def test_single_code_protocols_unchanged() -> None:
    spec = load_encounter_condition("anxiety_panic_attack")
    assert ed_diagnosis_code(spec, _patient(), country="US", encounter_id="ENC-1") == spec["icd10_code"]
