"""RNG-neutral CKD (N18) assignment for residents under 60 (Issue #2023)."""

from __future__ import annotations

from typing import Any

from clinosim.determinism import sha_bernoulli
from clinosim.locale.loaders.clinical import load_ckd_under60_prevalence

_SALT = "population.ckd_under60.v1"
_CODE = "N18"


def assign_ckd_under60(person: Any, country: str) -> bool:
    """Append ``N18`` when the person's age band and SHA draw select it."""
    if any(str(getattr(c, "code", c)).startswith(_CODE) for c in person.chronic_conditions):
        return False
    for band in load_ckd_under60_prevalence(country):
        if int(band["age_lo"]) <= person.age <= int(band["age_hi"]):
            if sha_bernoulli(f"{_SALT}|{person.person_id}", float(band["prevalence"])):
                person.chronic_conditions.append(_CODE)
                return True
            return False
    return False
