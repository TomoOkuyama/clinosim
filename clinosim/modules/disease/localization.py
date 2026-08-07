"""Disease-protocol localization helpers — country → YAML key, chief-complaint
translation, department extraction.

Extracted from ``simulator/helpers.py`` (Issue #544). These helpers all read
``DiseaseProtocol`` fields (chief_complaint, department) and belong beside
``protocol.py`` rather than under ``simulator/``. Callers keep their existing
``from clinosim.simulator.helpers import _country_to_yaml_key`` etc via the
helpers.py re-export facade for one deprecation cycle.
"""

from __future__ import annotations

from clinosim.modules.disease.protocol import DiseaseProtocol


def _country_to_yaml_key(country: str) -> str:
    """Convert country code (``JP`` / ``US``) to disease-YAML key
    (``japan`` / ``us``)."""
    return {"JP": "japan", "US": "us"}.get(country, "us")


def _disease_chief_complaint(protocol: DiseaseProtocol, country: str = "US") -> str:
    """Get chief complaint from disease protocol YAML (multi-language support).

    CIF stores English always (AD-30). JP chief complaint is resolved at FHIR
    output time via ``_disease_chief_complaint_ja``.
    """
    from clinosim.locale.text import resolve_text

    return resolve_text(protocol.chief_complaint, language="en") or "General malaise"


def _disease_chief_complaint_ja(protocol: DiseaseProtocol) -> str:
    """Get the Japanese chief complaint from disease protocol YAML.

    Issue #360 G1: ``Encounter.reasonCode.text`` on JP output previously fell
    back to the English ``chief_complaint`` string stored in CIF (AD-30
    canonical) when ICD-10 code_lookup could not resolve a Japanese display.
    Populating a separate JP field on the encounter at creation time lets the
    FHIR emitter emit Japanese in that fallback path.

    Returns ``""`` when the disease protocol's ``chief_complaint`` is a plain
    string (no per-language dict) or has no ``ja`` entry — the caller then
    leaves ``Encounter.chief_complaint_ja`` empty and the emitter's fallback
    stays as pre-fix (English string).
    """
    from clinosim.locale.text import resolve_text

    ja_text = resolve_text(protocol.chief_complaint, language="ja")
    # `resolve_text` returns the English fallback when JA is missing; detect
    # that so we don't stash English in the JA field.
    en_text = resolve_text(protocol.chief_complaint, language="en")
    if ja_text and ja_text != en_text:
        return ja_text
    return ""


def _disease_to_department(protocol: DiseaseProtocol) -> str:
    """Get the granular department from disease protocol YAML."""
    return protocol.department or "internal_medicine"
