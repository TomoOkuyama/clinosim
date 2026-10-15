"""BMI → E66 obesity code enricher (Issue #1137 cluster 2 axis 1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from clinosim.modules.metabolic.engine import _derive_e66_code, e66_bmi_enricher
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
        age=50,
        sex="M",
        date_of_birth=date(1976, 1, 1),
        bmi=bmi,
        chronic_conditions=list(chronic or []),
    )


# ---------------------------------------------------------------------------
# Pure derivation function
# ---------------------------------------------------------------------------


def test_derive_e66_normal_bmi_returns_none() -> None:
    """BMI < 25 is within the WHO reference range → no E66 code."""
    assert _derive_e66_code(18.0) is None
    assert _derive_e66_code(22.5) is None
    assert _derive_e66_code(24.9) is None


def test_derive_e66_overweight() -> None:
    """25 <= BMI < 30 → E66.3 (overweight)."""
    assert _derive_e66_code(25.0) == "E66.3"
    assert _derive_e66_code(27.5) == "E66.3"
    assert _derive_e66_code(29.9) == "E66.3"


def test_derive_e66_obesity() -> None:
    """30 <= BMI < 40 → E66.9 (obesity, unspecified)."""
    assert _derive_e66_code(30.0) == "E66.9"
    assert _derive_e66_code(35.0) == "E66.9"
    assert _derive_e66_code(39.9) == "E66.9"


def test_derive_e66_morbid_obesity() -> None:
    """BMI >= 40 → E66.01 (morbid obesity, Class III)."""
    assert _derive_e66_code(40.0) == "E66.01"
    assert _derive_e66_code(45.0) == "E66.01"
    assert _derive_e66_code(55.0) == "E66.01"


def test_derive_e66_boundary_exact_values() -> None:
    """Boundaries use <= on the lower edge (BMI 25.0 is overweight,
    not reference range). WHO + ICD-10 convention."""
    assert _derive_e66_code(25.0) == "E66.3"
    assert _derive_e66_code(30.0) == "E66.9"
    assert _derive_e66_code(40.0) == "E66.01"


# ---------------------------------------------------------------------------
# Enricher behavior
# ---------------------------------------------------------------------------


def test_enricher_appends_e66_3_for_overweight() -> None:
    p = _person("PT-OW", bmi=27.0)
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e66_bmi_enricher(ctx)
    assert "E66.3" in p.chronic_conditions


def test_enricher_appends_e66_9_for_obesity() -> None:
    p = _person("PT-OB", bmi=32.0)
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e66_bmi_enricher(ctx)
    assert "E66.9" in p.chronic_conditions


def test_enricher_appends_e66_01_for_morbid_obesity() -> None:
    p = _person("PT-MO", bmi=42.0)
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e66_bmi_enricher(ctx)
    assert "E66.01" in p.chronic_conditions


def test_enricher_leaves_normal_bmi_untouched() -> None:
    """A person with BMI < 25 gets no E66 code appended."""
    p = _person("PT-NORMAL", bmi=22.0, chronic=["I10"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e66_bmi_enricher(ctx)
    assert not any(c.startswith("E66") for c in p.chronic_conditions)
    # Pre-existing chronic conditions untouched.
    assert p.chronic_conditions == ["I10"]


def test_enricher_mutually_exclusive_no_double_append() -> None:
    """A person who already carries an E66 variant (e.g. imported
    from legacy demographics yaml) does not receive a second one
    even if their BMI nominally crosses the next tier."""
    p = _person("PT-ALREADY", bmi=42.0, chronic=["E66.9"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e66_bmi_enricher(ctx)
    assert p.chronic_conditions.count("E66.9") == 1
    assert "E66.01" not in p.chronic_conditions


def test_enricher_idempotent_on_repeat_call() -> None:
    """Running the enricher twice over the same population yields
    the same result (no duplicate E66 codes)."""
    p = _person("PT-REPEAT", bmi=35.0)
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    e66_bmi_enricher(ctx)
    e66_bmi_enricher(ctx)
    assert p.chronic_conditions.count("E66.9") == 1


def test_enricher_mixed_cohort() -> None:
    """A multi-person cohort with varied BMI gets per-person E66
    classification (normal / overweight / obesity / morbid)."""
    normal = _person("PT-N", bmi=23.0)
    overweight = _person("PT-OW", bmi=28.0)
    obesity = _person("PT-OB", bmi=35.0)
    morbid = _person("PT-MO", bmi=45.0)
    ctx = _Ctx(
        population=_Pop(
            {
                normal.person_id: normal,
                overweight.person_id: overweight,
                obesity.person_id: obesity,
                morbid.person_id: morbid,
            }
        )
    )
    e66_bmi_enricher(ctx)
    assert normal.chronic_conditions == []
    assert "E66.3" in overweight.chronic_conditions
    assert "E66.9" in obesity.chronic_conditions
    assert "E66.01" in morbid.chronic_conditions
