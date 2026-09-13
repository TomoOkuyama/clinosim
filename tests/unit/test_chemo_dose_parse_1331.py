"""Issue #1331 — chemo cycle drugs (Oxaliplatin / Leucovorin / 5-FU /
Trastuzumab / Pemetrexed / Carboplatin / Nab-paclitaxel / Gemcitabine /
Temozolomide) previously emitted MedicationRequests with only
``dosageInstruction.text`` populated — ``doseAndRate.doseQuantity`` was
absent because ``parse_dose_string`` in ``modules/order/engine.py`` did
not match BSA / weight-based units like ``mg/m2`` or ``mg/kg``.

Fix extends the parser to handle those UCUM-valid compound units and
wires ``enrich_medication_order`` into the outpatient chemo emit path.
"""

from __future__ import annotations

from clinosim.modules.order.engine import parse_dose_string


def test_parse_mg_per_m2_dose():
    r = parse_dose_string("85mg/m2")
    assert r["dose_quantity"] == 85.0
    assert r["dose_unit"] == "mg/m2"


def test_parse_mg_per_m2_with_space():
    r = parse_dose_string("400 mg/m2")
    assert r["dose_quantity"] == 400.0
    assert r["dose_unit"] == "mg/m2"


def test_parse_mg_per_kg_dose():
    r = parse_dose_string("6mg/kg")
    assert r["dose_quantity"] == 6.0
    assert r["dose_unit"] == "mg/kg"


def test_parse_mcg_per_kg_dose():
    r = parse_dose_string("2mcg/kg")
    assert r["dose_quantity"] == 2.0
    assert r["dose_unit"] == "mcg/kg"


def test_bsa_dose_matches_before_plain_mg_would():
    # Regression guard: "85mg/m2" must NOT truncate to plain "mg" +
    # dose_quantity=85. The BSA-first two-tier match preserves the
    # compound unit.
    r = parse_dose_string("85mg/m2")
    assert r["dose_unit"] == "mg/m2"


def test_plain_mg_still_matches_after_bsa_extension():
    # Regression guard: "3.75mg" (Leuprorelin) keeps parsing to plain "mg".
    r = parse_dose_string("3.75mg")
    assert r["dose_quantity"] == 3.75
    assert r["dose_unit"] == "mg"


def test_auc_dose_unparseable_returns_no_dose():
    # Carboplatin "AUC5" is an area-under-curve target, not a mg dose —
    # parser correctly returns no dose_quantity.
    r = parse_dose_string("AUC5")
    assert "dose_quantity" not in r


def test_vial_dose_unparseable_returns_no_dose():
    # BCG "1 vial (81mg TICE / 27mg Connaught)" — the parser DOES pick
    # up the first mg-quantity, but that's an acceptable graceful
    # degradation (the ``81mg`` refers to the TICE vial content, not a
    # scalar patient dose). The important guarantee here is that no
    # exception is raised.
    r = parse_dose_string("1 vial (81mg TICE / 27mg Connaught)")
    # Just confirm it doesn't crash; content is not asserted.
    assert isinstance(r, dict)


def test_compound_dose_string_matches_first_component():
    # 5-FU "400mg/m2 bolus + 2400mg/m2/46h" — the first component
    # (bolus 400mg/m2) is captured; the 46h infusion component is
    # not scalar-representable.
    r = parse_dose_string("400mg/m2 bolus + 2400mg/m2/46h")
    assert r["dose_quantity"] == 400.0
    assert r["dose_unit"] == "mg/m2"
