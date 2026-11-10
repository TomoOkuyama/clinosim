"""Shrink-only ratchet on code-data separation (Issue #3137).

configuration-and-reference-data-spec §4: values that differ by country (and
tunable clinical or statistical values) live in data, not in code branches or
unnamed literals. Per Python file under ``clinosim/`` the guard counts

* country / language branches (calls to ``is_jp`` / ``is_us`` /
  ``uses_jp_clins_profile``; comparisons with ``"JP"`` / ``"US"`` / ``"ja"`` /
  ``"en"``), and
* numeric literals in comparisons outside ``_<topic>_thresholds.py`` /
  ``_<topic>_defaults.py`` modules,

and holds each file at its committed baseline: a count may not grow, and a
file that drops below its baseline lowers it in the same change. The counter
and the baseline regenerate command live in ``tests/unit/code_data_separation.py``.
"""

from __future__ import annotations

import pytest

from tests.unit import code_data_separation as cds

pytestmark = pytest.mark.unit


def test_counts_the_country_and_language_branch_forms() -> None:
    src = (
        "if is_jp(country):\n    x = 1\n"
        "y = countries.is_us(c)\n"
        "z = uses_jp_clins_profile(lang)\n"
        'a = country == "JP"\n'
        'b = "en" != lang\n'
        'c = code.upper() in ("US", "JP")\n'
        'd = modality == "US"\n'  # ultrasound, not a country
        'e = "en" in entry\n'  # key presence, not a branch
    )
    assert cds.country_branches(src) == [1, 3, 4, 5, 6, 7]


def test_counts_numeric_literals_in_comparisons() -> None:
    src = (
        "if age < 18:\n    pass\n"
        "if hr >= 100 and sbp < 90:\n    pass\n"
        "if n > 0 or i == 1 or x == -1 or k >= 2:\n    pass\n"  # trivial values
        "if minutes >= 60:\n    pass\n"  # unit factor
        "if temp > 38.5:\n    pass\n"
        "if -5 > drift:\n    pass\n"
    )
    assert cds.numeric_literals(src) == [1, 3, 3, 9, 11]


def test_threshold_and_defaults_modules_are_exempt_from_the_literal_count() -> None:
    assert not cds.counts_literals("modules/order/_order_thresholds.py")
    assert not cds.counts_literals("simulator/_mar_defaults.py")
    assert cds.counts_literals("simulator/medication_pipeline.py")


def _report(kind: str, found: dict[str, int], baseline: dict[str, int]) -> tuple[dict, dict]:
    grown = {f: (n, baseline.get(f, 0)) for f, n in found.items() if n > baseline.get(f, 0)}
    shrunk = {f: (found.get(f, 0), n) for f, n in baseline.items() if found.get(f, 0) < n}
    return grown, shrunk


@pytest.mark.parametrize("kind", cds.KINDS)
def test_no_file_grows_beyond_its_baseline(kind: str) -> None:
    grown, _ = _report(kind, cds.current_counts()[kind], cds.load_baseline()[kind])
    assert not grown, (
        f"{cds.RULES[kind]} — new {kind.replace('_', ' ')} (found, baseline): {grown}. "
        "Move the value to YAML / a country profile or a named constant in a "
        "_<topic>_thresholds.py module instead of raising the baseline "
        "(configuration-and-reference-data-spec §4)."
    )


@pytest.mark.parametrize("kind", cds.KINDS)
def test_baseline_shrinks_with_the_code(kind: str) -> None:
    _, shrunk = _report(kind, cds.current_counts()[kind], cds.load_baseline()[kind])
    assert not shrunk, (
        f"{kind.replace('_', ' ')} dropped below the baseline (found, baseline): {shrunk}. "
        f"Lower it in the same change: {cds.REGENERATE}"
    )


def test_regenerating_never_raises_the_baseline() -> None:
    baseline = {"country_branches": {"a.py": 2}, "numeric_literals": {}}
    lowered = {"country_branches": {"a.py": 1}, "numeric_literals": {}}
    raised = {"country_branches": {"a.py": 3, "b.py": 1}, "numeric_literals": {}}
    assert cds.merge_lowered(baseline, lowered) == lowered
    with pytest.raises(ValueError, match="b.py|a.py"):
        cds.merge_lowered(baseline, raised)
