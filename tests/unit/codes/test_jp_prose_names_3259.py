"""Issue #3259: Japanese prose names a diagnosis as a chart does.

The MHLW ICD-10 title is the coding display (``coding.display``); prose uses
the clinical name of ``condition_label``. Before the fix Japanese narrative
printed classification titles with their index notation
(「本態性（原発性＜一次性＞）高血圧（症）」, 「アルツハイマー＜Alzheimer＞病の認知症
（G30.-†）」, 「胃，部位不明」 for gastric cancer, 「急性腎不全，詳細不明」 on the
death certificate), and the diabetic-retinopathy code E11.311 (ICD-10-CM) was
printed on JP records as a second plain 「2型糖尿病」.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clinosim.codes.icd10 import condition_label, condition_short_name, icd10_display
from clinosim.codes.loader import code_exists
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules.document.narrative.renderers._shared_helpers import diagnosis_coded

pytestmark = pytest.mark.unit

_DATA = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "data"

# Notation of the classification that a clinical name never carries: the
# ＜＞ synonym and ［］ inclusion brackets, the dagger-asterisk markers, an
# optional part in parentheses (（症）, （性）, （四）肢, （大脳）, 神経（学的）, 軸捻（転）),
# the comma of a qualifier (「，詳細不明」, 「，他に分類されないもの」) and
# full-width digits (２型).
_NOTATION = re.compile(
    r"[＜＞［］†＊０-９，]|（(症|性|四|大脳|学的|転)）|（[A-Z][0-9]|詳細不明|部位不明|程度不明|分類されない"
)


def _who_codes() -> list[str]:
    return sorted(yaml.safe_load((_DATA / "icd-10.yaml").read_text(encoding="utf-8"))["codes"])


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("I10", "高血圧"),
        ("E11.9", "2型糖尿病"),
        ("C16.9", "胃癌"),
        ("F00", "アルツハイマー型認知症"),
        ("E11.3", "糖尿病網膜症"),
        ("N17.9", "急性腎障害"),
        ("E66.9", "肥満"),
        ("F17.2", "ニコチン依存症"),
        ("J44.1", "COPD急性増悪"),
    ],
)
def test_jp_prose_label(code: str, label: str) -> None:
    assert condition_label(code, "JP", "ja") == label


def test_every_jp_icd_code_has_a_prose_name_without_classification_notation() -> None:
    bad = {
        code: condition_label(code, "JP", "ja")
        for code in _who_codes()
        if _NOTATION.search(condition_label(code, "JP", "ja") or "")
    }
    assert not bad


def test_short_name_resolves_the_most_specific_key_first() -> None:
    # Subcategory key, then the category: E11.311 (ICD-10-CM) and E11.3 (WHO)
    # both name the retinopathy, E11.9 the diabetes.
    assert condition_short_name("E11.311", "en") == "Diabetic retinopathy"
    assert condition_short_name("E11.3", "ja") == "糖尿病網膜症"
    assert condition_short_name("E11.9", "ja") == "2型糖尿病"
    assert condition_short_name("Q99.9", "ja") is None


@pytest.mark.parametrize(("cm", "who"), [("E11.21", "E11.2"), ("E11.311", "E11.3"), ("E11.42", "E11.4")])
def test_jp_diabetes_complication_codes_are_mhlw_icd10(cm: str, who: str) -> None:
    assert map_diagnosis_code(cm, "JP") == who
    assert code_exists("icd-10-mhlw", who, exact=True)
    # The coding display stays the official MHLW title.
    assert icd10_display(who, "JP", "ja").startswith("２型＜インスリン非依存性＞糖尿病＜NIDDM＞，")


def test_diagnosis_coded_maps_the_internal_code_and_names_it() -> None:
    assert diagnosis_coded("E11.311", "JP", "ja") == ("E11.3", "糖尿病網膜症")
    assert diagnosis_coded("J45.21", "JP", "ja") == ("J45.9", "喘息")
    assert diagnosis_coded("N17.9", "JP", "ja") == ("N17.9", "急性腎障害")
    # English coded lists keep the official display (ICD-10-CM titles read
    # as clinical names and carry no abbreviation).
    assert diagnosis_coded("N17.9", "US", "en") == ("N17.9", "Acute kidney failure, unspecified")
    # A code without any name falls back to the code.
    assert diagnosis_coded("Q99.9", "JP", "ja") == ("Q99.9", "Q99.9")


def _ctx(conditions: list, lang: str = "ja") -> SimpleNamespace:
    from clinosim.types.document import DocumentType

    return SimpleNamespace(
        patient=SimpleNamespace(
            chronic_conditions=conditions, current_medications=[], age=74, sex="F", date_of_birth=None
        ),
        encounter=SimpleNamespace(chief_complaint="", primary_nurse_id=""),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=0,
        vitals=[],
        lab_results=[SimpleNamespace(lab_name="hba1c", value=6.0, unit="%", is_abnormal=False)],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        materialized_facts=[],
        section_facts={},
        shift="",
        discharge_medications=[],
        working_diagnoses=[],
        roster_map={},
        authored_datetime=None,
    )


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_outpatient_problem_list_never_repeats_a_label(lang: str) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
        _compose_chronic_assessment_integrated,
    )

    # POP-007282: diabetes and its retinopathy; I80 and I82 are both DVT.
    codes = ["I10", "E11.9", "I80", "I82", "E11.311"]
    conds = [SimpleNamespace(code=c, stage="") for c in codes]
    text = _compose_chronic_assessment_integrated(_ctx(conds, lang))
    labels = [m.group(1) for m in re.finditer(r"^\d+\. ([^:：]+)[:：]", text, re.M)]
    assert len(labels) == len(set(labels)), text
    retinopathy = "糖尿病網膜症" if lang == "ja" else "Diabetic retinopathy"
    # The retinopathy is never folded into the diabetes item. Since #3876 a
    # problem the visit does not address has no item at all, so the
    # retinopathy (no treatment in this context) may be absent.
    diabetes_lines = [ln for ln in text.splitlines() if re.match(r"^\d+\. (2型糖尿病|Type 2 diabetes)", ln)]
    assert diabetes_lines and all(retinopathy not in ln for ln in diabetes_lines), text
    # The HbA1c control judgement belongs to the diabetes item only.
    assert text.count("HbA1c") == 1, text


def test_outpatient_subjective_lists_a_label_once() -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
        build_outpatient_subjective,
    )
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    conds = [SimpleNamespace(code=c, stage="") for c in ["E66.3", "E66.9", "I10"]]
    text, _ = build_outpatient_subjective(TemplateNarrativeGenerator(), _ctx(conds))
    assert text.count("肥満") == 1, text
