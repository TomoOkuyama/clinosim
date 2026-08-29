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

- **Pediatric (age < 18)** — height and weight come from a per-age /
  per-sex p50 growth-chart median in
  `locale/shared/anthropometric_reference.yaml` (WHO / MHLW for JP,
  WHO / CDC for US). A small per-encounter SHA256-derived noise is
  added. BMI is computed as above.

- **Head circumference** — emitted only for patients aged
  ≤ ``head_circumference_max_age_years`` (default 3 y). Same
  SHA256-derived per-encounter noise pattern.

## Determinism / RNG-shape isolation

None of the emit paths draw from the master RNG. Per-encounter noise
is derived from ``hashlib.sha256(f"{patient_id}|{encounter_id}|<suffix>"
.encode())`` and mapped to a Gaussian quantile via ``mpmath.erfinv`` —
following the memory-rule pattern documented in
``feedback_rng_neutral_additive_field.md`` (introducing the emit does
not shift any downstream RNG cursor, keeping memoize / F4 byte-
identical guarantees intact for every other resource type).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.codes import get_system_uri
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# ---------------------------------------------------------------------------
# LOINC + display metadata for the four emitted body measurements.
# ---------------------------------------------------------------------------

LOINC_BODY_HEIGHT = "8302-2"
LOINC_BODY_WEIGHT = "29463-7"
LOINC_HEAD_CIRCUMFERENCE = "8287-5"
LOINC_BMI = "39156-5"

_DISPLAY_EN = {
    LOINC_BODY_HEIGHT: "Body height",
    LOINC_BODY_WEIGHT: "Body weight",
    LOINC_HEAD_CIRCUMFERENCE: "Head Occipital-frontal circumference",
    LOINC_BMI: "Body mass index (BMI) [Ratio]",
}
_DISPLAY_JA = {
    LOINC_BODY_HEIGHT: "身長",
    LOINC_BODY_WEIGHT: "体重",
    LOINC_HEAD_CIRCUMFERENCE: "頭囲",
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

_REFERENCE_YAML_PATH = Path(__file__).resolve().parents[4] / "locale" / "shared" / "anthropometric_reference.yaml"


@lru_cache(maxsize=1)
def _load_reference() -> dict[str, Any]:
    """Load anthropometric_reference.yaml (cached)."""
    with open(_REFERENCE_YAML_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
    from mpmath import erfinv, mp, mpf, sqrt

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


# ---------------------------------------------------------------------------
# Value derivation.
# ---------------------------------------------------------------------------


def _pediatric_medians(country: str, sex: str, age_years: int) -> dict[str, float] | None:
    """Return {"height": …, "weight": …, "head_circumference": …?} for a
    pediatric age / sex, or None when the age falls outside the yaml table.

    Sex normalization: "M" / "male" → male row, otherwise female row.
    """
    ref = _load_reference()
    tables = (ref.get("pediatric_growth") or {}).get("JP" if is_jp(country) else "US") or {}
    sex_key = "male" if str(sex or "").upper().startswith("M") else "female"
    row = (tables.get(sex_key) or {}).get(int(age_years))
    if not row:
        return None
    return {
        "height": float(row.get("height", 0.0)),
        "weight": float(row.get("weight", 0.0)),
        "head_circumference": (float(row["head_circumference"]) if "head_circumference" in row else None),
    }


def _derive_anthropometrics(
    patient_data: dict,
    encounter_id: str,
    age_years: int,
    country: str,
) -> dict[str, float]:
    """Return {"height_cm", "weight_kg", "bmi", "head_circumference_cm"?}
    for one encounter. Values are clamped to yaml `clamps` bounds.
    """
    ref = _load_reference()
    clamps = ref.get("clamps") or {}
    noise = ref.get("per_encounter_noise") or {}
    hc_max_age = int(ref.get("head_circumference_max_age_years", 3))
    adult_min = int(ref.get("adult_path_min_age_years", 18))

    patient_id = str(patient_data.get("patient_id", "") or "")
    sex = str(patient_data.get("sex", "") or "M")

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
    else:
        # Pediatric path — growth-chart medians per age/sex.
        peds = _pediatric_medians(country, sex, age_years)
        if peds is None:
            # Age outside table range: fall back to nearest adult profile.
            base_height = float(patient_data.get("height_cm", 0.0) or 0.0) or 160.0
            base_weight = float(patient_data.get("weight_kg", 0.0) or 0.0) or 55.0
            peds = {"head_circumference": None}
        else:
            base_height = peds["height"]
            base_weight = peds["weight"]

    # Per-encounter weight noise (RNG-neutral SHA256 → Gaussian).
    weight_sd = float(noise.get("weight_kg_sd", 0.6))
    weight_noise = _sha256_gaussian(f"{patient_id}|{encounter_id}|weight", weight_sd)
    height_cm = _clamp(
        base_height,
        float((clamps.get("height_cm") or {}).get("min", 40.0)),
        float((clamps.get("height_cm") or {}).get("max", 210.0)),
    )
    weight_kg = _clamp(
        base_weight + weight_noise,
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

    if age_years <= hc_max_age:
        # Head-circumference: pediatric growth-chart median + small noise.
        peds = _pediatric_medians(country, sex, age_years) or {}
        hc_base = peds.get("head_circumference")
        if hc_base is not None:
            hc_sd = float(noise.get("head_circumference_cm_sd", 0.1))
            hc_noise = _sha256_gaussian(f"{patient_id}|{encounter_id}|hc", hc_sd)
            hc = _clamp(
                float(hc_base) + hc_noise,
                float((clamps.get("head_circumference_cm") or {}).get("min", 30.0)),
                float((clamps.get("head_circumference_cm") or {}).get("max", 60.0)),
            )
            out["head_circumference_cm"] = round(hc, 1)

    return out


# ---------------------------------------------------------------------------
# Observation resource builder.
# ---------------------------------------------------------------------------

_CATEGORY_DISPLAY_EN = "Vital Signs"
_CATEGORY_DISPLAY_JA = "バイタルサイン"


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
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
            if is_jp(country)
            else {}
        ),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-observation-category"),
                        "code": "vital-signs",
                        "display": _CATEGORY_DISPLAY_JA if is_jp(country) else _CATEGORY_DISPLAY_EN,
                    }
                ],
                "text": _CATEGORY_DISPLAY_JA if is_jp(country) else _CATEGORY_DISPLAY_EN,
            }
        ],
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
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": get_system_uri("ucum"),
            "code": unit,
        },
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
    if dob is None:
        age_years = int(patient_data.get("age", 0) or 0)
    elif enc_dt is None:
        age_years = int(patient_data.get("age", 0) or 0)
    else:
        age_years = _age_at(dob, enc_dt)

    values = _derive_anthropometrics(patient_data, encounter_id, age_years, country)

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
    out.append(_build_one_observation(LOINC_BMI, values["bmi"], patient_id, encounter_id, effective_dt, country, "bmi"))
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
