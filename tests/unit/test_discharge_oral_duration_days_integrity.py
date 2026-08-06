"""Load-time validator for `discharge_oral` `duration_days` fallback (Issue #462).

Sibling to `test_discharge_oral_route_integrity.py` (Issue #455). Same shape:
`_build_discharge_rx._append_item` substitutes `duration_days = 7` when the
entry omits the field. That fallback is a grounded inference for daily-dosed
drugs, but becomes a FALSE ASSERTION when the dose names an administration
interval longer than one week (`weekly`, `q6months`, etc.). The validator
here fails load-time so authors cannot introduce a new offender silently.

Coverage:
* dose_names_long_interval — positive + negative cases (intervals inside
  and outside the 7-day fallback envelope).
* _validate_drug_block_duration_days — fires on the offending shape,
  accepts an explicit override, ignores unrelated blocks.
* Corpus sweep — every currently-shipped `discharge_oral` entry passes
  the validator (the 2 known bad entries in
  `vertebral_compression_fracture.yaml` are fixed in the same PR).
"""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import (
    _validate_drug_block_duration_days,
    dose_names_long_interval,
    load_all_disease_protocols,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "dose,expected",
    [
        # Positive — intervals > 1 week
        ("60mg SC q6months", True),
        ("70mg PO weekly", True),
        ("Methotrexate 7.5mg PO weekly", True),
        ("Denosumab q6 months", True),
        ("q12weeks", True),
        ("MONTHLY", True),
        # Negative — daily or sub-daily (inside 7-day fallback envelope)
        ("20mg PO daily", False),
        ("500mg PO q6h PRN", False),
        ("875/125mg PO BID", False),
        ("40mg PO daily (remaining days of 5-day course)", False),
        # Negative — silence (fallback is best available inference)
        ("Resume or initiate controller therapy", False),
        ("", False),
        (None, False),  # tolerate missing dose gracefully
    ],
)
def test_dose_names_long_interval(dose, expected):
    assert dose_names_long_interval(dose or "") is expected


@pytest.mark.unit
def test_validator_rejects_long_interval_dose_without_duration_days():
    drugs = {"discharge_oral": {"japan": [{"drug": "Denosumab", "dose": "60mg SC q6months", "route": "SC"}]}}
    with pytest.raises(ValueError, match="Issue #462"):
        _validate_drug_block_duration_days("test_disease", drugs)


@pytest.mark.unit
def test_validator_accepts_long_interval_dose_with_explicit_duration_days():
    drugs = {
        "discharge_oral": {
            "japan": [{"drug": "Denosumab", "dose": "60mg SC q6months", "route": "SC", "duration_days": 180}]
        }
    }
    _validate_drug_block_duration_days("test_disease", drugs)  # must not raise


@pytest.mark.unit
def test_validator_accepts_daily_dose_without_duration_days():
    """Daily / sub-daily doses stay inside the 7-day fallback envelope, so
    silence remains a grounded inference (no false assertion)."""
    drugs = {
        "discharge_oral": {
            "us": [
                {"drug": "Acetaminophen", "dose": "650mg PO TID PRN"},
                {"drug": "Amoxicillin", "dose": "500mg PO q8h"},
            ]
        }
    }
    _validate_drug_block_duration_days("test_disease", drugs)  # must not raise


@pytest.mark.unit
def test_validator_ignores_non_discharge_oral_blocks():
    """`escalation` and other blocks have their own duration semantics (drip /
    titration) — the 7-day fallback does not apply to them. The validator must
    stay scoped to `discharge_oral`."""
    drugs = {
        "escalation": {"japan": [{"drug": "Furosemide drip", "dose": "10mg/h IV continuous"}]},
        "first_line": {
            "us": [{"drug": "Depo-Medrol", "dose": "40mg IM weekly"}]  # weekly IM, no fallback
        },
    }
    _validate_drug_block_duration_days("test_disease", drugs)  # must not raise


@pytest.mark.unit
def test_all_shipped_disease_yamls_pass_the_validator():
    """Corpus sweep — every discharge_oral entry currently in the reference
    data must pass the new duration_days validator. Catches new offenders
    introduced by future YAML edits."""
    protocols = load_all_disease_protocols()
    assert len(protocols) >= 30, "expected the disease corpus to be substantial"
