"""US Practitioner NPI identifier emission (Issue #1986).

US Core 6.1.0 Practitioner profile marks ``identifier`` with the NPI
slice (``http://hl7.org/fhir/sid/us-npi``) as must-support. Aggregate QA
on the US cohort showed 0 of 111 Practitioner resources carried an NPI
identifier — this test pins the fix.

NPI format: 10-digit numeric value conforming to the NPPES Luhn
check-digit algorithm (prefix ``80840`` + 9-digit base; the 10th digit
is the Luhn check digit computed over the 14-digit string, and only
the trailing 10 digits are published as the NPI).

Determinism: NPI is derived from ``sha256(salt + staff_id)`` so re-runs
are byte-identical and no master RNG is consumed (RNG-neutral additive
field pattern).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.practitioner import _build_practitioner

pytestmark = pytest.mark.unit

_NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"


def _us_staff(**overrides: object) -> dict:
    base: dict = {
        "name": "John Smith",
        "role": "physician",
        "department": "cardiology",
        "specialty": "cardiology",
        "qualification_year": 2001,
        "sex": "M",
        "phone": "555-123-4567",
        "email": "john.smith@hospital.example.org",
    }
    base.update(overrides)
    return base


def _npi_identifier(resource: dict) -> dict | None:
    for ident in resource.get("identifier", []) or []:
        if ident.get("system") == _NPI_SYSTEM:
            return ident
    return None


def _luhn_check(digits: str) -> bool:
    """Validate NPI Luhn check digit per CMS NPPES algorithm.

    The NPI is published as 10 digits; the check digit is computed over
    the 15-digit string formed by prefixing ``80840`` (ISO Issuer
    Identifier for US healthcare providers) to the first 9 digits.
    """
    assert len(digits) == 10 and digits.isdigit()
    base = "80840" + digits[:9]
    total = 0
    # Rightmost digit (which is the check digit itself) counts single;
    # positions to its left alternate double / single. Standard Luhn.
    reverse = (base + digits[9])[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Positive: US Practitioner emits NPI identifier
# ---------------------------------------------------------------------------


def test_us_practitioner_emits_npi_identifier() -> None:
    """Every US-cohort Practitioner carries an NPI identifier."""
    roster = {"DR-CA-001": _us_staff()}
    resource = _build_practitioner("DR-CA-001", roster, country="US")
    npi = _npi_identifier(resource)
    assert npi is not None, resource.get("identifier")


def test_us_practitioner_npi_value_is_10_digits() -> None:
    """NPI value is a 10-digit numeric string (NPPES canonical form)."""
    roster = {"DR-CA-001": _us_staff()}
    resource = _build_practitioner("DR-CA-001", roster, country="US")
    npi = _npi_identifier(resource)
    assert npi is not None
    value = npi["value"]
    assert isinstance(value, str)
    assert value.isdigit(), value
    assert len(value) == 10, value


def test_us_practitioner_npi_passes_luhn_checksum() -> None:
    """NPI check digit matches the CMS NPPES Luhn algorithm."""
    roster = {"DR-CA-001": _us_staff()}
    resource = _build_practitioner("DR-CA-001", roster, country="US")
    npi = _npi_identifier(resource)
    assert npi is not None
    assert _luhn_check(npi["value"]), npi["value"]


def test_us_practitioner_npi_is_deterministic() -> None:
    """Regenerating the same staff_id yields byte-identical NPI."""
    roster = {"DR-CA-001": _us_staff()}
    r1 = _build_practitioner("DR-CA-001", roster, country="US")
    r2 = _build_practitioner("DR-CA-001", roster, country="US")
    assert _npi_identifier(r1) == _npi_identifier(r2)


def test_us_practitioner_npi_varies_by_staff_id() -> None:
    """Different staff_id values produce different NPIs."""
    roster = {
        "DR-CA-001": _us_staff(),
        "DR-CA-002": _us_staff(),
        "NS-CA-001": _us_staff(role="nurse"),
    }
    npis = {sid: _npi_identifier(_build_practitioner(sid, roster, country="US"))["value"] for sid in roster}
    assert len(set(npis.values())) == len(npis), npis


@pytest.mark.parametrize(
    "role",
    [
        "physician",
        "nurse",
        "pharmacist",
        "lab_technician",
        "physical_therapist",
        "occupational_therapist",
        "speech_therapist",
        "medical_social_worker",
        "dietitian",
        "radiologist",
    ],
)
def test_us_npi_emitted_for_every_role(role: str) -> None:
    """NPI must be emitted regardless of practitioner role."""
    staff_id = f"{role[:3].upper()}-001"
    roster = {staff_id: _us_staff(role=role)}
    resource = _build_practitioner(staff_id, roster, country="US")
    npi = _npi_identifier(resource)
    assert npi is not None, (role, resource.get("identifier"))
    assert npi["value"].isdigit() and len(npi["value"]) == 10


def test_us_practitioner_npi_emitted_without_roster_entry() -> None:
    """Even without a roster entry we still emit an NPI — US Core requires
    it on every Practitioner reference, and the staff_id alone is enough
    to derive a deterministic value."""
    resource = _build_practitioner("DR-CA-999", roster_map=None, country="US")
    npi = _npi_identifier(resource)
    assert npi is not None, resource.get("identifier")
    assert npi["value"].isdigit() and len(npi["value"]) == 10


# ---------------------------------------------------------------------------
# Negative: JP cohort unaffected
# ---------------------------------------------------------------------------


def test_jp_practitioner_has_no_npi_identifier() -> None:
    """JP cohort keeps its MHLW license number — no NPI leakage."""
    jp_staff = {
        "name": "山田 太郎",
        "name_phonetic": "ヤマダ タロウ",
        "role": "physician",
        "department": "cardiology",
        "specialty": "cardiology",
        "qualification_year": 2001,
        "sex": "M",
    }
    roster = {"DR-CA-001": jp_staff}
    resource = _build_practitioner("DR-CA-001", roster, country="JP")
    for ident in resource.get("identifier", []) or []:
        assert ident.get("system") != _NPI_SYSTEM, ident
