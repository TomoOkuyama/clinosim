"""FHIR R4 anthropometric Observation builder (Issue #946).

Emits body-measurement Observations — height, weight, BMI, and (for
patients aged ≤ 3 y) head-circumference — on every encounter. Prior
to Issue #946 not a single anthropometric was emitted anywhere in the
generator output; downstream weight-based drug-dose verification, BMI
analytics, and pediatric growth-chart consumers all had zero data.

## Emit shape

One Observation per (patient, encounter, measurement). All four
observations share the following FHIR shape:

- `category = vital-signs` (per HL7 v3-ObservationCategory) — matches
  the sibling HR / SpO2 / temperature vitals emit path.
- `code.coding[0].system = LOINC`.
- `valueQuantity` with UCUM unit (`cm`, `kg`, `kg/m2`).
- `subject` → Patient reference, `encounter` → Encounter reference.
- `effectiveDateTime` = encounter admission datetime.
- Deterministic `id` derived from encounter id + measurement suffix
  (same opaque-id contract as sibling vital-sign builders).

## Value derivation

- **Adults (age ≥ 18)** — height is fixed per patient
  (`patient.height_cm`, set at Layer-1 population sampling from
  country-specific means in `locale/{us,jp}/demographics.yaml`
  `physiology:`). Weight is derived per encounter from
  `patient.weight_kg` plus a SHA256-derived per-encounter drift within
  ~± 1 kg (never crosses BMI-grade boundaries). BMI is computed at
  emit time from the emitted height and weight so the triple is
  internally consistent (Issue #946 acceptance criterion).

- **Pediatric (age < 18)** — each child keeps a stable growth
  percentile (Issue #2876): one z-score per measure, drawn once per
  patient, scales the per-sex growth-chart median
  (`modules/population/reference_data/anthropometric_reference.yaml`;
  WHO infant table, then CDC for US / MHLW-MEXT for JP) interpolated
  linearly by exact age in months: ``median(age) × (1 + cv × z)``.
  Height therefore never decreases between visits and has no birthday
  steps; newborns vary in length, weight and head circumference. Weight
  carries a small relative per-encounter noise (``pediatric_weight_cv``).
  BMI is computed as above.

- **Head circumference** — emitted only for patients aged
  ≤ ``head_circumference_max_age_years`` (default 3 y), on the same
  percentile model plus a small per-encounter noise.

## Determinism / RNG-shape isolation

None of the emit paths draw from the master RNG. Children's z-scores
and noise come from ``determinism.sha_normal`` keyed on the patient id
(z-scores) or ``{patient_id}|{encounter_id}|<suffix>`` (noise). The
adult weight drift keeps its original SHA256 → ``mpmath.erfinv``
formula (``_sha256_gaussian``) so adult output is unchanged.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes.loinc import loinc_for
from clinosim.codes.ucum import ucum_quantity
from clinosim.countries import lang_for
from clinosim.determinism import sha_normal
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_OBSERVATION_COMMON_PROFILE

# ---------------------------------------------------------------------------
# LOINC + display metadata for the four emitted body measurements.
# ---------------------------------------------------------------------------

LOINC_BODY_HEIGHT = loinc_for("anthropometric", "body_height")
LOINC_BODY_WEIGHT = loinc_for("anthropometric", "body_weight")
LOINC_HEAD_CIRCUMFERENCE = loinc_for("anthropometric", "head_circumference")
LOINC_BMI = loinc_for("anthropometric", "bmi")

_DISPLAY_EN = {
    LOINC_BODY_HEIGHT: "Body height",
    LOINC_BODY_WEIGHT: "Body weight",
    LOINC_HEAD_CIRCUMFERENCE: "Head Occipital-frontal circumference",
    LOINC_BMI: "Body mass index (BMI) [Ratio]",
}
_DISPLAY_JA = {
    LOINC_BODY_HEIGHT: t("fhir_obs_text.body_height", "ja"),
    LOINC_BODY_WEIGHT: t("fhir_obs_text.body_weight", "ja"),
    LOINC_HEAD_CIRCUMFERENCE: t("fhir_obs_text.head_circumference", "ja"),
    LOINC_BMI: "BMI",
}
_UNIT_UCUM = {
    LOINC_BODY_HEIGHT: "cm",
    LOINC_BODY_WEIGHT: "kg",
    LOINC_HEAD_CIRCUMFERENCE: "cm",
    LOINC_BMI: "kg/m2",
}

# ---------------------------------------------------------------------------
# Opaque id resolver (matches sibling vs-* / blood-* pattern).
# ---------------------------------------------------------------------------

ANTHROPOMETRIC_OBSERVATION_ID_PREFIX = "anthro-"
ANTHROPOMETRIC_OBSERVATION_KEY_SYSTEM = structural_key_system("anthropometric-observation-key")


def _resolve_anthropometric_id(structural_key: str) -> str:
    """FHIR id for one anthropometric Observation.

    Structural key body: ``{encounter_id or patient_id}-{suffix}`` where
    suffix ∈ ``{height, weight, bmi, hc}``. Preserved on
    ``Observation.identifier[]`` for round-trip.
    """
    return derive_opaque_id(ANTHROPOMETRIC_OBSERVATION_ID_PREFIX, structural_key)


# ---------------------------------------------------------------------------
# Reference-table loader.
# ---------------------------------------------------------------------------


def _load_reference() -> dict[str, Any]:
    """anthropometric_reference.yaml through the population module's validated loader."""
    from clinosim.modules.population._pediatric_anthropometry import load_anthropometric_reference

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
        hc_sd = float(noise.get("head_circumference_cm_sd", 0.1))
        hc = _clamp(
            hc_base + sha_normal(f"{patient_id}|{encounter_id}|hc", 0.0, hc_sd),
            float((clamps.get("head_circumference_cm") or {}).get("min", 30.0)),
            float((clamps.get("head_circumference_cm") or {}).get("max", 60.0)),
        )
        out["head_circumference_cm"] = round(hc, 1)

    return out


# ---------------------------------------------------------------------------
# Observation resource builder.
# ---------------------------------------------------------------------------


def _build_one_observation(
    loinc: str,
    value: float,
    patient_id: str,
    encounter_id: str,
    effective_dt: str,
    country: str,
    suffix: str,
) -> dict[str, Any]:
    """Assemble one FHIR anthropometric Observation resource."""
    display = _DISPLAY_JA[loinc] if is_jp(country) else _DISPLAY_EN[loinc]
    unit = _UNIT_UCUM[loinc]
    structural_key = f"{encounter_id or patient_id}-{suffix}"
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _resolve_anthropometric_id(structural_key),
        "identifier": [wrap_as_identifier(structural_key, ANTHROPOMETRIC_OBSERVATION_KEY_SYSTEM)],
        **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
        "status": "final",
        "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc,
                    "display": _DISPLAY_EN[loinc],
                }
            ],
            "text": display,
        },
        "subject": patient_ref(patient_id),
        "valueQuantity": ucum_quantity(value, unit),
    }
    if effective_dt:
        obs["effectiveDateTime"] = effective_dt
    if encounter_id:
        obs["encounter"] = encounter_ref(encounter_id)
    return obs


def build_anthropometric_observations(
    patient_data: dict,
    encounter: dict,
    country: str,
) -> list[dict[str, Any]]:
    """Return a list of body-height / body-weight / BMI [ / head-circ]
    Observation resources for one encounter. Empty list if the patient
    lacks a usable date_of_birth.
    """
    patient_id = str(patient_data.get("patient_id", "") or "")
    encounter_id = str(get_attr_or_key(encounter, "encounter_id", "") or "")

    dob = _parse_date_of_birth(patient_data.get("date_of_birth"))
    enc_dt = _parse_encounter_datetime(get_attr_or_key(encounter, "admission_datetime", None))
    age_months: float | None = None
    if dob is None:
        age_years = int(patient_data.get("age", 0) or 0)
    elif enc_dt is None:
        age_years = int(patient_data.get("age", 0) or 0)
    else:
        age_years = _age_at(dob, enc_dt)
        age_months = _age_in_months(dob, enc_dt)

    values = _derive_anthropometrics(patient_data, encounter_id, age_years, country, age_months)

    effective_dt = to_fhir_datetime(enc_dt.isoformat()) if enc_dt else ""

    out: list[dict[str, Any]] = []
    out.append(
        _build_one_observation(
            LOINC_BODY_HEIGHT, values["height_cm"], patient_id, encounter_id, effective_dt, country, "height"
        )
    )
    out.append(
        _build_one_observation(
            LOINC_BODY_WEIGHT, values["weight_kg"], patient_id, encounter_id, effective_dt, country, "weight"
        )
    )
    # Issue #1322: BMI is not a valid metric under age 2 (WHO / AAP: use
    # weight-for-length percentile instead). Suppress the BMI Observation
    # for infants; height + weight alone suffice for growth analytics.
    if age_years >= 2:
        out.append(
            _build_one_observation(LOINC_BMI, values["bmi"], patient_id, encounter_id, effective_dt, country, "bmi")
        )
    if "head_circumference_cm" in values:
        out.append(
            _build_one_observation(
                LOINC_HEAD_CIRCUMFERENCE,
                values["head_circumference_cm"],
                patient_id,
                encounter_id,
                effective_dt,
                country,
                "hc",
            )
        )
    return out


def _bb_anthropometrics(ctx: BundleContext) -> list[dict]:
    """Bundle builder: emit height / weight / BMI (+ head-circ if pediatric)
    for every encounter in the record.

    Registered in ``_BUNDLE_BUILDERS`` next to ``_bb_vitals``.
    """
    out: list[dict] = []
    encounters = ctx.record.get("encounters", []) or []
    patient_data = ctx.patient_data or {}
    for enc in encounters:
        enc_dict = (
            enc
            if isinstance(enc, dict)
            else {
                "encounter_id": getattr(enc, "encounter_id", ""),
                "admission_datetime": getattr(enc, "admission_datetime", None),
            }
        )
        out.extend(build_anthropometric_observations(patient_data, enc_dict, ctx.country))
    return out
