"""FHIR FamilyMemberHistory builder (AD-55 Base, AD-56 builder registry)."""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import resolve_lang
from clinosim.modules.family_history.engine import load_reference
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _build_diagnosis_codeable_concept,
    _map_diagnosis_code,
)


def _build_relationship_codeable(rel: str, disp: dict[str, str], lang: str) -> dict[str, Any]:
    """Build FamilyMemberHistory.relationship as a fully-populated CodeableConcept.

    Issue #360 G2 (iris4h-ai feedback 2026-07-22): the previous emission had
    ``coding[0].display`` set to the target-language string (e.g. "父" for
    JP). On JP output that Japanese display was subsequently stripped by
    ``_strip_japanese_display_on_english_only_systems`` (v3-RoleCode is
    listed under ``http://terminology.hl7.org/`` prefix, which is treated
    as an English-only CS), leaving both ``display`` and ``text`` empty —
    the UI had no human-readable label to render.

    This helper emits the FHIR-canonical two-slot pattern:

    * ``coding[0].display`` = English canonical (survives the strip walker
      because "Father"/"Mother"/"Sibling" contain no CJK characters).
    * ``text`` = target-language string ("父"/"母"/"兄弟姉妹" for JP;
      identical to the English display for US, so it is omitted there to
      avoid duplication).

    v3-RoleCode publishes English labels only, so this pattern is the
    only way to give a JP UI a JP label without violating the
    English-only-CS invariant. Sibling helpers should follow the same
    pattern for other English-only-CS CodeableConcepts (Issue #360
    tracking).
    """
    en_display = disp.get("en", rel)
    target_display = disp.get(lang, en_display)
    result: dict[str, Any] = {
        "coding": [
            {
                "system": get_system_uri("hl7-v3-rolecode"),
                "code": rel,
                "display": en_display,
            }
        ]
    }
    # Only emit `text` when it adds information beyond the English display
    # (i.e. on non-English locales). US output keeps the leaner shape.
    if target_display and target_display != en_display:
        result["text"] = target_display
    return result


def _resolve_family_history_code(code: str, country: str) -> str:
    """Family-history-context-aware code translation.

    Reuses ``_map_diagnosis_code`` (chronic/history → billable leaf) but rejects
    personal-history Z-code targets (Z86.*, Z87.*, Z82.*) which encode "patient's
    own past" semantics — inappropriate for a relative. In those cases the
    original code passes through and resolves in ``codes/data`` directly.
    Session 40 fix: keeps E11 → E11.9 and I64 → I63.9 corrections while
    preserving the pre-fix semantic for I63 (relative's cerebral infarction).
    """
    mapped = _map_diagnosis_code(code, country)
    if mapped.startswith("Z"):
        return code
    return mapped


def _build_family_history(ctx: BundleContext) -> list[dict]:
    """Build FHIR FamilyMemberHistory from CIF family_history (v3-RoleCode + ICD).

    One resource per relative; patient-scoped id so the write-time de-dup keeps a
    single copy across the patient's encounters. FamilyMemberHistory.sex is omitted
    (optional) to avoid a hardcoded gender system URI.
    """
    fams = ctx.record.get("family_history") or []
    if not fams:
        return []
    lang = resolve_lang(ctx.country)
    icd_system_key = system_key_for("diagnosis", ctx.country)
    rel_display = load_reference()["relationships"]
    out: list[dict] = []
    for i, fam in enumerate(fams):
        rel = _get(fam, "relationship", "")
        disp = rel_display.get(rel, {})
        res: dict[str, Any] = {
            "resourceType": "FamilyMemberHistory",
            "id": f"fmh-{ctx.patient_id}-{i:02d}",
            "status": "completed",
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "relationship": _build_relationship_codeable(rel, disp, lang),
            "deceasedBoolean": bool(_get(fam, "deceased", False)),
        }
        # Apply the locale diagnosis map (session 40 fix): family_history condition
        # codes are internal WHO / category codes (e.g. E11 = "Type 2 diabetes mellitus"
        # header, I64 = WHO-only Stroke NOS). For US, non-billable / WHO-only codes
        # must fold to a billable CM leaf (E11 → E11.9, I64 → I63.9); for JP, the map
        # is identity for WHO codes. Sibling of _fhir_conditions which already applies
        # this pattern. Without the map, code_lookup's prefix-child fallback silently
        # returns the wrong display (e.g. E11 → "with ketoacidosis without coma").
        #
        # Personal-history Z-code targets in the map (e.g. I63 → Z86.73 "Personal
        # history of TIA/cerebral infarction") are semantically wrong for a family
        # member — FamilyMemberHistory.condition.code means "the condition in the
        # relative," not the patient's personal history. Fall back to the original
        # code when the map target is a Z-code so the display resolves to the
        # actual disease (I63 → "Cerebral infarction").
        # C5-15 (session 43 cycle 5): FamilyMemberHistory.condition[].onsetString.
        # CIF family_history has no per-condition onset data (relatives are
        # patient-reported). Emit an "詳細不明" / "unknown" onsetString so the
        # field is populated per JP Core FamilyMemberHistory recommendation.
        _onset_unknown = "詳細不明" if lang == "ja" else "unknown onset"
        conditions = [
            {
                "code": _build_diagnosis_codeable_concept(
                    _resolve_family_history_code(code, ctx.country),
                    icd_system_key,
                    ctx.country,
                ),
                "onsetString": _onset_unknown,
            }
            for code in _get(fam, "condition_codes", []) or []
        ]
        if conditions:
            res["condition"] = conditions
        out.append(res)
    return out
