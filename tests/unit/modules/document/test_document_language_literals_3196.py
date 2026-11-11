"""Languages fixed to a literal in the document layer (Issue #3196).

Narrative text follows the document's output language (``ctx.target_lang``,
from the country profile through ``countries.lang_for``). A call in
``clinosim/modules/document`` may pass a literal ``"en"`` / ``"ja"`` only for
one of the reasons of the code-mapping spec, and every such call is pinned
here (the output layer has the same guard,
``tests/unit/output/test_fhir_language_literals_3180.py``):

* ``english-fallback`` — the English entry used after the requested language
  (spec §6 rule 1).
* ``language-field`` — a per-language field or placeholder (spec §5.2): the
  CIF ``description`` / ``description_ja`` pair, the
  ``{chief_complaint_<lang>}`` template placeholders.
* ``matching`` — not output: the English key used to recognise an existing
  value, or a check that a language map carries any text.

A new literal is either replaced by the output language or added here with
its reason. Selecting the language with ``"ja" if ... else "en"`` is never
allowed (spec §5.1).
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import clinosim.modules.document as document_pkg

pytestmark = pytest.mark.unit

ROOT = Path(document_pkg.__file__).parent
LANGS = frozenset({"ja", "en"})

ENGLISH_FALLBACK = "english-fallback"
LANGUAGE_FIELD = "language-field"
MATCHING = "matching"

# (file relative to clinosim/modules/document, callee, literal) -> (count, reason)
PINNED: dict[tuple[str, str, str], tuple[int, str]] = {
    # ClinicalImpressionRecord.description / description_ja: the CIF keeps
    # both languages (the Japanese text cannot be re-derived at FHIR emission).
    ("engine.py", "_describe", "en"): (1, LANGUAGE_FIELD),
    ("engine.py", "_describe", "ja"): (1, LANGUAGE_FIELD),
    ("narrative/_hedging.py", "get", "en"): (1, ENGLISH_FALLBACK),
    # The English prose lab name the LLM post-processor recognises.
    ("narrative/_replacement_localization.py", "get", "en"): (1, MATCHING),
    # The {chief_complaint_ja} / {chief_complaint_en} template placeholders.
    ("narrative/_template_helpers.py", "get", "ja"): (1, LANGUAGE_FIELD),
    ("narrative/_template_helpers.py", "get", "en"): (1, LANGUAGE_FIELD),
    # Whether a protocol's discharge-instruction section carries any text.
    ("narrative/renderers/_resolvers.py", "get", "en"): (1, MATCHING),
    ("narrative/renderers/_resolvers.py", "get", "ja"): (1, MATCHING),
    ("narrative/renderers/section_builders/discharge_summary.py", "get", "en"): (2, ENGLISH_FALLBACK),
    ("narrative/renderers/section_builders/outpatient_soap.py", "get", "en"): (1, ENGLISH_FALLBACK),
    # The HPI pertinent negatives' English fallback (Issue #3206).
    ("reference_data_loaders.py", "get", "en"): (1, ENGLISH_FALLBACK),
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
    assert not unpinned, f"take the language from ctx.target_lang / lang_for or pin it with a reason: {unpinned}"
    changed = {key: (found.get(key, 0), n) for key, n in pinned.items() if found.get(key, 0) != n}
    assert not changed, f"(found, pinned) — update PINNED: {changed}"


def test_pinned_reasons_are_known() -> None:
    assert {reason for _n, reason in PINNED.values()} <= {ENGLISH_FALLBACK, LANGUAGE_FIELD, MATCHING}


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


def test_no_per_language_generic_fallback_constants() -> None:
    """The generic fallback phrases are looked up in the document language
    at the call site, not frozen into ``_JA`` / ``_EN`` module constants."""
    from clinosim.modules.document.narrative import _template_helpers, template_generator

    for module in (_template_helpers, template_generator):
        for kind in ("FALLBACK", "ASSESSMENT", "PLAN"):
            for suffix in ("JA", "EN"):
                assert not hasattr(module, f"_GENERIC_{kind}_{suffix}")


def test_no_japanese_only_label_wrappers() -> None:
    from clinosim.modules.document.narrative import _replacement_localization, replacement_strategy

    for module in (_replacement_localization, replacement_strategy):
        for name in (
            "_lookup_ja_label",
            "_localize_severity_ja",
            "_localize_oxygen_device_ja",
            "_localize_arrival_mode_ja",
            "_localize_risk_level_ja",
            "_localize_barthel_band_ja",
        ):
            assert not hasattr(module, name), name


@pytest.mark.parametrize(
    ("severity", "lang", "expected_key"),
    [
        ("mild", "en", "hpi.onset.mild"),
        ("severe", "en", "hpi.onset.severe"),
        ("moderate", "fr", "hpi.onset.moderate"),
        ("unknown", "en", "hpi.onset.moderate"),
    ],
)
def test_hpi_onset_takes_the_language(severity: str, lang: str, expected_key: str) -> None:
    from clinosim.locale.i18n import t
    from clinosim.modules.document.narrative._template_helpers import _hpi_onset

    assert _hpi_onset(severity, lang) == t(expected_key, "en")
    assert _hpi_onset(severity, lang)


def test_lab_name_post_processor_takes_the_language() -> None:
    from clinosim.modules.document.narrative._replacement_localization import (
        localize_lab_names_in_sections,
        localize_lab_names_in_text,
    )

    assert localize_lab_names_in_text("Albumin 4.0 g/dL", "ja") == "アルブミン 4.0 g/dL"
    assert localize_lab_names_in_text("Albumin 4.0 g/dL", "en") == "Albumin 4.0 g/dL"
    assert localize_lab_names_in_sections({"a": "Creatinine 1.2"}, "ja") == {"a": "クレアチニン 1.2"}


def _hpi_ctx(lang: str) -> SimpleNamespace:
    patient = SimpleNamespace(
        sex="M",
        birth_date=None,
        chronic_conditions=[],
        current_medications=[],
    )
    enc = SimpleNamespace(chief_complaint="chest pain", chief_complaint_ja="胸痛")
    return SimpleNamespace(
        target_lang=lang,
        locale="US",
        patient=patient,
        encounter=enc,
        disease_protocol=None,
        reference_date=None,
    )


def test_hpi_extras_are_written_in_the_document_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """With authored narrative content in a language, the CIF-anchored HPI
    extras are written in that language, not always in Japanese."""
    from clinosim.modules.document.narrative.renderers.section_builders import hpi

    monkeypatch.setattr(hpi, "has_authored_narrative", lambda _lang: True)
    monkeypatch.setattr(hpi, "_age_at", lambda _ctx: 60)
    en = hpi._compose_hpi_extras_from_state(_hpi_ctx("en"))  # type: ignore[arg-type]
    ja = hpi._compose_hpi_extras_from_state(_hpi_ctx("ja"))  # type: ignore[arg-type]
    assert en and ja
    assert all(ord(c) < 0x3000 for c in en), en
    assert any(ord(c) > 0x3000 for c in ja), ja


# --- Fixed-language text outside lookups (Issue #3206) -----------------------

# A label written as an English (or Japanese) string literal in a renderer
# ("Vital signs: {x}", "Assessment: ... Plan: ...", "ROS: ...") bypasses the
# phrase catalog; so does joining items with a literal Japanese separator.
_LABEL_LITERAL = __import__("re").compile(r"^(?:[A-Z][A-Za-z ]+|ROS): ")


def test_no_section_label_in_a_string_literal() -> None:
    hits = []
    renderers = ROOT / "narrative" / "renderers"
    for path in sorted(renderers.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.JoinedStr) and node.values:
                head = node.values[0]
                if isinstance(head, ast.Constant) and isinstance(head.value, str) and _LABEL_LITERAL.match(head.value):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join"
                and isinstance(node.func.value, ast.Constant)
                and isinstance(node.func.value.value, str)
                and any(ord(c) > 0x3000 for c in node.func.value.value)
            ):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not hits, hits


@pytest.mark.parametrize(
    ("lang", "expected"), [("ja", "ROS: 発熱なし、下痢なし。"), ("en", "ROS: no fever, no diarrhea.")]
)
def test_hpi_ros_line_is_written_in_the_document_language(
    monkeypatch: pytest.MonkeyPatch, lang: str, expected: str
) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders import hpi

    monkeypatch.setattr(hpi, "has_authored_narrative", lambda _lang: True)
    monkeypatch.setattr(hpi, "_age_at", lambda _ctx: None)
    ctx = _hpi_ctx(lang)
    ctx.encounter = None
    ctx.disease_protocol = SimpleNamespace(disease_id="diabetic_ketoacidosis")
    assert hpi._compose_hpi_extras_from_state(ctx) == expected  # type: ignore[arg-type]


def test_hpi_pertinent_negatives_fall_back_to_english() -> None:
    from clinosim.modules.document.reference_data_loaders import hpi_pertinent_negatives

    assert hpi_pertinent_negatives("acute_mi", "fr") == hpi_pertinent_negatives("acute_mi", "en")
    assert hpi_pertinent_negatives("acute_mi", "ja")[0] == "労作時以外の胸痛エピソードなし"
    assert hpi_pertinent_negatives("no_such_disease", "ja") == []


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", "Vital signs: BP 120/80. General: no additional exam findings recorded."),
        ("ja", "バイタルサイン: BP 120/80。その他の身体所見の記載なし。"),
    ],
)
def test_vitals_only_physical_exam_phrase(lang: str, expected: str) -> None:
    from clinosim.locale.i18n import t

    text = t(
        "ed_physical_exam.vitals_prepend", lang, vitals="BP 120/80", text=t("physical_exam.no_other_findings", lang)
    )
    assert text == expected


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Assessment: A. Plan: P."), ("ja", "評価: A。 方針: P。")],
)
def test_inline_assessment_plan_phrase(lang: str, expected: str) -> None:
    from clinosim.locale.i18n import t

    a, p = ("A.", "P.") if lang == "en" else ("A。", "P。")
    assert t("ap_combined.assessment_plan_inline", lang, assessment=a, plan=p) == expected
