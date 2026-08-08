"""HL7 v2/v3 vocabulary StrEnums for the Encounter resource (Issue #562).

Extracts three small vocabularies previously threaded through the simulator
and FHIR emit paths as bare string literals:

- :class:`AdmitSource` — HL7 v2 admit-source codes (spec:
  ``http://terminology.hl7.org/CodeSystem/admit-source``).
- :class:`DischargeDisposition` — HL7 v2 discharge-disposition codes (spec:
  ``http://terminology.hl7.org/CodeSystem/discharge-disposition``).
- :class:`ActPriority` — HL7 v3 ActPriority codes (spec:
  ``http://terminology.hl7.org/CodeSystem/v3-ActPriority``).

Members cover only the values clinosim currently emits; add a member (with a
docstring citing the spec entry) when a new value is needed. ``StrEnum``
inherits from :class:`str`, so ``encounter.admit_source = AdmitSource.EMD``
stays wire-compatible with the pre-refactor ``str`` typing and existing
``str`` comparisons (``encounter.admit_source == "emd"``) continue to work.

FHIR emit sites should read ``.value`` explicitly to keep the JSON coding a
plain string literal in the output; this matches the pattern used for other
StrEnum-backed FHIR vocabularies in the codebase.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ActPriority",
    "AdmitSource",
    "DischargeDisposition",
]


class AdmitSource(StrEnum):
    """HL7 v2 admit-source ``http://terminology.hl7.org/CodeSystem/admit-source``."""

    EMD = "emd"
    """Emergency department — inpatient admitted via ED (most common inpatient path)."""

    OUTP = "outp"
    """Outpatient department — walk-in / scheduled outpatient encounter origin."""

    HOSP = "hosp"
    """Hospital transfer — synth-ED companion Encounter's discharge-to-inpatient path."""


class DischargeDisposition(StrEnum):
    """HL7 v2 discharge-disposition ``http://terminology.hl7.org/CodeSystem/discharge-disposition``."""

    HOME = "home"
    """Discharged to home / self-care (default for successful inpatient completion)."""

    EXP = "exp"
    """Expired — patient died during the encounter (session 59 #299: HL7 authoritative)."""


class ActPriority(StrEnum):
    """HL7 v3 ActPriority ``http://terminology.hl7.org/CodeSystem/v3-ActPriority``."""

    EM = "EM"
    """Emergency — highest urgency (ED encounters + inpatient admits for emergency-priority diseases)."""

    UR = "UR"
    """Urgent — inpatient admits for non-emergency-priority diseases."""

    R = "R"
    """Routine — outpatient encounters."""
