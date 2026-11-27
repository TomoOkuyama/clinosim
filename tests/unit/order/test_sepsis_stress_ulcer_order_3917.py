"""The sepsis stress-ulcer prophylaxis is a medication order, and no other
supportive line that names a catalogue drug is left as a therapy order unless
the drug is ordered elsewhere or the line is not a prescription (Issue #3917)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import clinosim
from clinosim.codes.drugs import identify_drug
from clinosim.countries import country_slot
from clinosim.datafiles import load_data_yaml
from clinosim.modules.order.engine import place_admission_orders, supportive_detail_raw
from clinosim.modules.order.treatment_classifier import classify_inpatient_supportive
from clinosim.simulator.renal_antibiotic_dose import RenalDoseContext, apply_renal_dose
from clinosim.types.encounter import OrderResult

pytestmark = pytest.mark.unit

_DISEASES = Path(clinosim.__file__).parent / "modules/disease/reference_data"
_ADM = datetime(2026, 3, 28, 15, 0)

# Supportive lines that name a catalogue drug without being a prescription of it:
# a monitoring or hold instruction, a procedure, a fluid formula.
_NOT_A_PRESCRIPTION = {
    ("alcohol_withdrawal", "withdrawal_monitoring"),
    ("aspiration_pneumonia", "oral_care"),
    ("gi_bleeding", "hold_anticoagulants"),
    ("hemorrhagic_stroke", "BP_management"),
    ("industrial_burn_severe", "IV_fluid"),
    ("subdural_hematoma", "anticoagulant_reversal"),
}


def _sepsis_orders(country: str) -> list:
    protocol = load_data_yaml(_DISEASES / "sepsis.yaml")
    return place_admission_orders(protocol, "P1", "E1", _ADM, country, np.random.default_rng(0))


@pytest.mark.parametrize("country", ["us", "jp"])
def test_sepsis_stress_ulcer_prophylaxis_is_a_famotidine_medication_order(country: str) -> None:
    (order,) = [o for o in _sepsis_orders(country) if o.display_name.startswith("stress_ulcer_prophylaxis")]
    assert order.order_type.value == "medication"
    assert (order.dose_quantity, order.dose_unit) == (20.0, "mg")
    assert order.route and order.route.upper() == "IV"
    assert order.frequency_per_day == 2
    assert order.duration_days == 7


@pytest.mark.parametrize("country", ["us", "jp"])
def test_supportive_lines_naming_a_drug_are_orders_or_declared(country: str) -> None:
    """A supportive line naming a catalogue drug is a medication order, unless
    the drug is also a first-line drug of the protocol (ordered there) or the
    line is a listed non-prescription."""
    problems: list[str] = []
    for path in sorted(_DISEASES.glob("*.yaml")):
        protocol = load_data_yaml(path)
        admission = (protocol.get("order_protocols") or {}).get("admission_orders") or {}
        first_line = (
            (protocol.get("drugs") or {}).get("first_line", {}).get(country_slot(country, scheme="legacy_japan"), [])
        )
        if isinstance(first_line, dict):
            first_line = [first_line]
        first_ids = {str(d.get("drug_id", "")) for d in first_line if isinstance(d, dict)}
        for sup in admission.get("supportive") or []:
            detail = supportive_detail_raw(sup, country)
            drug = identify_drug(detail)
            if drug is None:
                continue
            kind = classify_inpatient_supportive(detail, sup.get("type", ""))
            if kind.value == "medication" or drug.drug_id in first_ids:
                continue
            if (path.stem, sup.get("type")) in _NOT_A_PRESCRIPTION:
                continue
            problems.append(f"{path.stem}: {sup.get('type')}: {detail}")
    assert not problems, problems


def _famotidine(country: str):
    return next(o for o in _sepsis_orders(country) if o.display_name.startswith("stress_ulcer_prophylaxis"))


def _adjust(country: str, creatinine: float, age: int = 70, weight: float = 66.7):
    order = _famotidine(country)
    patient = SimpleNamespace(
        patient_id="P1", age=age, sex="M", date_of_birth=date(2026 - age, 3, 28), weight_kg=weight, height_cm=170.0
    )
    result = OrderResult(
        result_datetime=_ADM + timedelta(minutes=30),
        performed_by="T",
        lab_name="Creatinine",
        value=creatinine,
        unit="mg/dL",
        flag="",
    )
    apply_renal_dose(order, patient, _ADM, _ADM + timedelta(hours=1), RenalDoseContext([result], country))
    return order


@pytest.fixture(autouse=True)
def _charted_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "clinosim.modules.population.encounter_anthropometry.encounter_weight_kg",
        lambda patient, *args, **kwargs: patient.weight_kg,
    )


def test_us_famotidine_is_halved_below_crcl_50() -> None:
    order = _adjust("US", 3.0)  # CrCl about 22
    assert (order.dose_quantity, order.dose_unit, order.frequency) == (10.0, "mg", "Q12H")
    assert order.renal_dose_adjusted


def test_us_famotidine_unchanged_at_normal_clearance() -> None:
    order = _adjust("US", 0.9)
    assert (order.dose_quantity, order.renal_dose_adjusted) == (20.0, False)


def test_jp_famotidine_bands() -> None:
    mid = _adjust("JP", 1.7)  # CrCl about 43: 10 mg twice daily
    assert (mid.dose_quantity, mid.frequency) == (10.0, "Q12H")
    low = _adjust("JP", 3.5)  # CrCl about 19: 5 mg once daily, the written interval follows
    assert (low.dose_quantity, low.frequency) == (5.0, "DAILY")
    assert "q12h" not in low.display_name.lower()


@pytest.mark.parametrize(("creatinine", "dose"), [(0.9, 20.0), (1.7, 10.0), (3.5, 5.0)])
def test_jp_famotidine_order_name_reads_as_japanese_at_every_renal_dose(creatinine: float, dose: float) -> None:
    """The renally rewritten order name has a Japanese phrase of its own (no English type slug)."""
    from clinosim.locale.free_text import localize_drug_name
    from tests.unit.modules.document.narrative.test_jp_no_english_words_3034 import _english_words

    order = _adjust("JP", creatinine)
    assert order.dose_quantity == dose
    ja = localize_drug_name(order.display_name, "ja")
    assert "ファモチジン" in ja and not _english_words(ja), ja
    # The bare drug string (as the administration record lists it) carries no "x7" multiplier.
    bare = localize_drug_name(order.display_name.split(": ", 1)[-1], "ja")
    assert "ファモチジン" in bare and " x" not in bare, bare
