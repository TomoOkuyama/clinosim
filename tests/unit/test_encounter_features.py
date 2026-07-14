"""Unit tests for encounter features: outpatient, ED, ward/bed, diet, ADL, I/O, nursing."""

import pytest

from clinosim.simulator import run_beta, run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.fixture(scope="module")
def us_inpatient():
    scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="moderate")
    config = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, config)
    return dataset.patients[0]


@pytest.fixture(scope="module")
def small_population():
    config = SimulatorConfig(catchment_population=2000, random_seed=42, country="US")
    return run_beta(config)


class TestWardBed:
    def test_inpatient_has_ward(self, us_inpatient):
        assert us_inpatient.encounters[0].ward_id != ""

    def test_inpatient_has_bed(self, us_inpatient):
        assert us_inpatient.encounters[0].bed_number != ""

    def test_ward_format(self, us_inpatient):
        ward = us_inpatient.encounters[0].ward_id
        assert len(ward) == 2  # e.g. "3W"
        assert ward[0].isdigit()


class TestDietOrders:
    def test_has_diet_orders(self, us_inpatient):
        diets = [o for o in us_inpatient.orders if o.order_type.value == "diet"]
        assert len(diets) > 0

    def test_first_diet_is_npo(self, us_inpatient):
        diets = [o for o in us_inpatient.orders if o.order_type.value == "diet"]
        assert diets[0].display_name == "NPO"


class TestADL:
    def test_has_adl_assessments(self, us_inpatient):
        assert len(us_inpatient.adl_assessments) > 0

    def test_barthel_score_range(self, us_inpatient):
        for adl in us_inpatient.adl_assessments:
            assert 0 <= adl.barthel_score <= 100


class TestIO:
    def test_has_io_records(self, us_inpatient):
        assert len(us_inpatient.intake_output_records) > 0

    def test_io_has_positive_values(self, us_inpatient):
        for io in us_inpatient.intake_output_records:
            assert io.intake_iv_ml >= 0
            assert io.output_urine_ml >= 0


class TestPainScore:
    def test_full_round_vitals_have_pain_score(self, us_inpatient):
        # Pain score is recorded with full round vitals (not continuous monitor or recheck)
        full_vitals = [v for v in us_inpatient.vital_signs
                       if v.temperature_celsius is not None
                       and v.systolic_bp is not None
                       and v.respiratory_rate is not None]
        assert len(full_vitals) > 0
        assert all(v.pain_score is not None for v in full_vitals)

    def test_pain_score_range(self, us_inpatient):
        for v in us_inpatient.vital_signs:
            if v.pain_score is not None:
                assert 0 <= v.pain_score <= 10


class TestNursingNotes:
    def test_some_vitals_have_notes(self, us_inpatient):
        notes = [v for v in us_inpatient.vital_signs if v.nursing_note]
        assert len(notes) > 0  # at least admission note


class TestEDVisits:
    def test_ed_visits_generated(self, small_population):
        ed = [r for r in small_population.patients
              if r.encounters and r.encounters[0].encounter_type.value == "emergency"]
        assert len(ed) > 0

    def test_ed_has_chief_complaint(self, small_population):
        ed = [r for r in small_population.patients
              if r.encounters and r.encounters[0].encounter_type.value == "emergency"]
        if ed:
            assert ed[0].encounters[0].chief_complaint != ""


class TestEDAcuteInjection:
    """ED encounter scenarios fold their acute physiological impact into labs/vitals (AD-57)."""

    def _labs(self, condition_id, severity):
        from clinosim.modules.encounter.protocol import load_encounter_condition
        from clinosim.modules.physiology.engine import apply_disease_onset, derive_lab_values
        from clinosim.types.clinical import PhysiologicalState

        proto = load_encounter_condition(condition_id)
        state = PhysiologicalState()
        state = apply_disease_onset(
            state, severity, proto.get("initial_state_impact", {}),
            acid_base_type=proto.get("acid_base_type", "metabolic"))
        return derive_lab_values(state, sex="M", age=45)

    def test_uti_drives_inflammation(self):
        """Infectious ED presentation raises WBC/CRP with severity."""
        mild = self._labs("uti_uncomplicated", "mild")
        severe = self._labs("uti_uncomplicated", "severe")
        assert severe["WBC"] > mild["WBC"] > 7000
        assert severe["CRP"] > mild["CRP"]

    def test_gastroenteritis_drives_dehydration(self):
        """Volume loss raises BUN (prerenal) at severe."""
        severe = self._labs("viral_gastroenteritis", "severe")
        assert severe["BUN"] > 15

    def test_panic_attack_respiratory_alkalosis(self):
        """Hyperventilation → low pCO2, high pH (no metabolic acidosis)."""
        severe = self._labs("anxiety_panic_attack", "severe")
        assert severe["pCO2"] < 38
        assert severe["pH"] > 7.42

    def test_empty_impact_is_noop(self):
        """A local-only presentation (mild bite) leaves the baseline untouched."""
        baseline = self._labs("animal_bite", "mild")
        assert abs(baseline["WBC"] - 7000) < 800  # ~baseline, no systemic inflammation


class TestOutpatient:
    def test_outpatient_visits_generated(self, small_population):
        opd = [r for r in small_population.patients
               if r.encounters and r.encounters[0].encounter_type.value == "outpatient"]
        assert len(opd) > 0

    def test_outpatient_has_diagnosis(self, small_population):
        opd = [r for r in small_population.patients
               if r.encounters and r.encounters[0].encounter_type.value == "outpatient"]
        for r in opd[:5]:
            assert r.clinical_diagnosis.discharge_diagnosis_code != ""


class TestLabUnits:
    def test_all_labs_have_units(self, us_inpatient):
        for lab in us_inpatient.lab_results:
            assert lab.unit != "", f"Lab {lab.lab_name} missing unit"
