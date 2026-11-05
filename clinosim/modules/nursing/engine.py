"""Nursing module engine (Tier 1 #3 α-min-2, AD-64).

Loader (validated by the ``NursingAssessment`` model) + primary_nurse assignment.
POST_ENCOUNTER enricher entry: nursing_enricher (Task 5 owns, not here).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clinosim import determinism
from clinosim.datafiles import load_validated_yaml
from clinosim.types.staff import StaffRoster

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_ADL_CATEGORIES: frozenset[str] = frozenset({"eating", "bathing", "dressing", "toileting", "mobility"})
SUPPORTED_RISK_ASSESSMENTS: frozenset[str] = frozenset({"fall_risk", "pressure_ulcer_risk", "aspiration_risk"})
INPATIENT_ENCOUNTER_TYPES: frozenset[str] = frozenset({"inpatient", "icu", "rehab_inpatient"})


def _is_list_map(value: object) -> bool:
    """A non-empty language map whose values are lists (Issue #2508)."""
    return isinstance(value, dict) and bool(value) and all(isinstance(v, list) for v in value.values())


class _NursingFocus(BaseModel):
    """A nursing focus with its interventions, each language mapped to a list."""

    model_config = ConfigDict(extra="allow")

    focus: Any
    interventions: dict[str, Any]

    @field_validator("interventions")
    @classmethod
    def _interventions_map_each_language_to_a_list(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _is_list_map(value):
            raise ValueError("interventions must map each language to a list")
        return value


class NursingAssessment(BaseModel):
    """Shape of nursing_assessment.yaml: exactly the supported ADL categories
    and risk assessments, a baseline focus, and per-disease foci."""

    model_config = ConfigDict(extra="allow")

    adl_categories: dict[str, Any]
    risk_assessments: dict[str, Any]
    disease_specific_nursing_focus: dict[str, _NursingFocus]
    baseline: _NursingFocus

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not data:
            raise ValueError("nursing_assessment.yaml: empty top-level")
        return data

    @field_validator("adl_categories")
    @classmethod
    def _supported_adl_categories(cls, value: dict[str, Any]) -> dict[str, Any]:
        _require_exactly(set(value), SUPPORTED_ADL_CATEGORIES, "adl_categories ↔ SUPPORTED_ADL_CATEGORIES")
        return value

    @field_validator("risk_assessments")
    @classmethod
    def _supported_risk_assessments(cls, value: dict[str, Any]) -> dict[str, Any]:
        _require_exactly(set(value), SUPPORTED_RISK_ASSESSMENTS, "risk_assessments ↔ SUPPORTED_RISK_ASSESSMENTS")
        return value


def _require_exactly(keys: set[str], supported: frozenset[str], what: str) -> None:
    if keys != supported:
        raise ValueError(
            f"nursing_assessment.yaml {what} drift: "
            f"missing={sorted(supported - keys)}, extra={sorted(keys - supported)}"
        )


@lru_cache(maxsize=1)
def load_nursing_assessment() -> dict[str, Any]:
    """Load nursing_assessment.yaml + validate (cached)."""
    return load_validated_yaml(_REF_DIR / "nursing_assessment.yaml", NursingAssessment)


def assign_primary_nurse(encounter: Any, roster: StaffRoster | None, rng: np.random.Generator) -> str:
    """Pick a primary nurse uniformly from the encounter's ward (Issue #2700).

    Args:
        encounter: encounter object (dataclass or dict-like); its ``ward_id`` /
            ``department_id`` scope the nurse pool
        roster: StaffRoster with members; filters by role="nurse". None returns "" (no-roster
                fallback used when EnricherContext does not carry a roster, e.g. tests or
                enricher call sites that have not yet been wired with a roster).
        rng: per-encounter seeded RNG (derive_sub_seed caller's responsibility)

    Returns:
        staff_id of the assigned nurse, or "" if no nurses in roster or roster is None.
    """
    if roster is None:
        return ""
    from clinosim.modules.staff.engine import scoped_nurses

    # Issue #2700: a nurse of the encounter's ward, else its department.
    nurses = scoped_nurses(
        roster,
        ward=str(_o(encounter, "ward_id", "") or ""),
        department=str(_o(encounter, "department_id", "") or ""),
    )
    if not nurses:
        return ""
    nurse_ids = [n.staff_id for n in nurses]
    return str(rng.choice(nurse_ids))


# ---------------------------------------------------------------------------
# POST_ENCOUNTER enricher (Task 5)
# ---------------------------------------------------------------------------

from clinosim.modules._shared import (
    get_attr_or_key as _o,  # noqa: E402 — kept here to avoid circular import
)
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed  # noqa: E402


def nursing_enricher(ctx: Any) -> None:
    """POST_ENCOUNTER enricher: assign primary_nurse_id for inpatient/icu/rehab_inpatient encounters.

    Determinism via derive_sub_seed(master, ENRICHER_SEED_OFFSETS["nursing"], encounter_id).
    Master stream unchanged (AD-16). Skips non-inpatient encounter types.
    Falls back to "" when ctx carries no roster (no-roster safety net for test fixtures
    or future call sites where roster wiring is not yet complete).
    """
    roster = _o(ctx, "roster", None)
    records = _o(ctx, "records", []) or []
    for record in records:
        encounters = _o(record, "encounters", []) or []
        for enc in encounters:
            enc_type = _o(enc, "encounter_type", "")
            # Support both enum values (.value) and plain strings
            enc_type_str = enc_type.value if hasattr(enc_type, "value") else str(enc_type)
            if enc_type_str.lower() not in INPATIENT_ENCOUNTER_TYPES:
                continue
            enc_id = _o(enc, "encounter_id", "")
            sub_seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["nursing"], enc_id)
            rng = determinism.default_rng(sub_seed)
            enc.primary_nurse_id = assign_primary_nurse(enc, roster, rng)
