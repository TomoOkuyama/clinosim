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
def load_allergen_rxnorm_map() -> dict[str, str]:
    """Load the EN allergen substance → RxNorm ingredient CUI mapping.

    Reads the `allergen_rxnorm` block of `clinosim/codes/data/
    clinosim-allergen-substance.yaml`, migrated from the pre-#1880
    `clinosim/modules/output/fhir_r4/lib/reference_data.py::_ALLERGEN_RXNORM`
    inline dict (hardcoded-audit Finding 14).
    """
    _allergen_substance_catalog = _LOCALE_DIR.parent / "codes" / "data" / "clinosim-allergen-substance.yaml"
    raw = _load_yaml(_allergen_substance_catalog, fallback={})
    return {str(k): str(v) for k, v in (raw.get("allergen_rxnorm", {}) or {}).items()}


@lru_cache(maxsize=1)
def load_occupation_display() -> dict[str, dict[str, str]]:
    """Load occupation display table ({slug: {en, ja}}).

    Reads `clinosim/locale/shared/occupation_display.yaml` (migrated from
    the inline `_OCCUPATION_DISPLAY_{JA,EN}` dicts in
    `clinosim/modules/output/fhir_r4/lib/localization.py` under the
    post-#1849 review, hardcoded-audit Finding 5).
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "occupation_display.yaml", fallback={})
    return raw.get("occupations", {}) or {}


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
