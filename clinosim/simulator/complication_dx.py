"""In-hospital complications as dated diagnoses of the stay (Issue #3673).

A complication the daily loop (or the delirium rule) records in
``complications_occurred`` is only an event until it names a diagnosis. The
table ``reference_data/complication_diagnosis_codes.yaml`` says which tokens
do; :func:`complication_diagnoses` turns the coded ones into
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


class CodeByStayDiagnosis(BaseModel):
    """A protocol's code that depends on the stay's own diagnosis (Issue #3907):
    the first code of the stay whose 3-character category is a key of
    ``by_stay_category`` picks the code, else ``default``. Read from the codes
    the stay already carries; nothing is drawn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    by_stay_category: dict[str, str] = Field(min_length=1)
    default: str


class ComplicationDiagnosisCodes(BaseModel):
    """Schema of ``reference_data/complication_diagnosis_codes.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codes: dict[str, str] = Field(min_length=1)
    protocol_codes: dict[str, dict[str, str | CodeByStayDiagnosis]] = Field(default_factory=dict)
    distinct_code_categories: list[str] = Field(default_factory=list)
    non_diagnosis: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)


def validate_protocol_codes(protocol_codes: dict[str, dict[str, Any]], declared_tokens: dict[str, set[str]]) -> None:
    """Every per-protocol override names a protocol that exists and declares the
    token (``declared_tokens``: protocol id -> the complication tokens it
    declares); a code table naming a typo would silently never apply."""
    for protocol, tokens in protocol_codes.items():
        if protocol not in declared_tokens:
            raise ValueError(f"protocol_codes names {protocol!r}, which is not a disease protocol")
        for token in tokens:
            if token not in declared_tokens[protocol]:
                raise ValueError(f"protocol_codes: protocol {protocol!r} does not declare the complication {token!r}")


@functools.cache
def _table() -> ComplicationDiagnosisCodes:
    raw = load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "complication_diagnosis_codes.yaml")
    table = ComplicationDiagnosisCodes.model_validate(raw)
    if table.protocol_codes:
        from clinosim.modules.disease.protocol import load_all_disease_protocols

        declared = {
            disease_id: {str(c.get("name")) for c in protocol.complications if isinstance(c, dict) and c.get("name")}
            for disease_id, protocol in load_all_disease_protocols().items()
        }
        validate_protocol_codes(table.protocol_codes, declared)
    return table


def complication_diagnosis_codes() -> dict[str, str]:
    """Complication token -> internal diagnosis code (the YAML table)."""
    return dict(_table().codes)


def non_diagnosis_tokens() -> frozenset[str]:
    """Tokens that name no disease (events, treatment effects, nonspecific terms)."""
    return frozenset(_table().non_diagnosis)


def pending_tokens() -> frozenset[str]:
    """Disease-like tokens whose diagnosis code is not chosen and verified yet."""
    return frozenset(_table().pending)


def complication_diagnosis_code(token: str, disease_id: str = "", stay_codes: Iterable[str] = ()) -> str:
    """The diagnosis code of a complication token, ``""`` for an event with
    none. A delirium token resolves through the delirium rule.

    ``disease_id`` (Issue #3907): the protocol the complication occurred in. A
    token a protocol codes differently (``protocol_codes``: a septic
    cardiomyopathy, a burn wound infection, a traumatic rhabdomyolysis, a
    diabetic stay's hypoglycemia) gives that code; a code that depends on the
    stay's diabetes type reads ``stay_codes``. Any other protocol gets the
    token's default code."""
    override = _table().protocol_codes.get(disease_id, {}).get(token) if disease_id else None
    if isinstance(override, CodeByStayDiagnosis):
        by_category = override.by_stay_category
        for code in stay_codes:
            if code and code.split(".")[0] in by_category:
                return by_category[code.split(".")[0]]
        return override.default
    if override:
        return override
    return complication_diagnosis_codes().get(token) or delirium_token_code(token)


def diagnosis_category(code: str) -> str:
    """The key under which a diagnosis code counts as the same diagnosis as
    another (see ``_category``): public for the discharge summary's list."""
    return _category(code)


def _category(code: str) -> str:
    """The key of the first-onset-per-category rule: the 3-character ICD-10
    category, or the full code for a category whose members are different
    diagnoses (``distinct_code_categories``, e.g. E87 hypo- and hyperkalemia)."""
    category = code.split(".")[0]
    return code if category in _table().distinct_code_categories else category


def complication_diagnoses(
    complications: Iterable[Any],
    stay_codes: Iterable[str],
    chronic_codes: Iterable[str] = (),
    disease_id: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """``(entries, carried)`` for the coded complications of a stay.

    ``entries``: one dated ``working_diagnoses`` entry per coded complication.
    A code whose 3-character category (full code for a
    ``distinct_code_categories`` category) the stay already carries
    (``stay_codes``: principal, secondary and working codes; ``chronic_codes``:
    the patient's chronic codes) or an earlier complication already entered
    (the first onset wins) adds no entry; a complication that started as a new
    disease keeps its own entry.

    ``carried`` (Issue #3905): for each complication blocked that way, the code
    that carries its category, so the complication is still accounted for by
    an existing diagnosis. ``carrier`` says where that code is from: ``stay``
    (searched first), ``chronic`` or ``complication`` (an earlier entry).

    ``disease_id`` (Issue #3907): the stay's disease protocol, which picks a
    token's per-protocol code; the stay's own codes pick a diabetes type.
    """
    stay_codes = list(stay_codes)
    carriers: dict[str, tuple[str, str]] = {}
    for carrier, codes in (("stay", stay_codes), ("chronic", chronic_codes)):
        for code in codes:
            if code:
                carriers.setdefault(_category(code), (code, carrier))
    entries: list[dict[str, Any]] = []
    carried: list[dict[str, str]] = []
    for event in normalized_complications(list(complications)):
        if event["source"] in _OWN_ENTRY_SOURCES:
            continue
        code = complication_diagnosis_code(str(event["name"]), disease_id, stay_codes)
        if not code:
            continue
        category = _category(code)
        if category in carriers:
            carrying_code, carrier = carriers[category]
            if any(c["name"] == str(event["name"]) for c in carried):
                continue
            carried.append({"name": str(event["name"]), "carrying_code": carrying_code, "carrier": carrier})
            continue
        carriers[category] = (code, "complication")
        entries.append(
            {
                "disease_id": code,
                "onset_day": event["onset_day"],
                "onset_datetime": event["onset_datetime"],
                "source": WORKING_DIAGNOSIS_SOURCE,
            }
        )
    return entries, carried
