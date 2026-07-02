"""Integration test for Bug D — explicit -p must yield the same order of magnitude
of patients regardless of country, since the hospital recommended_population differs
by country (US=40000, JP=10000) but an explicit user value must override both equally.

Before the fix, `-p 500 --country JP` would have silently become 10000 (JP recommended)
while `-p 500 --country US` would have silently become 40000 (US recommended) — the
same explicit CLI flag producing wildly different, and silently different, cohort sizes.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.integration
def test_explicit_p_500_yields_us_and_jp_same_scale(tmp_path: object) -> None:
    us = tmp_path / "us500"
    jp = tmp_path / "jp500"
    for country, out in [("US", us), ("JP", jp)]:
        r = subprocess.run(
            [sys.executable, "-m", "clinosim.simulator.cli", "generate",
             "-p", "500", "--country", country, "-o", str(out),
             "--format", "cif"],
            capture_output=True, text=True, timeout=900,
        )
        assert r.returncode == 0, r.stderr
        assert "population=500" in r.stdout
        assert "Population: 500 persons" in r.stdout

    us_count = len(list((us / "cif" / "structural" / "patients").iterdir()))
    jp_count = len(list((jp / "cif" / "structural" / "patients").iterdir()))
    # Both were -p 500 → within a factor of 3 of each other.
    ratio = max(us_count, jp_count) / max(1, min(us_count, jp_count))
    assert ratio < 3.0, f"US={us_count}, JP={jp_count} — Bug D likely regressed"
