"""Drug-name → HomeMedication resolver.

Phase 4a Task 3: when the longitudinal engine's event pattern fires a
med-emitting event (e.g. SGLT2i / basal-insulin escalation), it declares
drug names (``emits_meds: list[str]``) rather than full metadata. This
resolver maps a drug name to a ``HomeMedication`` carrying dose / route /
frequency pulled from ``chronic_medications.yaml`` — the single source of
truth for home-med metadata.

Event specs reference drugs by catalog ``drug_id`` and are validated when
loaded, so a missing entry fails at load instead of producing a silent
oral default (Issue #2292).
"""

from __future__ import annotations

from functools import cache
from typing import Any

from clinosim.locale.loader import load_chronic_medications
from clinosim.types.patient import HomeMedication


@cache
def resolve_med_name(drug_ref: str) -> HomeMedication:
    """Return a HomeMedication for ``drug_ref`` from ``chronic_medications.yaml``.

    ``drug_ref`` is a catalog drug_id or a catalog name / alias, matched
    case-insensitively through :func:`clinosim.codes.drugs.find_drug`
    (Issue #2292: an exact, case-sensitive name match used to miss
    "Insulin glargine" and fall back to an oral, dose-less default).
    Legacy entries without a ``drug_id`` are matched by their ``drug`` field.

    Raises ``KeyError`` when no entry exists; event specs are validated at
    load (``EventSpec``) so this does not happen during generation.
    """
    from clinosim.codes.drugs import find_drug

    rec = find_drug(drug_ref)
    data = load_chronic_medications()
    for icd_block in _iter_icd_blocks(data):
        meds = icd_block.get("medications") if isinstance(icd_block, dict) else None
        if not isinstance(meds, list):
            continue
        for entry in meds:
            if not isinstance(entry, dict):
                continue
            drug_id = entry.get("drug_id") or ""
            if drug_id:
                if rec is None or rec.drug_id != drug_id:
                    continue
                return HomeMedication(
                    drug_name=rec.names.get("en", ""),
                    drug_name_ja=rec.names.get("ja", ""),
                    route=str(entry.get("route", "PO")),
                    dose=str(entry.get("dose", "")),
                    frequency=str(entry.get("frequency", "daily")),
                )
            # Legacy entry (drug_id absent — Rivaroxaban dose-embedded,
            # Tegafur-Gimeracil-Oteracil combo). Match by legacy drug field.
            if entry.get("drug") == drug_ref:
                return HomeMedication(
                    drug_name=str(entry["drug"]),
                    drug_name_ja=str(entry.get("drug_ja", "")),
                    route=str(entry.get("route", "PO")),
                    dose=str(entry.get("dose", "")),
                    frequency=str(entry.get("frequency", "daily")),
                )
    raise KeyError(f"resolve_med_name: {drug_ref!r} has no chronic_medications.yaml entry")


def _iter_icd_blocks(data: Any) -> list[dict]:
    """Walk the chronic_medications.yaml top-level dict; yield each ICD
    block value (``{medications: [...], monitoring: [...], ...}``)."""
    if not isinstance(data, dict):
        return []
    return [v for v in data.values() if isinstance(v, dict)]
