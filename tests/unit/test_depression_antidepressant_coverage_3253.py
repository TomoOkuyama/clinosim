"""Issue #3253 — a treated depression carries an antidepressant.

The F32 / F33 SSRI class in ``chronic_medications.yaml`` sums to < 1, so
before the fix a third (US) to half (JP) of patients at every PHQ-9 band
drew "no SSRI" — including PHQ-9 moderate-to-severe patients, for whom
the APA guideline (psychotherapy alone not for severe depression) and the
日本うつ病学会治療ガイドライン (精神療法単独は推奨されない、中等症・重症)
call for an antidepressant. Their follow-up visits still read
"antidepressant management".

Fix: a ``required_coverage`` rule fills the first-line class for the
listed bands with a SHA-salted choice (no draw on the sub-stream), the
visit reason / assessment text follow whether an antidepressant is on
file, and a new-onset depression in the longitudinal engine samples with
the person's country and age.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes.drugs import medication_matches
from clinosim.modules.patient.activator import _derive_home_medications

pytestmark = pytest.mark.unit

MODERATE_PLUS = ("PHQ-9 moderate", "PHQ-9 moderately severe", "PHQ-9 severe")


@dataclass
class _Cond:
    code: str
    stage: str = ""


def _meds(country: str, code: str, stage: str, pid: str):
    return _derive_home_medications([_Cond(code=code, stage=stage)], country=country, patient_id=pid)


def _on_antidepressant(meds) -> bool:
    return any(medication_matches(m, classes=("antidepressant",)) for m in meds)


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("code", ["F32", "F33"])
@pytest.mark.parametrize("stage", MODERATE_PLUS)
def test_moderate_or_worse_depression_always_gets_an_antidepressant(country: str, code: str, stage: str) -> None:
    for i in range(300):
        meds = _meds(country, code, stage, f"POP-{i:06d}")
        assert _on_antidepressant(meds), f"{country} {code} {stage} POP-{i:06d}: {[m.drug_name for m in meds]}"
        if country == "JP":
            assert not any(m.drug_name.lower() == "fluoxetine" for m in meds), "fluoxetine is not marketed in JP"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_mild_depression_keeps_a_non_drug_share(country: str) -> None:
    untreated = sum(
        1 for i in range(300) if not _on_antidepressant(_meds(country, "F32", "PHQ-9 mild", f"POP-{i:06d}"))
    )
    assert untreated > 0, "mild depression keeps the psychotherapy / watchful-waiting share"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_patients_with_a_drawn_ssri_keep_it(country: str) -> None:
    """The SSRI class draw is unchanged: a patient who drew an SSRI at the
    mild band draws the same one at the severe band (coverage only fills
    the residual branch)."""
    for i in range(300):
        pid = f"POP-{i:06d}"
        mild = [m.drug_name for m in _meds(country, "F32", "PHQ-9 mild", pid)]
        if mild:
            severe = [m.drug_name for m in _meds(country, "F32", "PHQ-9 severe", pid)]
            assert mild[0] in severe, (pid, mild, severe)


def test_coverage_consumes_no_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    from clinosim.locale import loader

    data = loader.load_chronic_medications()
    stripped = {
        k: ({kk: vv for kk, vv in v.items() if kk != "required_coverage"} if isinstance(v, dict) else v)
        for k, v in data.items()
    }
    for seed in range(50):
        rng_a = np.random.default_rng(seed)
        _derive_home_medications([_Cond("F32", "PHQ-9 severe")], rng_a, country="US", patient_id=f"P{seed}")
        with monkeypatch.context() as m:
            m.setattr("clinosim.locale.loader.load_chronic_medications", lambda: stripped)
            rng_b = np.random.default_rng(seed)
            _derive_home_medications([_Cond("F32", "PHQ-9 severe")], rng_b, country="US", patient_id=f"P{seed}")
        assert rng_a.random() == rng_b.random()


# ---------------------------------------------------------------------------
# Visit reason
# ---------------------------------------------------------------------------


def _hm(drug: str):
    from clinosim.types.patient import HomeMedication

    return HomeMedication(drug_name=drug)


@pytest.mark.parametrize("code", ["F32", "F33"])
@pytest.mark.parametrize("country", ["US", "JP"])
def test_visit_reason_follows_whether_an_antidepressant_is_on_file(code: str, country: str) -> None:
    from clinosim.locale.loader import load_chronic_followup
    from clinosim.simulator.outpatient import _visit_chief_complaint

    spec = load_chronic_followup()[code]
    untreated, _ = _visit_chief_complaint(spec, code, "", country, home_medications=[_hm("Amlodipine")])
    treated, _ = _visit_chief_complaint(spec, code, "", country, home_medications=[_hm("Sertraline")])
    for word in ("antidepressant", "抗うつ薬"):
        assert word not in untreated, untreated
    assert ("抗うつ薬" if country == "JP" else "antidepressant") in treated, treated
    assert untreated


# ---------------------------------------------------------------------------
# Assessment line
# ---------------------------------------------------------------------------


def _ctx(meds: list, lang: str):
    from clinosim.types.document import DocumentType, NarrativeContext
    from clinosim.types.patient import ChronicCondition, PatientProfile

    patient = PatientProfile(patient_id="pt-3253")
    patient.chronic_conditions = [ChronicCondition(code="F32", stage="PHQ-9 mild")]
    patient.current_medications = meds
    patient.age = 40
    patient.sex = "F"
    patient.date_of_birth = date(1986, 1, 1)
    vital = SimpleNamespace(
        systolic_bp=118, diastolic_bp=72, heart_rate=70, temperature_celsius=36.6, spo2=98.0, respiratory_rate=None
    )
    return NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc-3253", admission_datetime=datetime(2026, 8, 1, 10, 0)),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="mild",
        day_index=0,
        los_days=0,
        vitals=[vital],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_untreated_depression_assessment_does_not_claim_continued_management(lang: str) -> None:
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    gen = TemplateNarrativeGenerator()
    untreated = gen._compose_chronic_assessment_integrated(_ctx([], lang))
    treated = gen._compose_chronic_assessment_integrated(_ctx([_hm("Sertraline")], lang))
    assert ("management continued" if lang == "en" else "現行管理継続") not in untreated, untreated
    assert ("no pharmacotherapy" if lang == "en" else "薬物療法なし") in untreated, untreated
    assert ("management continued" if lang == "en" else "現行管理継続") in treated, treated


# ---------------------------------------------------------------------------
# Longitudinal new onset: the person's country and age
# ---------------------------------------------------------------------------


def test_new_onset_depression_in_jp_never_gets_fluoxetine() -> None:
    from clinosim.modules.longitudinal.engine import _add_base_chronic_meds_for_new_icd
    from clinosim.types.population import PersonRecord

    got_any = False
    for i in range(300):
        person = PersonRecord(
            person_id=f"POP-{i:06d}", household_id="HH", age=40, sex="F", date_of_birth=date(1986, 1, 1)
        )
        _add_base_chronic_meds_for_new_icd(person, "F32", country="JP", patient_age=40)
        names = [m.drug_name.lower() for m in person.current_medications]
        assert "fluoxetine" not in names, (person.person_id, names)
        got_any = got_any or bool(names)
    assert got_any
