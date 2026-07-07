"""FHIR R4 MedicationRequest / MedicationAdministration builders (FA-1 medications).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

import uuid
from typing import Any

from clinosim.codes import (
    get_system_uri,
    system_key_for,
)
from clinosim.codes import (
    lookup as code_lookup,
)
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import is_us, resolve_lang
from clinosim.modules.output._fhir_common import (
    _build_dosage_instruction,
    _map_mar_status,
    _parse_dose_for_mar,
    _strip_protocol_prefix,
)
from clinosim.modules.output._fhir_localization import _localize_drug_name
from clinosim.modules.output._fhir_reference_data import _ROUTE_SNOMED


def _map_order_status_to_fhir(status: str) -> str:
    """Map clinosim OrderStatus to FHIR R4 MedicationRequest.status.
    PR3b-3 adds 'stopped' mapping for discontinued empirical regimens.

    PR3b-3 adversarial-1 I-C2 fix: known OrderStatus values map deterministically;
    unknown values still fall back to "active" (FHIR valid) but the mapping is
    explicit so a future enum addition is caught by mypy strict / code review.
    """
    # All OrderStatus values exhaustively mapped (matches clinosim/types/encounter.py).
    # Adding a new OrderStatus enum value requires updating this mapping —
    # the comment + explicit listing surface the silent-no-op risk loud at
    # code review time (adversarial-1 I-C2).
    mapping = {
        "placed": "active",       # order placed but not yet acted on
        "accepted": "active",     # default operational state
        "in_progress": "active",  # in progress
        "resulted": "active",     # not normally used for MedicationRequest (lab path)
        "reviewed": "active",     # not normally used for MedicationRequest (lab path)
        "cancelled": "cancelled",
        "stopped": "stopped",     # PR3b-3: narrowed / de-escalated empirical
    }
    return mapping.get(status, "active")


def _build_medication_request(
    order: dict, patient_id: str, country: str,
    encounter_id: str = "", primary_dx_code: str = "",
) -> dict:
    """Build FHIR MedicationRequest resource."""
    drug_name_raw = order.get("display_name", "Unknown medication")
    # Strip protocol prefix (e.g. "DVT_prophylaxis:") from medicationCodeableConcept.text
    # The prefix goes to dosageInstruction note instead.
    drug_name_clean, protocol_category = _strip_protocol_prefix(drug_name_raw)
    drug_name = _localize_drug_name(drug_name_clean, country)
    # Strip dose info to get base drug name for code lookup (use cleaned name)
    base_name = drug_name_clean.split(" ")[0] if drug_name_clean else ""

    country_code = "US" if is_us(country) else "JP"
    lang = resolve_lang(country_code)
    drug_codes = load_code_mapping("drug", country_code)  # name → RxNorm/YJ

    code_value = drug_codes.get(base_name, "")
    drug_system_key = system_key_for("drug", country_code)
    display = code_lookup(drug_system_key, code_value, lang) if code_value else drug_name
    if display == code_value:
        display = drug_name
    code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": drug_name}
    if code_value:
        med_concept["coding"] = [{
            "system": code_system,
            "code": code_value,
            "display": display,
        }]

    # ID: prepend encounter_id to ensure global uniqueness across patient's
    # multiple encounters (raw order_id is patient-scoped only)
    base_oid = order.get("order_id") or str(uuid.uuid4())
    enc_ref_id = order.get("encounter_id", "") or encounter_id
    resource_id = f"{enc_ref_id}-{base_oid}" if enc_ref_id else base_oid

    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": resource_id,
        "status": _map_order_status_to_fhir(order.get("status", "")),
        "intent": "order",
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": order.get("ordered_datetime", ""),
    }

    # Encounter reference
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

    # Requester (ordering physician)
    if order.get("ordered_by"):
        resource["requester"] = {"reference": f"Practitioner/{order['ordered_by']}"}

    # Dosage instruction
    dosage = _build_dosage_instruction(order, country=country)
    if dosage:
        resource["dosageInstruction"] = [dosage]

    # Reason reference (link to primary diagnosis Condition)
    reason = order.get("reason_condition", "") or primary_dx_code
    if reason:
        cond_ref = f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary"
        resource["reasonReference"] = [{
            "reference": f"Condition/{cond_ref}",
        }]

    return resource


def _build_medication_admin(
    mar: dict, patient_id: str, index: int, country: str = "US",
    encounter_id: str = "", primary_dx_code: str = "",
) -> dict:
    """Build FHIR MedicationAdministration resource."""
    drug_name_raw = mar.get("drug_name", "")
    drug_name_clean, _ = _strip_protocol_prefix(drug_name_raw)
    drug_name = _localize_drug_name(drug_name_clean, country)
    base_name = drug_name_clean.split(" ")[0] if drug_name_clean else ""
    country_code = "US" if is_us(country) else "JP"
    lang = resolve_lang(country_code)
    drug_codes = load_code_mapping("drug", country_code)
    code_value = drug_codes.get(base_name, "")
    drug_system_key = system_key_for("drug", country_code)
    code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": drug_name}
    if code_value:
        display = code_lookup(drug_system_key, code_value, lang)
        coding = {"system": code_system, "code": code_value}
        if display and display != code_value:
            coding["display"] = display
        med_concept["coding"] = [coding]

    resource: dict[str, Any] = {
        "resourceType": "MedicationAdministration",
        "id": f"mar-{encounter_id or patient_id}-{index:05d}",
        "status": _map_mar_status(mar.get("status", "completed")),
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": mar.get("actual_datetime") or mar.get("scheduled_datetime", ""),
    }

    # Encounter context
    if encounter_id:
        resource["context"] = {"reference": f"Encounter/{encounter_id}"}

    # Cycle-1 C1-06/C1-07: MAR → MR audit-trail link. The MedicationRequest id
    # is formatted `{enc_id}-{order_id}` in _build_medication_request above; the
    # MAR carries the same order_id in CIF (types/encounter.MedicationAdministration).
    # Emit MedicationAdministration.request per FHIR R4 so the med-order-to-
    # administration chain resolves. Session 41 cycle 1 fix.
    mar_order_id = mar.get("order_id", "")
    if mar_order_id and encounter_id:
        resource["request"] = {"reference": f"MedicationRequest/{encounter_id}-{mar_order_id}"}

    if mar.get("administered_by"):
        resource["performer"] = [{"actor": {"reference": f"Practitioner/{mar['administered_by']}"}}]

    # Dosage with structured dose + route
    dose_text = mar.get("dose", "") or drug_name
    dose_str = mar.get("dose", "")
    parsed = _parse_dose_for_mar(dose_str or drug_name)
    dosage: dict[str, Any] = {"text": dose_text}
    if parsed.get("dose_quantity") is not None and parsed.get("dose_unit"):
        dosage["dose"] = {
            "value": parsed["dose_quantity"],
            "unit": parsed["dose_unit"],
            "system": get_system_uri("ucum"),
        }
    # Rate for continuous infusions
    if "CONTINUOUS" in dose_text.upper() or "DRIP" in dose_text.upper() or "/h" in dose_text:
        dosage["rateQuantity"] = {
            "value": parsed.get("dose_quantity") or 1,
            "unit": (parsed.get("dose_unit", "mL") + "/h"),
            "system": get_system_uri("ucum"),
        }
    # Route
    route = (mar.get("route") or parsed.get("route") or "").upper()
    if route:
        snomed = _ROUTE_SNOMED.get(route)
        if snomed:
            dosage["route"] = {
                "coding": [{"system": get_system_uri("snomed-ct"), **snomed}],
                "text": route,
            }
        else:
            dosage["route"] = {"text": route}
    resource["dosage"] = dosage

    # Reason reference (link to primary diagnosis)
    if primary_dx_code:
        cond_ref = f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary"
        resource["reasonReference"] = [{
            "reference": f"Condition/{cond_ref}",
        }]

    return resource
