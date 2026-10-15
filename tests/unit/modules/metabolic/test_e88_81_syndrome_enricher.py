"""E88.81 metabolic syndrome enricher (Issue #1137 cluster 2 axis 2).

Deterministic 4-way AND over BMI >= 30 + HTN (I10) + Dyslipidemia
(E78*) + DM (E10* or E11*). Mirrors the e66_bmi_enricher pattern:
POST_POPULATION, pure function, byte-identity preserving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from clinosim.modules.metabolic.engine import (
    _derive_metabolic_syndrome,
    e88_81_syndrome_enricher,
)
from clinosim.types.population import PersonRecord


@dataclass
class _Ctx:
    population: object
    master_seed: int = 42


class _Pop:
    def __init__(self, persons: dict):
        self.persons = persons


def _person(pid: str, bmi: float, chronic: list[str] | None = None) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=55,
        sex="M",
        date_of_birth=date(1971, 1, 1),
        bmi=bmi,
        chronic_conditions=list(chronic or []),
    )


# ---------------------------------------------------------------------------
# Pure derivation function
# ---------------------------------------------------------------------------


def test_derive_syndrome_requires_all_four() -> None:
    assert _derive_metabolic_syndrome(32.0, ["I10", "E78.5", "E11.9"]) == "E88.81"


def test_derive_syndrome_bmi_below_threshold_returns_none() -> None:
    assert _derive_metabolic_syndrome(29.9, ["I10", "E78.5", "E11.9"]) is None


def test_derive_syndrome_missing_htn_returns_none() -> None:
    assert _derive_metabolic_syndrome(35.0, ["E78.5", "E11.9"]) is None


def test_derive_syndrome_missing_dyslipidemia_returns_none() -> None:
    assert _derive_metabolic_syndrome(35.0, ["I10", "E11.9"]) is None


def test_derive_syndrome_missing_dm_returns_none() -> None:
    assert _derive_metabolic_syndrome(35.0, ["I10", "E78.5"]) is None


def test_derive_syndrome_type1_dm_also_qualifies() -> None:
    """E10 (Type 1 DM) satisfies the DM criterion equally."""
    assert _derive_metabolic_syndrome(32.0, ["I10", "E78.5", "E10.9"]) == "E88.81"


def test_derive_syndrome_category_header_codes_accepted() -> None:
    """Chronic lists may carry category headers (e.g. "E11") rather
    than billable leafs; both forms satisfy the AND."""
    assert _derive_metabolic_syndrome(32.0, ["I10", "E78", "E11"]) == "E88.81"


def test_derive_syndrome_exact_bmi_threshold() -> None:
    """BMI exactly 30.0 is at the inclusive lower edge."""
    assert _derive_metabolic_syndrome(30.0, ["I10", "E78.5", "E11.9"]) == "E88.81"


# ---------------------------------------------------------------------------
# Enricher behavior
# ---------------------------------------------------------------------------


def test_enricher_appends_e88_81_when_criteria_met() -> None:
    p = _person("PT-MS", bmi=33.0, chronic=["I10", "E78.5", "E11.9"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e88_81_syndrome_enricher(ctx)
    assert "E88.81" in p.chronic_conditions


def test_enricher_leaves_subcriteria_person_untouched() -> None:
    """A person with 3 of 4 criteria does NOT receive E88.81."""
    p = _person("PT-3OF4", bmi=33.0, chronic=["I10", "E78.5"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e88_81_syndrome_enricher(ctx)
    assert "E88.81" not in p.chronic_conditions
    assert p.chronic_conditions == ["I10", "E78.5"]


def test_enricher_leaves_sub_bmi_person_untouched() -> None:
    p = _person("PT-LEAN", bmi=24.0, chronic=["I10", "E78.5", "E11.9"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e88_81_syndrome_enricher(ctx)
    assert "E88.81" not in p.chronic_conditions


def test_enricher_idempotent_on_repeat_call() -> None:
    p = _person("PT-REPEAT", bmi=35.0, chronic=["I10", "E78.5", "E11.9"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e88_81_syndrome_enricher(ctx)
    e88_81_syndrome_enricher(ctx)
    assert p.chronic_conditions.count("E88.81") == 1


def test_enricher_mixed_cohort() -> None:
    """A multi-person cohort yields E88.81 only for the full AND."""
    full = _person("PT-FULL", bmi=35.0, chronic=["I10", "E78.5", "E11.9"])
    lean_full = _person("PT-LEAN-FULL", bmi=24.0, chronic=["I10", "E78.5", "E11.9"])
    partial = _person("PT-PARTIAL", bmi=35.0, chronic=["I10", "E78.5"])
    none = _person("PT-NONE", bmi=22.0, chronic=[])

    ctx = _Ctx(
        population=_Pop(
            {
                full.person_id: full,
                lean_full.person_id: lean_full,
                partial.person_id: partial,
                none.person_id: none,
            }
        )
    )
    e88_81_syndrome_enricher(ctx)
    assert "E88.81" in full.chronic_conditions
    assert "E88.81" not in lean_full.chronic_conditions
    assert "E88.81" not in partial.chronic_conditions
    assert "E88.81" not in none.chronic_conditions


def test_enricher_e66_e88_81_can_coexist() -> None:
    """E66.9 (BMI >=30 obesity) and E88.81 can both appear on the
    same person — they are distinct ICD facets (obesity vs the
    syndrome). The enricher does not drop one in favor of the other.
    """
    p = _person(
        "PT-BOTH",
        bmi=33.0,
        chronic=["I10", "E78.5", "E11.9", "E66.9"],
    )
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e88_81_syndrome_enricher(ctx)
    assert "E88.81" in p.chronic_conditions
    assert "E66.9" in p.chronic_conditions
