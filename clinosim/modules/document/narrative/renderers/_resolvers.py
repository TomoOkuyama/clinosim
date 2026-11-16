"""Resolver cluster — fallback-chain lookups for narrative generation.

Extracted from ``template_generator.TemplateNarrativeGenerator`` as step
C1p of the full-review Phase C renderer split (CRITICAL C1). Behavior
is byte-identical — the five class methods are now thin delegators.

``resolve_physical_exam`` dispatches back to the class helper
``generator._pydantic_day_findings_to_dict`` (Pydantic flattener that
has its own extraction phase C1s), so this module threads ``generator``
through where that call site needs it. The other resolvers depend only
on ``ctx`` plus reference-data loaders and are generator-free.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from clinosim.codes.drugs import drug_key, medication_matches
from clinosim.codes.valuesets import concept_group, iter_chronic_codes
from clinosim.locale.free_text import localize_drug_name
from clinosim.locale.i18n import t
from clinosim.locale.localized import localized
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document.narrative._narrative_utils import is_neonate
from clinosim.modules.document.reference_data_loaders import (
    load_discharge_instructions,
    load_physical_exam_findings,
)
from clinosim.timeutil import parse_iso_datetime

# A sentence ends at a full stop followed by a space (English; "1.5 L" does
# not end one) or at a Japanese full stop.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|(?<=。)")

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )
    from clinosim.types.document import NarrativeContext


def resolve_physical_exam(
    generator: TemplateNarrativeGenerator,
    ctx: NarrativeContext,
    archetype: str,
    day_index: int,
) -> dict[str, Any]:
    """Multi-step fallback chain for per-day physical exam findings.

    Fallback priority:
      1. disease_protocol.narrative.physical_exam_findings[archetype][day_N] (Pydantic)
      2. reference_data.findings[disease_id][archetype][day_N]
      3. Steps 1-2 at prior days (N-1 ... 0)
      4. baseline.reference_data[archetype][day_N] with same fallback
      5. Returns {} (caller uses generic phrase)
    """
    candidate_days = list(range(day_index, -1, -1))

    disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
    narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
    pex_data = load_physical_exam_findings()

    for day in candidate_days:
        day_key = f"day_{day}"

        if narrative is not None:
            proto_pex = _o(narrative, "physical_exam_findings", {})
            if isinstance(proto_pex, dict):
                arch_day = proto_pex.get(archetype, {})
                if isinstance(arch_day, dict):
                    day_findings = arch_day.get(day_key)
                    if day_findings is not None:
                        return generator._pydantic_day_findings_to_dict(day_findings)

        if disease_id:
            ref_findings = pex_data.get("findings", {})
            disease_findings = ref_findings.get(disease_id, {})
            arch_findings = disease_findings.get(archetype, {})
            day_entry = arch_findings.get(day_key)
            if day_entry is not None:
                return day_entry if isinstance(day_entry, dict) else {}

    # Issue #3260: a neonate without a disease-authored exam gets the newborn
    # exam set, not the adult baseline.
    if is_neonate(ctx):
        return resolve_neonatal_exam(ctx, day_index)

    baseline = pex_data.get("baseline", {})

    arch_baseline = baseline.get(archetype, {})
    for day in candidate_days:
        day_key = f"day_{day}"
        day_entry = arch_baseline.get(day_key)
        if day_entry is not None:
            return day_entry if isinstance(day_entry, dict) else {}

    for alt_arch, alt_data in baseline.items():
        if not isinstance(alt_data, dict):
            continue
        for day in candidate_days:
            day_key = f"day_{day}"
            day_entry = alt_data.get(day_key)
            if day_entry is not None:
                return day_entry if isinstance(day_entry, dict) else {}

    return {}


def resolve_neonatal_exam(ctx: NarrativeContext, day_index: int) -> dict[str, str]:
    """The newborn exam set of ``physical_exam_findings.yaml`` ``neonatal`` in
    ``ctx.target_lang`` (Issue #3260), as ``{body_system: text}``. The skin
    finding is the jaundice band of the latest total bilirubin measured by
    the note's time; none measured yet reads as the first band."""
    neonatal = load_physical_exam_findings()["neonatal"]
    lang = ctx.target_lang
    exam = {system: localized(text, lang) for system, text in neonatal["systems"].items()}
    bilirubin = _bilirubin_known_at(ctx, day_index)
    bands = neonatal["jaundice"]
    band = bands[0]
    for candidate in bands:
        if bilirubin is not None and bilirubin >= candidate["min_mg_dl"]:
            band = candidate
    exam["skin"] = localized(band["text"], lang)
    return exam


def _bilirubin_known_at(ctx: NarrativeContext, day_index: int) -> float | None:
    """Latest total bilirubin (mg/dL) measured by the document's authored time,
    or by the end of ``day_index`` when the document has no authored time."""
    series = (getattr(ctx, "newborn_workup", None) or {}).get("bilirubin_series") or []
    as_of = getattr(ctx, "authored_datetime", None)
    as_of_naive = as_of.replace(tzinfo=None) if as_of is not None else None
    latest: tuple[tuple[int, datetime], float] | None = None
    for entry in series:
        at = parse_iso_datetime(entry.get("timestamp"), lenient=True)
        at_naive = at.replace(tzinfo=None) if at is not None else None
        day = entry.get("day")
        if as_of_naive is not None and at_naive is not None:
            if at_naive > as_of_naive:
                continue
        elif day is None or day > day_index:
            continue
        key = (day if isinstance(day, int) else -1, at_naive or datetime.min)
        if latest is None or key >= latest[0]:
            latest = (key, float(entry["value_mg_dl"]))
    return latest[1] if latest is not None else None


def resolve_daily_trajectory(
    generator: TemplateNarrativeGenerator,
    ctx: NarrativeContext,
    archetype: str,
    day_index: int,
) -> dict[str, str]:
    """Fallback chain for SOAP-structured daily trajectory.

    Fallback priority:
      1. disease_protocol.course_archetypes[archetype].daily_trajectory[day_N]
      2. Same at prior days (N-1 ... 0)
      3. Generic SOAP entry (always succeeds)
    """
    traj, _ = resolve_daily_trajectory_with_source(generator, ctx, archetype, day_index)
    return traj


def resolve_daily_trajectory_with_source(
    generator: TemplateNarrativeGenerator,
    ctx: NarrativeContext,
    archetype: str,
    day_index: int,
) -> tuple[dict[str, str], str]:
    """Like resolve_daily_trajectory but also returns source path for facts_used.

    Returns (trajectory_dict, source_path) where source_path is an empty string
    when the generic fallback is used (not from disease YAML).
    """
    proto = ctx.disease_protocol
    if proto is None:
        return generic_trajectory(ctx), ""

    course_archetypes = _o(proto, "course_archetypes", {}) or {}
    archetype_data = course_archetypes.get(archetype) or {}

    daily_trajectory: dict[str, Any] = {}
    if isinstance(archetype_data, dict):
        daily_trajectory = archetype_data.get("daily_trajectory") or {}
    else:
        daily_trajectory = _o(archetype_data, "daily_trajectory", {}) or {}

    candidate_days = list(range(day_index, -1, -1))
    for day in candidate_days:
        day_key = f"day_{day}"
        entry = daily_trajectory.get(day_key)
        if entry is not None:
            source = f"disease_protocol.course_archetypes.{archetype}.daily_trajectory.{day_key}"
            if isinstance(entry, dict):
                return entry, source
            return {
                "subjective": _o(entry, "subjective", ""),
                "objective": _o(entry, "objective", ""),
                "assessment": _o(entry, "assessment", ""),
                "plan": _o(entry, "plan", ""),
            }, source

    return generic_trajectory(ctx), ""


def generic_trajectory(ctx: NarrativeContext) -> dict[str, str]:
    """Return generic SOAP entry for when no trajectory data is available."""
    lang = ctx.target_lang
    return {
        "subjective": t("fallback.generic_fallback", lang),
        "objective": t("fallback.generic_fallback", lang),
        "assessment": t("fallback.generic_assessment", lang),
        "plan": t("fallback.generic_plan", lang),
    }


def baseline_instruction_set(ctx: NarrativeContext) -> dict[str, Any]:
    """The base layer of a discharge instruction sheet: the YAML ``baseline``
    (adult) set. The one place a population-specific set replaces it — the
    newborn set of Issue #3260 is selected here when ``is_neonate(ctx)`` — so the
    disease layers and the patient gates apply to it unchanged."""
    return load_discharge_instructions().get("baseline") or {}


def _patient_condition_codes(ctx: NarrativeContext) -> list[str]:
    """The patient's chronic-condition codes plus the encounter's admission,
    discharge and working diagnosis codes (an admission for heart failure
    counts as heart failure)."""
    patient = getattr(ctx, "patient", None)
    codes = iter_chronic_codes(_o(patient, "chronic_conditions", []) if patient is not None else [])
    for dx in getattr(ctx, "diagnoses", None) or []:
        for key in ("admission_diagnosis_code", "discharge_diagnosis_code"):
            if code := str(_o(dx, key, "") or ""):
                codes.append(code)
        for wd in _o(dx, "working_diagnoses", []) or []:
            if code := str(_o(wd, "code", "") or ""):
                codes.append(code)
    return codes


def _gate_drugs(ctx: NarrativeContext, refs: list[str]) -> list[Any]:
    """Discharge-prescription items that are one of the catalog drugs or
    classes ``refs``."""
    meds = getattr(ctx, "discharge_medications", None) or []
    return [m for m in meds if medication_matches(m, drugs=refs, classes=refs)]


def _instruction_applies(gate: dict[str, Any] | None, ctx: NarrativeContext) -> bool:
    """True when the ``applies_when`` gate (clinosim-discharge-instruction.yaml,
    Issue #3254) holds for the patient. An unrecorded sex / smoking / alcohol
    value keeps the instruction."""
    if not gate:
        return True
    patient = getattr(ctx, "patient", None)
    for field in ("sex", "smoking_status", "alcohol_use"):
        allowed = gate.get(field)
        value = str(_o(patient, field, "") or "") if patient is not None else ""
        if allowed is not None and value and value not in allowed:
            return False
    codes = _patient_condition_codes(ctx)
    for group in gate.get("conditions") or ():
        if not any(concept_group(group).contains(c) for c in codes):
            return False
    for group in gate.get("exclude_conditions") or ():
        if any(concept_group(group).contains(c) for c in codes):
            return False
    refs = gate.get("discharge_drugs") or []
    return not refs or bool(_gate_drugs(ctx, refs))


def _fill_drugs(entry: dict[str, Any], ctx: NarrativeContext) -> dict[str, str]:
    """The entry's language texts with ``{drugs}`` replaced by the discharge
    drugs its gate matched, named per language."""
    texts = {lang: str(text) for lang, text in entry.items() if lang != "applies_when" and text}
    if not any("{drugs}" in text for text in texts.values()):
        return texts
    refs = (entry.get("applies_when") or {}).get("discharge_drugs") or []
    names: list[str] = []
    seen: set[str] = set()
    for med in _gate_drugs(ctx, refs):
        name, _ = strip_protocol_prefix(str(_o(med, "drug_name", "") or ""))
        if name and (key := drug_key(name)) not in seen:
            seen.add(key)
            names.append(name)
    return {
        lang: text.replace("{drugs}", t("list_sep.serial", lang).join(localize_drug_name(n, lang) for n in names))
        for lang, text in texts.items()
    }


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_BREAK.split(text.strip()) if s.strip()]


def _join_sentences(sentences: list[str]) -> str:
    """Sentences rejoined as :func:`_split_sentences` found them: a space
    after a Latin full stop, none after a Japanese one."""
    out = ""
    for sentence in sentences:
        out += sentence if not out or out.endswith("。") else " " + sentence
    return out


def dedupe_instruction_sentences(merged: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Drop, per language, every sentence already said by an earlier entry
    (case- and space-insensitive); an entry left with no text is dropped
    (Issue #3254: baseline, disease-specific and protocol texts overlap)."""
    seen: dict[str, set[str]] = {}
    out: dict[str, dict[str, str]] = {}
    for key, entry in merged.items():
        kept_entry: dict[str, str] = {}
        for lang, text in entry.items():
            lang_seen = seen.setdefault(lang, set())
            kept: list[str] = []
            for sentence in _split_sentences(text):
                norm = " ".join(sentence.casefold().split())
                if norm not in lang_seen:
                    lang_seen.add(norm)
                    kept.append(sentence.strip())
            kept_entry[lang] = _join_sentences(kept)
        if any(kept_entry.values()):
            out[key] = kept_entry
    return out


def resolve_discharge_instructions(ctx: NarrativeContext) -> dict[str, dict[str, str]]:
    """The patient's discharge instructions, ``{key: {en: "...", ja: "..."}}``.

    Layers, later ones replacing an earlier entry of the same key: the
    baseline set (:func:`baseline_instruction_set`), the disease-specific
    entries of clinosim-discharge-instruction.yaml, then the disease
    protocol's ``narrative.discharge_instructions``. An entry whose
    ``applies_when`` gate does not hold for the patient is skipped, so it
    neither shows nor replaces the layer below (Issue #3254). ``{drugs}``
    names the discharge drugs the gate matched, and a sentence already said
    by an earlier entry is dropped.
    """
    di_data = load_discharge_instructions()
    disease_specific: dict[str, Any] = di_data.get("disease_specific") or {}

    merged: dict[str, dict[str, str]] = {}

    def _layer(entries: dict[str, Any]) -> None:
        for key, entry in entries.items():
            if isinstance(entry, dict) and _instruction_applies(entry.get("applies_when"), ctx):
                merged[key] = _fill_drugs(entry, ctx)

    _layer(baseline_instruction_set(ctx))

    disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
    if disease_id and disease_id in disease_specific:
        _layer(disease_specific[disease_id] or {})

    narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
    if narrative is not None:
        proto_di = _o(narrative, "discharge_instructions", None)
        if proto_di is not None:
            _di_sections = ("follow_up", "activity", "medications", "emergency", "diet_lifestyle")
            for section in _di_sections:
                sec_data = _o(proto_di, section, {})
                if isinstance(sec_data, dict) and (sec_data.get("en") or sec_data.get("ja")):
                    merged[section] = dict(sec_data)

    return dedupe_instruction_sentences(merged)
