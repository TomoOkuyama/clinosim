"""What a scheduled screening visit does, read from its encounter protocol (Issue #2870).

A healthcare-calendar screening (annual exam, mammogram, colonoscopy) runs
the protocol's ``workup`` (labs and imaging, each drawn with its
probability), the ``screening_labs`` recommended for the person's age, sex,
BMI and country, the ``procedures`` every visit performs and the
``treatment`` drugs given for them. The result is the follow-up spec the
outpatient visit simulator takes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from clinosim.age_bands import age_band_covers
from clinosim.countries import country_slot
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.types.patient import PatientProfile


def _in_countries(countries: list[str] | None, country: str) -> bool:
    return not countries or country_slot(country) in {c.lower() for c in countries}


def screening_lab_applies(lab: dict[str, Any], patient: PatientProfile, country: str) -> bool:
    """Whether the protocol's ``screening_labs`` entry ``lab`` is recommended
    for ``patient`` in ``country`` (age band, sex, minimum BMI)."""
    if not _in_countries(lab.get("countries"), country):
        return False
    if not age_band_covers(lab["age"], int(patient.age)):
        return False
    sex = lab.get("sex") or "any"
    if sex != "any" and patient.sex != sex:
        return False
    min_bmi = lab.get("min_bmi")
    return min_bmi is None or float(patient.bmi) >= float(min_bmi)


def screening_visit_spec(
    condition_id: str, patient: PatientProfile, country: str, rng: np.random.Generator
) -> dict[str, Any]:
    """The follow-up spec of one screening visit of protocol ``condition_id``.

    ``rng`` is the visit's own workup stream: one draw per protocol lab,
    imaging study and treatment, whatever the country filter, so the draws
    do not depend on which entries apply.
    """
    proto = load_encounter_condition(condition_id)
    workup = proto.get("workup") or {}

    labs: list[str] = []
    for item in workup.get("labs") or []:
        if rng.random() < float(item.get("probability", 1.0)) and item["test"] not in labs:
            labs.append(str(item["test"]))
    for lab in proto.get("screening_labs") or []:
        if screening_lab_applies(lab, patient, country) and lab["test"] not in labs:
            labs.append(str(lab["test"]))

    imaging: list[dict[str, Any]] = []
    for item in workup.get("imaging") or []:
        drawn = rng.random() < float(item.get("probability", 1.0))
        if drawn and _in_countries(item.get("countries"), country):
            imaging.append(
                {
                    "test": str(item["test"]),
                    "abnormal_rate_by_severity": dict(item.get("abnormal_rate_by_severity") or {}),
                }
            )

    sedation: list[dict[str, Any]] = []
    for tx in proto.get("treatment") or []:
        drawn = rng.random() < float(tx.get("probability", 1.0))
        if drawn and tx.get("drug_id"):
            sedation.append({"drug_id": str(tx["drug_id"]), "dose": str(tx.get("dose") or ""), "route": tx["route"]})

    return {
        "labs": labs,
        "imaging": imaging,
        "procedures": [dict(p) for p in proto.get("procedures") or []],
        "procedural_sedation": sedation,
        "vitals": bool(workup.get("vitals", True)),
        "visit_length_key": condition_id,
    }
