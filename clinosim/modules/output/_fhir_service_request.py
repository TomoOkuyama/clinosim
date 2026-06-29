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
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.types.encounter import OrderStatus, OrderType

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

# Non-terminal OrderStatus values — stored as string .value to support both
# enum instances (dataclass path) and plain strings (JSON-deserialized dict path).
_NON_TERMINAL_STATUSES = frozenset({"placed", "accepted", "in_progress"})
_CANCELLED_STATUSES = frozenset({"cancelled", "stopped"})


def _o(order: Any, name: str, default: Any = None) -> Any:
    """Dual-access helper: dataclass attribute OR dict key (production path)."""
    return get_attr_or_key(order, name, default)


def _status_value(s: Any) -> str:
    """Normalize OrderStatus enum OR plain string to a comparable string value."""
    if isinstance(s, OrderStatus):
        return s.value
    if isinstance(s, str):
        return s
    return ""


def aggregate_panel_status(member_orders: list[Any]) -> str:
    """Aggregate panel member OrderStatus into a single FHIR ServiceRequest.status.

    Rule:
    - If ANY member is in {PLACED, ACCEPTED, IN_PROGRESS} → "active".
    - Else if ALL members are in {CANCELLED, STOPPED} → "revoked".
    - Else → "completed" (all terminal, at least one RESULTED/REVIEWED).

    Accepts both Order dataclass instances (test/direct-object path) and
    JSON-deserialized dicts (production CIF path).
    """
    if not member_orders:
        return "active"
    statuses = {_status_value(_o(o, "status")) for o in member_orders}
    if statuses & _NON_TERMINAL_STATUSES:
        return "active"
    if statuses <= _CANCELLED_STATUSES:
        return "revoked"
    return "completed"


def build_panel_counter(
    orders: list[Any],
) -> dict[tuple[str, str, Any], int]:
    """Build encounter-scoped panel instance counter.

    For panel Orders (non-empty panel_key), assign sequential index N per
    distinct (encounter_id, panel_key, ordered_datetime) tuple. Stand-alone
    Orders are not indexed (their SR id uses order_id directly).

    Deterministic: input Orders are sorted by (encounter_id, panel_key,
    ordered_datetime) before assigning N.

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). ``ordered_datetime`` may be a ``datetime`` object
    or an ISO-string; both are hashable and consistent within a single run.
    """
    counter: dict[tuple[str, str, Any], int] = {}
    panel_orders = [o for o in orders if _o(o, "panel_key", "")]
    panel_orders_sorted = sorted(
        panel_orders,
        key=lambda o: (
            str(_o(o, "encounter_id", "")),
            str(_o(o, "panel_key", "")),
            str(_o(o, "ordered_datetime", "")),
        ),
    )
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for o in panel_orders_sorted:
        key = (_o(o, "encounter_id", ""), _o(o, "panel_key", ""), _o(o, "ordered_datetime"))
        if key not in counter:
            scope = (_o(o, "encounter_id", ""), _o(o, "panel_key", ""))
            seen[scope] += 1
            counter[key] = seen[scope]
    return counter


def order_to_sr_id(
    order: Any,
    panel_counter: dict[tuple[str, str, Any], int],
) -> str:
    """Compute ServiceRequest.id for an Order (deterministic, stateless).

    Stand-alone: ``sr-{order_id}``.
    Panel: ``sr-{encounter_id}-{panel_key}-{N}`` where N from panel_counter.

    Accepts both Order dataclass instances and JSON-deserialized dicts.
    """
    panel_key = _o(order, "panel_key", "")
    if panel_key:
        enc_id = _o(order, "encounter_id", "")
        dt = _o(order, "ordered_datetime")
        idx = panel_counter[(enc_id, panel_key, dt)]
        return f"{SR_ID_PREFIX}{enc_id}-{panel_key}-{idx}"
    return f"{SR_ID_PREFIX}{_o(order, 'order_id', '')}"


def _bb_service_requests(ctx: BundleContext) -> list[dict[str, Any]]:
    """Builder entry point — emit ServiceRequest resources for LAB orders.

    Returns a list of raw FHIR ServiceRequest resources to be appended to
    the per-resource NDJSON files by ``_build_bundle``.

    Accepts both Order dataclass instances (test/direct-object path) and
    JSON-deserialized dicts (production CIF path via json.load).
    """
    orders: list[Any] = ctx.record.get("orders", []) or []
    lab_orders = [
        o for o in orders
        if _o(o, "order_type") in (OrderType.LAB, "lab")
    ]
    if not lab_orders:
        return []

    counter = build_panel_counter(lab_orders)
    panels = load_panel_definitions()
    country = ctx.country.lower()
    lang = "ja" if country == "jp" else "en"

    # Group panel orders by SR id; stand-alone Orders emit 1 SR each.
    panel_buckets: dict[str, list[Any]] = defaultdict(list)
    standalone_orders: list[Any] = []
    for o in lab_orders:
        if _o(o, "panel_key", ""):
            panel_buckets[order_to_sr_id(o, counter)].append(o)
        else:
            standalone_orders.append(o)

    resources: list[dict[str, Any]] = []
    for sr_id, members in sorted(panel_buckets.items()):
        anchor = members[0]
        panel_def = panels[_o(anchor, "panel_key", "")]
        sr = _build_panel_sr(sr_id, anchor, members, panel_def, lang)
        resources.append(sr)
    for o in standalone_orders:
        sr = _build_standalone_sr(o, lang)
        resources.append(sr)
    return resources


def _build_panel_sr(
    sr_id: str,
    anchor: Any,
    members: list[Any],
    panel_def: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
    """Build one ServiceRequest resource for a panel (all members share the SR).

    Accepts both Order dataclass instances and JSON-deserialized dicts.
    """
    panel_loinc = panel_def["loinc"]
    panel_display = code_lookup("loinc", panel_loinc, lang) or panel_def.get("display", "")
    placer_value = sr_id[len(SR_ID_PREFIX):]  # strip "sr-" prefix
    status = aggregate_panel_status(members)
    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(_o(anchor, "urgency", "routine"), "routine"),
        loinc_code=panel_loinc,
        loinc_display=panel_display,
        loinc_text=_o(anchor, "panel_key", ""),
        anchor=anchor,
        lang=lang,
    )


def _build_standalone_sr(o: Any, lang: str) -> dict[str, Any]:
    """Build one ServiceRequest resource for a stand-alone test.

    Accepts both Order dataclass instances and JSON-deserialized dicts.
    """
    order_id = _o(o, "order_id", "")
    sr_id = f"{SR_ID_PREFIX}{order_id}"
    placer_value = order_id
    status = aggregate_panel_status([o])
    order_code = _o(o, "order_code", "")
    display_name = _o(o, "display_name", "")
    loinc_display = code_lookup("loinc", order_code, lang) or display_name
    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(_o(o, "urgency", "routine"), "routine"),
        loinc_code=order_code,
        loinc_display=loinc_display,
        loinc_text=display_name,
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
    anchor: Any,
    lang: str,
) -> dict[str, Any]:
    """Shared SR resource skeleton for panel + stand-alone.

    Accepts both Order dataclass instances and JSON-deserialized dicts.
    ``anchor.ordered_datetime`` may be a ``datetime`` object or an ISO string.
    """
    snomed_display = code_lookup("snomed-ct", LAB_CATEGORY_SNOMED, lang) or (
        "臨床検査" if lang == "ja" else "Laboratory procedure"
    )
    # ordered_datetime may arrive as a datetime object (dataclass path) or an
    # ISO string (JSON-deserialized dict path).
    dt = _o(anchor, "ordered_datetime")
    authored_on: str = dt if isinstance(dt, str) else dt.isoformat()

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
        "subject": {"reference": f"Patient/{_o(anchor, 'patient_id', '')}"},
        "encounter": {"reference": f"Encounter/{_o(anchor, 'encounter_id', '')}"},
        "authoredOn": authored_on,
    }
    ordered_by = _o(anchor, "ordered_by", "")
    if ordered_by:
        sr["requester"] = {"reference": f"Practitioner/{ordered_by}"}
    clinical_intent = _o(anchor, "clinical_intent", "")
    if clinical_intent:
        sr["reasonCode"] = [{"text": clinical_intent}]
    return sr
