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
from pathlib import Path
from typing import NamedTuple

import yaml


_PANEL_REF = Path(__file__).parent / "reference_data" / "lab_panel_groups.yaml"
_PANELS_CACHE: dict[str, dict] | None = None


def load_panel_groups() -> dict[str, dict]:
    """Return the panel definitions from lab_panel_groups.yaml (cached).

    Key order matches the YAML insertion order, which is the grouping
    priority (ABG > CBC > BMP > LFT > Lipid > Coag > UA).
    """
    global _PANELS_CACHE
    if _PANELS_CACHE is None:
        with open(_PANEL_REF) as f:
            data = yaml.safe_load(f) or {}
        _PANELS_CACHE = data.get("panels") or {}
    return _PANELS_CACHE


class _GroupedPanel(NamedTuple):
    panel_name: str
    bucket: str            # "YYYY-MM-DDTHH:MM"
    obs_refs: list[str]    # Observation ids in YAML-component order


def group_lab_orders(orders: list[dict], encounter_id: str) -> list[_GroupedPanel]:
    """Group lab orders into panel DiagnosticReport candidates.

    For each lab order with a result, derive (analyte_name, bucket, obs_id).
    Then per minute-bucket, iterate panels in priority order; for each
    panel collect any matching analyte that has not already been consumed
    by a higher-priority panel at the same bucket. If at least
    ``min_components`` are matched (and, when ``skip_if_no_components_present``
    is set, at least one component was present), emit a ``_GroupedPanel``.

    Returns groups sorted by (bucket ascending, panel-priority order).
    """
    panels = load_panel_groups()

    # Build: bucket -> lab_name -> [obs_ref]. Multiple obs per (bucket, name) is
    # possible if the same analyte is drawn twice within a minute (rare).
    by_bucket: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for idx, order in enumerate(orders):
        if order.get("order_type") != "lab":
            continue
        result = order.get("result")
        if not result:
            continue
        when = (result.get("result_datetime") or "")[:16]
        if len(when) < 16:
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
