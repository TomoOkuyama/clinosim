"""Marital status and the emergency-contact relationship it allows (Issue #3189).

The tables are the country's ``locale/<cc>/marital_status.yaml`` (census
counts by sex and age band, and contact-relationship weights by marital
status and age band), read through
:func:`clinosim.locale.loader.load_marital_status`. A person's status is drawn
once, from a person-scoped sub-RNG, and kept on the ``PersonRecord``, so every
record of the person carries the same status.
"""

from __future__ import annotations

from typing import Any

from clinosim import determinism
from clinosim.age_bands import find_age_band_or_last
from clinosim.locale.loader import load_marital_status
from clinosim.modules._shared import normalize_probabilities
from clinosim.modules.patient._patient_activator_thresholds import MARITAL_STATUS_ADULT_AGE_MIN
from clinosim.types.population import PersonRecord

__all__ = [
    "activation_stream_relationships",
    "adult_age_min",
    "contact_relationships",
    "contact_role_code",
    "draw_marital_status",
    "minor_contact_relationships",
    "minor_marital_status",
    "person_marital_status",
]


def adult_age_min(country: str) -> int:
    """Age at or above which marital status is drawn and an adult emergency
    contact is named (the table's ``adult_age_min``)."""
    return int(load_marital_status(country).get("adult_age_min", MARITAL_STATUS_ADULT_AGE_MIN))


def minor_marital_status(country: str) -> str:
    """The status recorded below :func:`adult_age_min` (``""`` without a table)."""
    return str(load_marital_status(country).get("minor_code", ""))


def _row(table: dict[str, Any], age: int) -> dict[str, Any]:
    return dict(table[find_age_band_or_last(list(table), age)])


def _status_row(country: str, age: int, sex: str) -> dict[str, float]:
    dist = load_marital_status(country).get("distribution") or {}
    if sex in dist:
        return _row(dist[sex], age)
    # A sex the table does not split by: both sexes' counts pooled.
    pooled: dict[str, float] = {}
    for by_band in dist.values():
        for code, count in _row(by_band, age).items():
            pooled[code] = pooled.get(code, 0) + count
    return pooled


def draw_marital_status(person_id: str, date_of_birth: str, age: int, sex: str, country: str) -> str:
    """Draw a marital status from the census row of ``sex`` and ``age`` with the
    person-scoped stream (``""`` when the country has no table)."""
    from clinosim.seeding import marital_status_seed

    row = _status_row(country, age, sex)
    if not row:
        return ""
    codes = list(row)
    rng = determinism.default_rng(marital_status_seed(person_id, date_of_birth))
    return str(rng.choice(codes, p=normalize_probabilities([float(row[c]) for c in codes], fallback="raise")))


def person_marital_status(person: PersonRecord, age: int, country: str) -> str:
    """The person's marital status: the stored one, else drawn now and stored."""
    status = str(getattr(person, "marital_status", "") or "")
    if not status:
        status = draw_marital_status(person.person_id, str(person.date_of_birth), age, person.sex, country)
        person.marital_status = status
    return status


def contact_relationships(marital_status: str, age: int, country: str) -> tuple[list[str], list[float]]:
    """Relationship labels and probabilities of an adult's emergency contact
    given the marital status (empty when the table has no row for it)."""
    rels = (load_marital_status(country).get("emergency_contact") or {}).get("relationships") or {}
    if marital_status not in rels:
        return [], []
    row = _row(rels[marital_status], age)
    labels = list(row)
    return labels, list(normalize_probabilities([float(row[k]) for k in labels], fallback="raise"))


def minor_contact_relationships(country: str) -> tuple[list[str], list[float]]:
    """Relationship labels and probabilities of a minor's emergency contact
    (``emergency_contact.minor_relationships``, Issue #3658; empty without a
    table)."""
    row = (load_marital_status(country).get("emergency_contact") or {}).get("minor_relationships") or {}
    labels = list(row)
    if not labels:
        return [], []
    return labels, list(normalize_probabilities([float(row[k]) for k in labels], fallback="raise"))


def contact_role_code(relationship: str, contact_sex: str) -> str:
    """The specific v3-RoleCode of an emergency contact (Issue #3599): the
    relationship slug resolved by the contact's sex (father or mother, brother
    or sister, son or daughter, husband or wife), the generic code when the
    sex is not recorded, ``""`` for an unknown slug."""
    from clinosim.codes import slug_sex_to_code, slug_to_code

    specific = slug_sex_to_code("hl7-v3-rolecode").get(relationship, {}).get(contact_sex)
    return str(specific or slug_to_code("hl7-v3-rolecode").get(relationship, ""))


def activation_stream_relationships(age: int, country: str) -> tuple[list[str], list[float]]:
    """The relationship table whose draw the per-activation stream makes and
    discards, so the later draws of that stream keep their position."""
    contact = load_marital_status(country).get("emergency_contact") or {}
    return contact_relationships(str(contact.get("activation_stream_status", "")), age, country)
