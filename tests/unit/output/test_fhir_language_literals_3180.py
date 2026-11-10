"""Display languages fixed to a literal in the output layer (Issue #3180).

Text in FHIR output follows the output language of the country
(``countries.lang_for``). A call in ``clinosim/modules/output`` may pass a
literal ``"en"`` / ``"ja"`` to a display or label lookup only for one of the
reasons of the code-mapping spec, and every such call is pinned here:

* ``english-only`` — the ``coding.display`` of an English-only code system
  (LOINC, SNOMED CT, HL7, DICOM, UCUM; spec §5.3) or of a US-only code system
  (CVX, RxNorm): English in every locale, the label goes in ``text``.
* ``english-fallback`` — the English entry used after the requested language
  (spec §6 rule 1).
* ``jp-profile`` — a JP-only code system (JP Core, JP-CLINS, MEDIS, the JP
  document codes) or a text that only a JP Core / JP-CLINS / eCheckup
  structure carries, and that structure is emitted only in JP output.
* ``language-field`` — the value of a ``<base>_<lang>`` field (spec §5.2),
  read back with ``localized_field`` in the output language.
* ``matching`` — not output: the English / Japanese key used to recognise an
  existing value.

A new literal is either replaced by the output language or added here with
its reason. Selecting the language with ``"ja" if ... else "en"`` is never
allowed (spec §5.1).
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

import clinosim.modules.output as output_pkg

ROOT = Path(output_pkg.__file__).parent
LANGS = frozenset({"ja", "en"})

ENGLISH_ONLY = "english-only"
ENGLISH_FALLBACK = "english-fallback"
JP_PROFILE = "jp-profile"
LANGUAGE_FIELD = "language-field"
MATCHING = "matching"

# (file relative to clinosim/modules/output, callee, literal) -> (count, reason)
PINNED: dict[tuple[str, str, str], tuple[int, str]] = {
    ("fhir_r4/conditions/clinical_impression.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/conditions/code_status.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/conditions/conditions.py", "code_lookup", "en"): (3, ENGLISH_ONLY),
    ("fhir_r4/demographics/family_history.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/demographics/patient.py", "loinc_coding", "en"): (1, ENGLISH_ONLY),
    # hl7-coverage-class coding.display; the label is text_if_localized(...).
    ("fhir_r4/demographics/patient.py", "t", "en"): (4, ENGLISH_ONLY),
    # hl7-v2-0360 coding.display; the label is text.
    ("fhir_r4/demographics/practitioner.py", "localized", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/demographics/practitioner.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/demographics/smoking_alcohol.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    # JP-CLINS eDS category / type (jpfhir doc codes), the JP section-title
    # suffix, and the death-certificate / death-discharge-summary type in the
    # jpfhir doc-typecodes system (JP-CLINS output only).
    ("fhir_r4/documents/composition.py", "t", "ja"): (5, JP_PROFILE),
    ("fhir_r4/documents/composition.py", "_o", "en"): (1, ENGLISH_FALLBACK),
    # The LOINC display's fallback when the code is not registered.
    ("fhir_r4/documents/composition.py", "t", "en"): (1, ENGLISH_FALLBACK),
    ("fhir_r4/documents/composition.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/documents/composition.py", "registry_display", "en"): (2, ENGLISH_ONLY),
    # eCheckup (JP_DocumentReference for the health-checkup report).
    ("fhir_r4/documents/document_reference_checkup.py", "t", "ja"): (2, JP_PROFILE),
    ("fhir_r4/documents/documents.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/documents/imaging_report.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/documents/jp_clins/discharge_summary.py", "t", "ja"): (3, JP_PROFILE),
    ("fhir_r4/documents/jp_clins/echeckup_general.py", "t", "ja"): (1, JP_PROFILE),
    ("fhir_r4/documents/jp_clins/referral_note.py", "t", "ja"): (4, JP_PROFILE),
    ("fhir_r4/documents/jp_clins/referral_note.py", "format_referral_destination_text", "ja"): (1, JP_PROFILE),
    # JP_Organization_eCS referral destinations (JP catalog only).
    ("fhir_r4/documents/referral_orgs.py", "t", "ja"): (1, JP_PROFILE),
    ("fhir_r4/documents/referral_orgs.py", "dual_slot_concept", "ja"): (1, JP_PROFILE),
    ("fhir_r4/encounters/care_level.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/encounters/endpoint.py", "code_lookup", "en"): (2, ENGLISH_ONLY),
    # hl7-location-physical-type and SNOMED CT coding.display.
    ("fhir_r4/encounters/facility.py", "t", "en"): (2, ENGLISH_ONLY),
    # JP_Organization_eCS address.text (JP output only).
    ("fhir_r4/encounters/facility.py", "t", "ja"): (1, JP_PROFILE),
    # VitalSignReferenceRange.display_ja, read with localized_field(spec, "display", lang).
    ("fhir_r4/labs/_reference_ranges.py", "t", "ja"): (6, LANGUAGE_FIELD),
    ("fhir_r4/labs/anthropometrics.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/anthropometrics.py", "t", "en"): (1, ENGLISH_FALLBACK),
    ("fhir_r4/labs/blood_type.py", "registry_display", "en"): (3, ENGLISH_ONLY),
    # JP-CLINS uncoded lab local code (JP lab coding package only).
    ("fhir_r4/labs/coding_package.py", "display", "ja"): (1, JP_PROFILE),
    ("fhir_r4/labs/coding_strategy.py", "uncoded_analyte_display", "ja"): (1, JP_PROFILE),
    ("fhir_r4/labs/coding_strategy.py", "registry_display", "en"): (3, ENGLISH_ONLY),
    ("fhir_r4/labs/diagnostic_report.py", "language_slot", "en"): (4, ENGLISH_FALLBACK),
    ("fhir_r4/labs/diagnostic_report.py", "registry_display", "en"): (3, ENGLISH_ONLY),
    ("fhir_r4/labs/diagnostic_report.py", "system_coding", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/diagnostic_report.py", "_codes_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/imaging_study.py", "code_lookup", "en"): (4, ENGLISH_ONLY),
    # jp-document-codes (JP microbiology report) and the Japanese tail marker
    # stripped from an existing label.
    ("fhir_r4/labs/microbiology.py", "registry_display", "ja"): (1, JP_PROFILE),
    ("fhir_r4/labs/microbiology.py", "t", "ja"): (1, MATCHING),
    ("fhir_r4/labs/microbiology.py", "system_coding", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/microbiology.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/observations.py", "loinc_coding", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/observations.py", "localized_field", "en"): (2, ENGLISH_ONLY),
    ("fhir_r4/labs/observations.py", "t", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/labs/service_request.py", "system_coding", "en"): (4, ENGLISH_ONLY),
    ("fhir_r4/labs/service_request.py", "registry_display", "en"): (3, ENGLISH_ONLY),
    ("fhir_r4/labs/stage_scale_observations.py", "loinc_coding", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/lib/common.py", "system_coding", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/lib/common.py", "registry_display", "en"): (1, ENGLISH_FALLBACK),
    ("fhir_r4/lib/dosage.py", "system_coding", "en"): (1, ENGLISH_ONLY),
    # JP_eCS department extension placeholder (JP-CLINS output only).
    ("fhir_r4/lib/ecs_extensions.py", "department_display", "ja"): (1, JP_PROFILE),
    # jp-condition-severity (JP Core) and SNOMED CT severity.
    ("fhir_r4/lib/reference_data.py", "display", "ja"): (1, JP_PROFILE),
    ("fhir_r4/lib/reference_data.py", "snomed_display", "en"): (1, ENGLISH_ONLY),
    # JP Core fixedString unit, medication-nocoded (JP-CLINS) display.
    ("fhir_r4/medications/medications.py", "t", "ja"): (1, JP_PROFILE),
    ("fhir_r4/medications/medications.py", "registry_display", "ja"): (1, JP_PROFILE),
    ("fhir_r4/medications/medications.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/medications/medications.py", "get", "en"): (2, MATCHING),
    ("fhir_r4/medications/medications.py", "get", "ja"): (1, MATCHING),
    # JP-CLINS eCS post-process (runs on JP output only).
    ("fhir_r4/post_process/populate.py", "t", "ja"): (9, JP_PROFILE),
    ("fhir_r4/post_process/populate.py", "registry_display", "ja"): (1, JP_PROFILE),
    ("fhir_r4/post_process/populate.py", "narrative_label", "ja"): (1, JP_PROFILE),
    ("fhir_r4/post_process/populate.py", "system_coding", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/post_process/specimen.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/procedures/device.py", "registry_display", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/procedures/immunization.py", "code_lookup", "en"): (1, ENGLISH_ONLY),
    ("fhir_r4/procedures/procedures.py", "procedure_type_display", "en"): (1, ENGLISH_FALLBACK),
}


def _callee(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "?"


def _literal_language_calls() -> Counter[tuple[str, str, str]]:
    found: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            args = [*node.args, *(k.value for k in node.keywords if k.arg in ("lang", "language"))]
            for arg in args:
                if isinstance(arg, ast.Constant) and arg.value in LANGS:
                    found[(rel, _callee(node), arg.value)] += 1
    return found


def test_every_literal_language_call_is_pinned_with_a_reason() -> None:
    found = _literal_language_calls()
    pinned = {key: count for key, (count, _reason) in PINNED.items()}
    unpinned = {key: n for key, n in found.items() if key not in pinned}
    assert not unpinned, f"read the language from the country (lang_for) or pin it with a reason: {unpinned}"
    changed = {key: (found.get(key, 0), n) for key, n in pinned.items() if found.get(key, 0) != n}
    assert not changed, f"(found, pinned) — update PINNED: {changed}"


def test_pinned_reasons_are_known() -> None:
    assert {reason for _n, reason in PINNED.values()} <= {
        ENGLISH_ONLY,
        ENGLISH_FALLBACK,
        JP_PROFILE,
        LANGUAGE_FIELD,
        MATCHING,
    }


def test_no_language_selected_by_a_conditional_expression() -> None:
    """``"ja" if is_jp(...) else "en"`` picks the language by country (spec §5.1)."""
    hits = []
    for path in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.IfExp) and all(
                isinstance(b, ast.Constant) and b.value in LANGS for b in (node.body, node.orelse)
            ):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not hits, hits


# --- Sites that now follow the output language -------------------------------


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("US", {"8302-2": "Body height", "29463-7": "Body weight", "39156-5": "Body mass index (BMI) [Ratio]"}),
        ("JP", {"8302-2": "身長", "29463-7": "体重", "39156-5": "BMI"}),
    ],
)
def test_anthropometric_text_is_the_output_language_label(country: str, expected: dict[str, str]) -> None:
    from clinosim.modules.output.fhir_r4.labs import anthropometrics as a

    for loinc, text in expected.items():
        obs = a._build_one_observation(loinc, 1.0, "p1", "e1", "", country, "x")
        assert obs["code"]["text"] == text
        assert obs["code"]["coding"][0]["display"].isascii()


def test_head_circumference_text_per_language() -> None:
    from clinosim.modules.output.fhir_r4.labs import anthropometrics as a

    us = a._build_one_observation(a.LOINC_HEAD_CIRCUMFERENCE, 34.0, "p1", "e1", "", "US", "hc")
    jp = a._build_one_observation(a.LOINC_HEAD_CIRCUMFERENCE, 34.0, "p1", "e1", "", "JP", "hc")
    assert us["code"]["text"] == "Head Occipital-frontal circumference"
    assert jp["code"]["text"] == "頭囲"


def test_anthropometrics_has_no_per_language_tables() -> None:
    from clinosim.modules.output.fhir_r4.labs import anthropometrics as a

    assert not hasattr(a, "_DISPLAY_JA")
    assert not hasattr(a, "_DISPLAY_EN")


def test_jp_fallback_qualification_is_dual_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """HL7 v2-0360 is English-only: without the JP MHLW qualification table the
    JP Practitioner keeps the English display in the coding and the Japanese
    label in text (spec §5.3)."""
    from clinosim.modules.output.fhir_r4.demographics import practitioner as p

    monkeypatch.setattr(p, "load_practitioner_qualifications", lambda _country: {})
    roster = {"S1": {"name": "山田 太郎", "role": "physician"}}
    qual = p._build_practitioner("S1", roster, country="JP")["qualification"][0]["code"]
    assert qual["coding"][0]["display"] == "Doctor of Medicine"
    assert qual["text"] == "医師"


def test_us_qualification_has_no_duplicate_text() -> None:
    from clinosim.modules.output.fhir_r4.demographics import practitioner as p

    roster = {"S1": {"name": "John Smith", "role": "physician"}}
    qual = p._build_practitioner("S1", roster, country="US")["qualification"][0]["code"]
    assert qual == {"coding": [{"system": qual["coding"][0]["system"], "code": "MD", "display": "Doctor of Medicine"}]}


def test_hospital_course_procedure_names_follow_the_language() -> None:
    from clinosim.modules.output import hospital_course_extractor as h

    record = {"procedures": [{"procedure_code": "36556", "procedure_type": "central_line"}]}
    en = h.summarize_procedures(record, "en")
    ja = h.summarize_procedures(record, "ja")
    assert en != ja
    assert any(ord(c) > 0x3000 for c in ja[0])
