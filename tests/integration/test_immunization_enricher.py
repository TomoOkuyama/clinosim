import pytest

pytestmark = pytest.mark.integration


def _ctx(records, country="US", snapshot=None, seed=123):
    from clinosim.simulator.enrichers import EnricherContext

    class _Cfg:
        def __init__(self, country, snapshot_date):
            self.country = country
            self.snapshot_date = snapshot_date

    return EnricherContext(config=_Cfg(country, snapshot), master_seed=seed, records=records)


def _record(age=80, sex="F"):
    from datetime import date, datetime

    from clinosim.types.encounter import Encounter
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    p = PatientProfile(patient_id="p1", age=age, sex=sex, date_of_birth=date(2026 - age, 3, 1))
    enc = Encounter(admission_datetime=datetime(2026, 1, 10, 9, 0))
    return CIFPatientRecord(patient=p, encounters=[enc])


def test_enricher_fills_immunizations():
    from clinosim.modules.immunization.enricher import enrich_immunizations

    rec = _record()
    enrich_immunizations(_ctx([rec], snapshot="2026-01-15"))
    assert rec.immunizations, "no immunizations generated for an 80yo"
    from datetime import date

    assert all(r.occurrence_date <= date(2026, 1, 15) for r in rec.immunizations)


def test_enricher_deterministic():
    from clinosim.modules.immunization.enricher import enrich_immunizations

    r1, r2 = _record(), _record()
    enrich_immunizations(_ctx([r1], seed=99))
    enrich_immunizations(_ctx([r2], seed=99))

    def k(recs):
        return [(x.vaccine_cvx, x.occurrence_date) for x in recs]

    assert k(r1.immunizations) == k(r2.immunizations)


def test_vax_encounter_hosted_in_only_one_record_per_patient():
    """Regression for #1245.

    When a patient has N record files (one per primary encounter, as the
    simulator's per-encounter CIF sharding produces), any ENC-VAX-*
    companion encounter synthesized for that patient must be appended to
    EXACTLY ONE of those records — not to every record. Pre-fix behaviour
    replicated the synth VAX across all N records because
    ``generate_immunizations`` is deterministic per patient (same imm list
    → same orphan set → same synth encounter_id) and the enricher looped
    over records without deduping. At p=100 seed=342 this hit 23% of VAX
    encounters (one appearing in 9 records).
    """
    from datetime import date, datetime

    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    def _multi_encounter_record(enc_month: int) -> CIFPatientRecord:
        # Same patient (pid=p1), one primary encounter per month → simulating
        # the per-encounter CIF sharding for a patient with multiple visits.
        p = PatientProfile(patient_id="p1", age=45, sex="F", date_of_birth=date(1981, 3, 1))
        enc = Encounter(
            encounter_id=f"ENC-POP-p1-{enc_month:02d}",
            patient_id="p1",
            encounter_type=EncounterType.OUTPATIENT,
            status=EncounterStatus.COMPLETED,
            admission_datetime=datetime(2026, enc_month, 10, 9, 0),
            discharge_datetime=datetime(2026, enc_month, 10, 9, 30),
        )
        return CIFPatientRecord(patient=p, encounters=[enc])

    records = [_multi_encounter_record(m) for m in (2, 5, 8)]
    enrich_immunizations(_ctx(records, country="US", snapshot="2026-09-10", seed=123))

    # Count how many records host each ENC-VAX-* encounter.
    from collections import Counter

    vax_host_count: Counter = Counter()
    for rec in records:
        for enc in rec.encounters or []:
            eid = getattr(enc, "encounter_id", "") or ""
            if eid.startswith("ENC-VAX-"):
                vax_host_count[eid] += 1

    # Every synth VAX encounter must live in exactly one record.
    assert vax_host_count, "expected at least one synth VAX encounter for a 45yo across 8 months"
    for eid, hosts in vax_host_count.items():
        assert hosts == 1, f"{eid} appears in {hosts} records — expected exactly 1 (#1245)"

    # Immunizations remain per-patient (all records carry the imm list),
    # and their encounter_id should point at a real VAX encounter.
    for rec in records:
        for imm in rec.immunizations or []:
            eid = getattr(imm, "encounter_id", "") or ""
            if eid.startswith("ENC-VAX-"):
                assert eid in vax_host_count, f"imm.encounter_id={eid} points at no hosted VAX encounter"


def test_as_of_raises_when_no_deterministic_reference():
    """No snapshot_date AND no encounters with a valid admission_datetime is a
    caller/test-setup gap, not a real simulation path — fail loud instead of
    silently falling back to date.today() (determinism chain, 2026-07-04)."""
    from datetime import date

    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p1", age=80, sex="F", date_of_birth=date(1946, 3, 1)),
        encounters=[],
    )
    with pytest.raises(ValueError, match="snapshot_date"):
        enrich_immunizations(_ctx([rec], snapshot=None))
