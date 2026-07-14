"""Nursing module engine (Tier 1 #3 α-min-2, AD-64).

Loader + 6-layer validator + primary_nurse assignment.
POST_ENCOUNTER enricher entry: nursing_enricher (Task 5 owns, not here).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.types.staff import StaffRoster

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_ADL_CATEGORIES: frozenset[str] = frozenset(
    {"eating", "bathing", "dressing", "toileting", "mobility"}
)
SUPPORTED_RISK_ASSESSMENTS: frozenset[str] = frozenset(
    {"fall_risk", "pressure_ulcer_risk", "aspiration_risk"}
)
INPATIENT_ENCOUNTER_TYPES: frozenset[str] = frozenset({"inpatient", "icu", "rehab_inpatient"})


def _validate_nursing_assessment(data: dict[str, Any]) -> None:
    """6-layer silent-no-op defense for nursing_assessment.yaml."""
    # Layer 1: empty top-level check
    if not data:
        raise ValueError("nursing_assessment.yaml: empty top-level")

    # Layer 2: required top-level keys present (None check)
    for key in ("adl_categories", "risk_assessments", "disease_specific_nursing_focus", "baseline"):
        if data.get(key) is None:
            raise ValueError(f"nursing_assessment.yaml: missing required top-level key '{key}'")

    # Layer 3: baseline required fields
    baseline = data["baseline"]
    if not isinstance(baseline, dict) or "focus" not in baseline:
        raise ValueError(
            "nursing_assessment.yaml: baseline must have 'focus' field"
        )
    if "interventions_ja" not in baseline:
        raise ValueError(
            "nursing_assessment.yaml: baseline must have 'interventions_ja' field"
        )

    # Layer 4: forward + reverse coverage for adl_categories vs SUPPORTED_ADL_CATEGORIES
    adl_keys = set(data["adl_categories"].keys())
    if adl_keys != SUPPORTED_ADL_CATEGORIES:
        missing = SUPPORTED_ADL_CATEGORIES - adl_keys
        extra = adl_keys - SUPPORTED_ADL_CATEGORIES
        raise ValueError(
            f"nursing_assessment.yaml adl_categories ↔ SUPPORTED_ADL_CATEGORIES drift: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    # Layer 4b: forward + reverse coverage for risk_assessments vs SUPPORTED_RISK_ASSESSMENTS
    risk_keys = set(data["risk_assessments"].keys())
    if risk_keys != SUPPORTED_RISK_ASSESSMENTS:
        missing = SUPPORTED_RISK_ASSESSMENTS - risk_keys
        extra = risk_keys - SUPPORTED_RISK_ASSESSMENTS
        raise ValueError(
            f"nursing_assessment.yaml risk_assessments ↔ SUPPORTED_RISK_ASSESSMENTS drift: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    # Layer 5: per disease_specific_nursing_focus entry required fields
    disease_focus = data.get("disease_specific_nursing_focus", {}) or {}
    for disease_id, entry in disease_focus.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"nursing_assessment.yaml: disease_specific_nursing_focus[{disease_id!r}] "
                f"must be a dict"
            )
        if "focus" not in entry:
            raise ValueError(
                f"nursing_assessment.yaml: disease_specific_nursing_focus[{disease_id!r}] "
                f"missing required field 'focus'"
            )
        if "interventions_ja" not in entry:
            raise ValueError(
                f"nursing_assessment.yaml: disease_specific_nursing_focus[{disease_id!r}] "
                f"missing required field 'interventions_ja'"
            )

    # Layer 6: type checks (interventions_ja must be list)
    if not isinstance(baseline.get("interventions_ja"), list):
        raise ValueError(
            "nursing_assessment.yaml: baseline.interventions_ja must be a list"
        )
    for disease_id, entry in disease_focus.items():
        if not isinstance(entry.get("interventions_ja"), list):
            raise ValueError(
                f"nursing_assessment.yaml: disease_specific_nursing_focus[{disease_id!r}] "
                f"interventions_ja must be a list"
            )


@lru_cache(maxsize=1)
def load_nursing_assessment() -> dict[str, Any]:
    """Load nursing_assessment.yaml + validate (cached)."""
    with (_REF_DIR / "nursing_assessment.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_nursing_assessment(data)
    return data


def assign_primary_nurse(
    encounter: Any, roster: StaffRoster | None, rng: np.random.Generator
) -> str:
    """Pick a primary nurse from roster uniformly at random.

    Args:
        encounter: encounter object (dataclass or dict-like, unused except for type annotation)
        roster: StaffRoster with members; filters by role="nurse". None returns "" (no-roster
                fallback used when EnricherContext does not carry a roster, e.g. tests or
                enricher call sites that have not yet been wired with a roster).
        rng: per-encounter seeded RNG (derive_sub_seed caller's responsibility)

    Returns:
        staff_id of the assigned nurse, or "" if no nurses in roster or roster is None.
    """
    if roster is None:
        return ""
    nurses = roster.get_by_role("nurse")
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
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed  # noqa: E402


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
            sub_seed = derive_sub_seed(
                ctx.master_seed, ENRICHER_SEED_OFFSETS["nursing"], enc_id
            )
            rng = np.random.default_rng(sub_seed)
            enc.primary_nurse_id = assign_primary_nurse(enc, roster, rng)
