"""Medical / clinical display locale loaders — multilingual medication
term catalog, department display, frequency tokens, allergen RxNorm
mapping, prefecture JIS X 0401 codes, occupation display, diet-type
display.

Extracted from the historical god-file ``clinosim/locale/loader.py`` as
step C2b of the full-review Phase C locale split, continuing B1 /
C2a (clinical cluster).

Every function is re-exported at module scope on ``clinosim.locale.loader``
so each historical ``from clinosim.locale.loader import load_X`` call
site keeps working unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from clinosim.locale._io import _LOCALE_DIR, _load_yaml


@lru_cache(maxsize=1)
def load_med_terms() -> dict[str, dict[str, dict[str, str]]]:
    """Load the multi-language medication dosage / term catalog.

    Structure: ``{"categories": {slug: {lang: display}}, "terms":
    {slug: {lang: display}}}`` — same shape as the Phase 1d-1
    ``narrative_*.yaml`` and Phase 1d-2 ``llm_prompt_labels.yaml``
    files. Order is preserved from the YAML (substitutions are
    order-sensitive: longer keys must be tried first).

    Backing file: ``clinosim/locale/shared/med_terms.yaml`` (Phase
    1d-3, 2026-09-23). Adding a new locale (fr / zh / …) is a data
    change here — extend each entry with ``<lang>: <display>``.
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "med_terms.yaml", fallback={})
    return {
        "categories": raw.get("categories", {}) or {},
        "terms": raw.get("terms", {}) or {},
    }


@lru_cache(maxsize=1)
def load_med_terms_ja() -> dict[str, dict[str, str]]:
    """Deprecated alias — returns a ``{"categories": {slug: ja_value},
    "terms": {slug: ja_value}}`` view of the multi-language catalog for
    callers that predate Phase 1d-3.

    Use ``load_med_terms`` for new code. This shim projects each
    per-slot dict to its ``ja`` slot only; callers that need
    ``lang="en"`` (etc.) must migrate to ``load_med_terms`` and
    resolve via ``resolve_localized_display``.
    """
    ml = load_med_terms()
    return {
        "categories": {k: entry.get("ja", "") for k, entry in ml["categories"].items()},
        "terms": {k: entry.get("ja", "") for k, entry in ml["terms"].items()},
    }


@lru_cache(maxsize=1)
def load_department_display() -> dict[str, dict[str, str]]:
    """Load department display table ({key: {en, ja}})."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "department_display.yaml", fallback={})
    return raw.get("departments", {}) or {}


def department_display(dept: str, lang: str) -> str:
    """Display name of department ``dept`` in ``lang``: the table entry, then
    English, then the humanised key (Issue #2270; never a title-cased slug)."""
    entry = load_department_display().get(dept) or {}
    return str(entry.get(lang) or entry.get("en") or dept.replace("_", " "))


def department_specialty_snomed(dept: str) -> str:
    """SNOMED CT specialty code of department ``dept`` (``""`` when the
    department has no clinical specialty), Issue #2270."""
    return str((load_department_display().get(dept) or {}).get("specialty_snomed") or "")


@lru_cache(maxsize=1)
def load_clinician_roles() -> dict[str, dict[str, Any]]:
    """Staff roles (``codes/data/clinosim-clinician-role.yaml``): staff-id
    prefix, title, name suffix and qualification per role (Issue #2270)."""
    raw = _load_yaml(_LOCALE_DIR.parent / "codes" / "data" / "clinosim-clinician-role.yaml", fallback={})
    return {str(k): v for k, v in (raw.get("roles") or {}).items() if isinstance(v, dict)}


def role_display(role: str, lang: str, *, facet: str = "title") -> str:
    """Display of staff ``role`` in ``lang`` (then English, then the humanised
    role): ``facet`` "title" (Physical therapist / 理学療法士), "suffix" (the
    name suffix, nurse / 看護師) or "qualification" (the qualification
    display). Issue #2270."""
    row = load_clinician_roles().get(role) or {}
    if facet == "suffix":
        values = {"en": row.get("suffix_en"), "ja": row.get("suffix_ja")}
    elif facet == "qualification":
        qual = row.get("qualification") or {}
        values = {"en": qual.get("display_en"), "ja": qual.get("display")}
    else:
        values = dict(row.get("title") or {})
    return str(values.get(lang) or values.get("en") or role.replace("_", " "))


@lru_cache(maxsize=1)
def load_frequency_tokens() -> dict[str, tuple[int, int, str]]:
    """Load the frequency-token catalog.

    Returns `{token: (frequency, period, period_unit)}`. Reads
    `clinosim/codes/data/frequency-tokens.yaml`, consolidated under
    post-#1880 review (hardcoded-audit Finding 20) from the parallel
    `_FREQ_PER_DAY` (`clinosim/modules/order/engine.py`) and
    `_FREQ_LABEL_TIMING` (`clinosim/modules/output/fhir_r4/lib/common.py`)
    dicts.
    """
    path = _LOCALE_DIR.parent / "codes" / "data" / "frequency-tokens.yaml"
    raw = _load_yaml(path, fallback={})
    tokens = raw.get("tokens", {}) or {}
    out: dict[str, tuple[int, int, str]] = {}
    for key, row in tokens.items():
        if not isinstance(row, dict):
            continue
        out[str(key)] = (
            int(row.get("frequency", 0)),
            int(row.get("period", 1)),
            str(row.get("period_unit", "d")),
        )
    return out


@lru_cache(maxsize=1)
def load_occupation_display() -> dict[str, dict[str, str]]:
    """Load the occupation display table ({slug: {en, ja}}): the
    ``occupation`` section of ``locale/shared/vocabulary.yaml``, shared with
    the narrative and LLM prompts (Issue #2269)."""
    from clinosim.locale.loaders.narrative import load_vocabulary

    return load_vocabulary().get("occupation", {}) or {}


@lru_cache(maxsize=1)
def load_diet_type_display() -> dict[str, dict[str, str]]:
    """Load diet-type display table ({slug: {en, ja}}).

    Reads `clinosim/locale/shared/diet_type_display.yaml` (migrated from
    the inline `_diet_labels` conditional in
    `clinosim/modules/output/fhir_r4/encounters/encounter.py` under the
    post-#1880 review, hardcoded-audit Finding 13).
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "diet_type_display.yaml", fallback={})
    return raw.get("diet_types", {}) or {}
