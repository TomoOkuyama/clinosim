"""Issue #3554: one emergency and one diet instruction per summary, drug lines
that fit the prescription course, and facility-addressed instructions for a
facility discharge."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document import reference_data_loaders as rdl
from clinosim.modules.document.narrative.renderers import _resolvers

pytestmark = pytest.mark.unit

_FLUIDS = re.compile(r"plenty of fluids|十分な水分摂取", re.IGNORECASE)


def _ctx(
    disease_id: str | None,
    lang: str = "en",
    *,
    disposition: str = "home",
    meds: tuple[tuple[str, int | None], ...] = (),
    dx: str = "",
) -> SimpleNamespace:
    discharge = []
    for name, days in meds:
        item: dict[str, Any] = {"drug_name": name, "dose": ""}
        if days:
            item["rx_duration_days"] = days
        discharge.append(item)
    return SimpleNamespace(
        patient=SimpleNamespace(sex="M", smoking_status="never", alcohol_use="none", chronic_conditions=[]),
        disease_protocol=load_disease_protocol(disease_id) if disease_id else None,
        diagnoses=[{"admission_diagnosis_code": dx}] if dx else [],
        discharge_medications=discharge,
        encounter=SimpleNamespace(discharge_disposition=disposition),
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _text(ctx: Any) -> str:
    return " ".join(e.get(ctx.target_lang) or e["en"] for e in _resolvers.resolve_discharge_instructions(ctx).values())


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_mi_home_has_one_emergency_and_diet_and_no_fluids(lang: str) -> None:
    entries = _resolvers.resolve_discharge_instructions(_ctx("acute_mi", lang, dx="I21.0"))
    assert sorted(k for k in entries if k in {"emergency", "diet", "warning_signs", "diet_lifestyle"}) == [
        "diet",
        "emergency",
    ]
    assert not _FLUIDS.search(_text(_ctx("acute_mi", lang, dx="I21.0")))


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_mi_facility_has_no_home_emergency_or_normal_diet(lang: str) -> None:
    text = _text(_ctx("acute_mi", lang, disposition="snf", dx="I21.0"))
    assert not re.search(r"911|ambulance|119|直ちに救急|normal diet|通常食", text, re.IGNORECASE)
    assert "Facility staff" in text or "施設スタッフ" in text


def test_facility_dispositions_are_yaml_driven() -> None:
    data = rdl.load_discharge_instructions()
    assert {"snf", "other-hcf"} <= set(data["facility_dispositions"])
    assert _resolvers.discharge_setting(_ctx(None, disposition="other-hcf")) == "facility"
    assert _resolvers.discharge_setting(_ctx(None, disposition="home")) == "home"


def test_short_course_drug_not_in_every_day_list() -> None:
    meds = (("Aspirin", 7), ("Clopidogrel", 365), ("Atorvastatin", 365))
    text = _text(_ctx("acute_mi", meds=meds, dx="I21.0"))
    assert "every day" in text
    sentence = next(s for s in text.split(". ") if "every day" in s)
    assert "Aspirin" not in sentence and "Clopidogrel" in sentence


def test_only_short_course_drugs_falls_back_to_baseline_medication_line() -> None:
    text = _text(_ctx("acute_mi", meds=(("Aspirin", 7),), dx="I21.0"))
    assert "every day" not in text
    assert "Take all prescribed medications" in text


def test_specific_disease_warning_wins_over_generic_protocol_text() -> None:
    text = _text(_ctx("cellulitis"))
    assert "erythema" in text and "Return to ER if symptoms worsen" not in text


def test_fluid_advice_kept_for_uti_and_dropped_for_cirrhosis() -> None:
    assert "Drink 1.5-2 L" in _text(_ctx("urinary_tract_infection"))
    assert not _FLUIDS.search(_text(_ctx("liver_cirrhosis_decompensated", dx="K74.6")))
