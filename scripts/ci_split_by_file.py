"""Print the test files of one CI shard, split by whole file.

``ci.yml`` (and the nightly duration measurement) runs each test shard as
``pytest $(python scripts/ci_split_by_file.py --splits N --group G PATH...)``.
pytest-split cuts a suite test by test, so the tests of one file could land in
several shards and each of those shards built the file's module-scoped
fixtures (simulated cohorts) again, while ``.test_durations`` charged that
setup to one test only; the shards then ran far apart (Issue on file-level
splitting, 2026-11-26). Here a file is the unit: its weight is the sum of its
tests' durations in ``.test_durations`` (a file with no entry weighs as the
mean file), and files are bin-packed longest first onto the least-loaded
shard, ties broken by path, so the split is deterministic.

Test files are the ones pytest collects by default under the given paths:
``test_*.py`` and ``*_test.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_files(paths: Iterable[str], root: Path = _ROOT) -> list[str]:
    """The test files under ``paths`` (relative to ``root``), sorted."""
    found: set[str] = set()
    for path in paths:
        base = root / path
        for pattern in ("test_*.py", "*_test.py"):
            found.update(p.relative_to(root).as_posix() for p in base.rglob(pattern) if p.is_file())
    return sorted(found)


def file_durations(files: Iterable[str], durations: dict[str, float]) -> dict[str, float]:
    """Summed test duration per file; a file without an entry gets the mean."""
    files = list(files)
    wanted = set(files)
    totals: dict[str, float] = {}
    for nodeid, seconds in durations.items():
        name = nodeid.split("::", 1)[0]
        if name in wanted:
            totals[name] = totals.get(name, 0.0) + float(seconds)
    mean = sum(totals.values()) / len(totals) if totals else 1.0
    return {f: totals.get(f, mean) for f in files}


def split_files(files: Iterable[str], durations: dict[str, float], *, splits: int, group: int) -> list[str]:
    """The files of shard ``group`` (1-based) of ``splits``."""
    if splits < 1 or not 1 <= group <= splits:
        raise ValueError(f"group {group} is not within 1..{splits}")
    weights = file_durations(sorted(set(files)), durations)
    loads = [0.0] * splits
    members: list[list[str]] = [[] for _ in range(splits)]
    for name in sorted(weights, key=lambda f: (-weights[f], f)):
        target = min(range(splits), key=lambda i: (loads[i], i))
        loads[target] += weights[name]
        members[target].append(name)
    return sorted(members[group - 1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--splits", type=int, required=True)
    parser.add_argument("--group", type=int, required=True)
    parser.add_argument("--durations", default=str(_ROOT / ".test_durations"))
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    durations_path = Path(args.durations)
    durations = json.loads(durations_path.read_text()) if durations_path.exists() else {}
    chosen = split_files(test_files(args.paths), durations, splits=args.splits, group=args.group)
    if not chosen:
        print(f"no test files for group {args.group}/{args.splits}", file=sys.stderr)
        return 1
    print("\n".join(chosen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
