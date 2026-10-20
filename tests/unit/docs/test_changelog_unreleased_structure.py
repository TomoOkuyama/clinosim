"""CHANGELOG structure gate — one subsection per heading under [Unreleased].

Phase 4a final-review fix: when a new bullet was added to CHANGELOG, it
went into a new ``### Added`` block directly under ``## [Unreleased]``,
creating a duplicate heading with the existing ``### Added`` block that
held prior longitudinal subsystem bullets. Multiple identical subsection
headings under the same release confuses renderers and skimmers.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[3] / "CHANGELOG.md"


def _unreleased_subsection_counts() -> Counter[str]:
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    in_unreleased = False
    counts: Counter[str] = Counter()
    for line in lines:
        if line.startswith("## "):
            if in_unreleased:
                return counts
            if line.strip() == "## [Unreleased]":
                in_unreleased = True
            continue
        if in_unreleased and line.startswith("### "):
            counts[line.strip()] += 1
    return counts


def test_unreleased_has_single_added_subsection():
    """Phase 4a scope — the ``### Added`` subsection must appear at most
    once under ``## [Unreleased]`` so a Phase 4a bullet lands grouped
    with prior longitudinal subsystem additions, not as a stray second
    heading. Pre-existing duplicate ``### Changed`` / ``### Fixed``
    sections are a separate cleanup not in this plan's scope.
    """
    counts = _unreleased_subsection_counts()
    assert counts.get("### Added", 0) <= 1, (
        f"[Unreleased] has {counts.get('### Added', 0)} ### Added subsections — "
        f"merge Phase 4a bullet into the existing block"
    )
