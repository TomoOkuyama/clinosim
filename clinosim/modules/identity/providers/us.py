"""US identity provider (Issue #1107, session 103).

Samples an ``InsuranceEnrollment`` per household member from the age-conditional
distribution declared in ``us/identity.yaml sampling.insurance_distribution``
(Kaiser Family Foundation 2023 + CMS calibrated). Each enrollment carries the
sampled category (medicare / medicaid / private_employer / etc.) so the FHIR
adapter's ``_build_coverage_resources`` can dispatch to the matching payor
Organization + Coverage row.

Unlike JP:
  - No fiscal-year re-aging (calendar year benefit periods).
  - No 記号/枝番 composite identifier; ``group_symbol`` / ``branch_number``
    stay ``None`` and the identity.yaml ``fhir_coverage.ext_*`` URLs are
    blank so the emitter skips those extensions.
  - Age gate: 65 (identity.yaml ``age_gates.medicare_min_age``) → Medicare
    auto-enrollment (mapped to `late_elderly` slot
    for compatibility with the JP-shared ``_build_coverage_resources``
    aging-in logic — categorically the same "government-run insurance
    kicks in at threshold age" pattern).
  - ``assign_personal`` still returns a bare ``NationalIdentity(country="US")``
    — SSN etc. are never emitted (privacy chokepoint AD-54).
"""

from __future__ import annotations

from typing import Any

import numpy as np

import clinosim.modules.identity.generators as generators
from clinosim.age_bands import age_band_covers
from clinosim.country_profile import register_implementation
from clinosim.types import InsuranceEnrollment, NationalIdentity


def _sample_category(distribution: list[dict], age: int, rng: np.random.Generator) -> str:
    """Pick an insurance category from age-banded weights (defaults to 'uninsured')."""
    for band in distribution:
        try:
            covers = age_band_covers(band.get("age_range", "0-99"), age)
        except ValueError:
            continue
        if covers:
            weights = band.get("weights") or {}
            if not weights:
                continue
            keys = list(weights.keys())
            probs = np.asarray([float(weights[k]) for k in keys], dtype=float)
            total = float(probs.sum())
            if total <= 0:
                continue
            probs = probs / total
            return str(rng.choice(keys, p=probs))
    return "uninsured"


def _first_payer_number(payers_cfg: dict[str, Any], category: str) -> str:
    """Return the first ``number`` under ``payers[category]``, or empty string."""
    entries = payers_cfg.get(category) or []
    for e in entries:
        num = e.get("number") if isinstance(e, dict) else None
        if num:
            return str(num)
    return ""


@register_implementation("identity_provider", "us")
class USIdentityProvider:
    country = "US"

    def assign_household(
        self,
        members: list[Any],
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> dict[str, InsuranceEnrollment]:
        distribution = ((config.get("sampling") or {}).get("insurance_distribution")) or []
        payers = config.get("payers", {}) or {}
        if not distribution or not payers:
            return {}

        gates = config["age_gates"]
        medicare_age = int(gates["medicare_min_age"])
        medicare_categories = [str(c) for c in gates["medicare_categories"]]
        result: dict[str, InsuranceEnrollment] = {}
        for m in members:
            category = _sample_category(distribution, int(getattr(m, "age", 0)), rng)
            # 65+ hard auto-enrollment: even if the age-band weights happen
            # to draw a non-Medicare category (residual weight), the CMS
            # eligibility rule kicks in. Route to `late_elderly` slot so
            # the shared _build_coverage_resources aging-in logic works
            # identically to the JP 後期高齢者 pathway.
            # Age and categories from identity.yaml ``age_gates`` (Issue #3142).
            member_age = int(getattr(m, "age", 0))
            if member_age >= medicare_age and category not in medicare_categories:
                category = medicare_categories[0]
            insurer = _first_payer_number(payers, category)
            if not insurer:
                # Category configured but no payer number → skip (leaves the
                # member without a Coverage row; matches JP behaviour when
                # payers block is missing an entry).
                continue
            # Synthetic 11-digit member ID (matches CMS MBI length loosely
            # without producing a real, checksum-valid MBI).
            member_id = generators.numeric_id(rng, 11)
            result[m.person_id] = InsuranceEnrollment(
                country="US",
                category=category,
                insurer_number=insurer,
                member_id=member_id,
                group_symbol=None,
                branch_number=None,
            )
        return result

    def assign_personal(
        self,
        member: Any,
        household_latent: float,  # noqa: ARG002 — signature parity with JP provider
        rng: np.random.Generator,  # noqa: ARG002 — SSN etc. not generated
        config: dict[str, Any],  # noqa: ARG002 — no per-personal config for US
    ) -> NationalIdentity:
        return NationalIdentity(country="US")
