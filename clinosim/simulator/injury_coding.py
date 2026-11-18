"""Coding of an injury admission from the disease YAML (Issue #3258).

Three facts follow the stay's own identity, never the master RNG stream:

* the sampled injury diagnosis (``icd_codes.sample_variants`` with the weights
  of ``icd_codes.variants``), drawn from a SHA of the encounter id;
* the surgery the diagnosis calls for (``procedure.by_diagnosis``: a different
  operation, or none, per diagnosis and severity);
* the secondary external-cause code (``external_cause.<country slot>``), drawn
  from a SHA of the encounter id; a country without a list records none.
"""

from __future__ import annotations

from typing import Any

from clinosim import determinism
from clinosim.countries import country_slot

NO_SURGERY = "none"


def stay_primary_code(protocol: Any, encounter_id: str) -> str:
    """The primary ICD code of the stay: the protocol's ``icd_codes.primary``, or
    one of its weighted ``variants`` when ``sample_variants`` is set."""
    icd = getattr(protocol, "icd_codes", None) or {}
    primary = str(icd.get("primary") or "")
    variants = icd.get("variants") or []
    if not icd.get("sample_variants") or not variants:
        return primary
    return determinism.sha_weighted_choice(
        f"{encounter_id}|injury_diagnosis_variant",
        tuple(str(v["code"]) for v in variants),
        tuple(float(v["probability"]) for v in variants),
    )


def surgery_for_diagnosis(protocol: Any, code: str, severity: str) -> tuple[bool, dict[str, Any]]:
    """``(operate, overrides)`` for the stay's diagnosis. Without a
    ``procedure.by_diagnosis`` entry for ``code`` the protocol's own procedure
    applies; an entry is an override dict, ``none``, or ``{by_severity: {...}}``
    whose values are an override dict or ``none``."""
    entry = ((getattr(protocol, "procedure", None) or {}).get("by_diagnosis") or {}).get(code)
    if entry is None:
        return bool(getattr(protocol, "requires_surgery", False)), {}
    if isinstance(entry, dict) and "by_severity" in entry:
        entry = entry["by_severity"].get(severity, NO_SURGERY)
    if entry == NO_SURGERY:
        return False, {}
    return True, dict(entry)


def external_cause_code(protocol: Any, encounter_id: str, country: str) -> str:
    """The external-cause code recorded for the stay in ``country`` ("" when the
    protocol lists none for it)."""
    entries = ((getattr(protocol, "external_cause", None) or {}).get(country_slot(country))) or []
    if not entries:
        return ""
    return determinism.sha_weighted_choice(
        f"{encounter_id}|injury_external_cause",
        tuple(str(e["code"]) for e in entries),
        tuple(float(e["weight"]) for e in entries),
    )


def secondary_diagnosis_codes(protocol: Any, encounter_id: str) -> list[str]:
    """The secondary diagnosis codes of the stay: one of the protocol's weighted
    ``secondary_diagnosis`` entries, or none when it lists none."""
    entries = getattr(protocol, "secondary_diagnosis", None) or []
    if not entries:
        return []
    return [
        determinism.sha_weighted_choice(
            f"{encounter_id}|injury_secondary_diagnosis",
            tuple(str(e["code"]) for e in entries),
            tuple(float(e["weight"]) for e in entries),
        )
    ]
