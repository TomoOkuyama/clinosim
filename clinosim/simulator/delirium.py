"""Delirium derived from a persistent reduced level of consciousness (Issue #3519).

An inpatient whose recorded AVPU stays below Alert for days, and whose
``delirium_susceptibility`` is high enough, has a delirium episode: onset,
duration and resolution come from the recorded course and the entry goes into
``complications_occurred`` (ICD-10-CM / ICD-10 F05 as a secondary diagnosis).
The rule is ``reference_data/delirium_derivation.yaml``; nothing here draws
from an RNG.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.simulator.complications import build_complication


class DeliriumRules(BaseModel):
    """Schema of ``reference_data/delirium_derivation.yaml`` (Issue #3519)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    complication_name: str = Field(min_length=1)
    icd_code: str = Field(min_length=1)
    susceptibility_min: float = Field(ge=0)
    min_reduced_days: int = Field(ge=1)
    qualifying_levels: tuple[str, ...] = Field(min_length=1)
    existing_names: tuple[str, ...] = Field(min_length=1)


@functools.cache
def delirium_rules() -> DeliriumRules:
    """The validated delirium-derivation rules."""
    return DeliriumRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "delirium_derivation.yaml")
    )


def delirium_code() -> str:
    """The ICD-10-CM / ICD-10 code of a delirium episode."""
    return delirium_rules().icd_code


def delirium_token_code(token: str) -> str:
    """``icd_code`` for a complication token that names a delirium, else ``""``."""
    rules = delirium_rules()
    return rules.icd_code if token in rules.existing_names else ""


def has_delirium(complication_names: Iterable[str]) -> bool:
    """Whether any of ``complication_names`` names a delirium."""
    return bool(set(complication_names) & set(delirium_rules().existing_names))


def derive_delirium(
    vitals: Iterable[Any],
    susceptibility: float,
    admission_time: datetime,
    existing: Iterable[str] = (),
) -> dict[str, Any] | None:
    """The delirium complication entry of a stay, or ``None``.

    ``vitals`` are the stay's vital-sign records (``timestamp`` and
    ``consciousness_level``); the first episode that qualifies is returned.
    """
    rules = delirium_rules()
    if susceptibility < rules.susceptibility_min or has_delirium(existing):
        return None
    adm_date = admission_time.date()
    first_reduced: dict[int, datetime] = {}
    levels: dict[int, set[str]] = {}
    for v in vitals:
        level = getattr(v, "consciousness_level", "") or ""
        if not level:
            continue
        day = (v.timestamp.date() - adm_date).days
        if day < 0:
            continue
        levels.setdefault(day, set()).add(level)
        if level != "A" and (day not in first_reduced or v.timestamp < first_reduced[day]):
            first_reduced[day] = v.timestamp
    qualifying = set(rules.qualifying_levels)
    reduced_days = sorted(d for d, lv in levels.items() if lv - {"A"})
    run: list[int] = []
    for day in [*reduced_days, None]:
        if day is not None and (not run or day == run[-1] + 1):
            run.append(day)
            continue
        counted = [d for d in run if levels[d] & qualifying]
        if len(counted) >= rules.min_reduced_days:
            onset = counted[0]
            last = run[-1]
            resolved = last + 1 if (last + 1) in levels else None
            return {
                **build_complication(
                    rules.complication_name,
                    onset,
                    first_reduced[onset].isoformat(),
                    "derived_from_consciousness",
                ),
                "resolution_day": resolved,
                "duration_days": last - onset + 1,
            }
        run = [day] if day is not None else []
    return None
