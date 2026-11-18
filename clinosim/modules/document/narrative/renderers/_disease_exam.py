"""The admission physical examination of the admitting disease (Issues
#3245, #3227).

``disease_exam.yaml`` holds, per disease, the findings of the systems it
affects in every language. :func:`admission_exam` returns them for the note
(the H&P, the ED note of a patient admitted through the ED): the general
appearance with the consciousness level of the quoted vital-sign reading, and
the system findings without the clauses that reading contradicts.
:func:`apply_exam_rules` then makes the cardiovascular and neurological
findings agree with the patient's atrial fibrillation (an irregularly
irregular pulse) and with an acute stroke (the focal deficit, with the NIH
Stroke Scale score on the admission day), on any day.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from clinosim.locale.i18n import t
from clinosim.locale.localized import localized, normalize_lang
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative.renderers._exam_agreement import agreeing_clauses
from clinosim.modules.document.reference_data_loaders import load_disease_exam

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

_SEVERITY_ORDER = ("moderate", "mild", "severe")


def _disease_id(ctx: NarrativeContext) -> str:
    proto = ctx.disease_protocol
    return str(_o(proto, "disease_id", "") or "") if proto is not None else ""


def _by_severity(entry: dict[str, Any], severity: str) -> dict[str, str]:
    """The language map of ``entry`` (a language map, or a map by severity)
    for ``severity``; an unlisted severity reads as moderate, mild or severe."""
    if "en" in entry:
        return entry
    for key in (severity, *_SEVERITY_ORDER):
        if key in entry:
            return dict(entry[key])
    return {}


def _stable_int(ctx: NarrativeContext, salt: str, modulo: int) -> int:
    """A number in ``range(modulo)`` fixed by the encounter id and ``salt``
    (SHA-256, no random draw): the same in every document of the stay."""
    enc_id = str(_o(ctx.encounter, "encounter_id", "") or "") if ctx.encounter is not None else ""
    digest = hashlib.sha256(f"{enc_id}|{salt}".encode()).hexdigest()
    return int(digest, 16) % modulo


def admission_exam(ctx: NarrativeContext, reading: Any | None, states: dict[str, str] | None = None) -> dict[str, str]:
    """``{body system: finding}`` of the admitting disease in the note's
    language, ``{}`` when the disease has no authored exam. ``reading`` is the
    vital-sign record the note quotes: its AVPU level gives the consciousness
    clause, and a clause that states a vital sign ``states`` (``{vital: low |
    normal | high}`` of the reading) contradicts is left out."""
    data = load_disease_exam()
    entry = data.diseases.get(_disease_id(ctx))
    if entry is None:
        return {}
    lang = ctx.target_lang
    severity = str(ctx.severity or "")
    general = entry.general if entry.general is not None else _by_severity(data.general, severity)
    appearance = localized(general, lang)
    level = str(_o(reading, "consciousness_level", "") or "") if reading is not None else ""
    alertness = localized(data.consciousness.get(level, {}), lang)
    findings: dict[str, str] = {
        "general": t("list_sep.serial", lang).join(x for x in (alertness, appearance) if x),
    }
    for system, text in entry.systems.items():
        finding = agreeing_clauses(localized(_by_severity(text, severity), lang), states or {}, lang)
        if finding:
            findings[system] = finding
    return findings


def _clause_separator(lang: str) -> str:
    return t("list_sep.serial", lang)


def has_irregular_rhythm(ctx: NarrativeContext) -> bool:
    """True when the patient is in atrial fibrillation at the stay: an
    admission for AF, or chronic AF (ICD-10 ``I48``) outside the paroxysmal
    stage."""
    rule = load_disease_exam().atrial_fibrillation
    if _disease_id(ctx) in rule.disease_ids:
        return True
    stages = {s.lower() for s in rule.irregular_stages}
    for cond in _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient is not None else []:
        code = str(_o(cond, "code", "") or "")
        stage = str(_o(cond, "stage", "") or "").lower()
        if any(code.startswith(prefix) for prefix in rule.condition_code_prefixes) and stage in stages:
            return True
    return False


def _with_irregular_rhythm(text: str, lang: str) -> str:
    """``text`` (the cardiovascular finding) with an irregularly irregular
    rhythm: its regular-rhythm clause replaced, else the rhythm written first."""
    rule = load_disease_exam().atrial_fibrillation
    irregular = localized(rule.irregular, lang)
    if not text:
        return irregular
    if irregular.lower() in text.lower():
        return text
    code = normalize_lang(lang)
    regular = {c.lower() for c in rule.regular_clauses.get(code) or rule.regular_clauses["en"]}
    sep = _clause_separator(lang)
    clauses = [c.strip() for c in text.split(sep.strip()) if c.strip()]
    if any(c.lower() in regular for c in clauses):
        return sep.join(irregular if c.lower() in regular else c for c in clauses)
    return sep.join([irregular, *clauses])


def stroke_deficit(ctx: NarrativeContext, *, with_nihss: bool) -> str:
    """The focal deficit of an acute stroke admission in the note's language,
    ``""`` for another disease. The side of the weakness and the score are
    fixed per encounter from the encounter id; the score lies in the NIHSS
    band of the severity and is written only when ``with_nihss``."""
    rule = load_disease_exam().stroke
    if _disease_id(ctx) not in rule.disease_ids:
        return ""
    severity = str(ctx.severity or "")
    if severity not in rule.nihss:
        severity = "moderate"
    side = rule.right if _stable_int(ctx, "stroke_side", 2) == 0 else rule.left
    deficit = localized(side[severity], ctx.target_lang)
    if not with_nihss:
        return deficit
    low, high = rule.nihss[severity]
    score = low + _stable_int(ctx, "stroke_nihss", high - low + 1)
    return localized(rule.nihss_format, ctx.target_lang).format(deficit=deficit, score=score)


def apply_exam_rules(ctx: NarrativeContext, findings: dict[str, str], *, admission_day: bool) -> dict[str, str]:
    """``findings`` with the rhythm of a patient in atrial fibrillation and the
    deficit of an acute stroke written (Issue #3227); ``findings`` unchanged
    for any other patient. ``admission_day``: the exam is the admission exam,
    so the stroke deficit carries the NIHSS score."""
    out = dict(findings)
    deficit = stroke_deficit(ctx, with_nihss=admission_day)
    if deficit:
        out["neurological"] = deficit
    if has_irregular_rhythm(ctx):
        out["cardiovascular"] = _with_irregular_rhythm(out.get("cardiovascular", ""), ctx.target_lang)
    return out


def exam_findings(
    generator: Any, ctx: NarrativeContext, reading: Any | None, states: dict[str, str]
) -> tuple[dict[str, str], str]:
    """``({body system: finding}, source label)`` of the exam a note on
    ``ctx.day_index`` writes, in the note language: the admission day's is the
    admitting disease's (:func:`admission_exam`); any other day, and a disease
    without one, the protocol / baseline exam of the languages with authored
    narrative content. The AF rhythm and the stroke deficit are applied on any
    day. ``({}, "")`` when there is nothing to write."""
    from clinosim.countries import has_authored_narrative
    from clinosim.modules.document.narrative.renderers._shared_helpers import PHYSICAL_EXAM_SYSTEMS, select_exam_text

    findings: dict[str, str] = {}
    source = ""
    if ctx.day_index == 0:
        findings = admission_exam(ctx, reading, states)
        source = f"physical_exam_findings.disease_exam.{_disease_id(ctx)}" if findings else ""
    if not findings and has_authored_narrative(ctx.target_lang):
        phys_exam = generator._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
        findings = {
            system: text
            for system in PHYSICAL_EXAM_SYSTEMS
            if (text := select_exam_text(phys_exam.get(system), ctx.severity))
        }
        source = f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}" if findings else ""
    ruled = apply_exam_rules(ctx, findings, admission_day=ctx.day_index == 0)
    if ruled != findings:
        source = source or "physical_exam_findings.disease_exam.rules"
    return ruled, source
