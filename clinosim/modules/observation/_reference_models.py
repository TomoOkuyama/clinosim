"""Pydantic models of the observation reference YAML (configuration spec §2:
module reference YAML is validated at load by an ``extra="forbid"`` model).

``lab_aliases.yaml``, ``lab_constants.yaml`` and ``nursing_scores.yaml`` are
loaded through ``clinosim.datafiles.load_validated_yaml`` with these models;
the loaders keep returning the content as loaded, so the models only check.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictInt, StrictStr, model_validator

_NonNegFloat = Annotated[StrictFloat, Field(ge=0)]
_NonNegInt = Annotated[StrictInt, Field(ge=0)]
_Prob = Annotated[StrictFloat, Field(ge=0, le=1)]
_Name = Annotated[StrictStr, Field(min_length=1)]


# ---------------------------------------------------------------------------
# lab_aliases.yaml
# ---------------------------------------------------------------------------


class LabAliases(RootModel[dict[_Name, _Name]]):
    """Shape of ``lab_aliases.yaml``: a flat order name → canonical analyte map.

    An alias resolves in one step, so a target is never itself an alias, and
    no name maps to itself.
    """

    @model_validator(mode="after")
    def _one_step(self) -> LabAliases:
        aliases = self.root
        self_maps = sorted(k for k, v in aliases.items() if k == v)
        if self_maps:
            raise ValueError(f"lab alias maps to itself: {self_maps}")
        chained = sorted(k for k, v in aliases.items() if v in aliases)
        if chained:
            raise ValueError(f"lab alias target is itself an alias (aliases resolve in one step): {chained}")
        return self


# ---------------------------------------------------------------------------
# lab_constants.yaml
# ---------------------------------------------------------------------------


def _ordered(lo: float | None, hi: float | None) -> bool:
    return lo is None or hi is None or lo < hi


class LabConstants(BaseModel):
    """Shape of ``lab_constants.yaml`` (Issue #2302): per-analyte constants
    keyed by canonical lab name. Every analyte a section names has a unit."""

    model_config = ConfigDict(extra="forbid")

    biological_cv: dict[_Name, _NonNegFloat] = Field(min_length=1)
    analytical_cv: dict[_Name, _NonNegFloat] = Field(min_length=1)
    precision: dict[_Name, _NonNegInt] = Field(min_length=1)
    units: dict[_Name, StrictStr] = Field(min_length=1)
    physiologic_limits: dict[_Name, tuple[StrictFloat, StrictFloat]] = Field(min_length=1)
    baseline_normals: dict[_Name, StrictFloat] = Field(min_length=1)
    panic_thresholds: dict[_Name, tuple[StrictFloat | None, StrictFloat | None]] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> LabConstants:
        bad_limits = sorted(lab for lab, (lo, hi) in self.physiologic_limits.items() if not lo < hi)
        if bad_limits:
            raise ValueError(f"physiologic_limits: low must be below high for {bad_limits}")
        bad_panic = sorted(lab for lab, (lo, hi) in self.panic_thresholds.items() if not _ordered(lo, hi))
        if bad_panic:
            raise ValueError(f"panic_thresholds: low must be below high for {bad_panic}")
        empty_panic = sorted(lab for lab, (lo, hi) in self.panic_thresholds.items() if lo is None and hi is None)
        if empty_panic:
            raise ValueError(f"panic_thresholds: both cutoffs null for {empty_panic}")
        for section in (
            "biological_cv",
            "analytical_cv",
            "precision",
            "physiologic_limits",
            "baseline_normals",
            "panic_thresholds",
        ):
            no_unit = sorted(set(getattr(self, section)) - set(self.units))
            if no_unit:
                raise ValueError(f"{section}: analytes without a unit in `units`: {no_unit}")
        return self


# ---------------------------------------------------------------------------
# nursing_scores.yaml
# ---------------------------------------------------------------------------

_Band = tuple[StrictFloat | None, StrictFloat | None, _NonNegInt]
_Avpu = Literal["A", "V", "P", "U"]


def _check_bands(name: str, bands: list[_Band]) -> None:
    bad = [b for b in bands if not (b[0] is None or b[1] is None or b[0] <= b[1])]
    if bad:
        raise ValueError(f"news2.{name}: band low above high: {bad}")


def _check_ascending(name: str, lows: list[float]) -> None:
    if lows != sorted(lows) or len(set(lows)) != len(lows):
        raise ValueError(f"{name}: lower bounds must be strictly ascending, got {lows}")


class _News2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    respiratory_rate: list[_Band] = Field(min_length=1)
    spo2_scale1: list[_Band] = Field(min_length=1)
    on_supplemental_oxygen: _NonNegInt
    temperature_celsius: list[_Band] = Field(min_length=1)
    systolic_bp: list[_Band] = Field(min_length=1)
    heart_rate: list[_Band] = Field(min_length=1)
    consciousness: dict[_Avpu, _NonNegInt] = Field(min_length=4)

    @model_validator(mode="after")
    def _bands(self) -> _News2:
        for name in ("respiratory_rate", "spo2_scale1", "temperature_celsius", "systolic_bp", "heart_rate"):
            _check_bands(name, getattr(self, name))
        return self


class _Gcs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avpu_base: dict[_Avpu, Annotated[StrictInt, Field(ge=3, le=15)]] = Field(min_length=4)
    min: Annotated[StrictInt, Field(ge=3, le=15)]
    max: Annotated[StrictInt, Field(ge=3, le=15)]
    # total → (eye 1-4, verbal 1-5, motor 1-6), each row summing to its total.
    components: dict[
        StrictInt,
        tuple[
            Annotated[StrictInt, Field(ge=1, le=4)],
            Annotated[StrictInt, Field(ge=1, le=5)],
            Annotated[StrictInt, Field(ge=1, le=6)],
        ],
    ]

    @model_validator(mode="after")
    def _components(self) -> _Gcs:
        if self.min >= self.max:
            raise ValueError(f"gcs: min {self.min} must be below max {self.max}")
        bad_sum = sorted(total for total, parts in self.components.items() if sum(parts) != total)
        if bad_sum:
            raise ValueError(f"gcs.components: rows not summing to their total: {bad_sum}")
        missing = sorted(set(range(self.min, self.max + 1)) - set(self.components))
        if missing:
            raise ValueError(f"gcs.components: totals without components: {missing}")
        return self


class _Braden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # [barthel_low_inclusive, subscale_value]
    barthel_to_subscale: list[tuple[_NonNegInt, Annotated[StrictInt, Field(ge=1, le=4)]]] = Field(min_length=1)

    @model_validator(mode="after")
    def _ascending(self) -> _Braden:
        _check_ascending("braden.barthel_to_subscale", [low for low, _ in self.barthel_to_subscale])
        return self


class _Morse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_of_falling: _NonNegInt
    iv_access: _NonNegInt
    gait_impaired: _NonNegInt
    gait_weak: _NonNegInt
    mental_status_forgets_limits: _NonNegInt
    fall_history_probability_by_age: list[tuple[_NonNegInt, _Prob]] = Field(min_length=1)
    secondary_diagnosis: _NonNegInt
    ambulatory_aid_by_barthel_mobility: dict[_NonNegInt, _NonNegInt] = Field(min_length=1)
    # [score_low_inclusive, level]
    risk_levels: list[tuple[_NonNegInt, Literal["low", "moderate", "high"]]] = Field(min_length=1)

    @model_validator(mode="after")
    def _ascending(self) -> _Morse:
        _check_ascending("morse.fall_history_probability_by_age", [a for a, _ in self.fall_history_probability_by_age])
        _check_ascending("morse.risk_levels", [s for s, _ in self.risk_levels])
        return self


class _BarthelItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: _Name
    loinc: Annotated[StrictStr, Field(pattern=r"^\d+-\d$")]
    answers: dict[_NonNegInt, Annotated[StrictStr, Field(pattern=r"^LA\d+-\d$")]] = Field(min_length=2)


class NursingScores(BaseModel):
    """Shape of ``nursing_scores.yaml``."""

    model_config = ConfigDict(extra="forbid")

    news2: _News2
    gcs: _Gcs
    braden: _Braden
    morse: _Morse
    barthel_items: list[_BarthelItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_items(self) -> NursingScores:
        fields = [i.field for i in self.barthel_items]
        dup = sorted({f for f in fields if fields.count(f) > 1})
        if dup:
            raise ValueError(f"barthel_items: duplicate fields {dup}")
        return self
