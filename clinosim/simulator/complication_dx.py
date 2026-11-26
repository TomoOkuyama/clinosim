"""In-hospital complications as dated diagnoses of the stay (Issue #3673).

A complication the daily loop (or the delirium rule) records in
``complications_occurred`` is only an event until it names a diagnosis. The
table ``reference_data/complication_diagnosis_codes.yaml`` says which tokens
do; :func:`complication_diagnosis_entries` turns the coded ones into
``clinical_diagnosis.working_diagnoses`` entries carrying the complication's
own onset, which the FHIR output emits as secondary encounter-diagnosis
Conditions. Nothing here draws from an RNG.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.simulator.complications import normalized_complications
from clinosim.simulator.delirium import delirium_token_code

# Provenance of a working_diagnoses entry that is an in-hospital complication
# (read by the FHIR secondary-Condition builder to tag its evidence).
WORKING_DIAGNOSIS_SOURCE = "in_hospital_complication"
# A complication that is a disease started in hospital already has its own
# working_diagnoses entry (simulator/_dispatch.py).
_OWN_ENTRY_SOURCES = frozenset({"in_hospital_new_disease"})


class ComplicationDiagnosisCodes(BaseModel):
    """Schema of ``reference_data/complication_diagnosis_codes.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codes: dict[str, str] = Field(min_length=1)
    distinct_code_categories: list[str] = Field(default_factory=list)
    non_diagnosis: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)


@functools.cache
def _table() -> ComplicationDiagnosisCodes:
    raw = load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "complication_diagnosis_codes.yaml")
    return ComplicationDiagnosisCodes.model_validate(raw)


def complication_diagnosis_codes() -> dict[str, str]:
    """Complication token -> internal diagnosis code (the YAML table)."""
    return dict(_table().codes)


def non_diagnosis_tokens() -> frozenset[str]:
    """Tokens that name no disease (events, treatment effects, nonspecific terms)."""
    return frozenset(_table().non_diagnosis)


def pending_tokens() -> frozenset[str]:
    """Disease-like tokens whose diagnosis code is not chosen and verified yet."""
    return frozenset(_table().pending)


def complication_diagnosis_code(token: str) -> str:
    """The diagnosis code of a complication token, ``""`` for an event with
    none. A delirium token resolves through the delirium rule."""
    return complication_diagnosis_codes().get(token) or delirium_token_code(token)


def _category(code: str) -> str:
    """The key of the first-onset-per-category rule: the 3-character ICD-10
    category, or the full code for a category whose members are different
    diagnoses (``distinct_code_categories``, e.g. E87 hypo- and hyperkalemia)."""
    category = code.split(".")[0]
    return code if category in _table().distinct_code_categories else category


def complication_diagnosis_entries(complications: Iterable[Any], existing_codes: Iterable[str]) -> list[dict[str, Any]]:
    """One dated ``working_diagnoses`` entry per coded complication.

    Skips a code whose 3-character category (full code for a
    ``distinct_code_categories`` category) the stay already carries
    (``existing_codes``: principal, secondary, working and chronic codes) and
    a category already entered by an earlier complication (the first onset
    wins); a complication that started as a new disease keeps its own entry.
    """
    seen = {_category(c) for c in existing_codes if c}
    entries: list[dict[str, Any]] = []
    for event in normalized_complications(list(complications)):
        if event["source"] in _OWN_ENTRY_SOURCES:
            continue
        code = complication_diagnosis_code(str(event["name"]))
        if not code or _category(code) in seen:
            continue
        seen.add(_category(code))
        entries.append(
            {
                "disease_id": code,
                "onset_day": event["onset_day"],
                "onset_datetime": event["onset_datetime"],
                "source": WORKING_DIAGNOSIS_SOURCE,
            }
        )
    return entries
