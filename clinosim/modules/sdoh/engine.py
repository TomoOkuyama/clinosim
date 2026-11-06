"""SDOH reference data loader (AD-55 Base, data-only module variant).

No assignment / generation logic — smoking_status and alcohol_use are
demographics-driven attributes set on PatientProfile during activation
(see patient/activator.py + locale/{us,jp}/demographics.yaml). This
module only provides the enum→SNOMED + LOINC reference data needed by
FHIR builders.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes import code_exists
from clinosim.datafiles import load_data_yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


def _registered(system: str, code: str) -> str:
    if not code_exists(system, code, exact=True):
        raise ValueError(f"social_history.yaml {system} code {code!r} is not registered in codes/data/")
    return code


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snomed: str

    @field_validator("snomed")
    @classmethod
    def _snomed(cls, code: str) -> str:
        return _registered("snomed-ct", code)


class _Observable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loinc: str
    category: str = Field(min_length=1)
    values: dict[str, _Value] = Field(min_length=1)

    @field_validator("loinc")
    @classmethod
    def _loinc(cls, code: str) -> str:
        return _registered("loinc", code)


class _AgeGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alcohol_min_age: int = Field(ge=0)
    smoking_min_age: int = Field(ge=0)


class _SocialHistoryConfig(BaseModel):
    """Shape of social_history.yaml (Issue #2763)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    smoking_status: _Observable
    alcohol_use: _Observable
    age_gates: _AgeGates


@lru_cache(maxsize=1)
def load_social_history() -> dict:
    """Load SDOH social-history reference data.

    Returns a dict keyed by SDOH topic (currently ``smoking_status`` and
    ``alcohol_use``). Each topic value is a dict with:

      - ``loinc`` (str): US Core LOINC code for the Observation
      - ``category`` (str): FHIR Observation.category code (typically
        ``"social-history"``)
      - ``values`` (dict): enum key → ``{"snomed": "<code>"}`` mapping

    Display strings are NOT in this YAML — resolved at FHIR output time
    via ``clinosim.codes.lookup("snomed-ct", code, lang)``.
    """
    data = load_data_yaml(_REF_DIR / "social_history.yaml") or {}
    _SocialHistoryConfig.model_validate(data)
    return data
