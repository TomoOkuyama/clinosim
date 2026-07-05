"""Diagnosis types — Bayesian differential diagnosis candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

_UNSET_DATETIME = datetime(1970, 1, 1)


@dataclass
class DiagnosisCandidate:
    disease_code: str
    icd_code: str
    display_name: str
    probability: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class DifferentialDiagnosis:
    candidates: list[DiagnosisCandidate] = field(default_factory=list)
    working_diagnosis: str | None = None
    confirmed: bool = False
    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)

    @property
    def top_candidate(self) -> DiagnosisCandidate | None:
        return self.candidates[0] if self.candidates else None
