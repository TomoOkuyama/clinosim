"""Issue #3254: discharge instructions follow the patient — sex, smoking and
alcohol status, heart failure, the discharge prescription — and say each
thing once."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document import reference_data_loaders as rdl
from clinosim.modules.document.narrative.renderers import _resolvers
from clinosim.modules.document.narrative.renderers.section_builders import discharge_summary

pytestmark = pytest.mark.unit

_SMOKING = re.compile(r"smok|禁煙|喫煙", re.IGNORECASE)
_ALCOHOL = re.compile(r"alcohol|飲酒", re.IGNORECASE)
_FEMALE = re.compile(r"\(female\)|\(女性\)|front[- ]to[- ]back|前から後ろ", re.IGNORECASE)
_FLUIDS = re.compile(r"Drink plenty of fluids|十分な水分摂取|adequate hydration", re.IGNORECASE)
_BETA = re.compile(r"beta[- ]blocker|β ?遮断薬", re.IGNORECASE)


def _ctx(
    disease_id: str | None,
    lang: str,
    *,
    sex: str = "M",
    smoking: str = "never",
    alcohol: str = "none",
    chronic: tuple[str, ...] = (),
    meds: tuple[str, ...] = (),
    dx: str = "",
) -> SimpleNamespace:
    patient = SimpleNamespace(
        sex=sex,
        smoking_status=smoking,
        alcohol_use=alcohol,
        chronic_conditions=[{"code": c} for c in chronic],
    )
    return SimpleNamespace(
        patient=patient,
        disease_protocol=load_disease_protocol(disease_id) if disease_id else None,
        diagnoses=[{"admission_diagnosis_code": dx}] if dx else [],
        discharge_medications=[{"drug_name": m, "dose": ""} for m in meds],
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _text(ctx: Any) -> str:
    generator = SimpleNamespace(_resolve_discharge_instructions=_resolvers.resolve_discharge_instructions)
    text, _ = discharge_summary.build_discharge_instructions(generator, ctx)
    return text


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s*", text) if s.strip()]


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("disease", ["urinary_tract_infection", "bacterial_pneumonia"])
def test_male_never_smoker_gets_no_female_or_smoking_advice(lang: str, disease: str) -> None:
    text = _text(_ctx(disease, lang, sex="M", smoking="never"))
    assert text
    assert not _FEMALE.search(text), text
    assert not _SMOKING.search(text), text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_female_uti_patient_gets_hygiene_advice(lang: str) -> None:
    text = _text(_ctx("urinary_tract_infection", lang, sex="F"))
    assert _FEMALE.search(text), text
    assert "(female)" not in text and "(女性)" not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("disease", ["bacterial_pneumonia", "copd_exacerbation", "acute_mi"])
def test_current_smoker_gets_cessation_advice(lang: str, disease: str) -> None:
    assert _SMOKING.search(_text(_ctx(disease, lang, smoking="current")))


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_alcohol_advice_only_for_drinkers(lang: str) -> None:
    assert not _ALCOHOL.search(_text(_ctx("acute_mi", lang, alcohol="none")))
    assert _ALCOHOL.search(_text(_ctx("acute_mi", lang, alcohol="social")))


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize(
    ("disease", "chronic", "dx"),
    [
        ("atrial_fibrillation_rvr", ("I50",), "I48.91"),
        ("urinary_tract_infection", ("I50.9",), "N39.0"),
        ("heart_failure_exacerbation", (), "I50.9"),
        (None, ("I50",), ""),
    ],
)
def test_heart_failure_patient_is_not_told_to_drink_plenty(
    lang: str, disease: str | None, chronic: tuple[str, ...], dx: str
) -> None:
    text = _text(_ctx(disease, lang, chronic=chronic, dx=dx))
    assert not _FLUIDS.search(text), text
    assert re.search(r"weigh|体重", text, re.IGNORECASE), text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_patient_without_heart_failure_keeps_fluid_advice(lang: str) -> None:
    assert _FLUIDS.search(_text(_ctx("bacterial_pneumonia", lang)))


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_mi_medications_name_only_prescribed_drugs(lang: str) -> None:
    meds = ("Aspirin", "Clopidogrel", "Atorvastatin", "Amlodipine")
    text = _text(_ctx("acute_mi", lang, meds=meds))
    assert not _BETA.search(text), text
    assert not re.search(r"ACE|ARB", text), text
    names = (
        ("Aspirin", "Clopidogrel", "Atorvastatin")
        if lang == "en"
        else ("アスピリン", "クロピドグレル", "アトルバスタチン")
    )
    for name in names:
        assert name in text, text
    assert "Amlodipine" not in text and "アムロジピン" not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_mi_with_beta_blocker_names_it(lang: str) -> None:
    text = _text(_ctx("acute_mi", lang, meds=("Aspirin", "Metoprolol")))
    assert ("Metoprolol" if lang == "en" else "メトプロロール") in text, text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_mi_without_cardiac_drugs_falls_back_to_generic_medication_advice(lang: str) -> None:
    text = _text(_ctx("acute_mi", lang, meds=()))
    assert "{drugs}" not in text
    assert not _BETA.search(text), text
    assert not re.search(r"statin|スタチン|aspirin|アスピリン", text, re.IGNORECASE), text


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("disease", sorted(rdl.load_discharge_instructions()["disease_specific"]))
def test_no_sentence_repeats(lang: str, disease: str) -> None:
    ctx = _ctx(disease, lang, sex="F", smoking="current", alcohol="heavy", chronic=("I50",))
    sentences = _sentences(_text(ctx))
    assert len(sentences) == len(set(sentences)), sentences


def test_dedupe_drops_repeated_sentences_across_entries() -> None:
    merged = {
        "a": {"en": "Rest well. Stop smoking.", "ja": "休んでください。禁煙してください。"},
        "b": {"en": "Stop smoking.", "ja": "禁煙してください。"},
    }
    out = _resolvers.dedupe_instruction_sentences(merged)
    assert out == {"a": {"en": "Rest well. Stop smoking.", "ja": "休んでください。禁煙してください。"}}


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_pneumonia_has_no_unresolved_device_conditional(lang: str) -> None:
    text = _text(_ctx("bacterial_pneumonia", lang))
    assert not re.search(r"if provided|処方時", text), text


def test_gate_with_unknown_condition_group_fails_at_load() -> None:
    bad = {
        "baseline": {
            "hydrate": {"en": "Drink.", "ja": "飲水。", "applies_when": {"exclude_conditions": ["no_such_group"]}},
            "rest": {"en": "Rest.", "ja": "休息。"},
            "follow_up": {"en": "Follow up.", "ja": "受診。"},
        },
        "disease_specific": {},
    }
    with pytest.raises(ValueError, match="no_such_group"):
        rdl.DischargeInstructions.model_validate(bad)


def test_gate_with_unknown_drug_class_fails_at_load() -> None:
    bad = {
        "baseline": {
            "hydrate": {"en": "Drink.", "ja": "飲水。"},
            "rest": {"en": "Rest.", "ja": "休息。"},
            "follow_up": {"en": "Follow up.", "ja": "受診。"},
            "meds": {"en": "Take {drugs}.", "ja": "{drugs}。", "applies_when": {"discharge_drugs": ["no_such_class"]}},
        },
        "disease_specific": {},
    }
    with pytest.raises(ValueError, match="no_such_class"):
        rdl.DischargeInstructions.model_validate(bad)


def test_drug_placeholder_needs_a_drug_gate() -> None:
    bad = {
        "baseline": {
            "hydrate": {"en": "Drink.", "ja": "飲水。"},
            "rest": {"en": "Rest.", "ja": "休息。"},
            "follow_up": {"en": "Follow up.", "ja": "受診。"},
            "meds": {"en": "Take {drugs}.", "ja": "{drugs}。"},
        },
        "disease_specific": {},
    }
    with pytest.raises(ValueError, match="discharge_drugs"):
        rdl.DischargeInstructions.model_validate(bad)


def test_population_hook_selects_the_baseline_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # The adult baseline is the default; a population-specific set (the
    # neonatal set of Issue #3260) replaces it through one hook.
    ctx = _ctx(None, "en")
    assert _resolvers.baseline_instruction_set(ctx) == rdl.load_discharge_instructions()["baseline"]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_heart_failure_salt_advice_has_no_numeric_target(lang: str) -> None:
    # Neither AHA/ACC/HFSA 2022 §7.1.2 nor JCS/JHFS 2025 §11 2.4.3 sets a
    # numeric sodium / salt target: avoid excess, individualized advice.
    text = _text(_ctx("heart_failure_exacerbation", lang, dx="I50.9"))
    assert re.search(r"excessive sodium|減塩", text), text
    assert not re.search(r"(sodium|salt|塩分)[^.。]*\d+\s*(g|mg)", text, re.IGNORECASE), text
