"""Lab result time-series transformations for narrative context.

Renderer-neutral helpers that take raw CIF ``lab_results`` (list of
LabResult-shaped dicts) + the encounter's ``admission_datetime`` and
return day-partitioned / trend / carry-forward views. The narrative
renderer (:mod:`clinosim.modules.document.narrative.replacement_strategy`)
orchestrates converting these views into localized strings for the LLM
prompt.

Design contract
---------------

* **Pure functions.** No I/O, no globals, no rng. Determinism preserved
  automatically — the renderer that consumes them stays byte-neutral.
* **``result_datetime`` is the time source.** CIF ``lab_results`` already
  carry ``result_datetime``; adding a ``day`` field at the CIF layer is
  therefore unnecessary. The renderer passes the encounter's
  ``admission_datetime`` and each helper computes day-of-lab locally.
* **Day 0 = the calendar day of ``admission_datetime``.** ``day_index=0``
  in the narrative context therefore matches the H&P (入院初日).
* **No new tunable constants in ordinary code paths** (grand-design
  principle). The single 10% ``_STABLE_RELATIVE_DELTA`` band that
  separates "improving" from "stable" for same-flag comparisons is
  fixed and documented rather than yaml-driven — tuning it shifts
  only the improving/stable boundary near-noise deltas, not the
  clinical structure of the output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _get(d: Any, key: str, default: Any = None) -> Any:
    """dict[str, Any] or dataclass-like read."""
    if hasattr(d, key):
        return getattr(d, key)
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Day-of-lab primitive
# ---------------------------------------------------------------------------


def day_of_lab(lab: Any, admission_datetime: Any) -> int | None:
    """Return the day-since-admission integer for ``lab``.

    ``(result_datetime.date() - admission_datetime.date()).days``.
    Day 0 = the calendar day of admission (matches ``day_index=0`` in
    the narrative context = 入院初日). Returns ``None`` when either
    datetime is missing or unparseable, so callers can skip the lab
    rather than count it against the wrong day.
    """
    lab_dt = _parse_datetime(_get(lab, "result_datetime"))
    adm_dt = _parse_datetime(admission_datetime)
    if lab_dt is None or adm_dt is None:
        return None
    return (lab_dt.date() - adm_dt.date()).days


# ---------------------------------------------------------------------------
# Day-partitioned views
# ---------------------------------------------------------------------------


def labs_measured_on_day(
    lab_results: list[Any],
    admission_datetime: Any,
    day_index: int,
) -> list[Any]:
    """Subset of ``lab_results`` whose ``day_of_lab`` equals ``day_index``.

    Labs missing ``result_datetime`` are skipped (they cannot be assigned
    to a day; letting them through would over-report today's activity).
    """
    return [lab for lab in lab_results or [] if day_of_lab(lab, admission_datetime) == day_index]


def latest_by_lab_name(
    lab_results: list[Any],
    admission_datetime: Any,
    up_to_day: int,
) -> dict[str, Any]:
    """For each unique ``lab_name``, the most recent entry with
    ``day_of_lab ≤ up_to_day``.

    Represents the "current known state" of every test that has been
    ordered at least once by day ``up_to_day`` — the carry-forward
    view the renderer uses so notes on day N can mention tests that
    were last measured on day N-1 or earlier without stale-dating them.

    The most recent entry is chosen by strict ``result_datetime``
    ordering (not by day alone), so two same-day draws resolve
    deterministically to the later timestamp.
    """
    out: dict[str, Any] = {}
    for lab in lab_results or []:
        day = day_of_lab(lab, admission_datetime)
        if day is None or day > up_to_day:
            continue
        name = _get(lab, "lab_name") or _get(lab, "name")
        if not name:
            continue
        existing = out.get(name)
        if existing is None:
            out[name] = lab
            continue
        existing_dt = _parse_datetime(_get(existing, "result_datetime"))
        new_dt = _parse_datetime(_get(lab, "result_datetime"))
        if existing_dt is None or (new_dt is not None and new_dt > existing_dt):
            out[name] = lab
    return out


# ---------------------------------------------------------------------------
# Trend classification
# ---------------------------------------------------------------------------


# Flag severity ordering: higher = more abnormal. ``critical`` outranks
# ``H`` / ``L``; empty flag = normal. Used to detect improving /
# worsening direction independent of value polarity (a lab can be
# abnormally low OR high; comparing flags avoids the "high value moving
# lower is always improvement" mistake).
_FLAG_SEVERITY = {"": 0, "H": 1, "L": 1, "H*": 1, "L*": 1, "critical": 2, "!": 2}


def _flag_severity(flag: str | None) -> int:
    if flag is None:
        return 0
    return _FLAG_SEVERITY.get(flag, 1)


_STABLE_RELATIVE_DELTA = 0.10  # ±10% window; see module docstring.


def _classify_direction(
    current_flag: str,
    current_value: float,
    prior_flag: str,
    prior_value: float,
) -> str:
    """Return ``"improving"`` | ``"worsening"`` | ``"stable"``.

    Priority:
    1. Flag severity change wins (H → normal = improving; normal → H
       = worsening).
    2. Same severity: relative value change within ±10% = stable.
    3. Same severity, larger delta: for H / critical / H* labs, lower
       value = improving; for L / L* labs, higher value = improving.
       Empty-flag same-value cases fall through to stable.
    """
    cur_sev = _flag_severity(current_flag)
    pri_sev = _flag_severity(prior_flag)
    if cur_sev < pri_sev:
        return "improving"
    if cur_sev > pri_sev:
        return "worsening"
    if prior_value == 0:
        return "stable"
    rel = (current_value - prior_value) / abs(prior_value)
    if abs(rel) <= _STABLE_RELATIVE_DELTA:
        return "stable"
    if current_flag in {"L", "L*"}:
        return "improving" if current_value > prior_value else "worsening"
    if current_flag in {"H", "H*", "critical", "!"}:
        return "improving" if current_value < prior_value else "worsening"
    return "stable"


def lab_trend(
    lab_results: list[Any],
    admission_datetime: Any,
    day_index: int,
) -> list[dict[str, Any]]:
    """For each lab measured on ``day_index``, return a trend entry
    comparing it against the closest earlier measurement of the same
    ``lab_name``.

    Returns list of dicts with keys::

        name           lab_name (string)
        current_value  numeric
        current_flag   "" | "H" | "L" | "critical" | ...
        prior_value    numeric (None if no prior measurement)
        prior_day      int (None if no prior measurement)
        prior_flag     str (None if no prior measurement)
        direction      "improving" | "worsening" | "stable" | "initial"
    """
    by_name: dict[str, list[tuple[int, Any]]] = {}
    for lab in lab_results or []:
        day = day_of_lab(lab, admission_datetime)
        if day is None:
            continue
        name = _get(lab, "lab_name") or _get(lab, "name")
        if not name:
            continue
        by_name.setdefault(name, []).append((day, lab))

    for name in by_name:
        by_name[name].sort(
            key=lambda pair: (pair[0], _parse_datetime(_get(pair[1], "result_datetime")) or datetime.min)
        )

    out: list[dict[str, Any]] = []
    today_labs = labs_measured_on_day(lab_results, admission_datetime, day_index)
    for today_lab in today_labs:
        name = _get(today_lab, "lab_name") or _get(today_lab, "name")
        if not name:
            continue
        current_value = _get(today_lab, "value")
        current_flag = _get(today_lab, "flag") or ""
        prior_day: int | None = None
        prior_lab: Any = None
        for day, cand in by_name.get(name, []):
            if day < day_index:
                prior_day = day
                prior_lab = cand
            else:
                break
        if prior_lab is None:
            out.append(
                {
                    "name": name,
                    "current_value": current_value,
                    "current_flag": current_flag,
                    "prior_value": None,
                    "prior_day": None,
                    "prior_flag": None,
                    "direction": "initial",
                }
            )
            continue
        prior_value = _get(prior_lab, "value")
        prior_flag = _get(prior_lab, "flag") or ""
        try:
            direction = _classify_direction(current_flag, float(current_value), prior_flag, float(prior_value))
        except (TypeError, ValueError):
            direction = "stable"
        out.append(
            {
                "name": name,
                "current_value": current_value,
                "current_flag": current_flag,
                "prior_value": prior_value,
                "prior_day": prior_day,
                "prior_flag": prior_flag,
                "direction": direction,
            }
        )
    return out
