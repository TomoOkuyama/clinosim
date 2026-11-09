"""Issue #2985: the death summary's terminal course is built from the last
vitals recorded before death, not from a fixed deterioration phrase."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.mortality import build_dds_terminal_course
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.encounter import VitalSignRecord
from clinosim.types.patient import PatientProfile

_DEATH = datetime(2025, 3, 6, 0, 40)


def _vs(hour: int, day: int = 5, **kw) -> VitalSignRecord:
    base = dict(
        temperature_celsius=36.9,
        heart_rate=138,
        systolic_bp=82,
        diastolic_bp=50,
        respiratory_rate=26,
        spo2=86.0,
        consciousness_level="U",
        on_supplemental_oxygen=True,
        oxygen_flow_rate_lpm=10.0,
    )
    base.update(kw)
    return VitalSignRecord(timestamp=datetime(2025, 3, day, hour, 5), **base)


def _ctx(lang: str, vitals: list) -> NarrativeContext:
    encounter = SimpleNamespace(
        encounter_id="enc-2985",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2025, 3, 1, 10, 40),
        discharge_datetime=_DEATH,
        discharge_disposition="exp",
    )
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-2985"),
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=SimpleNamespace(disease_id="bacterial_pneumonia"),
        encounter_protocol=None,
        clinical_course_archetype="smooth_recovery",
        severity="severe",
        day_index=5,
        los_days=5,
        vitals=vitals,
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DEATH_DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", ["2025-03-05 23:05", "HR 138/min", "BP 82/50 mmHg", "RR 26/min", "SpO2 86% on oxygen", "Unresponsive"]),
        (
            "ja",
            ["2025-03-05 23:05", "心拍数 138/分", "血圧 82/50 mmHg", "呼吸数 26/分", "SpO2 86% (酸素投与下)", "無反応"],
        ),
    ],
)
def test_terminal_course_quotes_the_last_recorded_vitals(lang: str, expected: list[str]) -> None:
    text, facts = build_dds_terminal_course(None, _ctx(lang, [_vs(18, heart_rate=99), _vs(23)]))
    for part in expected:
        assert part in text, (part, text)
    assert "ctx.vitals" in facts


@pytest.mark.parametrize(("lang", "word"), [("en", "hemodynamic"), ("ja", "循環")])
def test_hypotension_reads_as_hemodynamic_deterioration(lang: str, word: str) -> None:
    text, _ = build_dds_terminal_course(None, _ctx(lang, [_vs(23, spo2=95.0, consciousness_level="A")]))
    assert word in text


@pytest.mark.parametrize(("lang", "word"), [("en", "respiratory failure"), ("ja", "呼吸不全")])
def test_hypoxaemia_reads_as_respiratory_failure(lang: str, word: str) -> None:
    text, _ = build_dds_terminal_course(
        None, _ctx(lang, [_vs(23, systolic_bp=118, diastolic_bp=70, consciousness_level="A")])
    )
    assert word in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_vitals_after_death_are_ignored(lang: str) -> None:
    text, _ = build_dds_terminal_course(None, _ctx(lang, [_vs(23), _vs(2, day=6, heart_rate=60)]))
    assert "2025-03-05 23:05" in text and "60" not in text.split("23:05", 1)[1][:30]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_cif_dict_vitals_with_iso_timestamps(lang: str) -> None:
    """The narrate pass hands the builder CIF dicts with ISO-string times."""
    from dataclasses import asdict

    vitals = [{**asdict(v), "timestamp": v.timestamp.isoformat()} for v in (_vs(18, heart_rate=99), _vs(23))]
    ctx = _ctx(lang, vitals)
    ctx.encounter.discharge_datetime = _DEATH.isoformat()
    text, _ = build_dds_terminal_course(None, ctx)
    assert "2025-03-05 23:05" in text and "138" in text


def test_a_later_monitor_pair_does_not_replace_the_last_full_set() -> None:
    monitor = _vs(23, systolic_bp=None, diastolic_bp=None, respiratory_rate=None, consciousness_level="")
    text, _ = build_dds_terminal_course(None, _ctx("en", [_vs(22), monitor]))
    assert "(2025-03-05 22:05)" in text and "BP 82/50 mmHg" in text
