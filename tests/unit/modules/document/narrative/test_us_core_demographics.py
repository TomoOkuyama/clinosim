"""Tests for US Core race / ethnicity in _render_patient_demographics
(Issue #1405 P1 refinement)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.document.narrative.replacement_strategy import (
    _render_patient_demographics,
)


def _p(**kw) -> SimpleNamespace:
    base = {
        "patient_id": "pt-1",
        "age": 55,
        "sex": "M",
        "occupation": "",
        "smoking_status": "",
        "alcohol_use": "",
        "marital_status": "",
        "employment_status": "",
        "insurance_type": "",
        "race": "",
        "ethnicity": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_race_ethnicity_en_hispanic_black() -> None:
    patient = _p(race="black", ethnicity="hispanic")
    out = _render_patient_demographics(patient, lang="en")
    assert "Black or African American" in out
    assert "Hispanic or Latino" in out
    assert "55 y/o male" in out


def test_race_ethnicity_ja_asian_not_hispanic() -> None:
    patient = _p(race="asian", ethnicity="not_hispanic")
    out = _render_patient_demographics(patient, lang="ja")
    assert "アジア系" in out
    assert "非ヒスパニック" in out
    assert "55歳男性" in out


def test_race_unknown_omits_silently() -> None:
    patient = _p(race="unknown", ethnicity="hispanic")
    out = _render_patient_demographics(patient, lang="en")
    # "unknown" collapses to empty via _localize_token
    assert "unknown" not in out.lower() or out.lower().count("unknown") == 0
    assert "Hispanic or Latino" in out  # ethnicity still shows


def test_race_ethnicity_empty_omits_silently() -> None:
    """JP records leave race="" / ethnicity=""; the line should not
    dangle a trailing separator or mention "race:" at all."""
    patient = _p()  # both empty
    out = _render_patient_demographics(patient, lang="en")
    assert "race" not in out.lower()
    assert "hispanic" not in out.lower()
    # The line still emits the leading age/sex anchor.
    assert "55 y/o" in out


def test_race_pacific_islander_native_en() -> None:
    patient = _p(race="pacific_islander")
    out = _render_patient_demographics(patient, lang="en")
    assert "Native Hawaiian or Other Pacific Islander" in out


def test_race_other_ja() -> None:
    patient = _p(race="other")
    out = _render_patient_demographics(patient, lang="ja")
    assert "その他人種" in out
