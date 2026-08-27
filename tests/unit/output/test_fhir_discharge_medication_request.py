"""Issue #445: `discharge_prescription.items[]` must reach FHIR as MedicationRequest.

`CIFPatientRecord.discharge_prescription` was consumed by the CSV adapter and the
discharge-summary narrative but by no FHIR builder, so take-home and outpatient-renewal
prescriptions were dropped from the FHIR export — a CIF→FHIR no-drop violation.

Measured on JP p=300 seed=42 before the fix: **3,542 prescription items** across 765
records (248 from 27 inpatient discharges, 3,294 from 738 outpatient renewals) existed in
CIF and produced zero MedicationRequest resources.

The constraints pinned here are the ones a future edit is most likely to break silently:

* **`expectedSupplyDuration` fixed values.** `unit` is the Japanese string `日` in BOTH
  `JP_MedicationRequest` (JP Core 1.2.0) and `JP_MedicationRequest_eCS` (JP-CLINS
  1.12.0); `code` is the UCUM token `d`. Putting `"d"` in `unit` is a fixed-value
  violation that survives dropping the eCS profile.
* **Open-ended supply sentinels.** Disease YAMLs write `duration_days: 0  # chronic`
  and `duration_days: ongoing`. Emitting `{"value": 0}` asserts a zero-day supply and a
  JSON string in `Duration.value` (type `decimal`) is a type violation, so the element is
  omitted instead — legal because both profiles put it at min=0.
* **No dosage invented.** Items transcribed from `patient.current_medications` have
  neither dose nor route (lost upstream, Issue #452). `dosageInstruction` is omitted
  rather than filled with the drug name, which would restate
  `medicationCodeableConcept.text` as if it were a dosage.
* **`identifier` split.** The builder writes the JP `rpNumber` + `orderInRp` slices
  (the walker never adds them and JP Core requires both); it must NOT write
  `requestIdentifier`, which the JP walker derives from `Resource.id` and skips when the
  system URI is already present.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import resolve_patient_id
from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.medications.medications import (
    DISCHARGE_RX_ID_PREFIX,
    OUTPATIENT_RX_ID_PREFIX,
    _build_discharge_medication_request,
    _supply_duration_days,
)

pytestmark = pytest.mark.unit

_RP_NUMBER_SYSTEM = "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber"
_ORDER_IN_RP_SYSTEM = "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex"
_REQUEST_IDENTIFIER_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"
_UCUM = "http://unitsofmeasure.org"
_SNOMED = "http://snomed.info/sct"

_DISCHARGE_ITEM = {
    "drug_name": "Furosemide",
    "dose": "20mg PO daily",
    "route": "PO",
    "duration_days": 7,
}
_TRANSCRIBED_ITEM = {
    "drug_name": "Atorvastatin 10mg",
    "dose": "",
    "route": "",
    "duration_days": 30,
}


def _build(item: dict, **kw: object) -> dict:
    params: dict = {
        "patient_id": "POP-000001",
        "country": "JP",
        "encounter_id": "ENC-1",
        "encounter_type": "inpatient",
        "seq": 1,
        "authored_on": "2025-03-19T03:44:00+09:00",
        "prescriber_id": "DOC-1",
    }
    params.update(kw)
    return _build_discharge_medication_request(item, **params)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- id / routing


def test_inpatient_and_outpatient_get_distinct_id_prefixes() -> None:
    """A take-home script at discharge and an outpatient renewal must be distinguishable.

    Post-Issue-#853: ids are opaque (rxdc-<12hex> vs rxopd-<12hex>). Assert
    the prefix survives and the opaque digests differ (different prefix hashes
    to different digests even for the same structural key).
    """
    inp = _build(_DISCHARGE_ITEM, encounter_type="inpatient")
    out = _build(_DISCHARGE_ITEM, encounter_type="outpatient")
    assert inp["id"].startswith(DISCHARGE_RX_ID_PREFIX)
    assert out["id"].startswith(OUTPATIENT_RX_ID_PREFIX)
    assert inp["id"] != out["id"]


def test_seq_drives_both_id_suffix_and_order_in_rp() -> None:
    """Post-Issue-#853: id no longer visibly contains seq (opaque), but the
    structural-key round-trip in identifier[] does, and orderInRp is unchanged.
    """
    r = _build(_DISCHARGE_ITEM, seq=4)
    # Opaque id no longer ends with "-04"; check the structural-key identifier instead.
    from clinosim.modules.output.fhir_r4.medications.medications import MEDICATION_REQUEST_KEY_SYSTEM

    struct_key = [i for i in r["identifier"] if i["system"] == MEDICATION_REQUEST_KEY_SYSTEM]
    assert len(struct_key) == 1
    assert struct_key[0]["value"].endswith("-04")
    order_in_rp = [i for i in r["identifier"] if i["system"] == _ORDER_IN_RP_SYSTEM]
    assert order_in_rp == [{"system": _ORDER_IN_RP_SYSTEM, "value": "4"}]


def test_category_follows_encounter_type_and_is_not_hardcoded() -> None:
    """96% of prescriptions are outpatient renewals; a hardcoded `discharge` mislabels them."""
    inp = _build(_DISCHARGE_ITEM, encounter_type="inpatient")
    out = _build(_DISCHARGE_ITEM, encounter_type="outpatient")
    assert inp["category"][0]["coding"][0]["code"] == "discharge"
    assert out["category"][0]["coding"][0]["code"] == "community"


# --------------------------------------------------------------------------- identifiers


def test_builder_emits_rp_slices_but_not_request_identifier() -> None:
    """JP Core needs identifier>=2 with rpNumber+orderInRp; requestIdentifier is the walker's."""
    r = _build(_DISCHARGE_ITEM)
    systems = [i["system"] for i in r["identifier"]]
    assert _RP_NUMBER_SYSTEM in systems
    assert _ORDER_IN_RP_SYSTEM in systems
    assert _REQUEST_IDENTIFIER_SYSTEM not in systems, (
        "hand-writing requestIdentifier stops the JP walker deriving it from Resource.id"
    )


def test_us_output_has_no_jp_identifier_slices() -> None:
    """Post-Issue-#853: identifier[] is present on every MR (structural-key
    round-trip), but the two JP-Core-only slices (rpNumber, orderInRp) must
    still stay out of US output."""
    r = _build(_DISCHARGE_ITEM, country="US")
    systems = [i.get("system") for i in r.get("identifier", [])]
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber" not in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex" not in systems


# --------------------------------------------------------------------------- supply duration


@pytest.mark.parametrize("raw", [0, -3, "ongoing", "", None, True, False, "n/a"])
def test_open_ended_or_unusable_duration_yields_no_element(raw: object) -> None:
    """`0` / `ongoing` are open-ended sentinels, not day counts."""
    assert _supply_duration_days(raw) is None
    r = _build({**_DISCHARGE_ITEM, "duration_days": raw})
    assert "expectedSupplyDuration" not in r["dispenseRequest"]


@pytest.mark.parametrize(("raw", "expected"), [(7, 7), (30, 30), ("28", 28), (365.0, 365)])
def test_positive_duration_jp_is_emitted_with_spec_fixed_values(raw: object, expected: int) -> None:
    r = _build({**_DISCHARGE_ITEM, "duration_days": raw}, country="JP")
    assert r["dispenseRequest"]["expectedSupplyDuration"] == {
        "value": expected,
        "unit": "日",
        "system": _UCUM,
        "code": "d",
    }


def test_supply_duration_unit_jp_is_the_japanese_character_not_the_ucum_token() -> None:
    """Regression pin: `unit` is `日` (fixedString in JP Core AND eCS), `code` is `d`."""
    esd = _build(_DISCHARGE_ITEM, country="JP")["dispenseRequest"]["expectedSupplyDuration"]
    assert esd["unit"] == "日"
    assert esd["code"] == "d"
    assert esd["unit"] != esd["code"]


def test_supply_duration_unit_us_matches_ucum_code_no_japanese_leakage() -> None:
    """Issue #730: US MedicationRequests must not carry the JP fixedString `"日"` in `unit`.

    JP profiles pin `unit == "日"` as a fixedString, but that constraint applies only
    to JP-declared MedicationRequests; a US resource has no such binding, and emitting
    the Japanese character in an English cohort leaks locale-inappropriate text
    (5271/5603 = 94% of US baseline MedicationRequests exhibited this pre-fix).
    """
    esd = _build(_DISCHARGE_ITEM, country="US")["dispenseRequest"]["expectedSupplyDuration"]
    assert esd["unit"] == "d", "US locale must emit UCUM Latin display, not the JP fixed value"
    assert esd["unit"] == esd["code"], "US .unit mirrors .code so downstream consumers get consistent text"
    assert "日" not in esd["unit"], "no CJK leakage into US output"


def test_no_refill_count_is_invented() -> None:
    """CIF carries no refill policy; guessing one asserts a workflow never modelled."""
    assert "numberOfRepeatsAllowed" not in _build(_DISCHARGE_ITEM)["dispenseRequest"]


# --------------------------------------------------------------------------- dosage


def test_dose_and_route_are_both_preserved() -> None:
    """The free-text dose must survive alongside the coded route (neither replaces the other)."""
    r = _build(_DISCHARGE_ITEM)
    dosage = r["dosageInstruction"][0]
    assert dosage["route"]["coding"][0]["system"] == _SNOMED
    assert dosage["route"]["text"] == "経口", "JP output localizes route.text to Japanese"
    assert "20mg" in dosage["text"], "the authored dose string must not be dropped"


def test_transcribed_item_gets_no_dosage_instruction() -> None:
    """No dose and no route in CIF means no dosage element — not the drug name as a stand-in."""
    r = _build(_TRANSCRIBED_ITEM)
    assert "dosageInstruction" not in r
    assert r["medicationCodeableConcept"]["text"]


def test_dosage_text_never_restates_the_drug_name() -> None:
    for item in (_DISCHARGE_ITEM, _TRANSCRIBED_ITEM):
        r = _build(item)
        dosage = (r.get("dosageInstruction") or [{}])[0]
        if dosage.get("text"):
            assert dosage["text"] != r["medicationCodeableConcept"]["text"]


def test_jp_dose_text_is_localized_and_us_is_not() -> None:
    jp = _build(_DISCHARGE_ITEM, country="JP")["dosageInstruction"][0]["text"]
    us = _build(_DISCHARGE_ITEM, country="US")["dosageInstruction"][0]["text"]
    assert jp == "20mg 経口 1日1回"
    assert us == "20mg PO daily"


def test_route_only_item_still_emits_the_coded_route() -> None:
    r = _build({**_DISCHARGE_ITEM, "dose": ""})
    dosage = r["dosageInstruction"][0]
    assert dosage["route"]["coding"][0]["code"]
    assert "text" not in dosage


# --------------------------------------------------------------------------- required fields


def test_authored_on_is_always_present() -> None:
    """`authoredOn` is min=1 in JP Core, so it can never be omitted."""
    assert _build(_DISCHARGE_ITEM)["authoredOn"] == "2025-03-19T03:44:00+09:00"
    assert _build(_DISCHARGE_ITEM)["dispenseRequest"]["validityPeriod"]["start"] == "2025-03-19T03:44:00+09:00"


def test_course_of_therapy_reflects_open_ended_supply() -> None:
    """A lifelong drug does not become a short course by being handed over at discharge."""
    acute = _build({**_DISCHARGE_ITEM, "duration_days": 5}, encounter_type="inpatient")
    chronic = _build({**_DISCHARGE_ITEM, "duration_days": 0}, encounter_type="inpatient")
    renewal = _build(_DISCHARGE_ITEM, encounter_type="outpatient")
    assert acute["courseOfTherapyType"]["coding"][0]["code"] == "acute"
    assert chronic["courseOfTherapyType"]["coding"][0]["code"] == "continuous"
    assert renewal["courseOfTherapyType"]["coding"][0]["code"] == "continuous"


def test_subject_encounter_and_prescriber_references() -> None:
    r = _build(_DISCHARGE_ITEM)
    assert r["subject"] == {"reference": f"Patient/{resolve_patient_id('POP-000001')}"}
    assert r["encounter"] == {"reference": f"Encounter/{resolve_encounter_id('ENC-1')}"}
    assert r["requester"] == {"reference": "Practitioner/DOC-1"}
    assert r["recorder"] == {"reference": "Practitioner/DOC-1"}


def test_missing_prescriber_omits_requester_rather_than_emitting_a_dangling_reference() -> None:
    r = _build(_DISCHARGE_ITEM, prescriber_id="")
    assert "requester" not in r
    assert "recorder" not in r


def test_medication_concept_is_resolved_through_the_shared_helper() -> None:
    """JP output must carry a coded medication, localized text, and no code-as-display."""
    r = _build(_DISCHARGE_ITEM, country="JP")
    concept = r["medicationCodeableConcept"]
    assert concept["text"]
    coding = concept["coding"][0]
    assert coding["display"] != coding["code"]
