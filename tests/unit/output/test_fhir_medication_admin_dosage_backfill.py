"""Tests for MedicationAdministration.dosage backfill from parent Order (Issue #851).

Prior emit dropped the entire ``dosage`` element on 23,543 (6.56 %) of
JP p=10000 s500 sample MedicationAdministration resources because:

- Continue-home-med / sliding-scale / PRN orders had no numeric dose at
  either MA or Order level, so ``_parse_dose_for_mar`` yielded no
  structured dose_quantity;
- The old mad-1 emit gate required ``dose`` OR ``rateQuantity`` to be
  present in the dosage dict before emitting the dosage element at all;
- No fallback backfill from the parent Order's ``dose_quantity`` /
  ``dose_unit`` / ``frequency`` / ``route`` fields;
- The MA record's own ``dose`` field often carried the drug name as a
  fallback (``"Fluticasone/Salmeterol"`` as the ``dose`` for the same
  drug), which we now treat as empty.

Fix: pass the parent Order to the MAR builder so we can backfill dose
text + route from the Order's structured fields, and relax the emit
gate to allow a dosage element with only route or a meaningful text.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin

# --- backfill from parent Order ---


def test_dosage_route_from_parent_order_when_mar_dose_empty():
    """`Fluticasone/Salmeterol` home-med case: mar.dose is a drug-name
    fallback and Order has no dose_quantity — dosage.route + text still
    populate via the freq + route composition."""
    mar = {
        "order_id": "ORD-1",
        "drug_name": "Fluticasone/Salmeterol",
        "dose": "Fluticasone/Salmeterol",  # drug-name fallback (treated as empty)
        "route": "INH",
        "status": "given",
    }
    parent = {
        "order_id": "ORD-1",
        "display_name": "Fluticasone/Salmeterol",
        "route": "INH",
        "frequency": "BID",
        "dose_quantity": None,
        "dose_unit": "",
    }
    resource = _build_medication_admin(
        mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1", parent_order=parent
    )
    assert "dosage" in resource, "dosage element must be emitted for home-med case"
    dosage = resource["dosage"]
    assert "route" in dosage
    assert (dosage.get("route") or {}).get("text") in ("吸入", "INH")


def test_dosage_backfill_composed_text_carries_freq_and_route():
    mar = {
        "order_id": "ORD-2",
        "drug_name": "Fluticasone/Salmeterol",
        "dose": "",
        "route": "INH",
        "status": "given",
    }
    parent = {
        "order_id": "ORD-2",
        "route": "INH",
        "frequency": "BID",
    }
    resource = _build_medication_admin(
        mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1", parent_order=parent
    )
    text = resource.get("dosage", {}).get("text", "")
    # Composed text should carry the route or freq (either token indicates backfill worked)
    assert text, f"dosage.text should be populated, got {text!r}"
    assert ("INH" in text) or ("吸入" in text) or ("BID" in text) or ("1日2回" in text)


def test_dosage_backfill_dose_from_parent_order_structured():
    """When parent has structured dose_quantity + dose_unit, backfill uses it."""
    mar = {
        "order_id": "ORD-3",
        "drug_name": "Normal saline",
        "dose": "",  # empty
        "route": "IV",
        "status": "given",
    }
    parent = {
        "order_id": "ORD-3",
        "dose_quantity": 1000,
        "dose_unit": "mL",
        "route": "IV",
        "frequency": "qd",
    }
    resource = _build_medication_admin(
        mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1", parent_order=parent
    )
    dosage = resource.get("dosage", {})
    assert "dose" in dosage, "structured dose from parent should populate dosage.dose"
    assert dosage["dose"].get("value") == 1000
    assert dosage["dose"].get("unit") == "mL"


def test_dosage_text_meaningful_when_mar_dose_is_drug_name():
    """MA.dose == drug_name is a fallback; treat as empty so we do not
    duplicate `medicationCodeableConcept.text` inside `dosage.text`."""
    mar = {
        "order_id": "ORD-4",
        "drug_name": "Fluticasone/Salmeterol",
        "dose": "Fluticasone/Salmeterol",
        "route": "INH",
        "status": "given",
    }
    parent = {"order_id": "ORD-4", "route": "INH", "frequency": "BID"}
    resource = _build_medication_admin(
        mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1", parent_order=parent
    )
    text = resource.get("dosage", {}).get("text", "")
    # `.text` must NOT be just the drug name
    assert text != "Fluticasone/Salmeterol"
    assert text != "フルチカゾン/サルメテロール"


# --- mad-1 gate relaxation ---


def test_dosage_emitted_when_route_present_but_no_structured_dose():
    """Even without dose or rate, dosage element should emit if route
    is populated. Prior behavior dropped the whole element."""
    mar = {
        "order_id": "ORD-5",
        "drug_name": "Sliding scale insulin",
        "dose": "sliding scale",
        "route": "SC",
        "status": "given",
    }
    parent = {"order_id": "ORD-5", "route": "SC", "frequency": "prn"}
    resource = _build_medication_admin(
        mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1", parent_order=parent
    )
    assert "dosage" in resource, "dosage should emit for sliding-scale case"
    assert "route" in resource["dosage"]


def test_dosage_still_omitted_when_no_route_and_no_text_and_no_dose():
    """Defensive: if MA carries nothing structured and no parent, and
    the resulting dosage dict has no route/text/dose/rate, still omit."""
    mar = {
        "order_id": "ORD-6",
        "drug_name": "Aspirin",  # only drug — no dose, no route
        "dose": "Aspirin",  # drug-name fallback (treated as empty)
        "route": "",
        "status": "given",
    }
    resource = _build_medication_admin(
        mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1", parent_order=None
    )
    # No route, no meaningful text, no dose, no rate → no dosage element
    dosage = resource.get("dosage", {})
    assert not dosage or not any(k in dosage for k in ("dose", "rateQuantity", "route", "text"))


def test_dosage_preserves_structured_path_when_mar_dose_parseable():
    """Existing structured path (MA.dose = "500mL"): unchanged."""
    mar = {
        "order_id": "ORD-7",
        "drug_name": "Normal saline",
        "dose": "500mL",
        "route": "IV",
        "status": "given",
    }
    resource = _build_medication_admin(mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1")
    dosage = resource.get("dosage", {})
    assert "dose" in dosage
    assert dosage["dose"].get("value") == 500
    assert dosage["dose"].get("unit") == "mL"


def test_dosage_backfill_works_without_parent_order():
    """When no parent_order passed and MA.dose is a drug-name fallback,
    keep the MA fields — route is still emitted, text may be empty."""
    mar = {
        "order_id": "ORD-8",
        "drug_name": "Fluticasone/Salmeterol",
        "dose": "Fluticasone/Salmeterol",  # drug-name fallback
        "route": "INH",
        "status": "given",
    }
    resource = _build_medication_admin(mar, patient_id="POP-1", index=0, country="JP", encounter_id="ENC-1")
    dosage = resource.get("dosage", {})
    # Route from MA still populates
    assert "route" in dosage
