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

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.timeutil import parse_iso_datetime

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
    lab_dt = parse_iso_datetime(_get(lab, "result_datetime"))
    adm_dt = parse_iso_datetime(admission_datetime)
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
        existing_dt = parse_iso_datetime(_get(existing, "result_datetime"))
        new_dt = parse_iso_datetime(_get(lab, "result_datetime"))
        if existing_dt is None or (new_dt is not None and new_dt > existing_dt):
            out[name] = lab
    return out


# ---------------------------------------------------------------------------
# One draw = the rows of one analyte reported close together
# ---------------------------------------------------------------------------


def group_draws(rows: list[tuple[datetime, Any]], window: timedelta) -> list[list[tuple[datetime, Any]]]:
    """Group the ``(time, lab)`` rows of ONE analyte, in time order, into
    draws: a row within ``window`` of the first row of the current draw
    belongs to it (``notable_labs.yaml`` ``draw_window_minutes``). The record
    carries separate rows for one blood draw, minutes apart, with slightly
    different values; they are one measurement for a note."""
    draws: list[list[tuple[datetime, Any]]] = []
    for at, lab in sorted(rows, key=lambda row: row[0]):
        if draws and at - draws[-1][0][0] <= window:
            draws[-1].append((at, lab))
        else:
            draws.append([(at, lab)])
    return draws


def _draw_window() -> timedelta:
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    return timedelta(minutes=notable_lab_rules().draw_window_minutes)


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
    """For each analyte measured on ``day_index`` (one value per draw, see
    :func:`group_draws`), return a trend entry comparing it against the
    closest earlier day's measurement of the same analyte.

    Returns list of dicts with keys::

        name           lab_name (string)
        current_value  numeric
        current_flag   "" | "H" | "L" | "critical" | ...
        prior_value    numeric (None if no prior measurement)
        prior_day      int (None if no prior measurement)
        prior_flag     str (None if no prior measurement)
        direction      "improving" | "worsening" | "stable" | "initial"
    """
    from clinosim.modules.observation.engine import canonical_lab_name

    # One draw per analyte (rows minutes apart are one measurement): the last
    # row of the draw stands for it, on the day it was reported.
    rows_by_analyte: dict[str, list[tuple[datetime, Any]]] = {}
    first_seen: dict[str, int] = {}
    for idx, lab in enumerate(lab_results or []):
        at = parse_iso_datetime(_get(lab, "result_datetime"))
        name = _get(lab, "lab_name") or _get(lab, "name")
        if at is None or not name or day_of_lab(lab, admission_datetime) is None:
            continue
        canon = canonical_lab_name(str(name))
        rows_by_analyte.setdefault(canon, []).append((at, lab))
        first_seen.setdefault(canon, idx)

    window = _draw_window()
    out: list[dict[str, Any]] = []
    for canon in sorted(rows_by_analyte, key=lambda c: first_seen[c]):
        draws = [
            (day_of_lab(d[-1][1], admission_datetime), d[-1][1]) for d in group_draws(rows_by_analyte[canon], window)
        ]
        today = [lab for day, lab in draws if day == day_index]
        if not today:
            continue
        today_lab = today[-1]
        name = _get(today_lab, "lab_name") or _get(today_lab, "name")
        current_value = _get(today_lab, "value")
        current_flag = _get(today_lab, "flag") or ""
        earlier = [(day, lab) for day, lab in draws if day is not None and day < day_index]
        if not earlier:
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
        prior_day, prior_lab = earlier[-1]
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


# ---------------------------------------------------------------------------
# Notable labs of a day (Issue #3230)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotableLab:
    """One analyte's entry in a note's notable labs: the CIF result shown
    (the day's worst flagged draw), the analyte's previous value, and the
    abnormality it names (a ``lab_finding.<slug>`` phrase key) if any."""

    lab: Any
    prior_value: Any
    finding: str | None


# Draw severity within one analyte's day: a panic result outranks a flagged
# (hemolysed) specimen, which outranks an ordinary H / L.
_DRAW_SEVERITY = {"critical": 3, "!": 3, "H*": 2, "L*": 2}
_HEMOLYZED_FLAGS = frozenset({"H*", "L*"})
_PANIC_FLAGS = frozenset({"critical", "!"})


def _lab_name(lab: Any) -> str:
    return str(_get(lab, "lab_name") or _get(lab, "name") or "")


def _lab_day(lab: Any, admission_datetime: Any) -> int | None:
    day = _get(lab, "day")
    return int(day) if day is not None else day_of_lab(lab, admission_datetime)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def flag_side(lab: Any) -> str | None:
    """The side of the reference range a flagged result is on (``"high"`` /
    ``"low"``; a panic result by the panic thresholds), ``None`` unflagged."""
    from clinosim.modules.observation.engine import panic_side

    flag = str(_get(lab, "flag") or "")
    if flag in _PANIC_FLAGS:
        return panic_side(_lab_name(lab), _get(lab, "value"))
    if flag.startswith("H"):
        return "high"
    if flag.startswith("L"):
        return "low"
    return None


def _names_finding(rule: Any, side: str | None, flag: str, value: float | None) -> bool:
    """Whether a flagged result on ``side`` names ``rule.finding``
    (``notable_labs.yaml`` findings): a panic result always; otherwise a
    value strictly beyond ``rule.beyond``, or any value when ``any_flag``."""
    if flag in _PANIC_FLAGS or rule.any_flag:
        return True
    if rule.beyond is None or value is None:
        return False
    return value < rule.beyond if side == "low" else value > rule.beyond


def _meets_kdigo_aki(lab: Any, at: datetime | None, history: list[tuple[datetime, Any]]) -> bool:
    """KDIGO 2012 AKI (``notable_labs.yaml`` ``aki``) at the shown creatinine:
    a rise by the absolute amount within its window, or to the relative
    multiple of the lowest value of the relative window."""
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    aki = notable_lab_rules().aki
    value = _numeric(_get(lab, "value"))
    if at is None or value is None:
        return False
    unit = str(_get(lab, "unit") or "")
    earlier = [(t, _numeric(_get(h, "value")), str(_get(h, "unit") or "")) for t, h in history if t < at]
    relative = [v for t, v, u in earlier if v and u == unit and t >= at - timedelta(days=aki.relative_window_days)]
    if relative and value >= aki.relative_rise * min(relative):
        return True
    if unit != aki.absolute_rise_unit:
        return False
    absolute = [
        v for t, v, u in earlier if v is not None and u == unit and t >= at - timedelta(hours=aki.absolute_window_hours)
    ]
    return bool(absolute) and round(value - min(absolute), 6) >= aki.absolute_rise


def select_notable_labs(
    lab_results: list[Any],
    admission_datetime: Any,
    day_index: int | None,
    as_of: datetime | None = None,
) -> list[NotableLab]:
    """The flagged results a note on hospital day ``day_index`` (``None``:
    the whole record) cites, one entry per analyte, in clinical priority.

    Only results reported at or before ``as_of`` (the note's authored time;
    ``None``: no cut-off) count. A daily note with an authored time cites
    the results of the ``window_hours`` up to it (``notable_labs.yaml``),
    so a result reported after one day's note is cited by the next; without
    one, the results of hospital day ``day_index``. Each analyte shows its
    worst draw of the window (panic flag, then hemolysed specimen, then
    H / L; the latest among equals) with the previous value of that analyte. Order: panic results;
    results naming an abnormality (``notable_labs.yaml`` findings, KDIGO AKI,
    hemolysed specimen); results newly abnormal against the previous value;
    persisting abnormalities; within a tier, by first report time. A result
    without a day or a time is kept (it cannot be placed after the note).
    """
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules
    from clinosim.modules.observation.engine import canonical_lab_name

    rules = notable_lab_rules()
    window_start = as_of - timedelta(hours=rules.window_hours) if as_of is not None and day_index is not None else None
    available: list[tuple[int, datetime | None, Any]] = []
    for idx, lab in enumerate(lab_results or []):
        at = parse_iso_datetime(_get(lab, "result_datetime"), lenient=True)
        if as_of is not None and at is not None and at > as_of:
            continue
        available.append((idx, at, lab))
    available.sort(key=lambda row: (row[1] or datetime.min, row[0]))

    rows: dict[str, list[tuple[datetime, Any]]] = {}
    for _, at, lab in available:
        if at is not None:
            rows.setdefault(canonical_lab_name(_lab_name(lab)), []).append((at, lab))
    window = timedelta(minutes=rules.draw_window_minutes)
    history = {canon: group_draws(analyte_rows, window) for canon, analyte_rows in rows.items()}

    shown: dict[str, tuple[int, datetime | None, Any]] = {}
    first_seen: dict[str, int] = {}
    for order, (_, at, lab) in enumerate(available):
        flag = str(_get(lab, "flag") or "")
        name = _lab_name(lab)
        if not flag or not name or _get(lab, "value") is None:
            continue
        if window_start is not None and at is not None:
            if at <= window_start:
                continue
        elif day_index is not None:
            day = _lab_day(lab, admission_datetime)
            if day is not None and day != day_index:
                continue
        canon = canonical_lab_name(name)
        first_seen.setdefault(canon, order)
        severity = _DRAW_SEVERITY.get(flag, 1)
        current = shown.get(canon)
        if current is None or severity >= current[0]:
            shown[canon] = (severity, at, lab)

    ranked: list[tuple[int, int, NotableLab]] = []
    for canon, (_, at, lab) in shown.items():
        flag = str(_get(lab, "flag") or "")
        # The previous value is the last result of an EARLIER draw, never a
        # sibling row of the shown draw.
        draws = history.get(canon, [])
        position = next((i for i, d in enumerate(draws) if any(h is lab for _, h in d)), None)
        earlier_rows = [row for d in draws[:position] for row in d] if position is not None else []
        prior = draws[position - 1][-1][1] if position else None
        finding: str | None = None
        if flag in _HEMOLYZED_FLAGS:
            finding = "hemolyzed"
        else:
            side = flag_side(lab)
            entry = rules.findings.get(canon)
            rule = getattr(entry, side) if entry is not None and side is not None else None
            if rule is not None and _names_finding(rule, side, flag, _numeric(_get(lab, "value"))):
                finding = rule.finding
            if finding is None and canon == rules.aki.analyte and _meets_kdigo_aki(lab, at, earlier_rows):
                finding = "aki"
        if flag in _PANIC_FLAGS:
            tier = 0
        elif finding is not None:
            tier = 1
        elif prior is None or not _get(prior, "flag"):
            tier = 2
        else:
            tier = 3
        prior_value = _get(prior, "value") if prior is not None else None
        ranked.append((tier, first_seen[canon], NotableLab(lab=lab, prior_value=prior_value, finding=finding)))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in ranked]
