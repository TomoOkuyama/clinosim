"""Issue #3264: the asthma exacerbation discharge instructions follow age —
peak flow only from 12 years, the controller named is the discharged one, the
control review uses the age-appropriate instrument."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.renderers import _resolvers

pytestmark = pytest.mark.unit


def _resolved(age: int, lang: str, meds: tuple[str, ...]) -> str:
    patient = SimpleNamespace(
        sex="F",
        age=age,
        date_of_birth=date(2026 - age, 1, 1),
        smoking_status="never",
        alcohol_use="none",
        chronic_conditions=[],
    )
    ctx = SimpleNamespace(
        patient=patient,
        encounter=SimpleNamespace(admission_datetime=date(2026, 6, 1), discharge_datetime=date(2026, 6, 4)),
        disease_protocol=load_disease_protocol("asthma_exacerbation"),
        diagnoses=[],
        discharge_medications=[{"drug_name": m, "dose": ""} for m in meds],
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )
    return " ".join(e.get(lang) or e["en"] for e in _resolvers.resolve_discharge_instructions(ctx).values())


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_child_gets_no_peak_flow_and_the_controller_it_takes(lang: str) -> None:
    text = _resolved(3, lang, ("Budesonide",))
    assert "peak flow" not in text.lower() and "ピークフロー" not in text
    assert "ICS/LABA" not in text
    assert ("Budesonide" in text) or ("ブデソニド" in text)
    assert "ACT" not in text.replace("Childhood ACT", "").replace("C-ACT", "")


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_school_child_is_reviewed_with_the_childhood_act(lang: str) -> None:
    text = _resolved(8, lang, ("Fluticasone propionate",))
    assert "peak flow" not in text.lower() and "ピークフロー" not in text
    assert "Childhood ACT" in text or "C-ACT" in text
    assert "Fluticasone" in text or "フルチカゾン" in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_an_adult_keeps_peak_flow_and_the_act(lang: str) -> None:
    text = _resolved(40, lang, ("Fluticasone/Salmeterol",))
    assert "peak flow" in text.lower() or "ピークフロー" in text
    assert "ACT" in text
    assert "Fluticasone" in text or "フルチカゾン" in text
