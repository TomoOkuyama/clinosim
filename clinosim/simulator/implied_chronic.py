"""Chronic conditions a stay implies (Issue #3263).

One rule, used by both the encounter profile (``inpatient``) and the person
record (``helpers._deactivate_to_layer1``) so a condition the stay adds to the
problem list is also kept for the person's later encounters.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from clinosim.determinism import sha_bernoulli


class ImpliedChronicPrevalence(BaseModel):
    """Schema of ``reference_data/implied_chronic_prevalence.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # disease_id -> ICD-10 base code -> share of the disease's patients.
    prevalence: dict[str, dict[str, Annotated[float, Field(gt=0.0, lt=1.0)]]] = Field(default_factory=dict)


@functools.cache
def _prevalence() -> dict[str, dict[str, float]]:
    from clinosim.datafiles import load_validated_yaml

    data = load_validated_yaml(
        Path(__file__).resolve().parent / "reference_data" / "implied_chronic_prevalence.yaml",
        ImpliedChronicPrevalence,
    )
    return {d: {c.split(".")[0]: float(p) for c, p in codes.items()} for d, codes in data["prevalence"].items()}


def implied_chronic_min_age(code: str) -> int | None:
    """Minimum patient age for an implied chronic condition, by ICD-10 base
    code (``implied_chronic_min_years`` in ``chronic_onset_min_age.yaml``;
    Issue #2286), or None when unrestricted."""
    from clinosim.locale.loader import load_chronic_age_limits

    value = (load_chronic_age_limits().get("implied_chronic_min_years") or {}).get(code.split(".")[0])
    return int(value) if value is not None else None


def implied_chronic_codes_to_add(
    disease_id: str,
    *,
    patient_id: str,
    sex: str,
    age: int,
    have_bases: set[str],
) -> list[str]:
    """The disease's implied chronic codes this patient carries and does not have yet.

    Skips codes already held, sex-locked codes for the other sex (Issue #947),
    age-restricted codes for younger patients (Issue #2286), and, for a code
    with a configured prevalence, the patients the per-patient hash draw leaves out.
    """
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.simulator.sex_gating import is_sex_locked_for

    try:
        implied = list(load_disease_protocol(disease_id).implied_chronic_codes)
    except (FileNotFoundError, KeyError, ValueError):
        return []
    shares = _prevalence().get(disease_id, {})
    sex_initial = (sex or "").upper()[:1]
    taken = set(have_bases)
    out: list[str] = []
    for code in implied:
        base = code.split(".")[0]
        if base in taken:
            continue
        if is_sex_locked_for(code, sex_initial):
            continue
        min_age = implied_chronic_min_age(base)
        if min_age is not None and age < min_age:
            continue
        share = shares.get(base)
        if share is not None and not sha_bernoulli(f"{patient_id}|{disease_id}|{base}|implied_prevalence", share):
            continue
        taken.add(base)
        out.append(code)
    return out
