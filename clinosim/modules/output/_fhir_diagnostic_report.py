"""FHIR DiagnosticReport panel grouping (AD-56 builder).

Post-hoc grouping of lab Observations into DiagnosticReport resources at
emit time. Pure function over the CIF orders list: no RNG, no CIF schema
read, no Observation-resource mutation. The bundle builder appends new
``dr-{panel}-{enc}-{seq}`` DRs after the existing microbiology ``dr-mb-*``
DRs.

Spec: docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md

Panel YAML + canonical loader live in ``clinosim.modules.order.panel_grouping``
(single source of truth per user directive: "データ参照やデータ生成のロジックは統一").
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, NamedTuple

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as _codes_lookup
from clinosim.modules._shared import get_attr_or_key
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output._fhir_service_request import (
    build_panel_counter,
    order_to_sr_id,
)
from clinosim.types.encounter import OrderType


def _o(obj: Any, name: str, default: Any = None) -> Any:
    """Dual-access helper: dataclass attribute OR dict key (production path)."""
    return get_attr_or_key(obj, name, default)


class _GroupedPanel(NamedTuple):
    panel_name: str
    bucket: str            # "YYYY-MM-DD" (day-resolution; see group_lab_orders)
    obs_refs: list[str]    # Observation ids in YAML-component order


def group_lab_orders(orders: list[Any], encounter_id: str) -> list[_GroupedPanel]:
    """Group lab orders into panel DiagnosticReport candidates.

    For each lab order with a result, derive (analyte_name, bucket, obs_id).
    Then per day-bucket, iterate panels in priority order; for each
    panel collect any matching analyte that has not already been consumed
    by a higher-priority panel at the same bucket. If at least
    ``min_components`` are matched (and, when ``skip_if_no_components_present``
    is set, at least one component was present), emit a ``_GroupedPanel``.

    Day-resolution bucket (YYYY-MM-DD) is the right granularity here: the
    clinosim lab generator randomizes per-component ``result_datetime`` even
    inside one panel order (ABG components from a single order may span
    multiple hours), so a minute- or hour-bucket would group almost nothing.
    Repeat draws on the same day (e.g. q4-6h BMP in DKA) collapse into one
    DR per panel per day — the FHIR DR result[] just grows accordingly. The
    DR's effectiveDateTime is reported as a date-only value (FHIR R4 allows
    partial-precision dateTime).

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). Uses _o() for dual dict/dataclass field access.

    Returns groups sorted by (bucket ascending, panel-priority order).
    """
    panels = load_panel_definitions()

    # Build: bucket -> lab_name -> [obs_ref]. Same analyte drawn multiple times
    # in a day (e.g. serial Cr) accumulates multiple refs; the first uncomsumed
    # ref per panel-component is used (see consume loop below).
    by_bucket: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for idx, order in enumerate(orders):
        ot = _o(order, "order_type")
        if ot not in (OrderType.LAB, "lab"):
            continue
        result = _o(order, "result")
        if not result:
            continue
        # result_datetime may be a datetime object (dataclass) or ISO string (dict).
        dt_raw = _o(result, "result_datetime")
        when = str(dt_raw)[:10] if dt_raw else ""
        if len(when) < 10:
            continue
        lab_name = _o(result, "lab_name") or _o(order, "display_name") or ""
        if not lab_name:
            continue
        obs_id = f"lab-{encounter_id}-{idx:04d}"
        by_bucket[when][lab_name].append(obs_id)

    groups: list[_GroupedPanel] = []
    for bucket in sorted(by_bucket.keys()):
        consumed: set[str] = set()
        for panel_name, panel in panels.items():
            components: list[str] = panel["components"]
            min_required: int = panel["min_components"]
            skip_if_empty: bool = bool(panel.get("skip_if_no_components_present"))

            present_count = 0
            obs_refs: list[str] = []
            for comp in components:
                refs = by_bucket[bucket].get(comp, [])
                for ref in refs:
                    if ref in consumed:
                        continue
                    obs_refs.append(ref)
                    consumed.add(ref)
                    present_count += 1
                    break
            if skip_if_empty and present_count == 0:
                continue
            if present_count < min_required:
                # Release partially-consumed refs so a later panel can grab them.
                for ref in obs_refs:
                    consumed.discard(ref)
                continue
            groups.append(_GroupedPanel(
                panel_name=panel_name, bucket=bucket, obs_refs=obs_refs,
            ))
    return groups


# ----------------------------------------------------------------------------
# FHIR resource construction
# ----------------------------------------------------------------------------

_CATEGORY_LAB_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0074"


def build_dr_resource(
    group: _GroupedPanel,
    patient_id: str,
    encounter_id: str,
    country: str,
    performer_ref: str | None,
    issued: str | None,
    seq: int,
) -> dict:
    """Build a single FHIR DiagnosticReport resource for a grouped panel.

    Args:
      group: a _GroupedPanel from group_lab_orders().
      patient_id: CIF patient id (becomes Patient/{patient_id} subject).
      encounter_id: CIF encounter id (becomes Encounter/{encounter_id}).
      country: "US" or "JP" — selects English vs Japanese LOINC display.
      performer_ref: optional FHIR-shaped reference (e.g. "Practitioner/TECH-LAB-001").
      issued: optional ISO timestamp of report issuance; if None, omitted.
      seq: encounter-scoped sequence number for id uniqueness when the
        same panel emits at multiple draw-times.

    Returns: a raw FHIR resource dict (no Bundle envelope).
    """
    panels = load_panel_definitions()
    panel = panels[group.panel_name]
    lang = "ja" if country == "JP" else "en"
    display = _codes_lookup("loinc", panel["loinc"], lang) or panel["display"]

    res: dict[str, object] = {
        "resourceType": "DiagnosticReport",
        "id": f"dr-{group.panel_name.lower()}-{encounter_id}-{seq}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": _CATEGORY_LAB_SYSTEM,
                "code": "LAB",
                "display": "Laboratory",
            }],
        }],
        "code": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": panel["loinc"],
                "display": display,
            }],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        # group.bucket is YYYY-MM-DD; FHIR R4 dateTime allows date-only precision.
        "effectiveDateTime": group.bucket,
        "result": [{"reference": f"Observation/{ref}"} for ref in group.obs_refs],
    }
    if issued:
        res["issued"] = issued
    if performer_ref:
        res["performer"] = [{"reference": performer_ref}]
    return res


def _sr_ids_for_group(
    group: _GroupedPanel,
    orders: list[Any],
    lab_orders: list[Any],
    panel_counter: dict,
    enc_id: str,
) -> list[str]:
    """Derive ServiceRequest ids for the contributing Orders of a panel group.

    obs_refs in a _GroupedPanel use the format ``lab-{enc_id}-{idx:04d}`` where
    ``idx`` is the 0-based position in the full ``orders`` list passed to
    ``group_lab_orders``.  We extract those indices to look up the exact Order
    objects, then derive their SR ids deterministically.  This handles both panel
    orders (panel_key set → SR id = sr-{enc}-{panel}-N) and stand-alone orders
    (panel_key="" → SR id = sr-{order_id}) without any panel_key filter that
    would silently miss stand-alone tests grouped into a panel DR.
    """
    prefix = f"lab-{enc_id}-"
    contributing: list[Any] = []
    for obs_id in group.obs_refs:
        if not obs_id.startswith(prefix):
            continue
        try:
            idx = int(obs_id[len(prefix):])
        except ValueError:
            continue
        if 0 <= idx < len(orders):
            contributing.append(orders[idx])
    return sorted({order_to_sr_id(o, panel_counter) for o in contributing})


def build_lab_panel_reports(ctx) -> list[dict]:
    """Bundle builder (AD-56): group ctx.record["orders"] into DR resources.

    Returns DRs in (bucket, panel-priority) order so the NDJSON output is
    stable across runs. Each DR carries ``basedOn`` referencing the
    ServiceRequest(s) for the contributing Orders (PR1: consistent
    writer↔reader derivation via build_panel_counter + order_to_sr_id).

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). Uses _o() for dual dict/dataclass field access.
    """
    orders = ctx.record.get("orders", []) or []
    enc_id = ctx.primary_enc_id or ""
    if not enc_id:
        return []

    # Collect lab orders with dual-access type check (dict + dataclass).
    lab_orders = [
        o for o in orders
        if _o(o, "order_type") in (OrderType.LAB, "lab")
    ]

    # Pre-compute panel counter once — same derivation as _bb_service_requests
    # so the SR ids produced here match those emitted in ServiceRequest.ndjson.
    panel_counter = build_panel_counter(lab_orders)

    groups = group_lab_orders(orders, enc_id)
    seq_by_panel: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    for g in groups:
        seq = seq_by_panel[g.panel_name]
        seq_by_panel[g.panel_name] = seq + 1
        report = build_dr_resource(
            g, ctx.patient_id, enc_id, ctx.country,
            performer_ref=None, issued=None, seq=seq,
        )
        # basedOn: look up contributing orders via the obs_id index embedded in
        # each obs_ref ("lab-{enc_id}-{idx:04d}").  This handles both panel orders
        # (panel_key set) and stand-alone orders (panel_key="") — either way the
        # SR id is derived correctly via order_to_sr_id + panel_counter.
        sr_ids = _sr_ids_for_group(g, orders, lab_orders, panel_counter, enc_id)
        report["basedOn"] = [{"reference": f"ServiceRequest/{sid}"} for sid in sr_ids]
        out.append(report)
    return out
