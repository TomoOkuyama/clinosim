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


def test_issue_911_gcs_not_set_when_consciousness_level_empty():
    """Issue #911: GCS must derive from AVPU. When a vital record has no
    AVPU sample (continuous-monitoring / event-recheck rows that emit
    without ``consciousness_level``), the enricher must NOT assign a
    GCS via the ``"A"`` default — the downstream FHIR emit path only
    fires AVPU Observations for vitals with ``consciousness_level`` set,
    so a defaulted GCS would surface as an unpaired GCS ≈ 15 record
    that same-day-joins against a real ``AVPU=U`` from a full-vitals
    round → the audit's 12,945 impossible pairs.
    """
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import VitalSignRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p_no_avpu", age=70),
        vital_signs=[
            # Explicit empty consciousness_level — mimics what
            # `_generate_vitals._emit` writes on continuous-monitoring /
            # event-recheck rows (``loc = _loc_for(...) if "loc" in fields
            # else ""``, then ``consciousness_level=loc`` overrides the
            # dataclass default "A").
            VitalSignRecord(spo2=95, heart_rate=80, consciousness_level=""),
        ],
    )
    enrich_nursing(EnricherContext(config=None, master_seed=42, records=[rec]))
    assert rec.vital_signs[0].gcs_score is None, (
        f"GCS must be None on vitals without AVPU sample; got {rec.vital_signs[0].gcs_score!r}"
    )
    # NEWS2 remains populated (it does not depend on AVPU).
    assert rec.vital_signs[0].news2_score is not None


def test_issue_911_gcs_reflects_avpu_band():
    """Issue #911: when AVPU is populated, GCS must fall within the
    clinical band for that AVPU category (per nursing_scores.yaml
    ``avpu_base``: A=15, V=13, P=9, U=5, with 0-1 jitter downwards).
    """
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import VitalSignRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    # Issue #911: A → strict 15 (no jitter); other bands keep ±1 jitter.
    for clvl, lo, hi in [("A", 15, 15), ("V", 12, 13), ("P", 8, 9), ("U", 4, 5)]:
        rec = CIFPatientRecord(
            patient=PatientProfile(patient_id=f"p_{clvl}", age=70),
            vital_signs=[VitalSignRecord(consciousness_level=clvl)],
        )
        enrich_nursing(EnricherContext(config=None, master_seed=42, records=[rec]))
        gcs = rec.vital_signs[0].gcs_score
        assert lo <= gcs <= hi, f"AVPU={clvl!r} expected GCS in [{lo},{hi}]; got {gcs}"


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
