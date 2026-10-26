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

from typing import TYPE_CHECKING, Any

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.reference_data_loaders import (
    load_discharge_instructions,
    load_physical_exam_findings,
)

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


def resolve_discharge_instructions(ctx: NarrativeContext) -> dict[str, dict[str, str]]:
    """Merge baseline + disease_specific discharge instructions.

    disease_specific entries take precedence over baseline for shared keys.
    Returns a flat dict {key: {en: "...", ja: "..."}}.
    """
    di_data = load_discharge_instructions()
    baseline: dict[str, Any] = di_data.get("baseline") or {}
    disease_specific: dict[str, Any] = di_data.get("disease_specific") or {}

    merged: dict[str, dict[str, str]] = {}
    for key, entry in baseline.items():
        if isinstance(entry, dict):
            merged[key] = dict(entry)

    disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
    if disease_id and disease_id in disease_specific:
        overrides = disease_specific[disease_id] or {}
        for key, entry in overrides.items():
            if isinstance(entry, dict):
                merged[key] = dict(entry)

    narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
    if narrative is not None:
        proto_di = _o(narrative, "discharge_instructions", None)
        if proto_di is not None:
            _di_sections = ("follow_up", "activity", "medications", "emergency", "diet_lifestyle")
            for section in _di_sections:
                sec_data = _o(proto_di, section, {})
                if isinstance(sec_data, dict) and (sec_data.get("en") or sec_data.get("ja")):
                    merged[section] = dict(sec_data)

    return merged
