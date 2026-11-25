"""scripts/ci_split_by_file.py — the file-level shard split of ci.yml.

The CI test shards are cut by whole test file so a module-scoped fixture is
built once, in one shard, and every test file must land in exactly one shard
(a file in no shard would silently stop running).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ci_split_by_file", _ROOT / "scripts" / "ci_split_by_file.py")
assert _spec is not None and _spec.loader is not None
split = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(split)


def _tree(tmp_path: Path, names: list[str]) -> Path:
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    return tmp_path


def test_test_files_follow_the_pytest_naming(tmp_path: Path) -> None:
    root = _tree(tmp_path, ["a/test_x.py", "a/b/y_test.py", "a/helper.py", "a/conftest.py", "a/b/test_z.txt"])
    assert split.test_files(["a"], root=root) == ["a/b/y_test.py", "a/test_x.py"]


def test_every_file_lands_in_exactly_one_group() -> None:
    files = [f"t/test_{i}.py" for i in range(23)]
    durations = {f"t/test_{i}.py::test_a": float(i) for i in range(20)}  # 3 files without an entry
    groups = [split.split_files(files, durations, splits=4, group=g) for g in range(1, 5)]
    flat = [f for g in groups for f in g]
    assert sorted(flat) == sorted(files)
    assert len(flat) == len(set(flat))


def test_groups_are_balanced_by_summed_file_duration() -> None:
    durations = {
        "t/test_big.py::a": 100.0,
        "t/test_big.py::b": 100.0,  # file total 200
        "t/test_mid.py::a": 120.0,
        "t/test_s1.py::a": 40.0,
        "t/test_s2.py::a": 40.0,
    }
    files = sorted({k.split("::")[0] for k in durations})
    groups = [split.split_files(files, durations, splits=2, group=g) for g in (1, 2)]
    loads = sorted(sum(v for k, v in durations.items() if k.split("::")[0] in g) for g in groups)
    assert loads == [200.0, 200.0]


def test_a_file_without_an_entry_counts_as_the_mean_file() -> None:
    durations = {"t/test_a.py::x": 10.0, "t/test_b.py::x": 30.0}
    assert split.file_durations(["t/test_a.py", "t/test_b.py", "t/test_new.py"], durations)["t/test_new.py"] == 20.0


def test_the_split_is_deterministic() -> None:
    files = [f"t/test_{i}.py" for i in range(10)]
    durations = {f"t/test_{i}.py::x": 5.0 for i in range(10)}  # all ties
    first = [split.split_files(files, durations, splits=3, group=g) for g in (1, 2, 3)]
    again = [split.split_files(list(reversed(files)), durations, splits=3, group=g) for g in (1, 2, 3)]
    assert first == again


def test_the_ci_suites_are_covered_by_the_repository_durations() -> None:
    """Every collected test file of the two CI suites goes to exactly one shard
    with the committed `.test_durations` and the ci.yml shard counts."""
    durations = json.loads((_ROOT / ".test_durations").read_text())
    for paths, splits in ((["tests/unit", "tests/modules", "tests/simulator"], 2), (["tests/integration"], 4)):
        files = split.test_files(paths, root=_ROOT)
        assert files, paths
        flat = [f for g in range(1, splits + 1) for f in split.split_files(files, durations, splits=splits, group=g)]
        assert sorted(flat) == files


def test_bad_group_is_rejected() -> None:
    with pytest.raises(ValueError):
        split.split_files(["t/test_a.py"], {}, splits=2, group=3)
