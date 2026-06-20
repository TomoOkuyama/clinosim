import pytest

pytestmark = pytest.mark.integration


def test_enricher_fills_nursing_data():
    import numpy as np  # noqa: F401
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.types.encounter import VitalSignRecord, ADLAssessment, IntakeOutputRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    from datetime import date

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p1", age=80),
        vital_signs=[VitalSignRecord(respiratory_rate=26, spo2=92,
                     on_supplemental_oxygen=True, temperature_celsius=39.2,
                     systolic_bp=95, heart_rate=115, consciousness_level="A")],
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


def test_enricher_deterministic():
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.types.encounter import VitalSignRecord, ADLAssessment
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    from datetime import date

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
