"""Issue #3243: a stay admitted through the ED was triaged in the ED.

The triage enricher records triage data on inpatient / ICU encounters whose
``admit_source`` is ``emd`` (triage time = the ED arrival), appends the ED
arrival vital-sign set derived from the state the patient was admitted in,
and takes the vitals cap and the ESI resources from the ED phase only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules._shared import ED_TRIAGE_DATA_SOURCE, ORDER_SET_ADMISSION_INITIAL
from clinosim.modules.observation.nursing_enricher import enrich_nursing
from clinosim.modules.triage.engine import admitted_ed_stay, triage_enricher, triage_level
from clinosim.simulator._ed_thresholds import ED_VITALS_OFFSET_MIN
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import VitalSignRecord
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_ADMISSION = datetime(2026, 3, 1, 18, 0)
_WARD_VITALS = VitalSignRecord(
    timestamp=datetime(2026, 3, 1, 20, 0), heart_rate=88, systolic_bp=128, spo2=97.0, consciousness_level="A"
)


def _record(admit_source: str = "emd", state: PhysiologicalState | None = None, enc_type: str = "inpatient"):
    enc = SimpleNamespace(
        encounter_id="ENC-POP-000001-1",
        encounter_type=enc_type,
        admit_source=admit_source,
        admission_datetime=_ADMISSION,
        severity="severe",
        chief_complaint="Chest pain",
        triage_data=None,
    )
    return SimpleNamespace(
        patient=SimpleNamespace(
            patient_id="POP-000001", date_of_birth=date(1955, 6, 1), age=70, baseline_vitals=BaselineVitals()
        ),
        encounters=[enc],
        orders=[],
        vital_signs=[_WARD_VITALS],
        physiological_states=[state or PhysiologicalState(sympathetic_activation=0.8, inflammation_level=0.6)],
        condition_event=None,
    )


def _run(record, country: str = "jp") -> None:
    triage_enricher(SimpleNamespace(master_seed=42, country=country, records=[record], roster=None))


def test_via_ed_admission_gets_triage_at_the_ed_arrival() -> None:
    record = _record()
    _run(record)
    triage = record.encounters[0].triage_data
    assert triage is not None
    assert triage.level_system == "JTAS"
    assert triage.level in {"1", "2", "3", "4", "5"}
    assert triage.triage_time == _ADMISSION - admitted_ed_stay()
    assert triage.chief_complaint_summary == "Chest pain"


def test_us_via_ed_admission_is_triaged_with_esi() -> None:
    record = _record()
    _run(record, country="us")
    assert record.encounters[0].triage_data.level_system == "ESI"


def test_icu_admission_via_ed_is_triaged_too() -> None:
    record = _record(enc_type="icu")
    _run(record)
    assert record.encounters[0].triage_data is not None


def test_via_ed_admission_gets_one_physiology_derived_arrival_vital_set() -> None:
    record = _record()
    _run(record)
    arrival = [v for v in record.vital_signs if v.data_source == ED_TRIAGE_DATA_SOURCE]
    assert len(arrival) == 1
    vs = arrival[0]
    assert vs.timestamp == _ADMISSION - admitted_ed_stay() + timedelta(minutes=ED_VITALS_OFFSET_MIN)
    assert vs.timestamp < _ADMISSION
    for field in ("temperature_celsius", "heart_rate", "systolic_bp", "diastolic_bp", "respiratory_rate", "spo2"):
        assert getattr(vs, field) is not None, field
    assert vs.pain_score is not None
    assert vs.consciousness_level in {"A", "V", "P", "U"}
    assert vs.gcs_score is not None
    # Sympathetic activation of the admitted state shows in the arrival HR.
    assert vs.heart_rate > BaselineVitals().heart_rate
    # The ward readings are kept as they were.
    assert record.vital_signs[0] is _WARD_VITALS


def test_arrival_vitals_and_triage_are_deterministic() -> None:
    a, b = _record(), _record()
    _run(a)
    _run(b)
    assert a.vital_signs[-1] == b.vital_signs[-1]
    assert a.encounters[0].triage_data == b.encounters[0].triage_data


def test_shock_on_arrival_caps_the_level_at_two() -> None:
    record = _record(state=PhysiologicalState(perfusion_status=0.15, sympathetic_activation=0.9))
    _run(record)
    arrival = record.vital_signs[-1]
    assert arrival.systolic_bp < 90 or arrival.consciousness_level in {"P", "U"}
    assert int(record.encounters[0].triage_data.level) <= 2


@pytest.mark.parametrize("admit_source", ["outp", "gp", ""])
def test_admission_not_through_the_ed_is_untouched(admit_source: str) -> None:
    record = _record(admit_source=admit_source)
    _run(record)
    assert record.encounters[0].triage_data is None
    assert record.vital_signs == [_WARD_VITALS]


def test_no_admitted_state_means_triage_without_arrival_vitals() -> None:
    record = _record()
    record.physiological_states = []
    _run(record)
    assert record.encounters[0].triage_data is not None
    assert record.vital_signs == [_WARD_VITALS]


def test_esi_resources_of_an_admission_come_from_its_initial_order_set() -> None:
    record = _record()
    record.vital_signs = []
    enc = record.encounters[0]
    ward = [
        SimpleNamespace(encounter_id=enc.encounter_id, order_type="lab", order_set="", display_name="CBC"),
        SimpleNamespace(encounter_id=enc.encounter_id, order_type="imaging", order_set="", display_name="CXR"),
    ]
    record.orders = ward
    assert triage_level(record, enc, 4) == 5  # no ED resources
    record.orders = [SimpleNamespace(**{**vars(o), "order_set": ORDER_SET_ADMISSION_INITIAL}) for o in ward]
    assert triage_level(record, enc, 4) == 3  # labs + imaging in the ED


def test_vitals_cap_of_an_admission_ignores_ward_readings() -> None:
    record = _record()
    enc = record.encounters[0]
    record.vital_signs = [VitalSignRecord(timestamp=datetime(2026, 3, 2, 8, 0), systolic_bp=70)]
    record.orders = []
    assert triage_level(record, enc, 4) == 5


def _nursing_record(extra: list[VitalSignRecord]):
    ward = [
        VitalSignRecord(timestamp=datetime(2026, 3, 1, 20, 0), heart_rate=90, consciousness_level="V"),
        VitalSignRecord(timestamp=datetime(2026, 3, 2, 8, 0), heart_rate=85, consciousness_level="V"),
    ]
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id="POP-000001", age=70),
        vital_signs=[*extra, *ward],
        adl_assessments=[],
        intake_output_records=[],
        nursing_risk_assessments=[],
    )


def test_nursing_enricher_keeps_the_arrival_gcs_and_draws_nothing_for_it() -> None:
    plain = _nursing_record([])
    arrival = VitalSignRecord(
        timestamp=datetime(2026, 3, 1, 14, 35), consciousness_level="P", gcs_score=9, data_source=ED_TRIAGE_DATA_SOURCE
    )
    with_arrival = _nursing_record([arrival])
    enrich_nursing(SimpleNamespace(master_seed=42, records=[plain]))
    enrich_nursing(SimpleNamespace(master_seed=42, records=[with_arrival]))
    assert arrival.gcs_score == 9
    assert [v.gcs_score for v in with_arrival.vital_signs[1:]] == [v.gcs_score for v in plain.vital_signs]
