"""Pure FHIR reference-data dictionaries (code/SNOMED/region lookup tables).

FA-1 Phase 2: module-level data literals extracted verbatim from
fhir_r4_adapter.py. These are pure data (no functions, no dependencies on
other adapter symbols) and are re-exported by fhir_r4_adapter as a facade.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from clinosim.codes import display, get_system_uri
from clinosim.codes.snomed import snomed_display, snomed_map

_SEVERITY_SNOMED: dict[str, dict[str, str]] = {}  # filled below from codes/data/snomed-maps.yaml

# iris4h-ai feedback F-4: JP Core `JP_ConditionSeverity_VS` は
# JP_ConditionSeverity_CS の 4 code(MI/MO/SE/UK)のみを許容。SNOMED は
# ValueSet 外 = ~5k info。JP output では JP CS を primary、SNOMED を
# secondary(国際互換性のため保持)として emit する。
#
# URI 出典:iris4h-ai/tx-server-build/.../CodeSystem-jp-conditionseverity-cs.json
# (JP CS の display は `中度`、`中等度` ではないので注意)
_JP_CONDITION_SEVERITY_CS = get_system_uri("jp-condition-severity")
_SEVERITY_JP: dict[str, dict[str, str]] = {
    sev: {"code": code, "display": display("jp-condition-severity", code, "ja") or ""}
    for sev, code in (("mild", "MI"), ("moderate", "MO"), ("severe", "SE"))
}
# NOTE: 過去に定義していた `_JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL`
# (`.../StructureDefinition/JP_Observation_ReferenceRangeSource`)は削除。
# 2026-07-17 fhir-jp-validator report で以下 2 点が判明したため:
# (1) URL は JP Core 1.2.0 / JP-CLINS 1.13.0 / jpfhir-terminology 2.2606.0
#     の StructureDefinition カタログに存在せず、HAPI が "extension is
#     unknown" として reject する。
# (2) `JP_Observation_LabResult_eCS` は `Observation.referenceRange.
#     extension max=0` を定めており、たとえ spec-valid URL でも emit 不可。
# → clinosim は referenceRangeSource extension を emit しない。
# 該当 issue: #202、削除の PR は fix/observation-reference-range-strip-extension。


# 47 prefecture → JIS X 0401 code mapping now lives in
# `clinosim/codes/data/jis-x-0401-prefectures.yaml` (post-#1880 review,
# hardcoded-audit Finding 4) — JIS X 0401 is a standards registry; the
# data belongs beside the other authority-adjacent catalogs. Load via
# `clinosim.codes.prefectures.prefecture_code()` (Issue #2265).


# Encounter type -> SNOMED code lives in
# clinosim/codes/data/snomed-maps.yaml (encounter_type) via
# clinosim.codes.snomed.snomed_for (Phase 3.β.4,
# #1808 follow-up). Displays resolve through
# `code_lookup("snomed-ct", …)` against the authority yaml; this
# module no longer carries any SNOMED code constants for encounter
# types.


def _snomed_rows(kind: str) -> dict[str, dict[str, str]]:
    """``{key: {code, display}}`` for a ``codes/data/snomed-maps.yaml``
    vocabulary, with the English display from ``snomed-ct.yaml`` (Issue #2258)."""
    return {key: {"code": code, "display": snomed_display(code, "en") or ""} for key, code in snomed_map(kind).items()}


# Order route → SNOMED CT. Codes: codes/data/snomed-maps.yaml `route`; displays:
# the SNOMED preferred terms in codes/data/snomed-ct.yaml (Issue #2258). History:
# #311 SL = 37839007 Sublingual route (37161004 is the rectal route); #1265 OPH;
# #2352 INFILTRATION / INTRA-ARTICULAR.
_ROUTE_SNOMED: dict[str, dict[str, str]] = _snomed_rows("route")
_SEVERITY_SNOMED.update(_snomed_rows("severity"))


# Issue #458: YAML-authored route abbreviations → canonical `_ROUTE_SNOMED`
# key.
#
# `_ROUTE_SNOMED`'s keys are the token vocabulary `parse_dose_string`
# (`modules/order/engine.py`) emits — which is why `INHALED` / `NEBULIZED` / `TOPICAL`
# are spelled out while the rest are abbreviated. Disease and locale YAMLs were authored
# against a THIRD vocabulary that nobody reconciled with it, so `_ROUTE_SNOMED.get(route)`
# returned None for `INH` / `NEB` / `INHALATION` and the builders fell back to
# `{"text": route}` with no coding. Measured on JP p=300 seed=42: 172 route elements
# (166 MedicationAdministration + 6 MedicationRequest) were text-only, all `NEB`.
#
# That these are real abbreviations rather than typos is corroborated by the sibling
# JP display map `_ROUTE_JA` (`fhir_r4/lib/localization.py`), which already carries
# `INH: "吸入"` — two maps over the same vocabulary disagreed.
#
# INVARIANT: every value here MUST be an existing `_ROUTE_SNOMED` key. This table adds
# NO new SNOMED code, which is why the authoritative-display guard in
# `tests/unit/output/test_fhir_route_snomed_display.py` is unaffected.
#
# Deliberately NOT aliased — these need a NEW canonical code and therefore per-code
# authoritative verification (fhirserver / tx.fhir.org `$lookup`), never a guess:
#   NASAL, NG, TRANSDERMAL, LOCAL, CATHETER, PROCEDURAL, PROCEDURE, EXTRACORPOREAL,
#   NON-PHARMACOLOGIC, OTHER, N/A
# Aliasing any of them onto a nearby existing code would be a silent code substitution
# (the class fixed for `SL` in #311). They keep the honest text-only form until verified.
_ROUTE_ALIASES: dict[str, str] = {
    "INH": "INHALED",
    "INHALATION": "INHALED",
    "NEB": "NEBULIZED",
}


# Issue #458: Recognized-but-text-only route values (upper-case). These come out
# as `{"text": VALUE}` with no SNOMED coding — either because they need a NEW
# canonical code that hasn't been authoritatively verified yet, or because the
# real fix is elsewhere (e.g. PROCEDURAL / CATHETER on procedure-shaped drug
# entries — see Issue #460 for the resource-type problem). Kept as an explicit
# allowlist so the YAML validator doesn't reject them and reviewers see the
# by-design set at a glance. Adding a value here MUST be intentional; a new
# YAML value NOT in canonical / aliases / this set fails load with ValueError.
_ROUTE_TEXT_ONLY_BY_DESIGN: frozenset[str] = frozenset(
    {
        "NASAL",
        "NG",
        "TRANSDERMAL",
        "LOCAL",
        "CATHETER",
        "PROCEDURAL",
        "PROCEDURE",
        "EXTRACORPOREAL",
        "NON-PHARMACOLOGIC",
        "OTHER",
        "N/A",
    }
)


KNOWN_ROUTE_VOCABULARY: frozenset[str] = frozenset(
    set(_ROUTE_SNOMED.keys()) | set(_ROUTE_ALIASES.keys()) | _ROUTE_TEXT_ONLY_BY_DESIGN
)
"""Every YAML-authored `route` value MUST upper-case into this set. Comprises
the canonical SNOMED-coded set (`_ROUTE_SNOMED`), the author-abbreviation
aliases (`_ROUTE_ALIASES`), and the by-design text-only allowlist
(`_ROUTE_TEXT_ONLY_BY_DESIGN`). Consumed by `validate_yaml_route_value` — the
import-time guard added in Issue #458."""


def iter_route_values(data: Any) -> Iterator[str]:
    """Yield every ``route:`` string found anywhere in a nested YAML structure.

    Walks dicts and lists recursively and picks up only string values keyed
    exactly ``route``. The one walker feeding :func:`validate_yaml_route_value`
    for the disease, encounter and chronic-medications YAMLs (Issue #458).
    """
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "route" and isinstance(v, str):
                yield v
            else:
                yield from iter_route_values(v)
    elif isinstance(data, list):
        for item in data:
            yield from iter_route_values(item)


def validate_yaml_route_value(raw_route: str, source: str) -> None:
    """Raise ValueError if `raw_route` is not a recognized route vocabulary token.

    `source` is a human-readable location string (e.g. disease id, file path)
    used only in the error message so the offender is trivial to locate.

    Case-insensitive: the raw value is upper-cased before lookup — matches the
    `.upper()` normalization at every runtime call site
    (`_fhir_common.build_route_concept` etc.).

    Purpose: closes the silent-no-op class documented in CLAUDE.md §
    "Import-time canonical-constants validation". A new YAML `route` value
    not on the canonical / alias / by-design set falls through to text-only
    silently — the exact drift that motivated Issue #458.
    """
    if not raw_route:
        return
    normalized = str(raw_route).upper().strip()
    if not normalized:
        return
    if normalized not in KNOWN_ROUTE_VOCABULARY:
        raise ValueError(
            f"{source}: unknown route value {raw_route!r} (normalized {normalized!r}). "
            f"Add to _ROUTE_SNOMED (with a verified SNOMED code), _ROUTE_ALIASES "
            f"(if it aliases an existing canonical), or _ROUTE_TEXT_ONLY_BY_DESIGN "
            f"in clinosim/modules/output/fhir_r4/lib/reference_data.py — do not guess a code."
        )
