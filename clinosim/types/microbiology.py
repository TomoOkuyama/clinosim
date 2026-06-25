"""Microbiology culture & antibiotic susceptibility types (AD-55 Base).

Codes only (AD-30): organism is a SNOMED code, antibiotic is a LOINC susceptibility
code, interpretation is an S/I/R code. Display text is resolved at output time via
``clinosim.codes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["SusceptibilityResult", "MicrobiologyResult"]


@dataclass
class SusceptibilityResult:
    """One antibiotic susceptibility result for an isolate."""

    antibiotic_loinc: str = ""  # LOINC "<drug> [Susceptibility]" test code
    interpretation: str = ""  # "S" | "I" | "R" (v3-ObservationInterpretation)


@dataclass
class MicrobiologyResult:
    """A single culture: specimen → organism (or no growth) → susceptibilities.

    hai_event_id links HAI-derived cultures back to their HAIEvent
    (extensions['hai']) — populated by modules/hai/enricher. Empty for
    community cultures.
    """

    encounter_id: str = ""
    specimen: str = ""  # controlled key: "blood" | "urine" | "sputum" | "wound"
    specimen_snomed: str = ""  # specimen-type SNOMED (display via codes); from YAML
    test_loinc: str = ""  # LOINC culture test code
    collected_datetime: datetime | None = None
    reported_datetime: datetime | None = None
    growth: bool = False  # False = no growth / negative culture
    organism_snomed: str = ""  # organism SNOMED code; "" if no growth
    quantitation: str = ""  # e.g. ">100,000 CFU/mL" (urine); free measurement, not display
    susceptibilities: list[SusceptibilityResult] = field(default_factory=list)
    hai_event_id: str = ""
