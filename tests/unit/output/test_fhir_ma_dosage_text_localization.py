"""MedicationAdministration.dosage.text must be localized on JP output (Issue #472).

The MedicationRequest builder ran `dose_text` through `_localize_dosage_terms`
(`_fhir_medications.py`) while the MedicationAdministration builder assigned it
raw, so every JP `MedicationAdministration.dosage.text` was emitted in English
(13,372 of 13,372 rows carrying the field, JP p=300 seed=42). The same function
already localized the rate-adjustment note, so the miss was inside a partially
wired code path — the J5 precedent named in CLAUDE.md.

These tests pin both call sites and assert they cannot drift apart again.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.builders.medications import (
    _build_dosage_instruction,
    _build_medication_admin,
)

_ENC = "ENC-POP-000001-000000000001"


def _admin(country: str, dose: str = "5.0mg DAILY") -> dict:
    return _build_medication_admin(
        {"drug_name": "Amlodipine", "dose": dose, "route": "PO", "status": "given"},
        patient_id="POP-000001",
        index=1,
        country=country,
        encounter_id=_ENC,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dose", "expected"),
    [
        ("5.0mg DAILY", "5.0mg 1日1回"),
        ("1.0g Q8H", "1.0g 8時間毎"),
        ("1000.0mg Q6H", "1000.0mg 6時間毎"),
        ("250mg TID", "250mg 1日3回"),
    ],
)
def test_jp_medication_admin_dosage_text_is_localized(dose: str, expected: str) -> None:
    """JP output carries no untranslated frequency/route abbreviation."""
    resource = _admin("JP", dose=dose)
    assert resource["dosage"]["text"] == expected


@pytest.mark.unit
def test_us_medication_admin_dosage_text_is_untouched() -> None:
    """`is_jp(country)` guards the localization — US output stays byte-identical."""
    resource = _admin("US")
    assert resource["dosage"]["text"] == "5.0mg DAILY"


@pytest.mark.unit
def test_jp_medication_admin_dosage_text_has_no_ascii_letters() -> None:
    """Guards the CLAUDE.md invariant "JP 出力は全 display/text/name が日本語".

    Units (mg / g / mL) are legitimately Latin, so this asserts on the
    alphabetic *words* that a frequency or route abbreviation would leave
    behind rather than on every Latin character.
    """
    import re

    text = _admin("JP")["dosage"]["text"]
    leftover = [w for w in re.findall(r"[A-Za-z]{2,}", text) if w.lower() not in {"mg", "ml", "mcg"}]
    assert leftover == [], f"untranslated words remain in JP dosage.text: {leftover}"


@pytest.mark.unit
def test_mr_and_ma_localize_the_same_dose_text_identically() -> None:
    """Drift guard: the two builders must agree, as they do for `route` (Issue #458).

    `_build_dosage_instruction` is the MedicationRequest side. Feeding both a dose
    that renders to the same free text pins that a future edit to one call site
    cannot silently leave the other in English.
    """
    mr = _build_dosage_instruction(
        {"route": "PO", "dose_quantity": 5.0, "dose_unit": "mg", "frequency": "DAILY"},
        country="JP",
    )
    ma = _admin("JP", dose="5.0mg PO DAILY")

    assert "DAILY" not in mr["text"]
    assert "DAILY" not in ma["dosage"]["text"]
    assert "1日1回" in mr["text"]
    assert "1日1回" in ma["dosage"]["text"]
