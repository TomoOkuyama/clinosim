"""Phase 3.β.6 — stage-label → SNOMED CT catalog externalisation.

The 24-entry ``_STAGE_SUMMARY_SNOMED`` dict in
``fhir_r4/conditions/conditions.py`` is retired. The catalog now
lives in ``clinosim/codes/data/clinosim-stage-to-snomed.yaml`` and is
read via ``clinosim.codes.stage_to_snomed.resolve_stage_snomed``.

These tests lock the SoT contract:
  * The retired module-local dict is gone from conditions.py.
  * Every catalog entry's SNOMED pointer resolves against snomed-ct.yaml.
  * The pre-fix stage set (24 labels across CKD / NYHA / GOLD / asthma
    severity / HTN / CCS) is fully preserved in the catalog.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.stage_to_snomed import all_stage_labels, resolve_stage_snomed
from clinosim.modules.output.fhir_r4.conditions import conditions as conditions_mod

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The module-local dict is retired.
# ---------------------------------------------------------------------------


def test_retired_module_local_dict_absent_from_conditions_module():
    assert not hasattr(conditions_mod, "_STAGE_SUMMARY_SNOMED"), (
        "_STAGE_SUMMARY_SNOMED must be retired — the catalog lives in "
        "clinosim/codes/data/clinosim-stage-to-snomed.yaml, read via "
        "clinosim.codes.stage_to_snomed.resolve_stage_snomed."
    )


# ---------------------------------------------------------------------------
# Pre-fix label set is fully preserved.
# ---------------------------------------------------------------------------


_PRE_FIX_LABELS: tuple[tuple[str, str], ...] = (
    ("CKD G1", "431855005"),
    ("CKD G2", "431856006"),
    ("CKD G3a", "700378005"),
    ("CKD G3b", "700379002"),
    ("CKD G4", "431857002"),
    ("CKD G5", "433146000"),
    ("NYHA I", "420300004"),
    ("NYHA II", "421704003"),
    ("NYHA III", "420913000"),
    ("NYHA IV", "422293003"),
    ("GOLD 1", "313296004"),
    ("GOLD 2", "313297008"),
    ("GOLD 3", "313299006"),
    ("GOLD 4", "135836000"),
    ("Mild intermittent", "427679007"),
    ("Mild persistent", "426979002"),
    ("Moderate persistent", "427295004"),
    ("Severe persistent", "426656000"),
    ("Stage 1", "827069000"),
    ("Stage 2", "827068008"),
    ("CCS I", "61490001"),
    ("CCS II", "41334000"),
    ("CCS III", "85284003"),
    ("CCS IV", "89323001"),
)


@pytest.mark.parametrize("label, expected_code", _PRE_FIX_LABELS)
def test_pre_fix_stage_label_resolves(label: str, expected_code: str):
    assert resolve_stage_snomed(label) == expected_code


def test_catalog_covers_exact_pre_fix_label_set():
    """A regression that silently drops a stage label fails here."""
    assert set(all_stage_labels()) == {label for label, _ in _PRE_FIX_LABELS}


# ---------------------------------------------------------------------------
# Every catalog SNOMED pointer resolves against snomed-ct.yaml (authority).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label, expected_code", _PRE_FIX_LABELS)
def test_every_pointer_resolves_against_snomed_ct_yaml(label: str, expected_code: str):
    """A dangling pointer would leave FHIR Condition.stage.summary.coding
    with a code the display lookup cannot resolve."""
    display_en = code_lookup("snomed-ct", expected_code, "en")
    assert display_en and display_en != expected_code, (
        f"stage {label} → SNOMED {expected_code} has no display in snomed-ct.yaml"
    )


# ---------------------------------------------------------------------------
# resolve_stage_snomed returns None (not raise) for unknown labels.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unknown", ["", "CKD G99", "AJCC IIB", "unknown-stage"])
def test_resolve_stage_snomed_returns_none_for_unknown(unknown: str):
    """A None return is the signal for the FHIR emitter to omit
    summary.coding and keep summary.text only — same semantics the
    retired dict.get() had."""
    assert resolve_stage_snomed(unknown) is None


# ---------------------------------------------------------------------------
# conditions.py now imports resolve_stage_snomed from the catalog loader.
# ---------------------------------------------------------------------------


def test_conditions_module_imports_resolve_stage_snomed():
    """A regression that re-introduces a module-local dict and drops
    this import fails here."""
    assert hasattr(conditions_mod, "resolve_stage_snomed")
