"""Pediatric asthma controller regimen and control instrument (Issue #3264)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import _asthma_control_phrase_key
from clinosim.modules.patient.activator import _derive_home_medications

pytestmark = pytest.mark.unit


@dataclass
class _Cond:
    code: str = "J45"
    stage: str = ""


def _meds(age: int, country: str) -> dict[str, str]:
    out = _derive_home_medications([_Cond()], np.random.default_rng(1), country=country, patient_age=age)
    return {m.drug_name.lower(): m.dose for m in out}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_toddler_gets_low_dose_nebulised_ics_not_icslaba(country: str) -> None:
    meds = _meds(3, country)
    assert not any("salmeterol" in n or "サルメテロール" in n for n in meds)
    assert any(n in ("budesonide", "ブデソニド") for n in meds)
    assert "250mcg" in meds.values()


@pytest.mark.parametrize("country", ["US", "JP"])
def test_school_child_gets_low_dose_fluticasone(country: str) -> None:
    meds = _meds(8, country)
    assert not any("salmeterol" in n or "サルメテロール" in n for n in meds)
    assert "50mcg" in meds.values()


@pytest.mark.parametrize("country", ["US", "JP"])
def test_adolescent_and_adult_keep_icslaba(country: str) -> None:
    for age in (12, 40):
        assert any("salmeterol" in n or "サルメテロール" in n for n in _meds(age, country))


@pytest.mark.parametrize(
    ("age", "key"),
    [
        (2, "chronic_monitoring.symptom_control_review"),
        (3, "chronic_monitoring.symptom_control_review"),
        (4, "chronic_monitoring.cact_control_review"),
        (8, "chronic_monitoring.cact_control_review"),
        (11, "chronic_monitoring.cact_control_review"),
        (12, "chronic_monitoring.act_control_review"),
        (45, "chronic_monitoring.act_control_review"),
        (None, "chronic_monitoring.act_control_review"),
    ],
)
def test_control_instrument_follows_age(age: int | None, key: str) -> None:
    assert _asthma_control_phrase_key(age) == key


def test_control_phrases_exist_in_both_languages_without_act_for_children() -> None:
    for lang in ("en", "ja"):
        child = t(_asthma_control_phrase_key(8), lang)
        toddler = t(_asthma_control_phrase_key(3), lang)
        assert "Childhood" in child or "C-ACT" in child
        assert "ACT" not in toddler
        assert not t(_asthma_control_phrase_key(3), lang).startswith("chronic_monitoring")
