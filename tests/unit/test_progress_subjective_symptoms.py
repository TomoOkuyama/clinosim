"""Progress-note subjective reflects pain, consciousness and withdrawal (#2095)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 5, 1, 10, 0)


def _ctx(day0: dict, day1: dict, lang: str = "ja", disease: str = "hip_fracture") -> SimpleNamespace:
    def v(day: int, extra: dict) -> dict:
        base = {"timestamp": datetime(2026, 5, 1 + day, 14, 0), "temperature_celsius": 36.8, "spo2": 97.0}
        return {**base, **extra}

    return SimpleNamespace(
        target_lang=lang,
        vitals=[v(0, day0), v(1, day1)],
        day_index=1,
        los_days=5,
        encounter={"encounter_id": "E1", "admission_datetime": _ADM},
        disease_protocol=SimpleNamespace(disease_id=disease),
        clinical_course_archetype="smooth_recovery",
    )


def test_pain_improving() -> None:
    text = compose_progress_subjective_from_state(_ctx({"pain_score": 8}, {"pain_score": 4}))
    assert "疼痛" in text and "8" in text and "4" in text


def test_pain_persistent_en() -> None:
    text = compose_progress_subjective_from_state(_ctx({"pain_score": 6}, {"pain_score": 6}, lang="en"))
    assert "Pain" in text and "6" in text


def test_new_confusion_and_recovery() -> None:
    new = compose_progress_subjective_from_state(_ctx({"consciousness_level": "A"}, {"consciousness_level": "V"}))
    assert "意識" in new
    better = compose_progress_subjective_from_state(_ctx({"consciousness_level": "P"}, {"consciousness_level": "A"}))
    assert "改善" in better


def test_withdrawal_symptoms() -> None:
    text = compose_progress_subjective_from_state(
        _ctx({"heart_rate": 118}, {"heart_rate": 112}, disease="alcohol_withdrawal")
    )
    assert "振戦" in text
