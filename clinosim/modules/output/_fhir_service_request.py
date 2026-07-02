"""ServiceRequest FHIR R4 builder (PR1: lab + imaging orders).

Reads CIF Orders (with ``order_type=OrderType.LAB`` and Order.panel_key
populated by the order engine), emits one ServiceRequest per panel
instance (4 CBC tests → 1 SR) and one per stand-alone Order. Panel SR
uses the LOINC panel code (58410-2 for CBC etc.) sourced from
``lab_panel_groups.yaml``; stand-alone uses Order.order_code (individual
LOINC for the analyte).

For IMAGING orders, emits one ServiceRequest per Order (1 Order = 1 SR;
multi-series is handled on the ImagingStudy side). Category uses SNOMED
363679005 + HL7 v2-0074 RAD dual coding (AD-46). bodySite is populated
from Order.imaging_body_site_code (SNOMED).

Compliance:
- US Core ServiceRequest profile (LAB category via SNOMED 108252007;
  Imaging category via SNOMED 363679005).
- JP Core ServiceRequest profile (placerOrderNumber via v2-0203 PLAC
  identifier.type.coding).
- Status aggregation rule (panel SR): any non-terminal member → active;
  all CANCELLED/STOPPED → revoked; otherwise (all terminal, at least one
  RESULTED/REVIEWED) → completed.
- Imaging SR status: 1:1 mapping (PLACED/ACCEPTED/IN_PROGRESS → active;
  CANCELLED/STOPPED → revoked; otherwise → completed).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import get_attr_or_key, is_jp, resolve_lang
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.types.encounter import OrderStatus, OrderType

# === Canonical constants (silent-no-op defense, PR-90 lesson) ===
SR_ID_PREFIX = "sr-"
PLACER_ORDER_NUMBER_SYSTEM = "urn:clinosim:placer-order-number"
LAB_CATEGORY_SNOMED = "108252007"
LAB_CATEGORY_V2_0074 = "LAB"
# === Imaging category constants (Tier 1 #2 PR1) ===
# SNOMED CT 363679005 "Imaging procedure" — owner: this file (builder that emits imaging SRs).
IMAGING_CATEGORY_SNOMED = "363679005"
# HL7 v2-0074 "Radiology" — owner: this file.
IMAGING_CATEGORY_V2_0074 = "RAD"
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
    assert member_orders, (
        "aggregate_panel_status: member_orders must be non-empty. "
        "Stand-alone callers pass [o] (single-element list); panel callers always "
        "have ≥1 member — empty list is a caller bug."
    )
    statuses = {_status_value(_o(o, "status")) for o in member_orders}
    # Treat None/unknown status (normalised to "") as non-terminal — conservative:
    # an unresolvable status should not be classified as terminal.
    if "" in statuses or statuses & _NON_TERMINAL_STATUSES:
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
    """Builder entry point — emit ServiceRequest resources for LAB + IMAGING orders.

    Polymorphic dispatch (Tier 1 #2 PR1):
    - LAB orders  → panel-aware grouping (existing PR1 path, unchanged).
    - IMAGING orders → 1 Order = 1 SR (multi-series handled by ImagingStudy).

    Returns a list of raw FHIR ServiceRequest resources to be appended to
    the per-resource NDJSON files by ``_build_bundle``.

    Accepts both Order dataclass instances (test/direct-object path) and
    JSON-deserialized dicts (production CIF path via json.load).
    """
    orders: list[Any] = ctx.record.get("orders", []) or []
    resources: list[dict[str, Any]] = []

    lab_orders = [o for o in orders if _o(o, "order_type") in (OrderType.LAB, "lab")]
    if lab_orders:
        resources.extend(_build_lab_service_requests(lab_orders, ctx))

    imaging_orders = [
        o for o in orders if _o(o, "order_type") in (OrderType.IMAGING, "imaging")
    ]
    if imaging_orders:
        resources.extend(_build_imaging_service_requests(imaging_orders, ctx))

    return resources


def _build_lab_service_requests(lab_orders: list[Any], ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit ServiceRequest resources for LAB orders (PR1 panel-aware path).

    Extracted from the original ``_bb_service_requests`` body — logic unchanged.
    Accepts both Order dataclass instances and JSON-deserialized dicts.
    """
    counter = build_panel_counter(lab_orders)
    panels = load_panel_definitions()
    country = ctx.country.lower()
    lang = resolve_lang(country)

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
    for o in sorted(standalone_orders, key=lambda x: _o(x, "order_id", "")):
        sr = _build_standalone_sr(o, lang, country)
        resources.append(sr)
    return resources


def _map_order_status_to_sr_status(status: Any) -> str:
    """Map OrderStatus → SR.status for imaging (1:1 Order:SR, no aggregation).

    Imaging SRs use simple 1:1 status mapping (unlike LAB panel SRs which
    aggregate member statuses). Rule mirrors aggregate_panel_status but
    operates on a single Order status value.

    Accepts both OrderStatus enum instances (dataclass path) and plain
    strings (JSON-deserialized dict path).
    """
    s = _status_value(status)
    if s in _NON_TERMINAL_STATUSES or s == "":
        return "active"
    if s in _CANCELLED_STATUSES:
        return "revoked"
    return "completed"


def _build_imaging_service_requests(orders: list[Any], ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one ServiceRequest per IMAGING Order.

    1 Order = 1 SR. Multi-series imaging (e.g. PA + Lateral CXR) is
    modelled as multiple ImagingSeries under one ImagingStudy — the SR
    references the study as a whole, not individual series.

    Accepts both Order dataclass instances and JSON-deserialized dicts.
    """
    lang = resolve_lang(ctx.country)
    country = ctx.country.lower()
    return [
        _build_imaging_sr(o, lang, country)
        for o in sorted(orders, key=lambda x: _o(x, "order_id", ""))
    ]


def _build_imaging_sr(order: Any, lang: str, country: str) -> dict[str, Any]:
    """Build one ServiceRequest resource for an IMAGING Order.

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). Uses ``_o()`` for dual field access.

    category: SNOMED 363679005 + HL7 v2-0074 RAD (AD-46 dual coding).
    bodySite: SNOMED from imaging_body_site_code.
    code: LOINC from order_code with display from body_sites.yaml when
      the code is not in clinosim/codes/data/loinc.yaml (imaging LOINC
      codes have limited ja entries; body_sites.yaml carries authoritative
      display_ja / display_en for the supported procedure+modality combos).
    """
    # Lazy import avoids circular dependency at module level.
    from clinosim.modules.imaging.engine import load_body_sites

    sr_id = f"{SR_ID_PREFIX}{_o(order, 'order_id', '')}"
    body_sites = load_body_sites()
    body_site_snomed = _o(order, "imaging_body_site_code", "")
    loinc_code = _o(order, "order_code", "")

    body_site_display = ""
    proc_display_from_bs = ""
    for bs_def in body_sites.values():
        if bs_def["snomed"] == body_site_snomed:
            body_site_display = bs_def.get(f"display_{lang}") or bs_def["display_en"]
            # Also try to find procedure display from procedure_codes for this
            # body site — exact LOINC match preferred; first entry as fallback.
            for pc in bs_def.get("procedure_codes", {}).values():
                if pc.get("loinc") == loinc_code:
                    proc_display_from_bs = pc.get(f"display_{lang}") or pc["display_en"]
                    break
            if not proc_display_from_bs:
                # Fallback: first procedure_codes entry for this body site + lang.
                for pc in bs_def.get("procedure_codes", {}).values():
                    proc_display_from_bs = pc.get(f"display_{lang}") or pc["display_en"]
                    break
            break

    # Display resolution: LOINC lookup → body_sites procedure display → Order.display_name.
    # For imaging LOINC codes not in clinosim/codes/data/loinc.yaml, the lookup
    # returns the code itself (not a meaningful display); body_sites.yaml is more
    # authoritative for the supported (modality, body_site) combos.
    raw_loinc_display = code_lookup("loinc", loinc_code, lang)
    loinc_display = (
        raw_loinc_display
        if (raw_loinc_display and raw_loinc_display != loinc_code)
        else (proc_display_from_bs or _o(order, "display_name", ""))
    )

    snomed_imaging_display = code_lookup("snomed-ct", IMAGING_CATEGORY_SNOMED, lang) or (
        "画像診断" if lang == "ja" else "Imaging procedure"
    )

    # Fail-loud on empty subject/encounter (PR-90 lesson: "Patient/" is FHIR-invalid).
    patient_id = _o(order, "patient_id", "")
    encounter_id_val = _o(order, "encounter_id", "")
    assert patient_id, f"_build_imaging_sr: patient_id must be non-empty (sr_id={sr_id!r})"
    assert encounter_id_val, f"_build_imaging_sr: encounter_id must be non-empty (sr_id={sr_id!r})"

    sr: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": sr_id,
        "identifier": [{
            "type": {
                "coding": [{
                    "system": V2_0203_SYSTEM,
                    "code": "PLAC",
                    "display": "Placer Identifier",
                }],
            },
            "system": PLACER_ORDER_NUMBER_SYSTEM,
            "value": _o(order, "order_id", ""),
        }],
        "status": _map_order_status_to_sr_status(_o(order, "status")),
        "intent": "order",
        "category": [{
            "coding": [
                {
                    "system": SNOMED_CT_SYSTEM,
                    "code": IMAGING_CATEGORY_SNOMED,
                    "display": snomed_imaging_display,
                },
                {
                    "system": V2_0074_SYSTEM,
                    "code": IMAGING_CATEGORY_V2_0074,
                    "display": "Radiology",
                },
            ],
        }],
        "priority": _PRIORITY_MAP.get(_o(order, "urgency", "routine"), "routine"),
        "code": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": loinc_code,
                "display": loinc_display,
            }],
            "text": _o(order, "display_name", ""),
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id_val}"},
    }

    # bodySite: emit when imaging_body_site_code is populated.
    if body_site_snomed:
        sr["bodySite"] = [{
            "coding": [{
                "system": SNOMED_CT_SYSTEM,
                "code": body_site_snomed,
                "display": body_site_display,
            }],
        }]

    # Optional fields
    dt = _o(order, "ordered_datetime")
    if dt is not None:
        sr["authoredOn"] = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
    ordered_by = _o(order, "ordered_by", "")
    if ordered_by:
        sr["requester"] = {"reference": f"Practitioner/{ordered_by}"}
    clinical_intent = _o(order, "clinical_intent", "")
    if clinical_intent:
        sr["reasonCode"] = [{"text": clinical_intent}]
    return sr


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


def _build_standalone_sr(o: Any, lang: str, country: str) -> dict[str, Any]:
    """Build one ServiceRequest resource for a stand-alone test.

    Applies the same internal-name → standard-code resolution as
    ``_build_lab_observation``: looks up ``display_name`` in the locale
    code mapping (code_mapping_lab.yaml) so that an order whose
    ``order_code`` is an internal test name (e.g. ``"WBC"``) resolves to
    the real LOINC / JLAC10 code (e.g. ``"6690-2"``).

    Accepts both Order dataclass instances and JSON-deserialized dicts.
    """
    order_id = _o(o, "order_id", "")
    sr_id = f"{SR_ID_PREFIX}{order_id}"
    placer_value = order_id
    status = aggregate_panel_status([o])
    raw_code = _o(o, "order_code", "")
    display_name = _o(o, "display_name", "")

    # Resolve internal test name → real standard code via locale mapping.
    # Mirrors _build_lab_observation (code_map.get(lab_name, order_code)).
    # country arrives lowercase ("us"/"jp"); load_code_mapping expects uppercase.
    country_code = "JP" if is_jp(country) else "US"
    code_map = load_code_mapping("lab", country_code)
    resolved_code = code_map.get(display_name)
    # Two-tier fallback: when JP map missing entry, try LOINC (US) map.
    if not resolved_code and is_jp(country_code):
        us_map = load_code_mapping("lab", "US")
        resolved_code = us_map.get(display_name)
    resolved_code = resolved_code or raw_code

    # Display text comes from the code system (LOINC for US, JLAC10 for JP).
    code_system_key = system_key_for("lab", country_code)
    loinc_display = code_lookup(code_system_key, resolved_code, lang) or display_name
    if loinc_display == resolved_code:  # no translation found
        loinc_display = display_name

    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(_o(o, "urgency", "routine"), "routine"),
        loinc_code=resolved_code,
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
    # Fail-loud on empty subject/encounter — "Patient/" is FHIR-invalid (PR-90 lesson).
    patient_id = _o(anchor, "patient_id", "")
    encounter_id_val = _o(anchor, "encounter_id", "")
    assert patient_id, (
        f"_build_sr_skeleton: patient_id must be non-empty (sr_id={sr_id!r})"
    )
    assert encounter_id_val, (
        f"_build_sr_skeleton: encounter_id must be non-empty (sr_id={sr_id!r})"
    )

    snomed_display = code_lookup("snomed-ct", LAB_CATEGORY_SNOMED, lang) or (
        "臨床検査" if lang == "ja" else "Laboratory procedure"
    )
    # ordered_datetime may arrive as a datetime object (dataclass path) or an
    # ISO string (JSON-deserialized dict path). If None, authoredOn is omitted.
    dt = _o(anchor, "ordered_datetime")
    if dt is None:
        authored_on = ""
    elif isinstance(dt, str):
        authored_on = dt
    else:
        authored_on = dt.isoformat()

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
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id_val}"},
    }
    if authored_on:
        sr["authoredOn"] = authored_on
    ordered_by = _o(anchor, "ordered_by", "")
    if ordered_by:
        sr["requester"] = {"reference": f"Practitioner/{ordered_by}"}
    clinical_intent = _o(anchor, "clinical_intent", "")
    if clinical_intent:
        sr["reasonCode"] = [{"text": clinical_intent}]
    return sr
