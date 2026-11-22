"""A supportive order's drug is named, a monitoring target is not a drug (Issue #3560)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._drug_names import (
    administered_drug_key,
    administered_drug_label,
    administered_drug_name,
)
from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note

pytestmark = pytest.mark.unit

_DAY = "2026-08-31"
_LACT = "lactulose: 30mL PO TID if encephalopathy"
_FLUID = "IV_fluid: NS 150-200 mL/h, target UOP > 1-1.5 mL/kg/h"


def _ctx(lang: str, meds: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        authored_datetime=datetime(2026, 8, 31, 17, 0),
        day_index=0,
        shift="day",
        encounter={"admission_datetime": "2026-08-31T09:54:00", "primary_nurse_id": ""},
        roster_map={},
        vitals=[],
        medications=meds,
        nursing_risk_assessments=[],
        patient={"date_of_birth": "1950-01-01"},
        disease_protocol=None,
        author_practitioner_id="",
    )


def _text(lang: str, meds: list[dict]) -> str:
    return render_nursing_shift_note(_ctx(lang, meds), SimpleNamespace()).raw_text


def _row(name: str, drug_id: str = "", status: str = "given", **kw) -> dict:
    return {"drug_name": name, "drug_id": drug_id, "status": status, "actual_datetime": f"{_DAY}T12:00:00", **kw}


def test_drug_prefix_is_kept_category_prefix_is_dropped() -> None:
    assert administered_drug_key({"drug_name": _LACT, "drug_id": "lactulose"}) == "lactulose"
    assert administered_drug_key({"drug_name": _LACT}) == "lactulose"
    assert administered_drug_name({"drug_name": _LACT}, "ja") == "ラクツロース"
    assert administered_drug_name({"drug_name": _LACT}, "en").lower() == "lactulose"
    label = administered_drug_label({"drug_name": _LACT, "drug_id": "lactulose"}, "ja")
    assert label.startswith("ラクツロース") and "30mL" in label and not label.startswith("30")
    assert administered_drug_key({"drug_name": "antipyretic: Acetaminophen 500mg PO q6h"}) == "acetaminophen"
    assert administered_drug_label({"drug_name": "antipyretic: Acetaminophen 500mg PO q6h"}, "en").startswith(
        "Acetaminophen"
    )


def test_monitoring_target_is_not_part_of_the_drug() -> None:
    for lang in ("en", "ja"):
        label = administered_drug_label({"drug_name": _FLUID}, lang)
        assert "UOP" not in label and "尿量" not in label and "target" not in label.lower() and "目標" not in label
        assert "150-200 mL/h" in label


def test_nameless_dose_falls_back_to_drug_id() -> None:
    assert administered_drug_label({"drug_name": "30mL PO TID", "drug_id": "lactulose"}, "ja") == "ラクツロース"


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_shift_note_meds_line_names_the_drug(lang: str) -> None:
    text = _text(lang, [_row(_LACT, "lactulose"), _row(_FLUID, "normal_saline")])
    assert ("ラクツロース" if lang == "ja" else "ctulose") in text
    assert not re.search(r"(^|[、,]\s*)\d+\s?mL", text)
    assert "UOP" not in text and "目標" not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_refusal_sentence_names_the_drug(lang: str) -> None:
    row = _row(_LACT, "lactulose", status="refused", scheduled_datetime=f"{_DAY}T12:00:00", route="PO")
    text = _text(lang, [row])
    assert ("ラクツロース" if lang == "ja" else "ctulose") in text
    assert "30mL PO" not in text and "if encephalopathy" not in text


def test_no_narrative_strips_the_prefix_for_a_drug_label() -> None:
    root = Path(__file__).resolve().parents[5] / "clinosim" / "modules" / "document"
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.name != "_drug_names.py" and "strip_protocol_prefix" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
