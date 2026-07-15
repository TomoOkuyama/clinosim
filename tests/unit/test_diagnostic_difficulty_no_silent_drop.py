"""Disease-YAML ``diagnostic_difficulty`` must not be silently dropped.

FP-YAML-1 (2026-07-06 FHIR completeness chain 1): the value is read *nested*
under the ``diagnostic:`` block (``inpatient.py`` does
``protocol.diagnostic.get("diagnostic_difficulty", 0.3)``), but several disease
YAMLs authored it at the *top level*, where ``DiseaseProtocol``'s
``extra="ignore"`` default drops it at load time — so the authored value
(e.g. acute_mi 0.25, sepsis 0.5) silently became the 0.3 fallback.

Two invariants guard the fix:
  1. The effective value equals the authored value (no silent drop).
  2. No disease YAML carries a top-level ``diagnostic_difficulty`` key
     (a precondition for turning on ``extra="forbid"`` — FP-YAML-3).
"""

from __future__ import annotations

import glob
import os

import pytest
import yaml

from clinosim.modules.disease.protocol import load_disease_protocol

pytestmark = pytest.mark.unit

_YAML_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "clinosim", "modules", "disease", "reference_data")
_DISEASE_FILES = sorted(glob.glob(os.path.join(_YAML_DIR, "*.yaml")))
_DISEASE_IDS = [os.path.basename(f)[:-5] for f in _DISEASE_FILES]


def _raw(disease_id: str) -> dict:
    with open(os.path.join(_YAML_DIR, f"{disease_id}.yaml")) as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("disease_id", _DISEASE_IDS)
def test_effective_diagnostic_difficulty_matches_authored(disease_id):
    """The value inpatient.py:608 reads must equal what the author wrote,
    regardless of whether it was placed top-level or nested."""
    raw = _raw(disease_id)
    top = raw.get("diagnostic_difficulty")
    nested = (raw.get("diagnostic") or {}).get("diagnostic_difficulty")
    authored = nested if nested is not None else top  # nested wins if both present
    expected = authored if authored is not None else 0.3

    protocol = load_disease_protocol(disease_id)
    effective = (protocol.diagnostic or {}).get("diagnostic_difficulty", 0.3)
    assert effective == expected, (
        f"{disease_id}: authored {authored} but simulation uses {effective} "
        f"(silent-drop of a top-level diagnostic_difficulty)"
    )


@pytest.mark.parametrize("disease_id", _DISEASE_IDS)
def test_no_top_level_diagnostic_difficulty(disease_id):
    """diagnostic_difficulty belongs under the diagnostic: block only.
    A top-level key is silently dropped and blocks extra='forbid'."""
    raw = _raw(disease_id)
    assert "diagnostic_difficulty" not in raw, (
        f"{disease_id}: move diagnostic_difficulty under the diagnostic: block (top-level is silently dropped)"
    )
