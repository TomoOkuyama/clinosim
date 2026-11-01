"""Drug-name → class[] resolver for drug safety.

Drug identity, aliases and classes come from the drug catalog
(``clinosim/codes/data/drugs.yaml``) through :mod:`clinosim.codes.drugs`
(Issue #2298); this module only adapts them to the rule engine's API.
"""

from __future__ import annotations

from clinosim.codes.drugs import drug_classes, drug_display, identify_drug


def canonical_name(drug_name: str) -> str | None:
    """English catalog name of the drug ``drug_name`` names (any id, name,
    alias, Japanese name or free-text order string); ``None`` if unknown."""
    rec = identify_drug(drug_name) if drug_name else None
    return rec.names.get("en") if rec is not None else None


def resolve_classes(drug_name: str) -> list[str]:
    """Catalog classes of the drug, with their dotted ancestors; [] if unknown."""
    return list(drug_classes(drug_name)) if drug_name else []


def japanese_display(drug_name: str) -> str | None:
    """Japanese catalog name of the drug ``drug_name`` names (Issue #2271)."""
    rec = identify_drug(drug_name) if drug_name else None
    return drug_display(rec.drug_id, "ja") if rec is not None else None
