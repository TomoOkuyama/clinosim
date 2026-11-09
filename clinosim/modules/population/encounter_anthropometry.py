"""Body measurements charted at one encounter (Issue #946, #2876, #2990).

The single derivation of the height / weight / BMI (/ head circumference)
a patient is measured at on an encounter. The FHIR anthropometric
Observation builder (``modules/output/fhir_r4/labs/anthropometrics.py``)
emits these values, and weight-based dosing reads the same weight
(``encounter_weight_kg``) so a dose matches the weight charted at the visit.

## Value derivation

- **Adults (age >= 18)** — height is fixed per patient
  (``height_cm``, set at Layer-1 population sampling from
  country-specific means in ``locale/{us,jp}/demographics.yaml``
  ``physiology:``). Weight is the profile ``weight_kg`` plus a
  SHA256-derived per-encounter drift within ~± 1 kg (never crosses
  BMI-grade boundaries). BMI is computed from the height and weight so
  the triple is internally consistent.

- **Pediatric (age < 18)** — each child keeps a stable growth
  percentile (Issue #2876): one z-score per measure, drawn once per
  patient, scales the per-sex growth-chart median
  (``reference_data/anthropometric_reference.yaml``; WHO infant table,
  then CDC for US / MHLW-MEXT for JP) interpolated linearly by exact age
  in months: ``median(age) × (1 + cv × z)``. Height therefore never
  decreases between visits and has no birthday steps. Weight carries a
  small relative per-encounter noise (``pediatric_weight_cv``). The
  profile ``weight_kg`` is not used: it is the weight at registration.

- **Head circumference** — only for patients aged
  ≤ ``head_circumference_max_age_years`` (default 3 y), on the same
  percentile model.

## Determinism / RNG-shape isolation

Nothing here draws from the master RNG. Children's z-scores and noise
come from ``determinism.sha_normal`` keyed on the patient id (z-scores)
or ``{patient_id}|{encounter_id}|<suffix>`` (noise). The adult weight
drift keeps its original SHA256 → ``mpmath.erfinv`` formula
(``_sha256_gaussian``) so adult output is unchanged. The same
(patient, encounter id, encounter date) always gives the same values.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from clinosim.determinism import sha_normal
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.population._pediatric_anthropometry import load_anthropometric_reference

_PATIENT_FIELDS = ("patient_id", "sex", "date_of_birth", "age", "height_cm", "weight_kg")


# ---------------------------------------------------------------------------
# Reference-table loader.
# ---------------------------------------------------------------------------


def _load_reference() -> dict[str, Any]:
    """anthropometric_reference.yaml through the population module's validated loader."""
    return load_anthropometric_reference()


# ---------------------------------------------------------------------------
# Deterministic per-encounter noise (RNG-neutral SHA256 quantile).
# ---------------------------------------------------------------------------


def _sha256_gaussian(key: str, sd: float) -> float:
    """Return a Gaussian sample with mean 0 / std ``sd``, derived from a
    stable SHA256 of ``key`` (no master-RNG consumption).

    16-bit quantile → inverse Gaussian CDF via mpmath.erfinv. Following
    ``feedback_rng_neutral_additive_field.md``: introducing this emit
    must not shift any downstream RNG cursor.
    """
    if sd <= 0:
        return 0.0
    from mpmath import erfinv, mp, mpf, sqrt  # type: ignore[import-untyped]

    mp.prec = 128
    h = hashlib.sha256(key.encode()).digest()
    # Uniform in (0, 1) — avoid exact 0 / 1 (erfinv diverges).
    raw = int.from_bytes(h[:4], "big") + 1
    quantile = mpf(raw) / mpf(2**32 + 1)
    # inverse CDF of standard normal at quantile q: sqrt(2) * erfinv(2q - 1)
    z = sqrt(2) * erfinv(2 * quantile - 1)
    return float(z) * sd


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Age at encounter.
# ---------------------------------------------------------------------------


def _parse_encounter_datetime(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00").split("+")[0])
    except (ValueError, TypeError):
        return None


def _parse_date_of_birth(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _age_at(dob: date, when: datetime) -> int:
    yrs = when.year - dob.year
    if (when.month, when.day) < (dob.month, dob.day):
        yrs -= 1
    return max(0, yrs)


def _age_in_months(dob: date, when: datetime) -> float:
    """Exact age in months (days / mean month length), 0 at or before ``dob``.

    Fractional so the growth curve advances smoothly between visits instead
    of stepping at month or birthday boundaries (Issue #2876).
    """
    return max(0.0, (when.date() - dob).days / _DAYS_PER_MONTH)


# ---------------------------------------------------------------------------
# Value derivation.
# ---------------------------------------------------------------------------


_DAYS_PER_MONTH = 365.25 / 12
_INFANT_MEDIAN_UPPER_MONTHS = 24
_MEASURES = ("height", "weight", "head_circumference")


def _sex_key(sex: str) -> str:
    return "male" if str(sex or "").upper().startswith("M") else "female"


def _pediatric_medians(country: str, sex: str, age_years: int) -> dict[str, float] | None:
    """Return the yearly growth-table row ``{"height", "weight"}`` for
    ``(country, sex, age_years)``, or None when the age falls outside the
    table. Used only for the adult fallback when a profile carries no
    stored height / weight.
    """
    ref = _load_reference()
    tables = (ref.get("pediatric_growth") or {}).get("JP" if is_jp(country) else "US") or {}
    row = (tables.get(_sex_key(sex)) or {}).get(int(age_years))
    if not row:
        return None
    return {"height": float(row.get("height", 0.0)), "weight": float(row.get("weight", 0.0))}


@lru_cache(maxsize=16)
def _growth_curve(country: str, sex_key: str, measure: str) -> tuple[tuple[float, float], ...]:
    """The reference median of one measure as ``((age_months, value), …)``,
    sorted by age (Issue #2876).

    Points: the monthly infant rows (both countries), then the yearly rows
    for ages >= 2 at mid-year (``(y + 0.5) × 12`` months) — the anchoring
    documented in ``anthropometric_reference.yaml``. Yearly rows 0 and 1 are
    superseded by the infant rows. Rows without the measure are skipped.
    """
    ref = _load_reference()
    points: list[tuple[float, float]] = []
    for month, row in ((ref.get("pediatric_growth_infant") or {}).get(sex_key) or {}).items():
        if row.get(measure) is not None:
            points.append((float(month), float(row[measure])))
    yearly = ((ref.get("pediatric_growth") or {}).get(country) or {}).get(sex_key) or {}
    first_yearly = _INFANT_MEDIAN_UPPER_MONTHS // 12
    for year, row in yearly.items():
        if int(year) >= first_yearly and row.get(measure) is not None:
            points.append(((int(year) + 0.5) * 12.0, float(row[measure])))
    return tuple(sorted(points))


def _median_at(country: str, sex: str, age_months: float, measure: str) -> float | None:
    """Reference median of ``measure`` at ``age_months``, linearly
    interpolated between the curve points and flat beyond its ends.
    None when the reference carries no value for the measure."""
    curve = _growth_curve("JP" if is_jp(country) else "US", _sex_key(sex), measure)
    if not curve:
        return None
    if age_months <= curve[0][0]:
        return curve[0][1]
    for (m0, v0), (m1, v1) in zip(curve, curve[1:], strict=False):
        if age_months <= m1:
            return v0 + (v1 - v0) * (age_months - m0) / (m1 - m0)
    return curve[-1][1]


def _growth_z_scores(patient_id: str, variation: dict[str, Any]) -> dict[str, float]:
    """One stable z-score per measure for this child (Issue #2876).

    Each measure mixes a shared body-size z (weight ``shared_size_correlation``)
    with its own z, so a large child is large on every measure. Drawn with
    ``sha_normal`` keyed on the patient id: the same at every visit and no
    master-RNG draw. Truncated at ``± z_limit``.
    """
    rho = float(variation.get("shared_size_correlation", 0.7))
    limit = float(variation.get("z_limit", 2.5))
    own = math.sqrt(max(0.0, 1.0 - rho * rho))
    size = sha_normal(f"anthropometry-growth|{patient_id}|size")
    return {
        m: _clamp(rho * size + own * sha_normal(f"anthropometry-growth|{patient_id}|{m}"), -limit, limit)
        for m in _MEASURES
    }


def _derive_anthropometrics(
    patient_data: dict,
    encounter_id: str,
    age_years: int,
    country: str,
    age_months: float | None = None,
) -> dict[str, float]:
    """Return {"height_cm", "weight_kg", "bmi", "head_circumference_cm"?}
    for one encounter. Values are clamped to yaml `clamps` bounds.

    Children (Issue #2876): the reference median at the exact age in months
    (``age_months``; mid-year of ``age_years`` when it is None), scaled by
    the child's stable percentile ``1 + cv × z``, plus a small per-encounter
    weight noise.
    """
    ref = _load_reference()
    clamps = ref.get("clamps") or {}
    noise = ref.get("per_encounter_noise") or {}
    hc_max_age = int(ref.get("head_circumference_max_age_years", 3))
    adult_min = int(ref.get("adult_path_min_age_years", 18))

    patient_id = str(patient_data.get("patient_id", "") or "")
    sex = str(patient_data.get("sex", "") or "M")

    height_noise = 0.0
    hc_base: float | None = None
    if age_years >= adult_min:
        # Adult path — patient profile carries height/weight/bmi already
        # sampled at Layer 1 from country-specific demographics.yaml.
        # Height is fixed per patient (no encounter noise). Weight varies
        # per encounter within the yaml sd; BMI recomputed at emit time.
        base_height = float(patient_data.get("height_cm", 0.0) or 0.0)
        base_weight = float(patient_data.get("weight_kg", 0.0) or 0.0)
        # Fallback: if the patient profile is missing height/weight
        # (external CIF ingest), synthesize from country demographics.
        if base_height <= 0.0 or base_weight <= 0.0:
            fallback = _pediatric_medians(country, sex, 17) or {"height": 165.0, "weight": 60.0}
            if base_height <= 0.0:
                base_height = float(fallback["height"])
            if base_weight <= 0.0:
                base_weight = float(fallback["weight"])
        weight_sd = float(noise.get("weight_kg_sd", 0.6))
        weight_kg = base_weight + _sha256_gaussian(f"{patient_id}|{encounter_id}|weight", weight_sd)
    else:
        months = age_months if age_months is not None else (age_years + 0.5) * 12.0
        variation = ref.get("pediatric_growth_variation") or {}
        z = _growth_z_scores(patient_id, variation)
        cv = {m: float(variation.get(f"{m}_cv", 0.0)) for m in _MEASURES}
        medians = {m: _median_at(country, sex, months, m) for m in _MEASURES}
        base_height = (medians["height"] or 160.0) * (1.0 + cv["height"] * z["height"])
        base_weight = (medians["weight"] or 55.0) * (1.0 + cv["weight"] * z["weight"])
        hc_median = medians["head_circumference"]
        if hc_median is not None:
            hc_base = hc_median * (1.0 + cv["head_circumference"] * z["head_circumference"])
        height_sd = float(noise.get("pediatric_height_cm_sd", 0.0))
        if height_sd > 0:
            height_noise = sha_normal(f"{patient_id}|{encounter_id}|height", 0.0, height_sd)
        weight_cv = float(noise.get("pediatric_weight_cv", 0.01))
        weight_kg = base_weight * (1.0 + sha_normal(f"{patient_id}|{encounter_id}|weight", 0.0, weight_cv))

    height_cm = _clamp(
        base_height + height_noise,
        float((clamps.get("height_cm") or {}).get("min", 40.0)),
        float((clamps.get("height_cm") or {}).get("max", 210.0)),
    )
    weight_kg = _clamp(
        weight_kg,
        float((clamps.get("weight_kg") or {}).get("min", 2.0)),
        float((clamps.get("weight_kg") or {}).get("max", 200.0)),
    )
    bmi = weight_kg / ((height_cm / 100.0) ** 2)
    bmi = _clamp(
        bmi,
        float((clamps.get("bmi") or {}).get("min", 10.0)),
        float((clamps.get("bmi") or {}).get("max", 60.0)),
    )

    out: dict[str, float] = {
        "height_cm": round(height_cm, 1),
        "weight_kg": round(weight_kg, 1),
        "bmi": round(bmi, 1),
    }

    if age_years <= hc_max_age and hc_base is not None:
        hc_sd = float(noise.get("head_circumference_cm_sd", 0.0))
        if hc_sd > 0:
            hc_base += sha_normal(f"{patient_id}|{encounter_id}|hc", 0.0, hc_sd)
        hc = _clamp(
            hc_base,
            float((clamps.get("head_circumference_cm") or {}).get("min", 30.0)),
            float((clamps.get("head_circumference_cm") or {}).get("max", 60.0)),
        )
        out["head_circumference_cm"] = round(hc, 1)

    return out


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def age_at_measurement(patient: Any, encounter_datetime: Any) -> tuple[int, float | None]:
    """``(age_years, age_months)`` of ``patient`` (a profile or its CIF dict)
    at ``encounter_datetime``. Without a date of birth or an encounter
    datetime the profile ``age`` is used and ``age_months`` is None."""
    dob = _parse_date_of_birth(get_attr_or_key(patient, "date_of_birth", None))
    enc_dt = _parse_encounter_datetime(encounter_datetime)
    if dob is None or enc_dt is None:
        return int(get_attr_or_key(patient, "age", 0) or 0), None
    return _age_at(dob, enc_dt), _age_in_months(dob, enc_dt)


def encounter_anthropometrics(
    patient: Any, encounter_id: str, encounter_datetime: Any, country: str
) -> dict[str, float]:
    """``{"height_cm", "weight_kg", "bmi", "head_circumference_cm"?}`` charted
    for ``patient`` (a ``PatientProfile`` or its CIF dict) on the encounter
    ``encounter_id`` starting at ``encounter_datetime`` (the encounter's
    admission datetime)."""
    data = {k: get_attr_or_key(patient, k, None) for k in _PATIENT_FIELDS}
    age_years, age_months = age_at_measurement(data, encounter_datetime)
    return _derive_anthropometrics(data, str(encounter_id or ""), age_years, country, age_months)


def encounter_weight_kg(patient: Any, encounter_id: str, encounter_datetime: Any, country: str) -> float:
    """Body weight (kg) charted on the encounter — the value of its
    body-weight Observation. Use it for weight-based doses."""
    return encounter_anthropometrics(patient, encounter_id, encounter_datetime, country)["weight_kg"]
