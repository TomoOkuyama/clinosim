from datetime import date, datetime

import pytest

from clinosim.modules.document.engine import document_enricher
from clinosim.types.clinical import ClinicalDocument


@pytest.mark.unit
def test_enricher_produces_stub_with_narrative_none():
    """AD-65: enricher must not populate narrative — pass side does it.

    NOTE: encounter_type is set to EncounterType.INPATIENT (not None) so that
    the admission_hp / progress_note / discharge_summary specs actually apply
    and the ClinicalDocument(...) construction branches execute — otherwise
    encounter_types_supported=[inpatient, icu, rehab_inpatient] gating (AD-64)
    would skip document generation entirely and the assertion below would be
    vacuously true even against the pre-fix code (which raised TypeError for
    the removed text_source=/sections= kwargs).
    """
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import Encounter, EncounterType
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001", age=65, sex="M", date_of_birth=date(1961, 1, 1)),
        encounters=[
            Encounter(
                encounter_id="ENC-1",
                encounter_type=EncounterType.INPATIENT,
                admission_datetime=datetime(2026, 1, 1, 9, 0),
                discharge_datetime=datetime(2026, 1, 3, 9, 0),
                attending_physician_id="DR-1",
            )
        ],
    )
    ctx = EnricherContext(config=None, master_seed=42, population=None, records=[rec])
    document_enricher(ctx)

    assert rec.documents, "expected at least one ClinicalDocument stub for an inpatient stay"
    for doc in rec.documents or []:
        assert isinstance(doc, ClinicalDocument)
        assert doc.narrative is None, f"enricher must produce stub; got {doc.narrative}"
