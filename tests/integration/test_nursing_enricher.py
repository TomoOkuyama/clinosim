import pytest

pytestmark = pytest.mark.integration


def test_enricher_fills_nursing_data():
    from datetime import date

    import numpy as np  # noqa: F401

    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import ADLAssessment, IntakeOutputRecord, VitalSignRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p1", age=80),
        vital_signs=[
            VitalSignRecord(
                respiratory_rate=26,
                spo2=92,
                on_supplemental_oxygen=True,
                temperature_celsius=39.2,
                systolic_bp=95,
                heart_rate=115,
                consciousness_level="A",
            )
        ],
        adl_assessments=[ADLAssessment(date=date(2026, 1, 1), barthel_score=20)],
        intake_output_records=[IntakeOutputRecord(date=date(2026, 1, 1), intake_iv_ml=1500)],
    )
    ctx = EnricherContext(config=None, master_seed=123, records=[rec])
    enrich_nursing(ctx)

    assert rec.vital_signs[0].news2_score == 13
    assert 3 <= rec.vital_signs[0].gcs_score <= 15
    assert len(rec.nursing_risk_assessments) == 1
    nra = rec.nursing_risk_assessments[0]
    assert 6 <= nra.braden_total <= 23
    assert nra.fall_risk_level in ("low", "moderate", "high")


def test_enricher_impaired_consciousness_affects_scores():
    """Vital with consciousness_level='P' on same day as ADL must lower Braden sensory
    and raise Morse fall risk compared to the all-Alert baseline."""
    from datetime import date, datetime

    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import ADLAssessment, VitalSignRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    target_date = date(2026, 3, 15)

    def _make_rec(clvl: str) -> CIFPatientRecord:
        return CIFPatientRecord(
            patient=PatientProfile(patient_id="p_impaired", age=75),
            vital_signs=[
                VitalSignRecord(
                    timestamp=datetime(2026, 3, 15, 8, 0),
                    consciousness_level=clvl,
                )
            ],
            adl_assessments=[ADLAssessment(date=target_date, barthel_score=50)],
        )

    rec_alert = _make_rec("A")
    rec_pain = _make_rec("P")

    enrich_nursing(EnricherContext(config=None, master_seed=42, records=[rec_alert]))
    enrich_nursing(EnricherContext(config=None, master_seed=42, records=[rec_pain]))

    nra_alert = rec_alert.nursing_risk_assessments[0]
    nra_pain = rec_pain.nursing_risk_assessments[0]

    # Braden sensory: Alert → 4, Pain → 2 (spec: consciousness lowers sensory subscale)
    assert nra_alert.braden_sensory == 4
    assert nra_pain.braden_sensory == 2

    # Morse: impaired consciousness adds mental_status_forgets_limits penalty
    assert nra_pain.morse_total > nra_alert.morse_total


def test_enricher_deterministic():
    from datetime import date

    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import ADLAssessment, VitalSignRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    def build():
        return CIFPatientRecord(
            patient=PatientProfile(patient_id="p1", age=80),
            vital_signs=[VitalSignRecord(consciousness_level="A")],
            adl_assessments=[ADLAssessment(date=date(2026, 1, 1), barthel_score=50)],
        )

    r1, r2 = build(), build()
    enrich_nursing(EnricherContext(config=None, master_seed=99, records=[r1]))
    enrich_nursing(EnricherContext(config=None, master_seed=99, records=[r2]))
    assert r1.nursing_risk_assessments[0] == r2.nursing_risk_assessments[0]
