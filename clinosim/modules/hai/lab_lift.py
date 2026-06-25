"""Phase 3a: HAI WBC + CRP forward-delta lab lift.

After the daily loop completes and POST_ENCOUNTER device + hai enrichers
populate `record.extensions["hai"]`, this module applies a forward-formula
delta to existing WBC + CRP observations for the affected encounter days.

Design rationale (spec §12 v3, 2026-06-25):
  - device + hai sampling depends on the encounter's full clinical course
    (icu_transferred, GCS, perfusion) which is only known AFTER the daily
    loop completes. So they cannot run before the loop.
  - But the daily loop has already produced WBC + CRP from state-driven
    formulas; HAI events arriving post-loop need to be reflected in those
    values.
  - We use forward-delta: for each affected observation, compute
        delta = derive_lab_values(state, lift>0) - derive_lab_values(state, lift=0)
    on the per-day state snapshot (from state_history), then add the delta
    to the existing obs.value. This preserves the original noise / circadian
    (which was added by the daily loop) while injecting the deterministic
    HAI inflammatory effect.
  - Forward formula (not reverse engineering) → no noise loss, mathematically
    exact, future-proof for Phase 3b/c sepsis cascade extensions.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_HAI_LIFT_ANALYTES = ("WBC", "CRP")


@lru_cache(maxsize=1)
def load_hai_lab_lift_config() -> tuple[float, dict[str, float]]:
    """Load reference_data/hai_lab_lift.yaml once.

    Returns ``(ramp_peak_days, {hai_type: lift_value})``.
    """
    cfg_path = Path(__file__).parent / "reference_data" / "hai_lab_lift.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return float(data["ramp_peak_days"]), dict(data["hai_lift"])


def apply_hai_lab_lift(
    record,
    encounter,
    state_history: list[Any],
    admission_time: datetime,
) -> int:
    """Apply the HAI WBC + CRP forward-delta lift to existing lab_results.

    Walks ``record.extensions["hai"]`` (populated by the hai enricher at
    POST_ENCOUNTER) and for each matching event modifies the value of every
    WBC + CRP observation whose ``result_datetime.date() >= onset_date``.

    The delta is computed as the difference between two
    ``derive_lab_values`` evaluations on the *same* per-day state snapshot:

    - ``clean_baseline = derive_lab_values(state, hai_inflammation_lift=0.0)``
    - ``clean_lifted   = derive_lab_values(state, hai_inflammation_lift=L)``
    - ``delta          = clean_lifted[analyte] - clean_baseline[analyte]``
    - ``obs.value      += delta``

    Because both evaluations are run on the same state and same hour, any
    deterministic noise / circadian terms cancel inside the difference; the
    delta isolates the pure HAI inflammatory effect. The original observation
    value retains whatever noise the daily loop applied.

    Returns the number of observation values modified (useful for tests and
    audit).
    """
    # Local imports to avoid module load cycles.
    from clinosim.modules.physiology.engine import derive_lab_values

    events = (getattr(record, "extensions", None) or {}).get("hai", []) or []
    if not events:
        return 0

    ramp_peak_days, lift_table = load_hai_lab_lift_config()
    patient = getattr(record, "patient", None)
    if patient is None:
        return 0
    sex = getattr(patient, "sex", "M")
    age = int(getattr(patient, "age", 60))
    admission_date = admission_time.date()
    encounter_id = getattr(encounter, "encounter_id", "")

    modified = 0
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
        lift_value = lift_table.get(getattr(ev, "hai_type", ""), 0.0)
        if lift_value <= 0.0:
            continue

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
            if obs_date < onset_dt:
                continue
            days_since = (obs_date - onset_dt).days
            ramp_factor = (
                min(1.0, days_since / ramp_peak_days)
                if ramp_peak_days > 0
                else 1.0
            )
            effective_lift = lift_value * ramp_factor
            if effective_lift <= 0.0:
                continue

            day_index = (obs_date - admission_date).days
            if day_index < 0 or day_index >= len(state_history):
                continue
            state_snap = state_history[day_index]

            obs_hour = res_dt.hour
            clean_baseline = derive_lab_values(
                state_snap, sex=sex, age=age, hour=obs_hour,
                hai_inflammation_lift=0.0,
            )
            clean_lifted = derive_lab_values(
                state_snap, sex=sex, age=age, hour=obs_hour,
                hai_inflammation_lift=effective_lift,
            )
            base = clean_baseline.get(lab_name)
            lifted = clean_lifted.get(lab_name)
            if base is None or lifted is None:
                continue
            delta = lifted - base
            if delta == 0:
                continue
            obs.value = round(float(val) + delta, 1)
            modified += 1
    return modified
