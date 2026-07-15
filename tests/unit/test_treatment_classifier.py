"""Unit tests for the canonical treatment classifier.

Verifies that both entry points (encounter-YAML default-MEDICATION path and
inpatient-YAML type-hint-dispatch path) correctly route non-drug items to
PROCEDURE / THERAPY and preserve MEDICATION classification for real drugs.

This is the J5-pattern regression guard for MR classification (session 44):
before this classifier was extracted, three separate call sites carried their
own keyword tables and diverged, leaking non-drug items like "Cardiac
monitoring" and "Oral fluids encouraged" out as MedicationRequest.
"""

from __future__ import annotations

import pytest

from clinosim.modules.order.treatment_classifier import (
    classify_encounter_treatment,
    classify_inpatient_supportive,
)
from clinosim.types.encounter import OrderType


class TestEncounterTreatmentDrugs:
    """Real drugs (default MEDICATION) must stay MEDICATION."""

    @pytest.mark.parametrize(
        "name",
        [
            "Acetaminophen 500mg",
            "Acetaminophen 1000mg",
            "Ibuprofen 400mg",
            "Ibuprofen 600mg",
            "IV normal saline 1000mL",
            "IV normal saline 500mL",
            "IV normal saline 1L",
            "Ketorolac 30mg",
            "Ketorolac 30mg IV",
            "Morphine 4mg IV",
            "Ondansetron 4mg",
            "Ondansetron 4mg IV",
            "Ipratropium bromide 0.5mg nebulized",
            "Nebulized salbutamol 2.5mg",
            "Silver sulfadiazine cream",
            "Diclofenac gel",
            "Lidocaine patch 5%",
            "Oxymetazoline nasal spray",
            "Proparacaine 0.5% eye drops",
            "Ofloxacin ophthalmic drops",
            "Corticosteroid intra-articular injection (triamcinolone)",
            "fentanyl IV sedation",
            "midazolam IV sedation",
            "Ceftriaxone 1g IV",
            "Amoxicillin/clavulanate 875/125mg",
            "Aspirin 325mg",
            "Prednisolone 40mg",
            "Tamsulosin 0.4mg",
            "Tetanus toxoid booster",
            "Tetanus toxoid 0.5mL",
            "influenza vaccine IM",
        ],
    )
    def test_drug_stays_medication(self, name: str) -> None:
        assert classify_encounter_treatment(name) == OrderType.MEDICATION


class TestEncounterTreatmentProcedures:
    """Physical / device interventions must classify as PROCEDURE."""

    @pytest.mark.parametrize(
        "name",
        [
            "Ice pack application",
            "Ice pack to affected area",
            "Heat pack application",
            "Elastic bandage wrap",
            "Cervical collar application",
            "Cool water irrigation",
            "Closed reduction",
            "Suture closure",
            "Skin staples",
            "Tissue adhesive (glue)",
            "Foley catheter insertion",
            "Foreign body removal with 25G needle",
            "Rust ring removal with burr",
            "Non-adherent dressing",
            "dressing change",
            "Wound irrigation with normal saline",
            "Nasal packing (anterior)",
            "Silver nitrate cauterization",
            "Endoscopy",
            "biopsy",
            "polypectomy",
            "Hemodialysis 4-hour session",
            "Short arm cast",
            "Short arm splint",
            "Posterior splint",
            "Sling immobilization",
            "Procedural sedation (Propofol/Midazolam)",
        ],
    )
    def test_procedure(self, name: str) -> None:
        assert classify_encounter_treatment(name) == OrderType.PROCEDURE


class TestEncounterTreatmentTherapy:
    """Observation / education / non-pharmacologic care must classify as THERAPY."""

    @pytest.mark.parametrize(
        "name",
        [
            "Cardiac monitoring",
            "Observation",
            "Observation and monitoring",
            "Neurological observation",
            "Oral fluids encouraged",
            "Dark room rest",
            "Surgical consult",
            "Urology consult",
            "PHQ-9 / GAD-7 screening",
            "Fagerström assessment",
            "wound assessment",
            "Motivational interviewing / counseling",
            "patient education (diet, lifestyle)",
            "Gait training",
            "resistance training",
            "supervised aerobic exercise",
            "Supervised therapeutic exercises",
            "Range of motion exercises",
            "Reassurance and breathing exercises",
            "Incentive spirometry instruction",
            "Modalities (heat/cold/TENS)",
            "Medication review and adjustment",
        ],
    )
    def test_therapy(self, name: str) -> None:
        assert classify_encounter_treatment(name) == OrderType.THERAPY


class TestInpatientSupportive:
    """Inpatient supportive uses type_hint dispatch; PROCEDURE keywords override."""

    def test_medication_type_stays_medication(self) -> None:
        # Real drug order with drug-typed hint stays MEDICATION.
        assert (
            classify_inpatient_supportive(
                "prednisone 40mg PO daily",
                "steroid",
            )
            == OrderType.MEDICATION
        )

    def test_medication_type_with_incidental_therapy_word_stays_medication(self) -> None:
        # Drug type wins over incidental therapy keyword in detail
        # (an anti-inflammatory that mentions "medication review at day 3"
        # is still a medication order, not a therapy).
        assert (
            classify_inpatient_supportive(
                "ibuprofen; consider medication review at day 3",
                "anti_inflammatory",
            )
            == OrderType.MEDICATION
        )

    def test_care_plan_type_stays_therapy(self) -> None:
        assert (
            classify_inpatient_supportive(
                "Cardiac monitoring for AF detection x48h minimum",
                "continuous_telemetry",
            )
            == OrderType.THERAPY
        )

    def test_procedure_keyword_overrides_medication_type(self) -> None:
        # RM-6b case: DVT_prophylaxis-typed order with device detail
        # (Sequential compression devices) routes to PROCEDURE, not MEDICATION.
        assert (
            classify_inpatient_supportive(
                "Sequential compression devices",
                "DVT_prophylaxis",
            )
            == OrderType.PROCEDURE
        )

    def test_procedure_keyword_overrides_care_plan_type(self) -> None:
        assert (
            classify_inpatient_supportive(
                "Foley catheter insertion",
                "wound_care",
            )
            == OrderType.PROCEDURE
        )

    def test_unknown_type_with_drug_substring_medication(self) -> None:
        assert (
            classify_inpatient_supportive(
                "some drug detail here",
                "some_drug_type",
            )
            == OrderType.MEDICATION
        )

    def test_unknown_type_no_match_therapy(self) -> None:
        # Unknown type + no keyword match → THERAPY (safe default; won't
        # generate MedicationAdministration).
        assert (
            classify_inpatient_supportive(
                "unknown supportive detail",
                "unknown_type",
            )
            == OrderType.THERAPY
        )

    def test_empty_type_no_match_therapy(self) -> None:
        assert (
            classify_inpatient_supportive(
                "just some free text",
                "",
            )
            == OrderType.THERAPY
        )


class TestNebulizerDrugVsDevice:
    """`Nebulized <drug>` is a MEDICATION; bare `nebulizer` setup is a PROCEDURE.

    The keyword table uses "nebulizer" (not "nebulize" / "nebulized") so that
    "Nebulized salbutamol 2.5mg" and "Ipratropium bromide nebulized" stay
    MEDICATION while a bare "Nebulizer setup" would be PROCEDURE.
    """

    def test_nebulized_drug_is_medication(self) -> None:
        assert classify_encounter_treatment("Nebulized salbutamol 2.5mg") == OrderType.MEDICATION
        assert classify_encounter_treatment("Ipratropium bromide 0.5mg nebulized") == OrderType.MEDICATION

    def test_bare_nebulizer_is_procedure(self) -> None:
        assert classify_encounter_treatment("Nebulizer setup") == OrderType.PROCEDURE


class TestNoDrugFalsePositives:
    """Common drug names must not accidentally match PROCEDURE or THERAPY keywords."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            # "IV normal saline" must not match "iv line"
            ("IV normal saline 1000mL", OrderType.MEDICATION),
            # Drugs in tablets/creams/etc. that could bump against generic keywords
            ("Ceftriaxone 1g IV", OrderType.MEDICATION),
            ("Ibuprofen 400mg", OrderType.MEDICATION),
            # DVT prophylaxis medication (not the sequential compression device)
            ("Enoxaparin 40mg SC", OrderType.MEDICATION),
            # An IV-titratable drip
            ("Nicardipine 5mg/h IV", OrderType.MEDICATION),
        ],
    )
    def test_no_false_positive(self, name: str, expected: OrderType) -> None:
        assert classify_encounter_treatment(name) == expected
