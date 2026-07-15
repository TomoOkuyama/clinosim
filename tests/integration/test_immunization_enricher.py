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
    p = PatientProfile(patient_id="p1", age=age, sex=sex,
                       date_of_birth=date(2026 - age, 3, 1))
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


def test_as_of_raises_when_no_deterministic_reference():
    """No snapshot_date AND no encounters with a valid admission_datetime is a
    caller/test-setup gap, not a real simulation path — fail loud instead of
    silently falling back to date.today() (determinism chain, 2026-07-04)."""
    from datetime import date

    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p1", age=80, sex="F",
                                date_of_birth=date(1946, 3, 1)),
        encounters=[],
    )
    with pytest.raises(ValueError, match="snapshot_date"):
        enrich_immunizations(_ctx([rec], snapshot=None))
