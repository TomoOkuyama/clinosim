"""Nursing flowsheet enricher (AD-55 Base, AD-56 post_records).

Fills NEWS2/GCS on each vital record and generates daily Braden/Morse risk
assessments. Uses a dedicated sub-seed so the main random stream is untouched.
"""

from __future__ import annotations

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.observation.nursing import (
    compute_braden,
    compute_gcs,
    compute_morse_fall_risk,
    compute_news2,
)
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.encounter import NursingRiskAssessment

# AVPU severity order: A (best/0) < V < P < U (worst/3).
# Used to pick the most-impaired consciousness per day from same-day vitals.
_AVPU_SEVERITY: dict[str, int] = {"A": 0, "V": 1, "P": 2, "U": 3}


def enrich_nursing(ctx) -> None:
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 70) or 70)
        seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["nursing"], pid or "x")
        rng = np.random.default_rng(seed)

        # 1) NEWS2 + GCS on each vital record (NEWS2 deterministic; GCS small jitter)
        #
        # Issue #911: GCS must derive from the SAME latent consciousness state
        # as AVPU. Previously the enricher defaulted ``consciousness_level``
        # to ``"A"`` (→ base 15 → jitter → GCS ~14/15) on every vital record
        # regardless of whether that record carried an AVPU sample.
        # `_generate_vitals` only sets ``consciousness_level`` on the routine
        # full-vitals rounds (feature-set-driven emit); continuous-monitoring
        # rows and event rechecks emit without AVPU. AVPU Observations are
        # only emitted for records where ``consciousness_level`` is populated
        # (labs/observations.py line 621's ``if loc:`` gate), so the extra
        # GCS Observations produced from the ``"A"``-defaulted rows were
        # unpaired GCS ≈ 15 records that the audit joins by same-day and
        # sees as ``AVPU=U → GCS=15`` contradictions (12,945 impossible pairs
        # at v0.5.0). Fix: skip GCS emission for vitals without AVPU — one
        # scale is not authored for the other to contradict.
        for vs in _get(rec, "vital_signs", []) or []:
            vsd = vs if isinstance(vs, dict) else vs.__dict__
            news2 = compute_news2(vsd)
            loc_val = vsd.get("consciousness_level", "") or ""
            gcs = compute_gcs(loc_val, perfusion_status=1.0, rng=rng) if loc_val else None
            if isinstance(vs, dict):
                vs["news2_score"] = news2
                if gcs is not None:
                    vs["gcs_score"] = gcs
            else:
                vs.news2_score = news2
                if gcs is not None:
                    vs.gcs_score = gcs

        # 2) Daily Braden + Morse from ADL (align by date) + I/O (IV present)
        adls = _get(rec, "adl_assessments", []) or []
        ios = _get(rec, "intake_output_records", []) or []
        iv_dates = {str(_get(io, "date")) for io in ios if (_get(io, "intake_iv_ml", 0) or 0) > 0}

        # Build date→worst-consciousness map from vitals.
        # For each day take the most impaired reading so the daily nursing assessment
        # reflects peak acuity (e.g. an obtunded patient isn't scored as Alert).
        consciousness_by_date: dict[str, str] = {}
        for vs in _get(rec, "vital_signs", []) or []:
            ts = _get(vs, "timestamp")
            if ts is None:
                continue
            # timestamp may be a datetime object or an ISO string — normalise to date string
            if hasattr(ts, "date"):
                day_key = str(ts.date())
            else:
                day_key = str(ts)[:10]
            clvl = _get(vs, "consciousness_level", "A") or "A"
            prev = consciousness_by_date.get(day_key, "A")
            if _AVPU_SEVERITY.get(clvl, 0) > _AVPU_SEVERITY.get(prev, 0):
                consciousness_by_date[day_key] = clvl

        out = []
        for adl in adls:
            adld = adl if isinstance(adl, dict) else adl.__dict__
            d = adld.get("date")
            # Derive consciousness from same-day vitals; default to Alert when absent.
            # volume_status is not persisted to CIF — always 0.0 (known limitation).
            loc = consciousness_by_date.get(str(d), "A")
            braden = compute_braden(adld, loc, volume_status=0.0, rng=rng)
            morse, level = compute_morse_fall_risk(age, adld, loc, has_iv=str(d) in iv_dates, rng=rng)
            if d is None:
                continue
            out.append(NursingRiskAssessment(date=d, morse_total=morse, fall_risk_level=level, **braden))
        _set(rec, "nursing_risk_assessments", out)
