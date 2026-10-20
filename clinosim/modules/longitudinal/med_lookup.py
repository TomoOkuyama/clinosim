"""Drug-name → HomeMedication resolver.

Phase 4a Task 3: when the longitudinal engine's event pattern fires a
med-emitting event (e.g. SGLT2i / basal-insulin escalation), it declares
drug names (``emits_meds: list[str]``) rather than full metadata. This
resolver maps a drug name to a ``HomeMedication`` carrying dose / route /
frequency pulled from ``chronic_medications.yaml`` — the single source of
truth for home-med metadata.

On miss (yaml authoring gap), returns a sensible default
``HomeMedication(drug_name=name, route="PO", frequency="daily")`` rather
than crashing — a yaml drift that would otherwise take down an entire
cohort generation.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from clinosim.locale.loader import load_chronic_medications
from clinosim.types.patient import HomeMedication


@cache
def resolve_med_name(drug_name: str) -> HomeMedication:
    """Return a HomeMedication for ``drug_name`` by looking up the first
    matching ``drug:`` entry in ``chronic_medications.yaml``.

    Lookup is cached (unbounded) — the yaml itself is small and the set
    of distinct drug names is bounded by the yaml's own entries.
    """
    data = load_chronic_medications()
    for icd_block in _iter_icd_blocks(data):
        meds = icd_block.get("medications") if isinstance(icd_block, dict) else None
        if not isinstance(meds, list):
            continue
        for entry in meds:
            if not isinstance(entry, dict):
                continue
            if entry.get("drug") == drug_name:
                return HomeMedication(
                    drug_name=str(entry["drug"]),
                    drug_name_ja=str(entry.get("drug_ja", "")),
                    route=str(entry.get("route", "PO")),
                    dose=str(entry.get("dose", "")),
                    frequency=str(entry.get("frequency", "daily")),
                )
    return HomeMedication(drug_name=drug_name, route="PO", frequency="daily")


def _iter_icd_blocks(data: Any) -> list[dict]:
    """Walk the chronic_medications.yaml top-level dict; yield each ICD
    block value (``{medications: [...], monitoring: [...], ...}``)."""
    if not isinstance(data, dict):
        return []
    return [v for v in data.values() if isinstance(v, dict)]
