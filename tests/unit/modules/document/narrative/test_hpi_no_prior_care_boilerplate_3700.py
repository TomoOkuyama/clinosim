"""The HPI no longer asserts who continues the home therapy or by which route
(Issue #3700): the home-medication sentence already states the therapy, and
neither the primary care physician nor an oral route is in the record."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_PHRASES = Path(__file__).resolve().parents[5] / "clinosim" / "locale" / "shared" / "narrative_phrases.yaml"


def _hpi(lang_country: str, meds: list[dict], conditions: list[str]) -> str:
    record = {
        "patient": {
            "patient_id": "POP-3700",
            "age": 70,
            "sex": "M",
            "current_medications": meds,
            "chronic_conditions": conditions,
        },
        "encounters": [
            {
                "encounter_id": "ENC-3700",
                "encounter_type": "inpatient",
                "admission_datetime": "2026-06-21T10:00:00",
                "chief_complaint": "Dyspnea" if lang_country == "US" else "呼吸困難",
            }
        ],
    }
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.ADMISSION_HP, 0, lang_country)
    return build_hpi(TemplateNarrativeGenerator(), ctx)[0]


_INHALER = [{"drug_name": "Tiotropium", "route": "inhaled"}]
_BOTH = [{"drug_name": "Tiotropium", "route": "inhaled"}, {"drug_name": "Metformin", "route": "oral"}]


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("meds", [_INHALER, _BOTH])
def test_no_primary_care_or_route_assertion(country: str, meds: list[dict]) -> None:
    text = _hpi(country, meds, ["J44.9", "E11.9"])
    for phrase in (
        "primary care physician",
        "Oral therapy",
        "Oral prescriptions",
        "かかりつけ医",
        "内服治療継続",
        "内服処方継続",
    ):
        assert phrase not in text, text


def test_home_medications_are_still_stated() -> None:
    assert "Home medications:" in _hpi("US", _INHALER, ["J44.9"])


def test_keys_are_removed() -> None:
    for key in ("prior_care_chronic", "prior_care_outpatient"):
        assert key not in _PHRASES.read_text(encoding="utf-8")
