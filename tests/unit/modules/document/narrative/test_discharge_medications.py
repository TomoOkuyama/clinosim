"""β-JP-1 chain 1a adv-1 I-1: discharge_medications = rx items only.

Pre-fix, ``_collect_medications`` merged ALL medication_administrations (MAR)
with ``discharge_prescription.items`` into ``ctx.medications``, and
``_build_discharge_medications`` rendered that whole list — so ICU drips
(Dobutamine / Norepinephrine) and protocol-prefixed in-hospital orders
(``DVT_prophylaxis: Enoxaparin...``) leaked into the discharge medication
narrative. The fix separates the sources:

- ``ctx.medications``  — MAR only (in-hospital administrations; consumed by
  ``extract_medication_facts`` / ``section_extractor``).
- ``ctx.discharge_medications`` — normalized ``discharge_prescription.items``
  only (consumed by ``_build_discharge_medications``).
- Protocol prefixes are stripped at render time via the promoted
  ``clinosim.modules._shared.strip_protocol_prefix``.
"""

from __future__ import annotations

import pytest

from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.passes import NarrativePass
from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit


_MAR = [
    {"drug_name": "Heparin", "dose": "5000 IU"},
    {"drug_name": "Nitroglycerin", "dose": ""},
    {"drug_name": "Dobutamine 2-20ug/kg/min IV drip", "dose": ""},
    {"drug_name": "Norepinephrine 0.05-0.3ug/kg/min IV drip", "dose": ""},
    {"drug_name": "DVT_prophylaxis: Enoxaparin 2000IU SC daily", "dose": ""},
]

_RX = {
    "prescription_id": "RX-P1-DC",
    "items": [
        {"drug_name": "Aspirin", "dose": "100mg"},
        {"drug_name": "Ticagrelor", "dose": "90mg"},
        {"drug_name": "Atorvastatin", "dose": "40mg"},
    ],
}

_PATIENT_DICT = {
    "medication_administrations": _MAR,
    "discharge_prescription": _RX,
}


# --- source collection (passes.py) ------------------------------------------


def test_collect_medications_is_mar_only():
    meds = NarrativePass._collect_medications(_PATIENT_DICT)
    names = [m["drug_name"] for m in meds]
    assert names == [m["drug_name"] for m in _MAR]
    # rx items must NOT be merged into ctx.medications any more
    assert "Aspirin" not in names


def test_collect_discharge_medications_is_rx_only():
    meds = NarrativePass._collect_discharge_medications(_PATIENT_DICT)
    assert [m["drug_name"] for m in meds] == ["Aspirin", "Ticagrelor", "Atorvastatin"]
    assert [m["dose"] for m in meds] == ["100mg", "90mg", "40mg"]


def test_collect_discharge_medications_normalizes_outpatient_drug_key():
    """outpatient.py renewal items carry ``drug`` (not ``drug_name``)."""
    patient_dict = {
        "discharge_prescription": {
            "items": [{"drug": "Metformin", "duration_days": 30}],
        },
    }
    meds = NarrativePass._collect_discharge_medications(patient_dict)
    assert meds == [{"drug_name": "Metformin", "dose": ""}]


def test_collect_discharge_medications_empty_when_no_rx():
    assert NarrativePass._collect_discharge_medications({}) == []


# --- rendering (template_generator.py) --------------------------------------


def _spec(type_key: str, country: str = "us"):
    for s in specs_for_country(country):
        if s.type_key == type_key:
            return s
    raise AssertionError(f"spec {type_key} not found")


def _ctx(lang: str = "en") -> NarrativeContext:
    return NarrativeContext(
        patient={"patient_id": "P1"},
        encounter={"encounter_id": "ENC-1"},
        encounter_type="inpatient",
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=4,
        los_days=4,
        vitals=[],
        lab_results=[],
        medications=list(_MAR),
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="us" if lang == "en" else "jp",
    )


def test_discharge_medications_section_renders_rx_items_only():
    """MI case: 3 rx drugs only — no ICU drips, no MAR leakage."""
    ctx = _ctx()
    ctx.discharge_medications = [
        {"drug_name": "Aspirin", "dose": "100mg"},
        {"drug_name": "Ticagrelor", "dose": "90mg"},
        {"drug_name": "Atorvastatin", "dose": "40mg"},
    ]
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_discharge_medications(ctx)
    assert text == "Aspirin; Ticagrelor; Atorvastatin"
    assert "drip" not in text
    assert "ctx.discharge_medications" in facts


def test_discharge_medications_section_strips_protocol_prefix():
    ctx = _ctx()
    ctx.discharge_medications = [
        {"drug_name": "DVT_prophylaxis: Enoxaparin 2000IU SC daily", "dose": ""},
        {"drug_name": "antipyretic: Acetaminophen 500mg PO q6h", "dose": ""},
    ]
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_discharge_medications(ctx)
    assert text == "Enoxaparin 2000IU SC daily; Acetaminophen 500mg PO q6h"


def test_discharge_medications_section_ignores_mar_in_ctx_medications():
    """ctx.medications (MAR) must no longer feed the discharge section."""
    ctx = _ctx()  # MAR present, discharge_medications empty
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_discharge_medications(ctx)
    assert text == "No discharge medications"
    assert facts == []


def test_discharge_medications_none_text_ja():
    ctx = _ctx(lang="ja")
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_discharge_medications(ctx)
    assert text == "退院処方なし"


# --- promoted shared helper ---------------------------------------------------


def test_strip_protocol_prefix_shared():
    assert strip_protocol_prefix("DVT_prophylaxis: Enoxaparin 2000IU SC daily") == (
        "Enoxaparin 2000IU SC daily",
        "DVT prophylaxis",
    )
    assert strip_protocol_prefix("Ceftriaxone 1g IV q8h") == ("Ceftriaxone 1g IV q8h", "")


def test_strip_protocol_prefix_fhir_alias_unchanged():
    """FHIR builders keep importing the same logic (single edit point)."""
    from clinosim.modules.output._fhir_common import _strip_protocol_prefix

    assert _strip_protocol_prefix is strip_protocol_prefix
