"""Issue #1761: F32 / F33 / F41 chronic-onset min-age floor.

Pre-fix the chronic-onset sampler had no min-age floor for the common
mood / anxiety ICDs. Cohort scan surfaced 58 patients with onset
before age 12 (youngest 2.8 y) — clinically implausible per DSM-5-TR:
MDD typical onset 15-25, GAD onset adolescence-adulthood (childhood
anxiety belongs under F93.x codes).

Fix: register F32 / F33 / F41 min-onset floors in
``chronic_onset_min_age.yaml`` so the activator clamps sampled onset
dates to the earliest clinically plausible age.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.patient.activator import _chronic_onset_min_age_table

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "chronic_onset_min_age.yaml"


def _load_floors() -> dict[str, int]:
    with _YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("codes") or {}


# ----------------------------------------------------------------------------
# Yaml floors declared
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,min_age",
    [
        ("F32", 12),  # MDD single — adolescent floor
        ("F33", 12),  # MDD recurrent
        ("F41", 13),  # GAD + anxiety family — adolescent-adult onset
    ],
)
def test_mood_anxiety_min_onset_age_registered(code: str, min_age: int) -> None:
    """Each ICD prefix must carry its DSM-5-aligned min-onset floor."""
    floors = _load_floors()
    assert floors.get(code) == min_age, f"{code} min-onset floor missing or wrong"


# ----------------------------------------------------------------------------
# Loader exposes floors to the activator clamp
# ----------------------------------------------------------------------------


def test_activator_loader_sees_new_floors() -> None:
    """The ``_chronic_onset_min_age_table`` loader surfaces the new
    F32 / F33 / F41 entries — regression guard against a cache or
    key-casing mismatch between yaml + activator."""
    codes, _default = _chronic_onset_min_age_table()
    assert codes.get("F32") == 12
    assert codes.get("F33") == 12
    assert codes.get("F41") == 13


# ----------------------------------------------------------------------------
# Pediatric codes stay allowed
# ----------------------------------------------------------------------------


def test_pediatric_specific_f93_not_in_floors() -> None:
    """F93.x is the childhood-anxiety family — it must NOT be gated
    by the F41 floor. The code-splitting (``.split('.')[0]``) at the
    call site uses the ICD-10 base, so F93 would need its own entry
    to receive a floor — the yaml deliberately does not add one so
    pediatric anxiety stays representable."""
    floors = _load_floors()
    assert "F93" not in floors
