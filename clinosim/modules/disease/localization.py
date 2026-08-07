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


def target_los_config(
    protocol: DiseaseProtocol,
    country: str,
    severity: str,
) -> dict[str, float] | None:
    """Canonical resolver for ``protocol.target_los`` (Issue #550).

    Returns the ``{"mean", "sd", "min", "max"}`` dict for the requested
    ``(country, severity)`` slot, or ``None`` when the protocol has no entry
    for it. The caller decides how to interpret ``None`` — the inpatient
    simulator falls back to a hardcoded default distribution, while the
    narrative template generator falls back to the observed ``ctx.los_days``.

    Fallback shape:

    * **Country**: if the country's yaml key (``japan`` / ``us``) is not
      present in ``protocol.target_los``, falls back to the ``"us"`` key
      (matches the default-US locale convention documented in
      ``AGENTS.md § Country / locale convention``). This preserves the
      inpatient simulator's pre-canonical behaviour verbatim.
    * **Severity**: no fallback — the caller receives ``None`` when the
      severity slot is missing so it can apply its own domain-appropriate
      default (a hardcoded distribution for sampling vs the observed
      encounter length for a narrative sentence).

    Placed here (not in ``protocol.py`` as Issue #550's proposal suggested)
    because this module already owns ``_country_to_yaml_key``; keeping the
    two helpers together avoids a duplicate mapping and a
    ``protocol → localization → protocol`` import cycle.
    """
    country_key = _country_to_yaml_key(country)
    los_by_country = protocol.target_los.get(country_key) or protocol.target_los.get("us", {})
    if not los_by_country:
        return None
    cfg = los_by_country.get(severity)
    return cfg if isinstance(cfg, dict) else None


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
