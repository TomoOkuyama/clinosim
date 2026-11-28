"""Rename-aware ratchet on code-data separation (Issues #3137, #3977).

configuration-and-reference-data-spec §4: values that differ by country (and
tunable clinical or statistical values) live in data, not in code branches or
unnamed literals. Per Python file under ``clinosim/`` the guard counts

* country / language branches (calls to ``is_jp`` / ``is_us`` /
  ``uses_jp_clins_profile``; comparisons with ``"JP"`` / ``"US"`` / ``"ja"`` /
  ``"en"``), and
* numeric literals in comparisons outside ``_<topic>_thresholds.py`` /
  ``_<topic>_defaults.py`` modules,

and holds the total per rule at the committed total: a total may not rise. A
decrease passes without editing the baseline, and moving or renaming a file is
not a raise (entries are keyed by content, not by path). The stored totals are
lowered by ``python -m tests.unit.code_data_separation --write``, never inside
a feature change. New content keys are reported in the test output. The counter
lives in ``tests/unit/code_data_separation.py``.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

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


BRANCH_FILE = 'def f(c):\n    if is_jp(c):\n        return 1\n    return c == "US"\n'
LITERAL_FILE = "class K:\n    def m(self, x):\n        return x > 38.5 or x < 35.0\n"


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _baseline_of(root: Path) -> dict:
    return cds.baseline_from(cds.scan(root))


def test_the_stored_totals_reproduce_the_counts_before_the_format_change() -> None:
    # Totals per rule measured on the per-file baseline this format replaced.
    assert cds.load_baseline()["totals"] == {"country_branches": 35, "numeric_literals": 165}
    assert cds.totals(cds.current_scan()) == cds.load_baseline()["totals"]


def test_entries_are_keyed_by_rule_qualified_name_and_normalized_text(tmp_path: Path) -> None:
    found = cds.scan(_tree(tmp_path, {"a/mod.py": LITERAL_FILE + BRANCH_FILE}))
    assert dict(found["numeric_literals"]) == {
        "numeric_literals::K.m::x > 38.5": 1,
        "numeric_literals::K.m::x < 35.0": 1,
    }
    assert set(found["country_branches"]) == {
        "country_branches::f::is_jp(c)",
        "country_branches::f::c == 'US'",
    }
    assert "mod.py" not in "".join(found["numeric_literals"])  # no module path in a key


def test_moving_a_counted_file_passes(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"simulator/loop.py": LITERAL_FILE + BRANCH_FILE})
    baseline = _baseline_of(root)
    (root / "modules/owner").mkdir(parents=True)
    shutil.move(str(root / "simulator/loop.py"), str(root / "modules/owner/engine.py"))
    verdict = cds.compare(baseline, cds.scan(root))
    assert verdict.raised == {}
    assert verdict.new_keys == []


def test_adding_a_counted_constant_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"m.py": LITERAL_FILE})
    baseline = _baseline_of(root)
    _tree(root, {"n.py": "def g(h):\n    return h >= 120\n"})
    verdict = cds.compare(baseline, cds.scan(root))
    assert verdict.raised == {"numeric_literals": (3, 2)}
    assert verdict.new_keys == ["numeric_literals::g::h >= 120"]


def test_removing_a_counted_constant_passes_without_a_baseline_edit(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"m.py": LITERAL_FILE + BRANCH_FILE})
    baseline = _baseline_of(root)
    _tree(root, {"m.py": BRANCH_FILE})
    verdict = cds.compare(baseline, cds.scan(root))
    assert verdict.raised == {}
    assert verdict.lowered == {"numeric_literals": (0, 2)}


def test_a_net_zero_swap_passes_but_its_new_key_is_reported(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"m.py": "def g(h):\n    return h >= 120\n"})
    baseline = _baseline_of(root)
    _tree(root, {"m.py": "def g(h):\n    return h >= 130\n"})
    verdict = cds.compare(baseline, cds.scan(root))
    assert verdict.raised == {}
    assert verdict.new_keys == ["numeric_literals::g::h >= 130"]


def test_the_counting_rules_are_unchanged_for_a_scanned_tree(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "countries/jp/x.py": "ok = is_jp(c)\n",  # country packages are exempt from branches
            "mod/_x_thresholds.py": "ok = a > 99\n",  # thresholds modules are exempt from literals
            "mod/y.py": "ok = a > 99 and is_us(c)\n",
        },
    )
    assert cds.totals(cds.scan(root)) == {"country_branches": 1, "numeric_literals": 1}


def test_writing_lowers_the_totals_and_never_raises_them(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"m.py": LITERAL_FILE + BRANCH_FILE})
    baseline = _baseline_of(root)
    _tree(root, {"m.py": BRANCH_FILE})
    lowered = cds.lowered_baseline(baseline, cds.scan(root))
    assert lowered["totals"] == {"country_branches": 2, "numeric_literals": 0}
    _tree(root, {"m.py": LITERAL_FILE + BRANCH_FILE + "def g(h):\n    return h >= 120\n"})
    with pytest.raises(ValueError, match="numeric_literals"):
        cds.lowered_baseline(baseline, cds.scan(root))


@pytest.mark.parametrize("kind", cds.KINDS)
def test_no_rule_total_exceeds_its_stored_total(kind: str) -> None:
    verdict = cds.compare(cds.load_baseline(), cds.current_scan())
    assert kind not in verdict.raised, (
        f"{cds.RULES[kind]} — total {kind.replace('_', ' ')} rose (found, stored): {verdict.raised[kind]}. "
        f"New content keys: {verdict.new_keys}. "
        "Move the value to YAML / a country profile or a named constant in a "
        "_<topic>_thresholds.py module instead of raising the baseline "
        "(configuration-and-reference-data-spec §4). A move is not a raise."
    )


def test_new_content_keys_are_reported() -> None:
    verdict = cds.compare(cds.load_baseline(), cds.current_scan())
    if verdict.new_keys:
        warnings.warn(
            f"code/data ratchet: new content keys (net-zero swaps are visible here): {verdict.new_keys}", stacklevel=1
        )
    if verdict.lowered:
        warnings.warn(
            f"code/data ratchet: totals can be lowered with: {cds.REGENERATE} ({verdict.lowered})", stacklevel=1
        )
