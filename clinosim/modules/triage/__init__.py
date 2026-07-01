"""Triage module(Tier 1 #3 α-min-2 always-on Module, AD-55).

ED encounter で JTAS(JP)/ ESI(US)level + arrival_mode + acuity_score を
sampling、EncounterRecord.triage_data に populate。

POST_ENCOUNTER enricher、order=93(before nursing=94, before document=95)。
"""

from __future__ import annotations

from clinosim.types.triage import TriageData

__all__ = ["TriageData"]
