"""Issue #1770: every I10 chronic-HTN patient gets an ACE/ARB (first-line
pillar per ACC/AHA 2017 + JNC 8 + ESC/ESH 2023).

Pre-fix the I10 chronic_medications.yaml entry assigned Candesartan with
``probability: 0.5``, leaving ~50 % of baseline I10 patients without any
ACE/ARB. On the p=10k 5y US cohort 46 % of ``htn_escalate_third_agent_i10``-
escalated patients ended up as triple-therapy without the ACE/ARB
pillar (CCB + HCTZ + no RAS blocker).

Fix: raise Candesartan baseline sampling probability to 1.0. RNG-neutral
by activator design (Bernoulli sampler consumes the same draw regardless
of the probability value — only the outcome changes).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "chronic_medications.yaml"


def _load_i10_medications() -> list[dict]:
    with _YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return (data.get("I10") or {}).get("medications") or []


def test_i10_regimen_includes_candesartan_at_full_probability() -> None:
    """Issue #1770 fix: Candesartan is a first-line ACE/ARB pillar for
    chronic HTN; every I10 baseline patient must receive it."""
    meds = _load_i10_medications()
    candesartan_entries = [m for m in meds if m.get("drug_id") == "candesartan"]
    assert len(candesartan_entries) == 1, "I10 regimen must declare exactly one candesartan entry"
    assert candesartan_entries[0].get("probability", 1.0) == 1.0, (
        "Pre-fix 0.5 → post-fix 1.0 (ACC/AHA 2017 first-line pillar)"
    )


def test_i10_regimen_preserves_amlodipine_ccb_pillar() -> None:
    """The amlodipine (CCB) pillar stays unchanged — the fix is
    additive and the regimen is still CCB + ACE/ARB + (optional
    thiazide escalation)."""
    meds = _load_i10_medications()
    amlodipine_entries = [m for m in meds if m.get("drug_id") == "amlodipine"]
    assert len(amlodipine_entries) == 1
    # No explicit probability means default 1.0.
    assert amlodipine_entries[0].get("probability", 1.0) == 1.0


def test_i10_regimen_hctz_remains_escalation_only() -> None:
    """HCTZ (thiazide) is the Phase 4b.1 escalation drug — baseline
    probability stays at 0.0 so activation sampler never picks it;
    only the longitudinal engine's htn_escalate_third_agent_i10 event
    adds it."""
    meds = _load_i10_medications()
    hctz_entries = [m for m in meds if m.get("drug_id") == "hydrochlorothiazide"]
    assert len(hctz_entries) == 1
    assert hctz_entries[0].get("probability") == 0.0


def test_i10_regimen_spironolactone_remains_escalation_only() -> None:
    """Spironolactone (4th-agent MRA, Issue #1762) likewise stays
    at baseline probability 0.0."""
    meds = _load_i10_medications()
    spiro_entries = [m for m in meds if m.get("drug_id") == "spironolactone"]
    assert len(spiro_entries) == 1
    assert spiro_entries[0].get("probability") == 0.0
