"""Datetime / period / instant field normalization for FHIR resources.

Extracted from ``_fhir_post_process.py`` (Issue #555 PR3, folds Issue #556).
Universal walker that rewrites string-typed datetime / instant / period
fields to the country-appropriate TZ suffix.
"""

from __future__ import annotations

# session 48 feedback FB-F1: 全 emit resource で dateTime / instant field を
# TZ 付与に正規化する post-emit normalization pass。builders 個別修正の代替。
# 対象 field は FHIR R4 で dateTime / instant 型を持つ known-name 一覧。
_DATETIME_FIELDS = frozenset(
    (
        # top-level dateTime
        "authoredOn",
        "effectiveDateTime",
        "performedDateTime",
        "date",
        "started",
        "receivedTime",
        "recordedDate",
        "onsetDateTime",
        "occurrenceDateTime",
        "abatementDateTime",
        "assertedDate",
        "authored",
        "assertedDateTime",
        "collectedDateTime",  # Specimen.collection.collectedDateTime (nested)
        "time",  # attester.time / Provenance.recorded など
        # instant type
        "issued",
        "recorded",
        "createdOn",
        "sent",
        "lastUpdated",
    )
)


_PERIOD_FIELDS = frozenset(("start", "end"))


# Period-typed dict keys the walker treats as `{"start": ..., "end": ...}` sub-objects.
# Issue #570 audit: `performedPeriod` / `effectivePeriod` / `occurrencePeriod` were
# recursed but their `start`/`end` were not in `_DATETIME_FIELDS`, so JST leaked
# through them on US cohorts. Enumerated here as a single source of truth.
_PERIOD_KEYS = frozenset(
    (
        "period",
        "validityPeriod",
        "servicedPeriod",
        "performedPeriod",
        "effectivePeriod",
        "occurrencePeriod",
        "authoredOnPeriod",
    )
)


# instant 型 field(秒精度+TZ 必須)
_INSTANT_FIELDS = frozenset(("issued", "lastUpdated"))


def _normalize_dt(v, country: str = "", want_instant: bool = False):
    """string dateTime → country-specific TZ suffix 付与 / rewrite。

    Issue #570 locale gate: builders unconditionally emit ``+09:00`` (JST) via
    ``to_fhir_datetime`` / ``to_fhir_instant``. This walker then rewrites the
    suffix per country: JP keeps ``+09:00``; other cohorts (US default) get
    ``Z`` (UTC neutral). Other pre-existing TZ suffixes (e.g. ``-05:00``) are
    preserved as-is.
    """
    from clinosim.modules.output.fhir_r4.lib.common import tz_suffix_for_country

    tz = tz_suffix_for_country(country)
    if not isinstance(v, str) or not v:
        return v
    # date-only YYYY-MM-DD は通す(FHIR date 型として valid)
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        if want_instant:
            # instant 要求 → 秒 + TZ 補完
            return f"{v}T00:00:00{tz}"
        return v
    if "T" not in v:
        return v  # 空 or 非 datetime 形式は不変
    # 既に JST suffix — country が JP なら維持、それ以外は country の TZ に rewrite。
    if v.endswith("+09:00"):
        return v if tz == "+09:00" else v[:-6] + tz
    # 他 TZ (Z, -05:00 等) は既に explicit なので変更しない (builder or upstream 意図)。
    if v.endswith("Z") or (len(v) >= 6 and v[-6] in "+-" and v[-3] == ":"):
        return v
    # TZ 無し → country の TZ を付与。秒欠落補完 (instant 用)。
    if want_instant and v.count(":") == 1:
        v = v + ":00"
    return v + tz


def _normalize_dt_fields(resource, country: str = "") -> None:
    """resource dict を再帰 walk、_DATETIME_FIELDS / _INSTANT_FIELDS / Period を正規化。

    Issue #570: threads ``country`` through so US cohorts append UTC (``Z``)
    instead of JST (``+09:00``). Callers with country in scope must pass it;
    the default `""` falls back to UTC (safest neutral).
    """
    if isinstance(resource, dict):
        for k, v in list(resource.items()):
            if k in _INSTANT_FIELDS and isinstance(v, str):
                resource[k] = _normalize_dt(v, country, want_instant=True)
            elif k in _DATETIME_FIELDS and isinstance(v, str):
                resource[k] = _normalize_dt(v, country)
            elif k in _PERIOD_KEYS and isinstance(v, dict):
                for pk in _PERIOD_FIELDS:
                    if pk in v:
                        v[pk] = _normalize_dt(v[pk], country)
                _normalize_dt_fields(v, country)
            elif isinstance(v, (dict, list)):
                _normalize_dt_fields(v, country)
    elif isinstance(resource, list):
        for item in resource:
            _normalize_dt_fields(item, country)
