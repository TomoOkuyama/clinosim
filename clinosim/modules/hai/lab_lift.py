"""Phase 3a: HAI WBC + CRP forward-delta lab lift.

After the daily loop completes and POST_ENCOUNTER device + hai enrichers
populate ``record.extensions["hai"]``, this module applies a closed-form
forward delta to existing WBC + CRP observations for the affected
encounter days.

Design rationale (spec §12 v3, 2026-06-25):
  - device + hai sampling depends on the encounter's full clinical course
    (icu_transferred, GCS, perfusion) which is only known AFTER the daily
    loop completes. So they cannot run before the loop.
  - But the daily loop has already produced WBC + CRP from state-driven
    formulas; HAI events arriving post-loop need to be reflected in those
    values.
  - We use a closed-form delta derived from the same formulas
    ``derive_lab_values`` uses internally for CRP + WBC, evaluated on the
    same per-day state snapshot and same draw-time hour. The delta is the
    pure inflammatory lift (other state-driven analytes and noise are not
    re-derived), and it is added to the existing ``obs.value`` so the
    original measurement noise + circadian is preserved.

Code-review hardening (post PR-90 xhigh review, 2026-06-25):
  - Single source of truth for hai_type strings: ``modules.hai.HAI_TYPES``
    (lowercase canonical) — the previous draft had UPPERCASE keys in the
    YAML while the enricher writes lowercase, silently no-op'ing the
    entire feature in production.
  - ``state_history[N+1]`` is the post-day-N state the daily loop used
    to derive day-N labs (state_history[0] = admission state).
  - Multi-event semantics: max across matching events (consistent with
    sibling helper documentation), not additive.
  - ``round_to_precision`` + ``determine_flag`` are re-applied so the
    lifted value respects the same integer-WBC convention the daily loop
    uses and so CSV / CIF consumers do not see WBC ≈ 16,000 flagged "N".
  - Hour passed to the closed-form is the ORDER'S draw hour
    (``order.ordered_datetime.hour``) — the hour the daily loop's
    ``derive_lab_values`` used — not the obs result hour. WBC circadian
    cancels exactly when both sides use the same hour.
  - Closed-form delta avoids invoking ``derive_lab_values`` (30+ analyte
    pipeline) twice per observation; only WBC + CRP need lifting.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.hai import HAI_TYPES
from clinosim.modules.observation.engine import determine_flag, round_to_precision

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

_HAI_LIFT_ANALYTES = ("WBC", "CRP")


def _validate_hai_lab_lift_config(data: dict) -> None:
    """Validate hai_lab_lift.yaml at load time (sibling sweep, 2026-06-29).

    6-layer silent-no-op defense:
    1. top-level empty guard
    2. ramp_peak_days numeric and > 0
    3. hai_lift bucket non-empty
    4. each hai_type ⊆ HAI_TYPES
    5. each lift value numeric and ∈ [0, 1]
    6. HAI_TYPES forward-coverage
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("hai_lab_lift.yaml empty — silent no-op risk")
    ramp = data.get("ramp_peak_days")
    if not isinstance(ramp, (int, float)) or float(ramp) <= 0:
        raise ValueError(
            f"hai_lab_lift.yaml: ramp_peak_days {ramp!r} must be > 0"
        )
    lift_table = data.get("hai_lift") or {}
    if not lift_table:
        raise ValueError(
            "hai_lab_lift.yaml: hai_lift bucket empty — silent no-op risk"
        )
    valid_types = set(HAI_TYPES)
    for hai_type, value in lift_table.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_lab_lift.yaml has unknown hai_type keys {hai_type!r} — "
                f"must use HAI_TYPES {HAI_TYPES} (case-sensitive)"
            )
        if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
            raise ValueError(
                f"hai_lab_lift.yaml: {hai_type!r} lift value {value!r} "
                f"not in [0, 1]"
            )
    missing = valid_types - set(lift_table.keys())
    if missing:
        raise ValueError(
            f"hai_lab_lift.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_lab_lift_config() -> tuple[float, dict[str, float]]:
    """Load reference_data/hai_lab_lift.yaml once.

    Returns ``(ramp_peak_days, {hai_type: lift_value})``. Validation by
    ``_validate_hai_lab_lift_config`` covers the 6-layer silent-no-op
    defense pattern (sibling sweep, 2026-06-29).
    """
    data = yaml.safe_load((_REF_DIR / "hai_lab_lift.yaml").read_text(encoding="utf-8"))
    _validate_hai_lab_lift_config(data)
    return float(data["ramp_peak_days"]), dict(data["hai_lift"])


def _wbc_pre_circadian(infl: float) -> float:
    """WBC formula from physiology.engine.derive_lab_values BEFORE the
    diurnal circadian factor is applied. Kept in lockstep with the source.
    """
    if infl < 0.8:
        return 7000 + infl * 12000
    return max(1500, 7000 + 0.8 * 12000 - (infl - 0.8) * 30000)


def _circadian_wbc(hour: int) -> float:
    """Daily-loop WBC circadian factor; nadir ~04:00, peak ~16:00."""
    return 1.0 + 0.10 * (-math.cos((hour - 4) * math.pi / 12))


def _hai_lift_delta(
    state: Any, lab_name: str, effective_lift: float, draw_hour: int,
) -> float:
    """Closed-form WBC + CRP delta for the HAI inflammation lift.

    Mirrors the exact formulas in physiology.engine.derive_lab_values' CRP
    + WBC blocks so the delta equals what ``derive(state, lift>0) -
    derive(state, lift=0)`` would compute, but without invoking the full
    derive pipeline (30+ analytes recomputed for nothing). Only WBC and
    CRP are affected by hai_inflammation_lift via effective_infl.
    """
    infl = state.inflammation_level
    eff_infl = min(1.0, infl + effective_lift)
    if eff_infl == infl:
        return 0.0
    if lab_name == "CRP":
        # CRP = 0.3 + 400 * effective_infl ** 3  (hour-independent)
        return 400.0 * (eff_infl ** 3 - infl ** 3)
    if lab_name == "WBC":
        circ = _circadian_wbc(draw_hour)
        return (_wbc_pre_circadian(eff_infl) - _wbc_pre_circadian(infl)) * circ
    return 0.0


def _best_effective_lift(
    matching: list[tuple[date, float]],
    obs_date: date,
    ramp_peak_days: float,
) -> float:
    """Max effective_lift across all matching HAI events for this obs day.
    Multi-event semantics: ``max`` (not sum) - co-infections do not stack
    additive inflammation; the documented severity is the strongest of
    the simultaneous insults.
    """
    best = 0.0
    for onset_dt, lift_value in matching:
        days_since = (obs_date - onset_dt).days
        if days_since < 0:
            continue
        ramp = (
            min(1.0, days_since / ramp_peak_days) if ramp_peak_days > 0 else 1.0
        )
        eff = lift_value * ramp
        if eff > best:
            best = eff
    return best


def apply_hai_lab_lift(
    record,
    encounter,
    state_history: list[Any],
    admission_time: datetime,
) -> int:
    """Apply HAI WBC + CRP forward-delta to existing lab_results.

    For each WBC + CRP observation whose result_datetime.date() falls on or
    after a matching ``extensions["hai"]`` event's onset_date, add a closed-
    form forward delta to obs.value (preserving original noise + circadian),
    then re-apply ``round_to_precision`` + ``determine_flag`` so consumers
    that read ``obs.flag`` directly (CSV adapter, audit scripts) see the
    correct H/L marker on the lifted value.

    Returns the number of observation values modified.
    """
    events = (getattr(record, "extensions", None) or {}).get("hai") or []
    if not events:
        return 0

    ramp_peak_days, lift_table = load_hai_lab_lift_config()
    encounter_id = getattr(encounter, "encounter_id", "")

    # Pre-resolve matching events: parse onset_date once, look up lift_value
    # once (single source of truth lookups validated against HAI_TYPES at
    # YAML load time).
    matching: list[tuple[date, float]] = []
    for ev in events:
        if getattr(ev, "encounter_id", None) != encounter_id:
            continue
        onset_str = getattr(ev, "onset_date", None)
        if not onset_str:
            continue
        try:
            onset_dt = date.fromisoformat(onset_str)
        except (TypeError, ValueError):
            continue
        hai_type = getattr(ev, "hai_type", "")
        lift_value = lift_table.get(hai_type, 0.0)
        if lift_value <= 0.0:
            continue
        matching.append((onset_dt, lift_value))
    if not matching:
        return 0

    patient = getattr(record, "patient", None)
    if patient is None:
        return 0
    sex = getattr(patient, "sex", "M")
    admission_date = admission_time.date()

    # Map OrderResult id -> Order so the WBC circadian uses the ORDER's
    # draw hour (the hour ``derive_lab_values`` was originally called
    # with), not the later result_datetime.hour.
    result_to_order = {
        id(o.result): o
        for o in (getattr(record, "orders", None) or [])
        if getattr(o, "result", None) is not None
    }

    modified = 0
    for obs in getattr(record, "lab_results", None) or []:
        lab_name = getattr(obs, "lab_name", "")
        if lab_name not in _HAI_LIFT_ANALYTES:
            continue
        val = getattr(obs, "value", None)
        if not isinstance(val, (int, float)):
            continue
        res_dt = getattr(obs, "result_datetime", None)
        if not isinstance(res_dt, datetime):
            continue
        obs_date = res_dt.date()

        effective_lift = _best_effective_lift(
            matching, obs_date, ramp_peak_days,
        )
        if effective_lift <= 0.0:
            continue

        day_index = (obs_date - admission_date).days
        # state_history[0] is the admission state; state_history[N+1] is
        # the post-day-N state the daily loop used to derive day-N labs.
        state_idx = day_index + 1
        if state_idx < 0 or state_idx >= len(state_history):
            continue
        state_snap = state_history[state_idx]

        order = result_to_order.get(id(obs))
        if order is not None and isinstance(
            getattr(order, "ordered_datetime", None), datetime,
        ):
            draw_hour = order.ordered_datetime.hour
        else:
            # Fallback: most lab draws happen at 5-6 AM; result hour is
            # within 2-4 hours later. Use 6 AM so a missing order
            # back-reference does not silently produce a circadian-
            # mismatched delta.
            draw_hour = 6

        delta = _hai_lift_delta(state_snap, lab_name, effective_lift, draw_hour)
        if delta == 0:
            continue

        new_val = round_to_precision(lab_name, float(val) + delta)
        obs.value = new_val
        obs.flag = determine_flag(lab_name, new_val, sex=sex)
        modified += 1
    return modified
