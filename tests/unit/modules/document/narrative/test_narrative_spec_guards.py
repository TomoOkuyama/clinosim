"""Guards of docs/design-guides/narrative-and-document-generation-spec.md
(Issue #2733): BMI bands are taken from ``bmi_band`` only."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.modules.document.narrative._narrative_interpretation_thresholds import bmi_band, bp_band

pytestmark = pytest.mark.unit

_DOC = Path(__file__).resolve().parents[5] / "clinosim/modules/document"
_THRESHOLDS = "narrative/_narrative_interpretation_thresholds.py"
# A comparison of a BMI-named value with a band boundary literal.
_BMI_COMPARE = re.compile(
    r"bmi\w*\s*(<|>|<=|>=)\s*(18\.5|25(\.0)?|30(\.0)?)\b|(18\.5|25(\.0)?|30(\.0)?)\s*(<|>|<=|>=)\s*\w*bmi", re.I
)


def test_bmi_bands_only_through_bmi_band() -> None:
    offenders = [
        f"{p.relative_to(_DOC)}:{i}"
        for p in sorted(_DOC.rglob("*.py"))
        if str(p.relative_to(_DOC)) != _THRESHOLDS
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if not line.lstrip().startswith("#") and _BMI_COMPARE.search(line)
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    ("bmi", "band"), [(18.4, "underweight"), (18.5, "normal"), (24.9, "normal"), (25.0, "overweight"), (30.0, "obese")]
)
def test_each_boundary_belongs_to_the_upper_band(bmi: float, band: str) -> None:
    assert bmi_band(bmi) == band


_BP_COMPARE = re.compile(r"(<|>|<=|>=)\s*NARRATIVE_BP_\w+|NARRATIVE_BP_\w+\s*(<|>|<=|>=)")


def test_blood_pressure_bands_only_through_bp_band() -> None:
    """Issue #2751: the BP thresholds are compared only inside the thresholds module."""
    offenders = [
        f"{p.relative_to(_DOC)}:{i}"
        for p in sorted(_DOC.rglob("*.py"))
        if str(p.relative_to(_DOC)) != _THRESHOLDS
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if not line.lstrip().startswith("#") and _BP_COMPARE.search(line)
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    ("sbp", "dbp", "band"),
    [
        (139, 89, "high_normal"),
        (140, 70, "hypertension"),
        (120, 90, "hypertension"),
        (130, 70, "high_normal"),
        (120, 85, "high_normal"),
        (129, 84, "normal"),
    ],
)
def test_each_bp_boundary_belongs_to_the_upper_band(sbp: int, dbp: int, band: str) -> None:
    assert bp_band(sbp, dbp) == band
