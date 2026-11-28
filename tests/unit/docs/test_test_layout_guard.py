"""Guard on the test layout stated in ``tests/README.md`` (Issue #3990).

The README says the path under ``tests/`` mirrors the path under ``clinosim/``,
that no new file goes to the top level of ``tests/unit/``, and that a test does
not add a local ``_patient()`` builder. Nothing enforced it, so the flat area
grew by 75 files since v0.7.0 and 100+ local builders remain. This guard counts

* ``flat_test_files`` - ``tests/unit/test_*.py`` files, and
* ``local_patient_builders`` / ``local_stay_builders`` / ``local_record_builders``
  - module- or class-level ``_patient`` / ``_stay`` / ``_record`` functions in any
  file under ``tests/``,

and holds each total at the committed total (shrink-only, the shared ratchet
format of ``tests/unit/ratchet_baseline.py``). Moving a flat file to its
mirrored directory lowers the total and deleting one passes without a baseline
edit; neither is a new content key. The counter is
``tests/unit/layout_ratchet.py``; lower the stored totals with
``python -m tests.unit.layout_ratchet --write`` (never inside a feature change).
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import pytest

from tests.unit import layout_ratchet as lr

pytestmark = pytest.mark.unit

PATIENT = "def _patient(age=50):\n    return age\n"
STAY = "class T:\n    def _stay(self, n):\n        return n\n"
RECORD = "def _record(a, b=1):\n    return a\n"
NESTED = "def test_x():\n    def _patient():\n        return 1\n"  # a closure inside one test, not a shared builder


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _baseline_of(root: Path) -> dict:
    return lr.baseline_from(lr.scan(root))


def test_counts_flat_files_and_builders_by_content_key(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "unit/test_a.py": PATIENT,
            "unit/helpers.py": "x = 1\n",  # not a test file
            "unit/sub/test_b.py": STAY + RECORD,  # mirrored directory: not flat
            "unit/sub/test_c.py": NESTED,  # a nested closure is not a local builder
        },
    )
    found = lr.scan(root)
    assert dict(found["flat_test_files"]) == {"flat_test_files::<module>::test_a.py": 1}
    assert dict(found["local_patient_builders"]) == {"local_patient_builders::<module>::def _patient(age=50)": 1}
    assert dict(found["local_stay_builders"]) == {"local_stay_builders::T::def _stay(self, n)": 1}
    assert dict(found["local_record_builders"]) == {"local_record_builders::<module>::def _record(a, b=1)": 1}
    assert "unit/sub" not in "".join("".join(c) for c in found.values())  # no path in a key


def test_a_new_flat_test_file_fails_and_names_the_mirrored_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"unit/test_old.py": "x = 1\n"})
    baseline = _baseline_of(root)
    _tree(root, {"unit/test_new_flat.py": "x = 1\n"})
    verdict = lr.compare(baseline, lr.scan(root))
    assert verdict.raised == {"flat_test_files": (2, 1)}
    assert verdict.new_keys == ["flat_test_files::<module>::test_new_flat.py"]
    message = lr.failure_message("flat_test_files", verdict)
    assert "tests/unit/<path under clinosim/>" in message
    assert "test_new_flat.py" in message


@pytest.mark.parametrize(
    ("kind", "text", "fixture"),
    [
        ("local_patient_builders", PATIENT, "patient_factory"),
        ("local_stay_builders", RECORD.replace("_record", "_stay"), "tests/conftest.py"),
        ("local_record_builders", RECORD, "tests/conftest.py"),
    ],
)
def test_a_new_local_builder_fails_and_names_the_fixture(tmp_path: Path, kind: str, text: str, fixture: str) -> None:
    root = _tree(tmp_path, {"unit/sub/test_old.py": "x = 1\n"})
    baseline = _baseline_of(root)
    _tree(root, {"unit/sub/test_old.py": text})
    verdict = lr.compare(baseline, lr.scan(root))
    assert verdict.raised == {kind: (1, 0)}
    assert fixture in lr.failure_message(kind, verdict)


def test_moving_a_flat_file_to_its_mirrored_directory_passes(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"unit/test_flat.py": PATIENT + STAY, "unit/test_other.py": "x = 1\n"})
    baseline = _baseline_of(root)
    (root / "unit/modules/owner").mkdir(parents=True)
    shutil.move(str(root / "unit/test_flat.py"), str(root / "unit/modules/owner/test_flat.py"))
    verdict = lr.compare(baseline, lr.scan(root))
    assert verdict.raised == {}
    assert verdict.new_keys == []  # the builders keep their keys; the flat file is gone, not added
    assert verdict.lowered == {"flat_test_files": (1, 2)}


def test_deleting_a_flat_file_passes_without_a_baseline_edit(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"unit/test_a.py": PATIENT, "unit/test_b.py": "x = 1\n"})
    baseline = _baseline_of(root)
    (root / "unit/test_a.py").unlink()
    verdict = lr.compare(baseline, lr.scan(root))
    assert verdict.raised == {}
    assert set(verdict.lowered) == {"flat_test_files", "local_patient_builders"}


def test_writing_lowers_the_totals_and_never_raises_them(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"unit/test_a.py": "x = 1\n", "unit/test_b.py": "x = 1\n"})
    baseline = _baseline_of(root)
    (root / "unit/test_b.py").unlink()
    assert lr.lowered_baseline(baseline, lr.scan(root))["totals"]["flat_test_files"] == 1
    _tree(root, {"unit/test_c.py": "x = 1\n", "unit/test_d.py": "x = 1\n"})
    with pytest.raises(ValueError, match="flat_test_files"):
        lr.lowered_baseline(baseline, lr.scan(root))


@pytest.mark.parametrize("kind", lr.KINDS)
def test_no_rule_total_exceeds_its_stored_total(kind: str) -> None:
    verdict = lr.compare(lr.load_baseline(), lr.current_scan())
    assert kind not in verdict.raised, lr.failure_message(kind, verdict)


def test_stale_entries_are_reported_so_the_baseline_can_be_lowered() -> None:
    verdict = lr.compare(lr.load_baseline(), lr.current_scan())
    if verdict.new_keys:
        warnings.warn(
            f"test layout: new content keys (net-zero swaps are visible here): {verdict.new_keys}", stacklevel=1
        )
    if verdict.lowered:
        warnings.warn(
            f"test layout: stale totals can be lowered with: {lr.REGENERATE} ({verdict.lowered})", stacklevel=1
        )
