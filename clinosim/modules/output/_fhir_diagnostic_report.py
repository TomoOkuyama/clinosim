"""FHIR DiagnosticReport panel grouping (AD-56 builder).

Post-hoc grouping of lab Observations into DiagnosticReport resources at
emit time. Pure function over the CIF orders list: no RNG, no CIF schema
read, no Observation-resource mutation. The bundle builder appends new
``dr-{panel}-{enc}-{seq}`` DRs after the existing microbiology ``dr-mb-*``
DRs.

Spec: docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import yaml

from clinosim.codes import get_system_uri, lookup as _codes_lookup


_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_PANEL_REF = _REF_DIR / "lab_panel_groups.yaml"


@lru_cache(maxsize=1)
def load_panel_groups() -> dict[str, dict]:
    """Return the panel definitions from lab_panel_groups.yaml (cached).

    Key order matches the YAML insertion order, which is the grouping
    priority (ABG > CBC > BMP > LFT > Lipid > Coag > UA).
    """
    with open(_PANEL_REF) as f:
        data = yaml.safe_load(f) or {}
    return data.get("panels") or {}


class _GroupedPanel(NamedTuple):
    panel_name: str
    bucket: str            # "YYYY-MM-DD" (day-resolution; see group_lab_orders)
    obs_refs: list[str]    # Observation ids in YAML-component order


def group_lab_orders(orders: list[dict], encounter_id: str) -> list[_GroupedPanel]:
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

    Returns groups sorted by (bucket ascending, panel-priority order).
    """
    panels = load_panel_groups()

    # Build: bucket -> lab_name -> [obs_ref]. Same analyte drawn multiple times
    # in a day (e.g. serial Cr) accumulates multiple refs; the first uncomsumed
    # ref per panel-component is used (see consume loop below).
    by_bucket: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for idx, order in enumerate(orders):
        if order.get("order_type") != "lab":
            continue
        result = order.get("result")
        if not result:
            continue
        when = (result.get("result_datetime") or "")[:10]
        if len(when) < 10:
            continue
        lab_name = result.get("lab_name") or order.get("display_name") or ""
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
    panels = load_panel_groups()
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


def build_lab_panel_reports(ctx) -> list[dict]:
    """Bundle builder (AD-56): group ctx.record["orders"] into DR resources.

    Returns DRs in (bucket, panel-priority) order so the NDJSON output is
    stable across runs.
    """
    orders = ctx.record.get("orders", []) or []
    enc_id = ctx.primary_enc_id or ""
    if not enc_id:
        return []
    groups = group_lab_orders(orders, enc_id)
    seq_by_panel: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    for g in groups:
        seq = seq_by_panel[g.panel_name]
        seq_by_panel[g.panel_name] = seq + 1
        out.append(build_dr_resource(
            g, ctx.patient_id, enc_id, ctx.country,
            performer_ref=None, issued=None, seq=seq,
        ))
    return out
