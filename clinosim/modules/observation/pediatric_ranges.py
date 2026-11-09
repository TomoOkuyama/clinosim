"""Pediatric vital-sign ranges and lab reference intervals (Issue #2872).

``reference_data/pediatric_reference_ranges.yaml`` holds age-banded normal
ranges for children: vital signs by age in completed months (Fleming et al.
2011 centiles, PALS 2020 blood pressure), labs by age in completed years
(Harriet Lane Handbook). These accessors are the one place that answers
"which range applies to a child of this age"; ``None`` means no pediatric
band covers the age (adults, or a vital / analyte not listed) and the
caller keeps its adult range.

Readers: the FHIR vital-sign and lab Observation builders (referenceRange,
interpretation), :func:`clinosim.modules.observation.engine.determine_flag`
(CIF lab flag), the physiology lab derivation (a child's true value), the
physiology vital-sign derivation (a child's respiratory-rate ceiling,
Issue #2926) and the patient activator (a child's baseline vitals).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clinosim.age_bands import find_age_band, parse_closed_age_band
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t

__all__ = [
    "PEDIATRIC_UPPER_AGE_MONTHS",
    "PEDIATRIC_VITAL_SIGNS",
    "PediatricVitalRange",
    "age_in_completed_months",
    "age_independent_vital_range_text",
    "carry_vital_centile",
    "pediatric_lab_band",
    "pediatric_lab_center",
    "pediatric_lab_range",
    "pediatric_lab_range_text",
    "pediatric_vital_range",
    "pediatric_vital_max",
    "pediatric_vital_range_text",
]

_PATH = Path(__file__).resolve().parent / "reference_data" / "pediatric_reference_ranges.yaml"

PEDIATRIC_VITAL_SIGNS: tuple[str, ...] = ("heart_rate", "respiratory_rate", "systolic_bp", "diastolic_bp")
"""The vital signs the YAML may band (``vs`` dict / BaselineVitals field names)."""

_MONTHS_PER_YEAR = 12

PEDIATRIC_UPPER_AGE_MONTHS: int = 18 * _MONTHS_PER_YEAR
"""A patient is a child below 18 years (the upper end of the YAML's bands)."""


class _VitalBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float
    median: float
    high: float
    critical_low: float | None
    critical_high: float | None

    @model_validator(mode="after")
    def _ordered(self) -> _VitalBand:
        if not self.low <= self.median <= self.high:
            raise ValueError(f"vital band needs low <= median <= high, got {self}")
        if self.critical_low is not None and self.critical_low >= self.low:
            raise ValueError(f"critical_low {self.critical_low} must lie below the normal low {self.low}")
        if self.critical_high is not None and self.critical_high <= self.high:
            raise ValueError(f"critical_high {self.critical_high} must lie above the normal high {self.high}")
        return self


class _LabBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all: tuple[float, float] | None = None
    M: tuple[float, float] | None = None
    F: tuple[float, float] | None = None

    @model_validator(mode="after")
    def _one_shape(self) -> _LabBand:
        if (self.all is None) == (self.M is None or self.F is None):
            raise ValueError("a lab band gives either `all` or both `M` and `F`")
        for rng in (self.all, self.M, self.F):
            if rng is not None and not rng[0] < rng[1]:
                raise ValueError(f"lab band needs low < high, got {rng}")
        return self


class _LabAnalyte(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str
    bands: dict[str, _LabBand]

    @field_validator("bands")
    @classmethod
    def _closed_bands(cls, bands: dict[str, _LabBand]) -> dict[str, _LabBand]:
        _check_bands(bands)
        return bands


def _check_bands(bands: dict[str, Any]) -> None:
    """Bands are closed, non-empty and do not overlap."""
    spans = sorted(parse_closed_age_band(k) for k in bands)
    if not spans:
        raise ValueError("no age bands")
    for (_, prev_hi), (lo, _) in zip(spans, spans[1:], strict=False):
        if lo <= prev_hi:
            raise ValueError(f"overlapping age bands in {sorted(bands)}")


class PediatricReferenceRanges(BaseModel):
    """Shape of pediatric_reference_ranges.yaml."""

    model_config = ConfigDict(extra="forbid")

    age_independent_vital_signs: list[str]
    vital_signs: dict[str, dict[str, _VitalBand]]
    physiological_max: dict[str, dict[str, float]]
    labs: dict[str, _LabAnalyte]

    @model_validator(mode="after")
    def _independent_not_banded(self) -> PediatricReferenceRanges:
        both = set(self.age_independent_vital_signs) & set(self.vital_signs)
        if both:
            raise ValueError(f"vital sign(s) {sorted(both)} are both banded and age-independent")
        return self

    @field_validator("vital_signs")
    @classmethod
    def _known_vitals(cls, vitals: dict[str, dict[str, _VitalBand]]) -> dict[str, dict[str, _VitalBand]]:
        unknown = set(vitals) - set(PEDIATRIC_VITAL_SIGNS)
        if unknown:
            raise ValueError(f"unknown vital sign(s) {sorted(unknown)}")
        for bands in vitals.values():
            _check_bands(bands)
        return vitals

    @model_validator(mode="after")
    def _max_above_normal(self) -> PediatricReferenceRanges:
        """Each ceiling is a known vital sign and lies above the normal high
        of every vital-sign band it overlaps (the normal range stays reachable)."""
        for vital, ceilings in self.physiological_max.items():
            if vital not in PEDIATRIC_VITAL_SIGNS:
                raise ValueError(f"physiological_max: unknown vital sign {vital!r}")
            _check_bands(ceilings)
            for key, ceiling in ceilings.items():
                lo, hi = parse_closed_age_band(key)
                for band_key, band in (self.vital_signs.get(vital) or {}).items():
                    b_lo, b_hi = parse_closed_age_band(band_key)
                    if b_lo <= hi and lo <= b_hi and ceiling <= band.high:
                        raise ValueError(
                            f"physiological_max {vital} {key}: {ceiling} is not above the normal high "
                            f"{band.high} of band {band_key}"
                        )
        return self

    @field_validator("labs")
    @classmethod
    def _known_labs(cls, labs: dict[str, _LabAnalyte]) -> dict[str, _LabAnalyte]:
        from clinosim.modules.observation.engine import canonical_lab_name

        offenders = [name for name in labs if canonical_lab_name(name) != name]
        if offenders:
            raise ValueError(f"lab names must be canonical lab names: {offenders}")
        return labs


@lru_cache(maxsize=1)
def _table() -> dict[str, Any]:
    return load_validated_yaml(_PATH, PediatricReferenceRanges)


@dataclass(frozen=True)
class PediatricVitalRange:
    """The normal and critical range of one vital sign for one age band."""

    band: str
    low: float
    median: float
    high: float
    critical_low: float | None
    critical_high: float | None


def age_in_completed_months(birth: date | datetime | str | None, when: date | datetime | str | None) -> int | None:
    """Completed months of age on ``when`` (``None`` when either date is unknown)."""

    def _as_date(value: date | datetime | str | None) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                return None
        return None

    born, on = _as_date(birth), _as_date(when)
    if born is None or on is None or on < born:
        return None
    months = (on.year - born.year) * _MONTHS_PER_YEAR + (on.month - born.month)
    if on.day < born.day:
        months -= 1
    return max(0, months)


def pediatric_vital_range(vital: str, age_months: int | None) -> PediatricVitalRange | None:
    """The pediatric range of ``vital`` at ``age_months``, or ``None`` (adult range applies)."""
    if age_months is None:
        return None
    bands = (_table().get("vital_signs") or {}).get(vital) or {}
    key = find_age_band(bands, age_months)
    if key is None:
        return None
    row = bands[key]
    return PediatricVitalRange(
        band=str(key),
        low=float(row["low"]),
        median=float(row["median"]),
        high=float(row["high"]),
        critical_low=None if row.get("critical_low") is None else float(row["critical_low"]),
        critical_high=None if row.get("critical_high") is None else float(row["critical_high"]),
    )


def carry_vital_centile(vital: str, value: float, from_months: int | None, to_months: int | None) -> float | None:
    """``value`` of ``vital`` set for a child of ``from_months``, carried to the
    same centile at ``to_months`` (Issue #2988): its position between the
    band's median and the 1st (below) or 99th (above) centile is kept, so a
    median child stays on the median as the median falls with age. ``None``
    when either age has no pediatric band (an adult, or 18 years and older)."""
    start = pediatric_vital_range(vital, from_months)
    end = pediatric_vital_range(vital, to_months)
    if start is None or end is None:
        return None
    if value >= start.median:
        span, target = start.high - start.median, end.high - end.median
    else:
        span, target = start.median - start.low, end.median - end.low
    return end.median + (value - start.median) * (target / span if span else 1.0)


def pediatric_vital_max(vital: str, age_months: int | None) -> float | None:
    """The highest value the generator lets ``vital`` reach at ``age_months``
    (Issue #2926), or ``None`` when no band covers the age (adult clamp applies)."""
    if age_months is None:
        return None
    ceilings = (_table().get("physiological_max") or {}).get(vital) or {}
    key = find_age_band(ceilings, age_months)
    return None if key is None else float(ceilings[key])


def age_independent_vital_range_text(vital: str, age_months: int | None, lang: str) -> str | None:
    """``referenceRange.text`` "Normal range for all ages" for a child's vital
    sign whose range does not depend on age (temperature, SpO2), else ``None``."""
    if age_months is None or age_months >= PEDIATRIC_UPPER_AGE_MONTHS:
        return None
    if vital not in (_table().get("age_independent_vital_signs") or ()):
        return None
    return t("fhir_obs_text.normal_range_all_ages", lang)


def _months_label(band: str, lang: str) -> str:
    """``"24-35"`` -> "2 years"; ``"12-17"`` -> "12–17 months"; ``"0-0"`` -> "0 months"."""
    lo, hi = parse_closed_age_band(band)
    if lo % _MONTHS_PER_YEAR == 0 and (hi + 1) % _MONTHS_PER_YEAR == 0 and hi >= 2 * _MONTHS_PER_YEAR - 1:
        return _years_label(lo // _MONTHS_PER_YEAR, (hi + 1) // _MONTHS_PER_YEAR - 1, lang)
    if lo == hi:
        return t("fhir_obs_text.age_months_single", lang, n=lo)
    return t("fhir_obs_text.age_months_range", lang, lo=lo, hi=hi)


def _years_label(lo: int, hi: int, lang: str) -> str:
    if lo == hi:
        return t("fhir_obs_text.age_years_single", lang, n=lo)
    return t("fhir_obs_text.age_years_range", lang, lo=lo, hi=hi)


def pediatric_vital_range_text(rng: PediatricVitalRange, lang: str) -> str:
    """``referenceRange.text`` of a pediatric vital range: "Normal range for age 2 years"."""
    return t("fhir_obs_text.normal_range_for_age", lang, age=_months_label(rng.band, lang))


def pediatric_lab_band(lab_name: str, age_years: int | None) -> tuple[str, dict[str, Any]] | None:
    """``(band key, band row)`` of ``lab_name`` at ``age_years``, or ``None``."""
    if age_years is None:
        return None
    analyte = (_table().get("labs") or {}).get(lab_name)
    if not analyte:
        return None
    bands = analyte.get("bands") or {}
    key = find_age_band(bands, int(age_years))
    return None if key is None else (str(key), bands[key])


def _band_range(row: dict[str, Any], sex: str) -> tuple[float, float]:
    # The model guarantees `all` or both `M` and `F`.
    rng = row.get(sex) or row.get("all") or row["F"]
    return float(rng[0]), float(rng[1])


def pediatric_lab_range(lab_name: str, age_years: int | None, sex: str) -> tuple[float, float, str, str] | None:
    """``(low, high, unit, band)`` of the pediatric interval for the child, or ``None``.

    A sex-specific band with an unknown sex uses the female interval.
    """
    found = pediatric_lab_band(lab_name, age_years)
    if found is None:
        return None
    band, row = found
    low, high = _band_range(row, sex)
    unit = str((_table()["labs"][lab_name]).get("unit") or "")
    return low, high, unit, band


def pediatric_lab_center(lab_name: str, age_years: int | None, sex: str) -> float | None:
    """Midpoint of the child's pediatric interval for ``lab_name`` (generator target), or ``None``."""
    found = pediatric_lab_range(lab_name, age_years, sex)
    if found is None:
        return None
    return (found[0] + found[1]) / 2


def pediatric_lab_range_text(band: str, lang: str) -> str:
    """``referenceRange.text`` of a pediatric lab interval: "Pediatric reference interval, age 1–12 years"."""
    lo, hi = parse_closed_age_band(band)
    return t("fhir_obs_text.pediatric_lab_range", lang, age=_years_label(lo, hi, lang))
