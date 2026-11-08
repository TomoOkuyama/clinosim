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
    assert bp_band(sbp, dbp, "JP") == band


@pytest.mark.parametrize(
    ("sbp", "dbp", "band"),
    [
        (130, 70, "hypertension"),
        (120, 80, "hypertension"),
        (129, 79, "high_normal"),
        (120, 70, "high_normal"),
        (119, 79, "normal"),
    ],
)
def test_us_bp_bands_follow_acc_aha_2017(sbp: int, dbp: int, band: str) -> None:
    """Issue #2860: US notes band BP by the 2017 ACC/AHA guideline, not JSH 2019."""
    assert bp_band(sbp, dbp, "US") == band


_VITAL_FIELDS = {
    "bp": re.compile(r"\{[^}]*\b(sbp|systolic\w*)\b[^}]*\}"),
    "hr": re.compile(r"\{[^}]*\b(hr|heart_rate|pulse)\b[^}]*\}"),
    "rr": re.compile(r"\{[^}]*\b(rr|resp\w*)\b[^}]*\}"),
    "spo2": re.compile(r"\{[^}]*\bspo2\w*\b[^}]*\}"),
    "temp": re.compile(r"\{[^}]*\b(temp\w*|bt)\b[^}]*\}"),
}


def test_vitals_lines_only_through_format_vitals_line() -> None:
    """Spec §3: a one-line vitals summary (three or more vital signs in one
    formatted string) is rendered only by ``format_vitals_line``."""
    offenders = []
    for p in sorted(_DOC.rglob("*.py")):
        if p.name == "_vitals_line.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"\bf[\"']", line):
                continue
            if sum(1 for rx in _VITAL_FIELDS.values() if rx.search(line)) >= 3:
                offenders.append(f"{p.relative_to(_DOC)}:{i}")
    assert not offenders, offenders


def test_every_facts_tag_literal_is_in_the_facts_vocabulary() -> None:
    """Spec §3 (Issue #2819): every facts_used tag the renderers write starts
    with a prefix of the check-narratives facts vocabulary."""
    import re
    from pathlib import Path

    from clinosim.modules.document.narrative.semantic_check import _ALLOWED_FACT_PREFIXES

    root = Path(__file__).resolve().parents[5] / "clinosim" / "modules" / "document"
    pattern = re.compile(r'facts(?:_used)?\s*(?:\.append|\.extend|\+=)\s*\(\s*\[?\s*f?"([^"{]+)')
    bad = [
        f"{p.relative_to(root)}: {m.group(1)}"
        for p in sorted(root.rglob("*.py"))
        for m in pattern.finditer(p.read_text(encoding="utf-8"))
        if not m.group(1).startswith(_ALLOWED_FACT_PREFIXES)
    ]
    assert not bad, bad
