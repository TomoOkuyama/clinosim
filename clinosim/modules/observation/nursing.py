"""Nursing score computation functions (NEWS2, GCS, Braden, Morse).

All functions are pure — rng is injected as a parameter, no global random state (AD-16).
Data-driven via reference_data/nursing_scores.yaml (authoritative published instruments).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

_DATA = Path(__file__).parent / "reference_data" / "nursing_scores.yaml"


@lru_cache(maxsize=1)
def _scores() -> dict:
    with open(_DATA) as f:
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
    return max(0, min(20, total))


def compute_gcs(consciousness_level: str, perfusion_status: float,
                rng: np.random.Generator) -> int:
    cfg = _scores()["gcs"]
    base = int(cfg["avpu_base"].get(consciousness_level, 15))
    # Poor perfusion (shock/encephalopathy) nudges GCS down slightly, deterministic + small noise.
    decrement = int(round((1.0 - perfusion_status) * 2))
    jitter = int(rng.integers(0, 1, endpoint=True))  # 0 or 1, deterministic per sub-seed
    score = base - decrement - jitter
    return max(cfg["min"], min(cfg["max"], score))


def _barthel_to_subscale(barthel: int) -> int:
    table = _scores()["braden"]["barthel_to_subscale"]
    sub = 1
    for low, val in table:
        if barthel >= low:
            sub = int(val)
    return sub


def compute_braden(adl: dict, consciousness_level: str, volume_status: float,
                   rng: np.random.Generator) -> dict:
    barthel = adl.get("barthel_score", 100) if adl else 100
    activity = _barthel_to_subscale(barthel)
    mobility = _barthel_to_subscale(barthel)
    sensory = 4 if consciousness_level == "A" else 2
    # Higher volume (edema/incontinence proxy) → more moisture risk (lower subscale).
    moisture = 3 if volume_status > 0.3 else 4
    nutrition = max(1, min(4, activity + int(rng.integers(-1, 1, endpoint=True))))
    friction = 2 if barthel < 60 else 3
    total = sensory + moisture + activity + mobility + nutrition + friction
    return {
        "braden_sensory": sensory, "braden_moisture": moisture,
        "braden_activity": activity, "braden_mobility": mobility,
        "braden_nutrition": nutrition, "braden_friction": friction,
        "braden_total": max(6, min(23, total)),
    }


def compute_morse_fall_risk(age: int, adl: dict, consciousness_level: str,
                            has_iv: bool, rng: np.random.Generator) -> tuple[int, str]:
    cfg = _scores()["morse"]
    barthel = adl.get("barthel_score", 100) if adl else 100
    score = 0
    if age >= 75:
        score += cfg["history_of_falling"]
    if has_iv:
        score += cfg["iv_access"]
    if barthel < 60:
        score += cfg["gait_impaired"]
    elif barthel < 90:
        score += cfg["gait_weak"]
    if consciousness_level != "A":
        score += cfg["mental_status_forgets_limits"]
    # small deterministic jitter
    score = max(0, min(125, score + int(rng.integers(-5, 5, endpoint=True))))
    level = "low"
    for low, lvl in cfg["risk_levels"]:
        if score >= low:
            level = lvl
    return score, level
