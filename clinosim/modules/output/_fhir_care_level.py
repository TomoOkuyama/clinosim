"""FHIR JP 要介護度 (long-term-care need level) social-history Observation
builder (AD-55 Base, JP only).

Extracted from the former _fhir_sdoh.py (PR2 G2 SDOH integrity refactor,
2026-06-24) for single-responsibility separation. care_level uses a
custom JP code system (jp-care-level, MHLW 介護保険 区分) and has a
different shape from the LOINC-keyed smoking/alcohol observations, so
it deserves its own file.

Data source: ctx.record.care_level (set by clinosim/modules/care_level/
enricher during post-records pass for JP patients only).
"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _social_category,
    _value,
)
from clinosim.modules.output._fhir_smoking_alcohol import _sdoh_effective_datetime


def _build_care_level(ctx: BundleContext) -> list[dict]:
    """JP 要介護度 (long-term-care need level) social-history Observation."""
    code = ctx.record.get("care_level") or ""
    if not code:
        return []
    lang = resolve_lang(ctx.country)
    text = "要介護度" if is_jp(ctx.country) else "Long-term care need level"
    # C2-10 (session 42 cycle 2): derive effectiveDateTime from earliest
    # encounter admission (mirrors _fhir_smoking_alcohol._sdoh_effective_datetime
    # pattern from C1-12). Care-level is patient-level SDOH, so tying it to the
    # first encounter is appropriate as a proxy for when the level was recorded.
    effective_dt = _sdoh_effective_datetime(ctx)
    o: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"carelevel-{ctx.patient_id}",
        # Session 46 chain #2: JP Core Observation_Common profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
            if is_jp(ctx.country)
            else {}
        ),
        "status": "final",
        "category": _social_category(ctx.country),
        "code": {"text": text},
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        "valueCodeableConcept": _value("jp-care-level", code, lang),
    }
    if effective_dt:
        o["effectiveDateTime"] = effective_dt
    return [o]
