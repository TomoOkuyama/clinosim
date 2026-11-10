"""Discharge outcome of a finished inpatient stay (Issue #3150).

The DPC 退院時転帰 a Japanese hospital records: improved, unchanged,
worsened, death from the condition, ... — a fact of the clinical course, not
the destination. Derived from what the CIF records at discharge (death,
destination, course archetype, admission diagnosis) by the ordered rules of
``locale/shared/discharge_outcomes.yaml``; each country codes it through its
``code_mapping_discharge_disposition.yaml``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import get_attr_or_key

_PATH = Path(__file__).resolve().parents[2] / "locale" / "shared" / "discharge_outcomes.yaml"


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str
    deceased: bool | None = None
    admission_diagnosis_prefix: list[str] = Field(default_factory=list)
    destination: list[str] = Field(default_factory=list)
    course_archetype: list[str] = Field(default_factory=list)


class DischargeOutcomesFile(BaseModel):
    """Shape of ``discharge_outcomes.yaml``."""

    model_config = ConfigDict(extra="forbid")
    metadata: dict[str, Any] = Field(default_factory=dict)
    outcomes: list[str] = Field(min_length=1)
    rules: list[_Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _known_outcomes_and_a_default(self) -> DischargeOutcomesFile:
        unknown = sorted({r.outcome for r in self.rules} - set(self.outcomes))
        if unknown:
            raise ValueError(f"rules name unknown outcomes {unknown}")
        last = self.rules[-1]
        if last.deceased is not None or last.admission_diagnosis_prefix or last.destination or last.course_archetype:
            raise ValueError("the last rule must be the unconditional default")
        return self


@cache
def _rules() -> tuple[dict[str, Any], ...]:
    return tuple(load_validated_yaml(_PATH, DischargeOutcomesFile)["rules"])


def discharge_outcome(encounter: Any, *, deceased: bool = False) -> str:
    """The discharge outcome key of a finished inpatient ``encounter`` (a CIF
    Encounter or its dict); ``deceased`` is the in-hospital death of the
    simulated course."""
    dx = str(get_attr_or_key(encounter, "admission_diagnosis_code", "") or "")
    dest = str(get_attr_or_key(encounter, "discharge_disposition", "") or "")
    arch = str(get_attr_or_key(encounter, "clinical_course_archetype", "") or "")
    for rule in _rules():
        if rule.get("deceased") is not None and bool(rule["deceased"]) != bool(deceased):
            continue
        prefixes = rule.get("admission_diagnosis_prefix") or []
        if prefixes and not any(dx.startswith(p) for p in prefixes):
            continue
        if rule.get("destination") and dest not in rule["destination"]:
            continue
        if rule.get("course_archetype") and arch not in rule["course_archetype"]:
            continue
        return str(rule["outcome"])
    raise AssertionError("discharge_outcomes.yaml has an unconditional last rule")
