"""Nursing flowsheet enricher (AD-55 Base, AD-56 post_records).

Fills NEWS2/GCS on each vital record and generates daily Braden/Morse risk
assessments. Uses a dedicated sub-seed so the main random stream is untouched.
"""

from __future__ import annotations

from clinosim import determinism
from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.observation._nursing_score_thresholds import NEWS2_MIN_AGE_YEARS
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
        # Issue #2872: NEWS2 is an adult score (RCP 2017: age >= 16). The
        # recorded age is read as is here (``age`` above maps 0 to 70).
        _recorded_age = _get(patient, "age", None) if patient else None
        news2_applies = _recorded_age is None or int(_recorded_age) >= NEWS2_MIN_AGE_YEARS
        seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["nursing"], pid or "x")
        rng = determinism.default_rng(seed)

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
            news2 = compute_news2(vsd) if news2_applies else None
            loc_val = vsd.get("consciousness_level", "") or ""
            gcs = compute_gcs(loc_val, perfusion_status=1.0, rng=rng) if loc_val else None
            if isinstance(vs, dict):
                if news2 is not None:
                    vs["news2_score"] = news2
                if gcs is not None:
                    vs["gcs_score"] = gcs
            else:
                if news2 is not None:
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

        # Issue #2692: Morse "secondary diagnosis" — a medical diagnosis besides
        # the reason for this stay (any chronic condition on the problem list).
        has_secondary = bool(_get(patient, "chronic_conditions", None))
        # Morse "history of falling": once per stay, from a hash (no RNG).
        from clinosim.modules.observation.nursing import morse_fall_history
        from clinosim.seeding import morse_fall_history_unit

        _encs = _get(rec, "encounters", []) or []
        _enc_id = str(_get(_encs[0], "encounter_id", "") or "") if _encs else ""
        fell_recently = morse_fall_history(age, morse_fall_history_unit(pid or "x", _enc_id))
        out = []
        for adl in adls:
            adld = adl if isinstance(adl, dict) else adl.__dict__
            d = adld.get("date")
            # Derive consciousness from same-day vitals; default to Alert when absent.
            # volume_status is not persisted to CIF — always 0.0 (known limitation).
            loc = consciousness_by_date.get(str(d), "A")
            braden = compute_braden(adld, loc, volume_status=0.0, rng=rng)
            morse, level, morse_items = compute_morse_fall_risk(
                age,
                adld,
                loc,
                has_iv=str(d) in iv_dates,
                rng=rng,
                has_secondary_diagnosis=has_secondary,
                fell_recently=fell_recently,
            )
            if d is None:
                continue
            out.append(NursingRiskAssessment(date=d, morse_total=morse, fall_risk_level=level, **braden, **morse_items))
        _set(rec, "nursing_risk_assessments", out)
