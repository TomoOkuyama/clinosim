"""Nursing flowsheet enricher (AD-55 Base, AD-56 post_records).

Fills NEWS2/GCS on each vital record and generates daily Braden/Morse risk
assessments. Uses a dedicated sub-seed so the main random stream is untouched.
"""

from __future__ import annotations

import hashlib

import numpy as np

from clinosim.modules.observation.nursing import (
    compute_braden,
    compute_gcs,
    compute_morse_fall_risk,
    compute_news2,
)
from clinosim.types.encounter import NursingRiskAssessment

_NURSING_SEED_OFFSET = 0x4E55  # "NU"


def _sub_seed(master_seed: int, key: str) -> int:
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:6], "big")
    return (int(master_seed) + _NURSING_SEED_OFFSET + h) % (2**32)


def _get(obj, name, default=None):
    """Read attr or dict key (records may be dataclasses)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enrich_nursing(ctx) -> None:
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 70) or 70)
        rng = np.random.default_rng(_sub_seed(ctx.master_seed, pid or "x"))

        # 1) NEWS2 + GCS on each vital record (NEWS2 deterministic; GCS small jitter)
        for vs in _get(rec, "vital_signs", []) or []:
            vsd = vs if isinstance(vs, dict) else vs.__dict__
            news2 = compute_news2(vsd)
            gcs = compute_gcs(vsd.get("consciousness_level", "A"),
                              perfusion_status=1.0, rng=rng)
            if isinstance(vs, dict):
                vs["news2_score"], vs["gcs_score"] = news2, gcs
            else:
                vs.news2_score, vs.gcs_score = news2, gcs

        # 2) Daily Braden + Morse from ADL (align by date) + I/O (IV present)
        adls = _get(rec, "adl_assessments", []) or []
        ios = _get(rec, "intake_output_records", []) or []
        iv_dates = {str(_get(io, "date")) for io in ios if (_get(io, "intake_iv_ml", 0) or 0) > 0}
        out = []
        for adl in adls:
            adld = adl if isinstance(adl, dict) else adl.__dict__
            d = adld.get("date")
            loc = "A"  # consciousness proxy; could be refined from same-day vitals
            braden = compute_braden(adld, loc, volume_status=0.0, rng=rng)
            morse, level = compute_morse_fall_risk(
                age, adld, loc, has_iv=str(d) in iv_dates, rng=rng)
            out.append(NursingRiskAssessment(
                date=d, morse_total=morse, fall_risk_level=level, **braden))
        if isinstance(rec, dict):
            rec["nursing_risk_assessments"] = out
        else:
            rec.nursing_risk_assessments = out
