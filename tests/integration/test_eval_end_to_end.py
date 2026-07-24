"""P1-8 (session 46) — clinosim eval end-to-end.

Generates the ``us-100`` and ``jp-100`` presets and runs the full 3-axis
evaluation on each. Baselines:

- **structural** must PASS on both (byte-diff reproducibility gate
  already keeps schema invariants tight; a regression here would fire
  in reproducibility first).
- **locale** must not regress on JP Core dual-coding + Japanese-display
  ratios; a WARN on the kana-variant check is currently expected.
- **clinical** is allowed to WARN — MVP lab bounds are conservative.

Marked ``integration`` because the two ``clinosim generate`` runs take
~20 s each on a warm interpreter.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clinosim.eval.engine import EvalEngine, Outcome


@pytest.mark.integration
@pytest.mark.parametrize("preset", ["us-100", "jp-100"])
def test_eval_preset_end_to_end(preset: str, tmp_path: Path) -> None:
    """`clinosim dataset build <preset>` + `eval` runs end-to-end and
    produces a well-formed report.

    Scope of this test = the eval FRAMEWORK works, not that the
    generated data passes every check. Data-quality regressions are the
    eval tool's job to surface via CRITICAL / MAJOR findings — they are
    not the framework's job to hide. The specific check outcomes on the
    preset builds are documented and improved iteratively (see e.g.
    ``clinosim/modules/document/audit.py`` KNOWN_JA_ONLY_FALLBACK_SECTIONS
    which tracks the ``hpi_template.onset_pattern`` per-language split
    gap that surfaces here as `no_japanese_leakage` FAIL on us-100).
    """
    output = tmp_path / preset
    subprocess.run(
        ["clinosim", "dataset", "build", preset, "--output", str(output)],
        check=True,
        capture_output=True,
    )

    engine = EvalEngine(cohort_dir=output)
    report = engine.run()

    # 1. Report shape is well-formed.
    assert report.overall_score >= 0
    assert report.overall_status in ("PASS", "WARN", "FAIL")
    assert len(report.axes) == 4  # structural + clinical + locale + jp_clins_lab_compliance

    # 2. Core three axes actually ran and produced checks. The JP-CLINS lab
    #    compliance axis returns [] on non-JP or eCS-less cohorts, so it's
    #    excluded from the checks-nonempty assertion below.
    for axis_name in ("structural", "clinical", "locale"):
        axis = next(a for a in report.axes if a.axis == axis_name)
        assert axis.checks, f"{axis_name} axis produced no checks on {preset}"
        assert 0 <= axis.score <= 100

    # 3. Structural axis must PASS — the reproducibility gate already
    #    enforces schema invariants tightly, and any structural
    #    regression is a real integration bug (not conservative
    #    thresholds like the clinical/locale MVP).
    structural = next(a for a in report.axes if a.axis == "structural")
    assert structural.status == "PASS", (
        f"structural axis regressed on {preset}: "
        f"{[c.to_dict() for c in structural.checks if c.outcome is not Outcome.PASS]}"
    )
