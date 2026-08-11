"""Nursing score computation functions (NEWS2, GCS, Braden, Morse).

All functions are pure — rng is injected as a parameter, no global random state (AD-16).
Data-driven via reference_data/nursing_scores.yaml (authoritative published instruments).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.modules.observation._nursing_score_thresholds import (
    AVPU_TO_BRADEN_SENSORY,
    BARTHEL_DEFAULT,
    BRADEN_FRICTION_BEDBOUND_MAX_EXCLUSIVE,
    BRADEN_FRICTION_LIMITED_MAX_EXCLUSIVE,
    BRADEN_MOISTURE_HIGH_THRESHOLD,
    BRADEN_MOISTURE_LOW_THRESHOLD,
    BRADEN_MOISTURE_MID_THRESHOLD,
    BRADEN_NUTRITION_JITTER_HIGH,
    BRADEN_NUTRITION_JITTER_LOW,
    BRADEN_SCORE_MAX,
    BRADEN_SCORE_MIN,
    GCS_JITTER_HIGH,
    GCS_JITTER_LOW,
    GCS_PERFUSION_DECREMENT_SCALE,
    MORSE_GAIT_IMPAIRED_MAX_EXCLUSIVE,
    MORSE_GAIT_WEAK_MAX_EXCLUSIVE,
    MORSE_HISTORY_AGE_THRESHOLD,
    MORSE_JITTER_HIGH,
    MORSE_JITTER_LOW,
    MORSE_SCORE_MAX,
    MORSE_SCORE_MIN,
    NEWS2_SCORE_MAX,
    NEWS2_SCORE_MIN,
)

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


@lru_cache(maxsize=1)
def _scores() -> dict:
    with open(_REF_DIR / "nursing_scores.yaml") as f:
        return yaml.safe_load(f) or {}


def _band_points(value, bands) -> int:
    """bands: list of [low|null, high|null, points]; inclusive bounds."""
    if value is None:
        return 0
    for low, high, pts in bands:
        if (low is None or value >= low) and (high is None or value <= high):
            return int(pts)
    return 0


def compute_news2(vs: dict) -> int:
    cfg = _scores()["news2"]
    total = 0
    total += _band_points(vs.get("respiratory_rate"), cfg["respiratory_rate"])
    total += _band_points(vs.get("spo2"), cfg["spo2_scale1"])
    if vs.get("on_supplemental_oxygen"):
        total += int(cfg["on_supplemental_oxygen"])
    total += _band_points(vs.get("temperature_celsius"), cfg["temperature_celsius"])
    total += _band_points(vs.get("systolic_bp"), cfg["systolic_bp"])
    total += _band_points(vs.get("heart_rate"), cfg["heart_rate"])
    total += int(cfg["consciousness"].get(vs.get("consciousness_level", "A"), 0))
    return max(NEWS2_SCORE_MIN, min(NEWS2_SCORE_MAX, total))


def compute_gcs(consciousness_level: str, perfusion_status: float, rng: np.random.Generator) -> int:
    cfg = _scores()["gcs"]
    base = int(cfg["avpu_base"].get(consciousness_level, 15))
    # Poor perfusion (shock/encephalopathy) nudges GCS down slightly, deterministic + small noise.
    decrement = int(round((1.0 - perfusion_status) * GCS_PERFUSION_DECREMENT_SCALE))
    jitter = int(rng.integers(GCS_JITTER_LOW, GCS_JITTER_HIGH, endpoint=True))  # 0 or 1, deterministic per sub-seed
    score = base - decrement - jitter
    return max(cfg["min"], min(cfg["max"], score))


def _barthel_to_subscale(barthel: int) -> int:
    table = _scores()["braden"]["barthel_to_subscale"]
    sub = 1
    for low, val in table:
        if barthel >= low:
            sub = int(val)
    return sub


def compute_braden(adl: dict, consciousness_level: str, volume_status: float, rng: np.random.Generator) -> dict:
    barthel = adl.get("barthel_score", BARTHEL_DEFAULT) if adl else BARTHEL_DEFAULT
    activity = _barthel_to_subscale(barthel)
    mobility = _barthel_to_subscale(barthel)
    # Sensory perception subscale tracks AVPU 1:1 (published range 1-4):
    # unresponsive patients cannot sense/respond to pressure-related discomfort.
    sensory = AVPU_TO_BRADEN_SENSORY.get(consciousness_level, 4)
    # Higher volume (edema/incontinence proxy) → more moisture risk (lower subscale).
    if volume_status > BRADEN_MOISTURE_HIGH_THRESHOLD:
        moisture = 1
    elif volume_status > BRADEN_MOISTURE_MID_THRESHOLD:
        moisture = 2
    elif volume_status > BRADEN_MOISTURE_LOW_THRESHOLD:
        moisture = 3
    else:
        moisture = 4
    nutrition = max(
        1,
        min(4, activity + int(rng.integers(BRADEN_NUTRITION_JITTER_LOW, BRADEN_NUTRITION_JITTER_HIGH, endpoint=True))),
    )
    if barthel < BRADEN_FRICTION_BEDBOUND_MAX_EXCLUSIVE:
        friction = 1
    elif barthel < BRADEN_FRICTION_LIMITED_MAX_EXCLUSIVE:
        friction = 2
    else:
        friction = 3
    total = sensory + moisture + activity + mobility + nutrition + friction
    return {
        "braden_sensory": sensory,
        "braden_moisture": moisture,
        "braden_activity": activity,
        "braden_mobility": mobility,
        "braden_nutrition": nutrition,
        "braden_friction": friction,
        "braden_total": max(BRADEN_SCORE_MIN, min(BRADEN_SCORE_MAX, total)),
    }


def compute_morse_fall_risk(
    age: int, adl: dict, consciousness_level: str, has_iv: bool, rng: np.random.Generator
) -> tuple[int, str]:
    cfg = _scores()["morse"]
    barthel = adl.get("barthel_score", BARTHEL_DEFAULT) if adl else BARTHEL_DEFAULT
    score = 0
    if age >= MORSE_HISTORY_AGE_THRESHOLD:
        score += cfg["history_of_falling"]
    if has_iv:
        score += cfg["iv_access"]
    if barthel < MORSE_GAIT_IMPAIRED_MAX_EXCLUSIVE:
        score += cfg["gait_impaired"]
    elif barthel < MORSE_GAIT_WEAK_MAX_EXCLUSIVE:
        score += cfg["gait_weak"]
    if consciousness_level != "A":
        score += cfg["mental_status_forgets_limits"]
    # small deterministic jitter
    score = max(
        MORSE_SCORE_MIN,
        min(MORSE_SCORE_MAX, score + int(rng.integers(MORSE_JITTER_LOW, MORSE_JITTER_HIGH, endpoint=True))),
    )
    level = "low"
    for low, lvl in cfg["risk_levels"]:
        if score >= low:
            level = lvl
    return score, level
