"""US outpatient notes state US BP / LDL targets (Issue #2860)."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD,
    NARRATIVE_LDL_ELEVATED_THRESHOLD,
    chronic_control_targets,
)

pytestmark = pytest.mark.unit


def test_us_targets_are_acc_aha() -> None:
    us = chronic_control_targets("US")
    assert us.bp.target == (130, 80)
    assert us.ldl.target is None
    assert (us.ldl.elevated, us.ldl.borderline, us.ldl.high) == (130, 160, 190)


def test_jp_targets_are_jsh_jas_and_back_the_jp_constants() -> None:
    jp = chronic_control_targets("jp")
    assert jp.bp.target == (140, 90)
    assert jp.ldl.target == 120
    assert NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD == 140
    assert NARRATIVE_LDL_ELEVATED_THRESHOLD == 120
