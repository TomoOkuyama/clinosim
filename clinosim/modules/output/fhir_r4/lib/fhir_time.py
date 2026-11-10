"""FHIR date / dateTime / instant conversion with the country's time-zone
suffix, and ``meta.lastUpdated`` derivation (split out of ``common.py`` in
Issue #2530)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from clinosim.country_profile import country_profile

__all__ = [
    "derive_meta_last_updated",
    "to_fhir_date",
    "to_fhir_datetime",
    "to_fhir_instant",
    "tz_suffix_for_country",
]


# cycle 8 拡張 (feedback FB-F1):
# JP コホートの dateTime / instant field は JST (+09:00) を必ず付与する。
# HAPI FHIR Validator (JP Core 準拠) は TZ 無し dateTime を regex エラーとする。
# to_fhir_datetime + to_fhir_instant で単一 seam 化、per-builder 個別修正回避。
_JST_TZ_SUFFIX = "+09:00"
# Suffix when no country is in scope (UTC, the neutral default). A country's
# own suffix is its profile ``timezone`` (Issue #3141).
_UTC_TZ_SUFFIX = "Z"


def tz_suffix_for_country(country: str) -> str:
    """Canonical timezone suffix for the country's FHIR datetime / instant fields.

    The country profile's ``timezone`` (``locale/<cc>/country.yaml``: JP →
    ``+09:00``, US → ``Z``; Issue #3141). No country → ``Z`` (UTC); a country
    without a profile raises ``KeyError``. Callers use this instead of
    hardcoding a TZ suffix so US cohorts do not silently emit JST timestamps
    (Issue #570 locale-gate convention).
    """
    if not str(country or "").strip():
        return _UTC_TZ_SUFFIX
    return country_profile(country).timezone


def _append_tz_if_missing(s: str) -> str:
    """ISO 8601 datetime string に TZ が無ければ ``+09:00`` (JST) を付与。

    Historical helper: builders unconditionally append JST here. The post-emit
    walker (:func:`clinosim.modules.output.fhir_r4.post_process._normalize_dt_fields`)
    rewrites the suffix per-country afterwards (Issue #570 locale gate), so US
    cohorts do not retain JST in their final output.

    既に TZ suffix(+HH:MM / -HH:MM / Z)がある場合は passthrough。
    'T' を含まない date-only 文字列 (YYYY-MM-DD) は passthrough(FHIR は date
    型として許容)。
    """
    if not s or "T" not in s:
        return s
    # tail check for existing TZ
    tail = s[-6:]  # like "+09:00" or "-05:00"
    if s.endswith("Z"):
        return s
    if len(s) >= 6 and (tail.startswith("+") or tail.startswith("-")) and tail[3] == ":":
        return s
    # short TZ form "+0900" (no colon)
    if len(s) >= 5 and (s[-5] == "+" or s[-5] == "-") and s[-5:-2].lstrip("+-").isdigit():
        return s
    return s + _JST_TZ_SUFFIX


def to_fhir_datetime(value: Any) -> str:
    """Normalize a datetime-like value to a FHIR R4 ``dateTime`` string with TZ.

    FHIR R4 ``dateTime`` requires ISO 8601 with ``T`` separator; ``str(datetime)``
    produces space-separated form which fails the R4 regex. This helper accepts:
    ``datetime`` / ``date`` objects (via ``.isoformat()``), ISO strings
    (passthrough), space-separated strings (normalized to ``T`` form),
    ``None`` / empty string (→ ``""``).

    Single edit point for the ``str(x)`` / ``hasattr(x, "isoformat")`` fallback
    pattern previously scattered across FHIR builders (FP-UNIFY-2, 2026-07-07).

    cycle 8 (feedback FB-F1): TZ 無し文字列には JST (+09:00) を付与。
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (datetime, date)):
        s = value.isoformat()
    else:
        s = str(value)
        if len(s) >= 11 and s[10] == " ":
            s = s[:10] + "T" + s[11:]
    return _append_tz_if_missing(s)


def _with_country_tz(s: str, tz: str) -> str:
    """Append ``tz`` to an ISO datetime string that carries no TZ suffix."""
    return s if _append_tz_if_missing(s) == s else s + tz


def to_fhir_deceased_datetime(value: Any, country: str) -> str:
    """Normalize ``Patient.deceasedDateTime``.

    Issue #1440: a bare date value emits as ``YYYY-MM-DD`` and gets
    interpreted by strict temporal checks as ``T00:00:00``. Any
    same-day intra-day event — most importantly a death-related
    inpatient encounter's ``period.end`` and a post-mortem
    ``Condition.recordedDate`` — then falls after the deceased
    moment even though the simulator's intent was that the patient
    died at the end of the last encounter.

    Expand a date-only input to end-of-day (``T23:59:59``) with the
    country's canonical TZ suffix so every same-day event lands before
    the deceased moment. Full datetime inputs (already carrying a time
    component) keep their time, with the country's TZ when naive — the documented time of an
    in-hospital death (``PatientProfile.death_datetime``, Issue #2984)
    takes this path.

    Empty / ``None`` returns ``""`` (matches ``to_fhir_datetime``).
    """
    if value is None or value == "":
        return ""
    tz = tz_suffix_for_country(country)
    # Full datetime object → its ISO form, at the country's TZ when naive.
    if isinstance(value, datetime):
        return _with_country_tz(value.isoformat(), tz)
    # date object → end-of-day at the country's TZ.
    if isinstance(value, date) and not isinstance(value, datetime):
        return f"{value.isoformat()}T23:59:59{tz}"
    # String forms.
    s = str(value)
    # Already carries a time component → keep it; a naive time gets the
    # country's TZ (Issue #2984: the post-emit TZ walker does not visit
    # ``deceasedDateTime``, so the JST default must not leak into US).
    if "T" in s and len(s) >= 11:
        return _with_country_tz(s, tz)
    # Space-separated datetime → normalize the separator then forward.
    if len(s) >= 11 and s[10] == " ":
        return _with_country_tz(s[:10] + "T" + s[11:], tz)
    # Date-only string (``YYYY-MM-DD``) → expand to end-of-day.
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s}T23:59:59{tz}"
    # Fallback: forward as-is.
    return to_fhir_datetime(s)


def to_fhir_instant(value: Any) -> str:
    """Normalize to FHIR R4 ``instant`` (秒精度 + TZ 必須).

    ``instant`` is stricter than ``dateTime``: time-of-day and TZ are required.
    Milliseconds recommended. feedback FB-F1 で導入。
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        s = value.isoformat()
        # ensure seconds present
        if "." not in s.split("T", 1)[1] and s.count(":") == 2:
            pass  # already has seconds
        elif s.count(":") == 1:
            s += ":00"
        return _append_tz_if_missing(s)
    if isinstance(value, date):
        # date-only → make midnight instant with JST (post-process walker
        # rewrites for non-JP cohorts per Issue #570).
        return f"{value.isoformat()}T00:00:00{_JST_TZ_SUFFIX}"
    s = str(value)
    if len(s) >= 11 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    # date-only string → append midnight
    if "T" not in s and len(s) == 10:
        return f"{s}T00:00:00{_JST_TZ_SUFFIX}"
    # ensure seconds present
    if s.count(":") == 1:
        s += ":00"
    return _append_tz_if_missing(s)


def to_fhir_date(value: Any) -> str:
    """Normalize a datetime-like value to a FHIR R4 ``date`` string (YYYY-MM-DD).

    Strips any time component. Accepts ``date`` / ``datetime`` objects, ISO
    strings, space-separated strings, ``None`` / empty string (→ ``""``).
    Companion to :func:`to_fhir_datetime` (FP-UNIFY-2, 2026-07-07).
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def derive_meta_last_updated(resource: dict, prefer: tuple[str, ...]) -> str | None:
    """Canonical fallback resolver for FHIR ``Resource.meta.lastUpdated`` (Issue #549).

    Walks ``prefer`` field paths in order and returns the first non-empty value.
    Supports dotted paths for nested lookups (e.g. ``"effectivePeriod.end"``).
    Returns ``None`` when no field yields a value — callers may then apply a
    secondary fallback (bundle-context timestamp, doc-source datetime, etc.).

    Six emit sites populated ``meta.lastUpdated`` with five distinct hardcoded
    fallback chains before this helper; new resource types had no canonical
    pattern to follow. The chain is now expressed as a tuple at each call site
    and the traversal shares one implementation.
    """
    for path in prefer:
        cur: Any = resource
        for part in path.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur:
            return cur
    return None
