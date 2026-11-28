"""Fired counters: how many times each named code path ran in one run (Issue #3976).

A refactoring that moves a code path must show that the path ran in the
comparison it is proven by; a path that never ran is not proven by a
byte-identical output. Each such path calls :func:`count` with a dotted
name (``"complication.antibiotic.ordered"``) at the point where it acts.
The comparison script (``scripts/refactor-diff.sh``) reads the counts of a
run from a sidecar file and prints them next to the output differences.

The counters are observability only:

- they draw no random number and read no generator, so adding or removing a
  call never moves a stream (determinism spec §4);
- they are not part of the simulation output: nothing in CIF, FHIR, the
  narratives or the logs reads them; a caller that wants them reads
  :func:`snapshot` (the corpus runner writes it to a sidecar file);
- they are module-level state, like the newborn baseline-screen tracker:
  ``run_beta`` and ``run_forced`` call :func:`reset` at their start, so the
  counts are those of the latest run in the process.

The module imports nothing from clinosim, so every layer may call it.
"""

from __future__ import annotations

from collections.abc import Iterable

_COUNTS: dict[str, int] = {}


def count(path: str, n: int = 1, *, when: bool = True) -> None:
    """Add ``n`` to the counter of ``path`` when ``when`` is true.

    ``when`` lets a call site count a condition it has already computed in
    one statement (``count("discharge.held.ventilation", when=ventilated)``)
    without a new branch around the call.
    """
    if when and n:
        _COUNTS[path] = _COUNTS.get(path, 0) + n


def count_each(prefix: str, names: Iterable[str]) -> None:
    """Count ``<prefix>.<name>`` once for every name (a complication's declared actions)."""
    for name in names:
        count(f"{prefix}.{name}")


def reset() -> None:
    """Forget every count (the start of a run)."""
    _COUNTS.clear()


def snapshot() -> dict[str, int]:
    """The counts so far, sorted by path."""
    return dict(sorted(_COUNTS.items()))
