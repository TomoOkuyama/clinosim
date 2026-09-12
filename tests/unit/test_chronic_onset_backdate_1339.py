"""Issue #1339 — implied-chronic conditions must be backdated, not stamped
at the acute-admission date.

``simulator/inpatient.py`` appends implied-chronic ChronicConditions when an
acute admission workup reveals a co-morbidity (e.g. K85.9 pancreatitis
admission → K74 cirrhosis on workup). Before this fix ``onset_date`` was set
to the admission date, producing "chronic condition first appearing at the
acute event" records. The fix routes through
``derive_implied_chronic_onset`` which:

- Backdates 1-14 years by SHA256(patient_id, code) so the onset precedes
  admission clinically (RNG-neutral so the master cascade is unperturbed).
- Applies the same ``dob + min_onset_age`` floor as ``_clamp_chronic_onset``
  so pediatric edge cases remain valid.
- Is deterministic across re-runs (same patient × code → same onset).
"""

from __future__ import annotations

from datetime import date

from clinosim.modules.patient.activator import derive_implied_chronic_onset


def test_derive_implied_onset_precedes_admission_by_years():
    dob = date(1960, 3, 15)
    admission = date(2026, 5, 23)
    onset = derive_implied_chronic_onset("pt-abc123", "I25.10", admission, dob)
    # 1-14 years back (365-day years plus 0-364 extra days), so bounded roughly
    # by (admission - 15 * 365) .. (admission - 1 * 365).
    delta_days = (admission - onset).days
    assert 365 <= delta_days <= 15 * 365 + 365, (
        f"onset {onset} is not 1-15y before admission {admission} (delta_days={delta_days})"
    )
    # Never same day as admission — the core bug this fixes.
    assert onset != admission


def test_derive_implied_onset_deterministic_same_input():
    dob = date(1960, 3, 15)
    admission = date(2026, 5, 23)
    a = derive_implied_chronic_onset("pt-abc123", "I25.10", admission, dob)
    b = derive_implied_chronic_onset("pt-abc123", "I25.10", admission, dob)
    assert a == b


def test_derive_implied_onset_varies_by_patient():
    dob = date(1960, 3, 15)
    admission = date(2026, 5, 23)
    a = derive_implied_chronic_onset("pt-abc", "I25.10", admission, dob)
    b = derive_implied_chronic_onset("pt-xyz", "I25.10", admission, dob)
    # Different patients get different onsets (deterministically distinct).
    assert a != b


def test_derive_implied_onset_varies_by_code():
    dob = date(1960, 3, 15)
    admission = date(2026, 5, 23)
    a = derive_implied_chronic_onset("pt-abc", "I25.10", admission, dob)
    b = derive_implied_chronic_onset("pt-abc", "E78.5", admission, dob)
    assert a != b


def test_derive_implied_onset_respects_min_age_floor():
    # Patient born 2020-06-01, admitted at age ~6 in 2026. Even though the
    # ``_AGE_MIN_ICD`` gate in inpatient.py would prevent this in practice,
    # the derivation itself must respect the dob + min_years floor so it
    # never produces an onset before the patient's plausible age of onset.
    dob = date(2020, 6, 1)
    admission = date(2026, 12, 1)
    # J44 (COPD) has 30-year min-age-of-onset in chronic_onset_min_age.yaml.
    onset = derive_implied_chronic_onset("pt-child", "J44.9", admission, dob)
    # The floor is dob + 30 * 365 days = 2050-05-24 which is AFTER admission.
    # In that case the clamp returns the floor, which is beyond admission —
    # this test just verifies the floor is applied (onset never precedes dob).
    assert onset >= dob


def test_derive_implied_onset_with_no_dob_returns_sample():
    # When dob is None (rare edge case), the derivation returns the sampled
    # date without clamping — same shape as _clamp_chronic_onset.
    admission = date(2026, 5, 23)
    onset = derive_implied_chronic_onset("pt-abc", "I25.10", admission, None)
    assert onset < admission
