"""Japan identity provider (AD-54).

Numbering rules:
  - 社保 (employee): 記号 shared at the employer level (Phase 1 simplification: one
    記号 per household for the head's employer), member id shared, 枝番 per individual.
    Non-working dependents under 75 are 被扶養者 on the head's record.
  - 国保 (national): insurer + 記号 shared at the household level, 枝番 per individual.
  - 後期高齢者 (75+): per-individual enrollment, own member id, no household sharing.

Card / マイナ保険証 holding uses a Gaussian-copula household model: marginal
age-banded rates are preserved exactly while `household_icc` controls correlation.
"""

from __future__ import annotations

from statistics import NormalDist
from typing import Any

import numpy as np

import clinosim.modules.identity.generators as generators
from clinosim.types import InsuranceEnrollment, NationalIdentity

_NORM = NormalDist()


def _rate_for_age(table: dict[str, float], age: int) -> float:
    """Look up an age-banded rate. Band keys are 'lo-hi' or open-ended 'lo-'."""
    for key, val in table.items():
        lo_s, _, hi_s = key.partition("-")
        lo = int(lo_s)
        hi = int(hi_s) if hi_s else 200
        if lo <= age <= hi:
            return float(val)
    return 0.0


class JPIdentityProvider:
    country = "JP"

    def assign_household(
        self,
        members: list[Any],
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> dict[str, InsuranceEnrollment]:
        result: dict[str, InsuranceEnrollment] = {}
        payers = config.get("payers", {})

        non_elderly = [m for m in members if m.age < 75]
        elderly = [m for m in members if m.age >= 75]

        if non_elderly:
            scheme, subscriber = self._sample_scheme(non_elderly, config, rng)
            head = (
                subscriber
                if scheme == "employee" and subscriber is not None
                else max(non_elderly, key=lambda m: m.age)
            )
            insurer = self._insurer_for(scheme, payers, rng)
            symbol = generators.numeric_id(rng, 4)  # 記号 (employer for 社保 / 世帯 for 国保)
            base_member = generators.numeric_id(rng, 8 if scheme == "employee" else 6)
            # Head first, then dependents — branch numbers 01, 02, ...
            ordered = sorted(non_elderly, key=lambda m: (m is not head, -m.age, m.person_id))
            for i, m in enumerate(ordered, start=1):
                if scheme == "employee":
                    category = "employee" if m is head else "dependent"
                else:
                    category = "national"
                result[m.person_id] = InsuranceEnrollment(
                    country="JP",
                    category=category,
                    insurer_number=insurer,
                    member_id=base_member,
                    group_symbol=symbol,
                    branch_number=generators.branch_number(i),
                )

        for m in elderly:
            insurer = self._insurer_for("late_elderly", payers, rng)
            result[m.person_id] = InsuranceEnrollment(
                country="JP",
                category="late_elderly",
                insurer_number=insurer,
                member_id=generators.numeric_id(rng, 8),
                group_symbol=None,
                branch_number=None,
            )

        return result

    def assign_personal(
        self,
        member: Any,
        household_latent: float,
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> NationalIdentity:
        icc = float(config.get("household_icc", 0.5))
        card_rate = _rate_for_age(config.get("card_holding_rate", {}), member.age)
        ins_rate = _rate_for_age(config.get("mynumber_insurance_rate", {}), member.age)

        has_card = self._copula_decision(card_rate, household_latent, icc, rng)
        # マイナ保険証 registration requires holding the card. Registration among card
        # holders is an independent draw at the conditional rate ins_rate/card_rate, so the
        # population linked marginal = P(card)·P(reg|card) = ins_rate exactly (in expectation).
        # (Household clustering is still inherited via card holding.)
        cond = min(1.0, ins_rate / card_rate) if card_rate > 0 else 0.0
        linked = has_card and bool(rng.random() < cond)

        national_id = (
            generators.my_number(rng) if config.get("generate_national_id", True) else None
        )
        return NationalIdentity(
            country="JP",
            national_id=national_id,
            has_id_card=has_card,
            id_card_linked_to_insurance=linked,
        )

    # --- helpers -----------------------------------------------------------

    def _sample_scheme(
        self, non_elderly: list[Any], config: dict[str, Any], rng: np.random.Generator
    ) -> tuple[str, Any]:
        """Decide 被用者保険 (employee) vs 国保 (national) for the household.

        Occupation-driven: the working-age member most likely to be an employee becomes
        the 被保険者 (others 被扶養者). Falls back to an age-band distribution when no
        occupation table is configured. Returns (scheme, subscriber_or_None).
        """
        occ_prob = config.get("employee_probability_by_occupation", {})
        working = [m for m in non_elderly if 15 <= m.age < 75]
        if occ_prob and working:
            default_p = float(config.get("default_employee_probability", 0.0))

            def emp_p(m: Any) -> float:
                return float(occ_prob.get(getattr(m, "occupation", "other"), default_p))

            cand = max(working, key=emp_p)
            return ("employee", cand) if rng.random() < emp_p(cand) else ("national", None)

        head = max(non_elderly, key=lambda m: m.age)
        dist = _rate_table_for_age(config.get("insurance_category_distribution", {}), head.age)
        p = float(dist.get("employee", 0.5)) if dist else 0.5
        return ("employee", head) if rng.random() < p else ("national", None)

    def _insurer_for(
        self, scheme: str, payers: dict[str, Any], rng: np.random.Generator
    ) -> str:
        """Pick a representative payer's 保険者番号 for the scheme (name resolved at output)."""
        options = payers.get(scheme) or []
        if not options:
            return ""
        choice = options[int(rng.integers(0, len(options)))]
        return str(choice["number"])

    def _copula_decision(
        self, p: float, household_latent: float, icc: float, rng: np.random.Generator
    ) -> bool:
        p = min(max(p, 1e-6), 1 - 1e-6)
        threshold = _NORM.inv_cdf(p)
        e = float(rng.standard_normal())
        latent = (icc**0.5) * household_latent + ((1.0 - icc) ** 0.5) * e
        return bool(latent < threshold)


def _rate_table_for_age(table: dict[str, dict[str, float]], age: int) -> dict[str, float]:
    for key, val in table.items():
        lo_s, _, hi_s = key.partition("-")
        lo = int(lo_s)
        hi = int(hi_s) if hi_s else 200
        if lo <= age <= hi:
            return val
    return {}
