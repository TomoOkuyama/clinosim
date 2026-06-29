"""ServiceRequest FHIR R4 builder (PR1: lab orders, panel-aware grouping).

Reads CIF Orders (with ``order_type=OrderType.LAB`` and Order.panel_key
populated by the order engine), emits one ServiceRequest per panel
instance (4 CBC tests → 1 SR) and one per stand-alone Order. Panel SR
uses the LOINC panel code (58410-2 for CBC etc.) sourced from
``lab_panel_groups.yaml``; stand-alone uses Order.order_code (individual
LOINC for the analyte).

Compliance:
- US Core ServiceRequest profile (LAB category via SNOMED 108252007).
- JP Core ServiceRequest profile (placerOrderNumber via v2-0203 PLAC
  identifier.type.coding).
- Status aggregation rule (panel SR): any non-terminal member → active;
  all CANCELLED/STOPPED → revoked; otherwise (all terminal, at least one
  RESULTED/REVIEWED) → completed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.types.encounter import Order, OrderStatus, OrderType

# === Canonical constants (silent-no-op defense, PR-90 lesson) ===
SR_ID_PREFIX = "sr-"
PLACER_ORDER_NUMBER_SYSTEM = "urn:clinosim:placer-order-number"
LAB_CATEGORY_SNOMED = "108252007"
LAB_CATEGORY_V2_0074 = "LAB"
# System URIs derived from the canonical registry (never hardcode per CLAUDE.md).
V2_0203_SYSTEM = get_system_uri("hl7-v2-0203")
V2_0074_SYSTEM = get_system_uri("hl7-diagnostic-service-section")
SNOMED_CT_SYSTEM = get_system_uri("snomed-ct")

# HL7 v2 administrative labels ("Placer Identifier", "Laboratory") are NOT
# in clinosim/codes/data/ — they are FHIR-spec-defined administrative
# strings. Hardcoded in _build_sr_skeleton; a future locale extension could
# move these to a per-locale YAML if JP-display variants are desired.

# Stand-alone Order priority → SR.priority pass-through.
_PRIORITY_MAP = {
    "routine": "routine",
    "urgent": "urgent",
    "stat": "stat",
    "asap": "asap",
}

# Non-terminal OrderStatus values (used in panel SR.status aggregation).
_NON_TERMINAL_STATUSES = frozenset({
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.IN_PROGRESS,
})
_CANCELLED_STATUSES = frozenset({OrderStatus.CANCELLED, OrderStatus.STOPPED})


def aggregate_panel_status(member_orders: list[Order]) -> str:
    """Aggregate panel member OrderStatus into a single FHIR ServiceRequest.status.

    Rule:
    - If ANY member is in {PLACED, ACCEPTED, IN_PROGRESS} → "active".
    - Else if ALL members are in {CANCELLED, STOPPED} → "revoked".
    - Else → "completed" (all terminal, at least one RESULTED/REVIEWED).
    """
    if not member_orders:
        return "active"
    statuses = {o.status for o in member_orders}
    if statuses & _NON_TERMINAL_STATUSES:
        return "active"
    if statuses <= _CANCELLED_STATUSES:
        return "revoked"
    return "completed"


def build_panel_counter(
    orders: list[Order],
) -> dict[tuple[str, str, datetime], int]:
    """Build encounter-scoped panel instance counter.

    For panel Orders (non-empty panel_key), assign sequential index N per
    distinct (encounter_id, panel_key, ordered_datetime) tuple. Stand-alone
    Orders are not indexed (their SR id uses order_id directly).

    Deterministic: input Orders are sorted by (encounter_id, panel_key,
    ordered_datetime) before assigning N.
    """
    counter: dict[tuple[str, str, datetime], int] = {}
    panel_orders = [o for o in orders if o.panel_key]
    panel_orders_sorted = sorted(
        panel_orders,
        key=lambda o: (o.encounter_id, o.panel_key, o.ordered_datetime),
    )
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for o in panel_orders_sorted:
        key = (o.encounter_id, o.panel_key, o.ordered_datetime)
        if key not in counter:
            scope = (o.encounter_id, o.panel_key)
            seen[scope] += 1
            counter[key] = seen[scope]
    return counter


def order_to_sr_id(
    order: Order,
    panel_counter: dict[tuple[str, str, datetime], int],
) -> str:
    """Compute ServiceRequest.id for an Order (deterministic, stateless).

    Stand-alone: ``sr-{order_id}``.
    Panel: ``sr-{encounter_id}-{panel_key}-{N}`` where N from panel_counter.
    """
    if order.panel_key:
        idx = panel_counter[(order.encounter_id, order.panel_key, order.ordered_datetime)]
        return f"{SR_ID_PREFIX}{order.encounter_id}-{order.panel_key}-{idx}"
    return f"{SR_ID_PREFIX}{order.order_id}"


def _bb_service_requests(ctx: BundleContext) -> list[dict[str, Any]]:
    """Builder entry point — emit ServiceRequest resources for LAB orders.

    Returns a list of raw FHIR ServiceRequest resources to be appended to
    the per-resource NDJSON files by ``_build_bundle``.

    Not yet wired into _BUNDLE_BUILDERS — that happens in Task 5.
    """
    orders: list[Order] = ctx.record.get("orders", []) or []
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    if not lab_orders:
        return []

    counter = build_panel_counter(lab_orders)
    panels = load_panel_definitions()
    country = ctx.country.lower()
    lang = "ja" if country == "jp" else "en"

    # Group panel orders by SR id; stand-alone Orders emit 1 SR each.
    panel_buckets: dict[str, list[Order]] = defaultdict(list)
    standalone_orders: list[Order] = []
    for o in lab_orders:
        if o.panel_key:
            panel_buckets[order_to_sr_id(o, counter)].append(o)
        else:
            standalone_orders.append(o)

    resources: list[dict[str, Any]] = []
    for sr_id, members in sorted(panel_buckets.items()):
        anchor = members[0]
        panel_def = panels[anchor.panel_key]
        sr = _build_panel_sr(sr_id, anchor, members, panel_def, lang)
        resources.append(sr)
    for o in standalone_orders:
        sr = _build_standalone_sr(o, lang)
        resources.append(sr)
    return resources


def _build_panel_sr(
    sr_id: str,
    anchor: Order,
    members: list[Order],
    panel_def: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
    """Build one ServiceRequest resource for a panel (all members share the SR)."""
    panel_loinc = panel_def["loinc"]
    panel_display = code_lookup("loinc", panel_loinc, lang) or panel_def.get("display", "")
    placer_value = sr_id[len(SR_ID_PREFIX):]  # strip "sr-" prefix
    status = aggregate_panel_status(members)
    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(anchor.urgency, "routine"),
        loinc_code=panel_loinc,
        loinc_display=panel_display,
        loinc_text=anchor.panel_key,
        anchor=anchor,
        lang=lang,
    )


def _build_standalone_sr(o: Order, lang: str) -> dict[str, Any]:
    """Build one ServiceRequest resource for a stand-alone test."""
    sr_id = f"{SR_ID_PREFIX}{o.order_id}"
    placer_value = o.order_id
    status = aggregate_panel_status([o])
    loinc_display = code_lookup("loinc", o.order_code, lang) or o.display_name
    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(o.urgency, "routine"),
        loinc_code=o.order_code,
        loinc_display=loinc_display,
        loinc_text=o.display_name,
        anchor=o,
        lang=lang,
    )


def _build_sr_skeleton(
    *,
    sr_id: str,
    placer_value: str,
    status: str,
    priority: str,
    loinc_code: str,
    loinc_display: str,
    loinc_text: str,
    anchor: Order,
    lang: str,
) -> dict[str, Any]:
    """Shared SR resource skeleton for panel + stand-alone."""
    snomed_display = code_lookup("snomed-ct", LAB_CATEGORY_SNOMED, lang) or (
        "臨床検査" if lang == "ja" else "Laboratory procedure"
    )
    sr: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": sr_id,
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": V2_0203_SYSTEM,
                            "code": "PLAC",
                            "display": "Placer Identifier",
                        }
                    ]
                },
                "system": PLACER_ORDER_NUMBER_SYSTEM,
                "value": placer_value,
            }
        ],
        "status": status,
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": SNOMED_CT_SYSTEM,
                        "code": LAB_CATEGORY_SNOMED,
                        "display": snomed_display,
                    },
                    {
                        "system": V2_0074_SYSTEM,
                        "code": LAB_CATEGORY_V2_0074,
                        "display": "Laboratory",
                    },
                ]
            }
        ],
        "priority": priority,
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display,
                }
            ],
            "text": loinc_text,
        },
        "subject": {"reference": f"Patient/{anchor.patient_id}"},
        "encounter": {"reference": f"Encounter/{anchor.encounter_id}"},
        "authoredOn": anchor.ordered_datetime.isoformat(),
    }
    if anchor.ordered_by:
        sr["requester"] = {"reference": f"Practitioner/{anchor.ordered_by}"}
    if anchor.clinical_intent:
        sr["reasonCode"] = [{"text": anchor.clinical_intent}]
    return sr
