"""Monitoring orders name the drug the patient takes (Issue #2294)."""

from __future__ import annotations

import pytest

from clinosim.modules.monitoring.mapping import load_medication_monitoring, matched_medication_names
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit


def test_rosuvastatin_matches_statin_rule_but_keeps_its_own_name() -> None:
    mapping = load_medication_monitoring()
    meds = [HomeMedication(drug_name="Rosuvastatin", drug_name_ja="ロスバスタチン")]
    names = matched_medication_names(meds, mapping)
    assert names == {"Atorvastatin": ("Rosuvastatin", "ロスバスタチン")}


def test_valsartan_keeps_its_own_name_under_the_arb_rule() -> None:
    mapping = load_medication_monitoring()
    meds = [HomeMedication(drug_name="Valsartan", drug_name_ja="バルサルタン")]
    assert matched_medication_names(meds, mapping)["Candesartan"] == ("Valsartan", "バルサルタン")


def test_rule_drug_itself_uses_its_names() -> None:
    mapping = load_medication_monitoring()
    meds = [HomeMedication(drug_name="Atorvastatin", drug_name_ja="")]
    assert matched_medication_names(meds, mapping)["Atorvastatin"] == ("Atorvastatin", "アトルバスタチン")
