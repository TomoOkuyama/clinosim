"""The supplemental-oxygen course of one stay (Issue #3469).

A patient is on oxygen or not, and stays so until weaned: the on / off state,
device and flow are carried across the readings of a stay instead of being
decided afresh from each noisy room-air SpO2. Oxygen starts at the first
reading below the target (device and flow from the draw that reading made),
is titrated up while the SpO2 on oxygen is still below the target (one
``up_step_lpm`` per reading towards the draw's flow, Issue #3643) and down
(``down_step_lpm``, the device following the flow) while it stays above
the target plus ``down_margin_spo2`` (Issue #3632), and is stopped once the
room-air SpO2 has stayed at or above the target plus a margin for
``wean_hours`` (``reference_data/oxygen_course.yaml``). Everything
here is RNG-free: the caller keeps making the per-reading draw and passes it.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.simulator._oxygen_therapy_thresholds import (
    O2_NASAL_CANNULA_FLOW_MAX_LPM,
    O2_NON_REBREATHER_FLOW_MIN_LPM,
)

__all__ = [
    "NivRules",
    "OxygenCourse",
    "OxygenCourseRules",
    "VentilationRules",
    "oxygen_course_rules",
    "round_oxygen_flow",
]

# (on, flow L/min, device) as _o2_for returns them.
O2Draw = tuple[bool, float | None, str]


class VentilationRules(BaseModel):
    """Mechanical ventilation after an intubation (Issue #3535)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    device: str = Field(min_length=1)
    equivalent_flow_lpm: float = Field(gt=0)
    diet: str = Field(min_length=1)
    oxygenation_impairment_below: float = Field(gt=0, le=1)
    consciousness_impairment_below: float = Field(gt=0, le=1)
    consecutive_days: int = Field(ge=1)
    min_days_after_intubation: int = Field(ge=0)
    max_days: int = Field(ge=1)
    post_extubation_device: str = Field(min_length=1)
    post_extubation_flow_lpm: float = Field(gt=0)


class NivRules(BaseModel):
    """Non-invasive ventilation of a respiratory-failure complication (Issue #3705)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_action: str = Field(min_length=1)
    order_name: str = Field(min_length=1)
    existing_order_pattern: str = Field(min_length=1)
    device: str = Field(min_length=1)
    equivalent_flow_lpm: float = Field(gt=0)
    diet: str = Field(min_length=1)
    oxygenation_impairment_below: float = Field(gt=0, le=1)
    consciousness_impairment_below: float = Field(gt=0, le=1)
    consecutive_days: int = Field(ge=1)
    min_days_after_start: int = Field(ge=0)
    max_days: int = Field(ge=1)
    post_niv_device: str = Field(min_length=1)
    post_niv_flow_lpm: float = Field(gt=0)


class OxygenCourseRules(BaseModel):
    """Schema of ``reference_data/oxygen_course.yaml`` (Issues #3469, #3535)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wean_hours: float = Field(gt=0)
    wean_margin_spo2: float = Field(ge=0)
    wean_min_readings: int = Field(ge=1)
    flow_step_lpm: float = Field(gt=0)
    up_step_lpm: float = Field(gt=0)
    down_step_lpm: float = Field(gt=0)
    down_margin_spo2: float = Field(gt=0)
    down_hours: float = Field(gt=0)
    down_min_readings: int = Field(ge=1)
    min_flow_lpm: float = Field(gt=0)
    ventilation: VentilationRules
    niv: NivRules


@functools.cache
def oxygen_course_rules() -> OxygenCourseRules:
    """The validated oxygen weaning rules."""
    return OxygenCourseRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "oxygen_course.yaml")
    )


def round_oxygen_flow(flow: float | None) -> float | None:
    """The flow as set on a flowmeter: rounded to ``flow_step_lpm`` (Issue #3556).

    Applied only when the flow is recorded; the SpO2 and the course's titration
    use the unrounded flow, so the recorded SpO2 does not change. A positive
    flow never rounds down to zero (the lowest setting is one step)."""
    if not flow:
        return None
    step = oxygen_course_rules().flow_step_lpm
    return max(step, round(round(flow / step) * step, 3))


def device_for_flow(flow: float) -> str:
    """The delivery device for ``flow`` L/min, by the same cut-offs as the
    per-reading dispatcher (``_o2_for``): nasal cannula up to
    ``O2_NASAL_CANNULA_FLOW_MAX_LPM``, non-rebreather from
    ``O2_NON_REBREATHER_FLOW_MIN_LPM``, a simple mask between (Issue #3632)."""
    if flow >= O2_NON_REBREATHER_FLOW_MIN_LPM:
        return "non-rebreather"
    return "nasal_cannula" if flow <= O2_NASAL_CANNULA_FLOW_MAX_LPM else "simple_mask"


@dataclass
class OxygenCourse:
    """Oxygen state carried across the readings of a stay (chronological)."""

    on: bool = False
    flow: float | None = None
    device: str = ""
    stable_since: datetime | None = None  # first of the current run of satisfactory room-air readings
    stable_readings: int = 0
    # Issue #3632: the current run of readings whose SpO2 on oxygen is above the band.
    high_since: datetime | None = None
    high_readings: int = 0
    # Issue #3535: the ventilated period (intubation .. extubation); ``None``
    # until intubated / while not yet extubated.
    ventilated_since: datetime | None = None
    ventilated_until: datetime | None = None
    extubation_ready_days: int = 0
    # Issue #3705: the non-invasive-ventilation period (start .. wean); ``None``
    # until started / while still on NIV.
    niv_since: datetime | None = None
    niv_until: datetime | None = None
    niv_ready_days: int = 0

    def niv_at(self, when: datetime) -> bool:
        """True while the patient is on non-invasive ventilation at ``when``."""
        return (
            self.niv_since is not None and when >= self.niv_since and (self.niv_until is None or when < self.niv_until)
        )

    def niv_during(self, start: datetime) -> bool:
        """True when the patient is, or was after ``start``, on NIV."""
        return self.niv_since is not None and (self.niv_until is None or self.niv_until > start)

    def start_niv(self, when: datetime) -> None:
        """NIV started at ``when`` (no effect on the ventilator): on NIV until :meth:`end_niv`."""
        if self.ventilated_at(when):
            return
        rules = oxygen_course_rules().niv
        self.niv_since, self.niv_until, self.niv_ready_days = when, None, 0
        self.on, self.flow, self.device = True, None, rules.device
        self.stable_since, self.stable_readings = None, 0
        self.high_since, self.high_readings = None, 0

    def end_niv(self, when: datetime) -> None:
        """NIV weaned (or replaced by intubation) at ``when``. Oxygen continues on the
        post-NIV device unless the patient is ventilated."""
        rules = oxygen_course_rules().niv
        self.niv_until = when
        if not self.ventilated_at(when):
            self.on, self.flow, self.device = True, rules.post_niv_flow_lpm, rules.post_niv_device
            self.stable_since, self.stable_readings = None, 0
            self.high_since, self.high_readings = None, 0

    def niv_wean_due(
        self, oxygenation_impairment: float, consciousness_impairment: float, days_after_start: int, *, force: bool
    ) -> bool:
        """Evaluate the NIV weaning rule on one end-of-day state (stateful: counts
        consecutive satisfactory days). ``force`` ends NIV regardless (the end of the
        simulated stay)."""
        rules = oxygen_course_rules().niv
        if (
            oxygenation_impairment < rules.oxygenation_impairment_below
            and consciousness_impairment < rules.consciousness_impairment_below
        ):
            self.niv_ready_days += 1
        else:
            self.niv_ready_days = 0
        if force or days_after_start >= rules.max_days:
            return True
        return days_after_start >= rules.min_days_after_start and self.niv_ready_days >= rules.consecutive_days

    def ventilated_at(self, when: datetime) -> bool:
        """True while the patient is on the ventilator at ``when``."""
        return (
            self.ventilated_since is not None
            and when >= self.ventilated_since
            and (self.ventilated_until is None or when < self.ventilated_until)
        )

    def ventilated_during(self, start: datetime) -> bool:
        """True when the patient is, or was after ``start``, on the ventilator."""
        return self.ventilated_since is not None and (self.ventilated_until is None or self.ventilated_until > start)

    def start_ventilation(self, when: datetime) -> None:
        """Intubated at ``when``: ventilated until :meth:`end_ventilation`."""
        rules = oxygen_course_rules().ventilation
        if self.niv_since is not None and self.niv_until is None:
            self.niv_until = when  # NIV failure: intubated during NIV (Issue #3705)
        self.ventilated_since, self.ventilated_until = when, None
        self.on, self.flow, self.device = True, None, rules.device
        self.stable_since, self.stable_readings, self.extubation_ready_days = None, 0, 0
        self.high_since, self.high_readings = None, 0

    def end_ventilation(self, when: datetime) -> None:
        """Extubated at ``when``: oxygen continues on the post-extubation
        device and is weaned by the usual rules."""
        rules = oxygen_course_rules().ventilation
        self.ventilated_until = when
        self.on, self.flow, self.device = True, rules.post_extubation_flow_lpm, rules.post_extubation_device
        self.stable_since, self.stable_readings = None, 0
        self.high_since, self.high_readings = None, 0

    def extubation_due(
        self, oxygenation_impairment: float, consciousness_impairment: float, days_after_intubation: int, *, force: bool
    ) -> bool:
        """Evaluate the extubation rule on one end-of-day state (stateful:
        counts consecutive satisfactory days). ``force`` ends ventilation
        regardless (the end of the simulated stay)."""
        rules = oxygen_course_rules().ventilation
        if (
            oxygenation_impairment < rules.oxygenation_impairment_below
            and consciousness_impairment < rules.consciousness_impairment_below
        ):
            self.extubation_ready_days += 1
        else:
            self.extubation_ready_days = 0
        if force or days_after_intubation >= rules.max_days:
            return True
        return (
            days_after_intubation >= rules.min_days_after_intubation
            and self.extubation_ready_days >= rules.consecutive_days
        )

    def observe(
        self,
        when: datetime,
        room_air_spo2: float,
        target: float,
        draw: O2Draw,
    ) -> O2Draw:
        """The (on, flow, device) of the reading at ``when``.

        ``draw`` is what the per-reading dispatcher returned for
        ``room_air_spo2`` (on / flow / device).
        """
        d_on, d_flow, d_device = draw
        if not self.on:
            if d_on:
                self.on, self.flow, self.device = True, d_flow, d_device
                self.stable_since, self.stable_readings = None, 0
                self.high_since, self.high_readings = None, 0
            return self.state()
        rules = oxygen_course_rules()
        if room_air_spo2 >= target + rules.wean_margin_spo2:
            if self.stable_since is None:
                self.stable_since = when
            self.stable_readings += 1
            if self.stable_readings >= rules.wean_min_readings and when - self.stable_since >= timedelta(
                hours=rules.wean_hours
            ):
                self.on, self.flow, self.device = False, None, ""
                self.stable_since, self.stable_readings = None, 0
                self.high_since, self.high_readings = None, 0
        else:
            self.stable_since, self.stable_readings = None, 0
        return self.state()

    def resolve(
        self,
        when: datetime,
        room_air_spo2: float,
        target: float,
        draw: O2Draw,
        spo2_on_oxygen: Callable[[float, float], float],
    ) -> tuple[bool, float | None, str, float]:
        """:meth:`observe` plus the SpO2 recorded on oxygen: the flow is
        raised to the draw's while the SpO2 on oxygen is still below
        ``target`` and lowered one step while it stays above the band
        (Issue #3632). Returns (on, flow, device, recorded SpO2). While
        ventilated (Issue #3535) the device is the ventilator and the SpO2 is
        raised as by ``ventilation.equivalent_flow_lpm``."""
        if self.ventilated_at(when):
            vent = oxygen_course_rules().ventilation
            return True, None, vent.device, spo2_on_oxygen(room_air_spo2, vent.equivalent_flow_lpm)
        if self.niv_at(when):
            niv = oxygen_course_rules().niv
            return True, None, niv.device, spo2_on_oxygen(room_air_spo2, niv.equivalent_flow_lpm)
        on, flow, device = self.observe(when, room_air_spo2, target, draw)
        if not on:
            return False, None, "", room_air_spo2
        spo2 = spo2_on_oxygen(room_air_spo2, flow or 0.0)
        if self._lower_flow_due(when, spo2, target):
            rules = oxygen_course_rules()
            step = rules.flow_step_lpm
            self.flow = max(rules.min_flow_lpm, round((flow or 0.0) / step) * step - rules.down_step_lpm)
            self.device = device_for_flow(self.flow)
            self.high_since, self.high_readings = None, 0
            flow, device = self.flow, self.device
            spo2 = spo2_on_oxygen(room_air_spo2, flow)
        d_flow = draw[1]
        if spo2 < target and draw[0] and d_flow is not None and (flow is None or d_flow > flow):
            # Issue #3643: one ``up_step_lpm`` towards the draw's flow, not the
            # draw's flow itself (a jump of several litres between two readings).
            raised = d_flow if not flow else min(d_flow, flow + oxygen_course_rules().up_step_lpm)
            self.flow = raised
            self.device = draw[2] if raised == d_flow else device_for_flow(raised)
            flow, device = self.flow, self.device
            spo2 = spo2_on_oxygen(room_air_spo2, flow)
        return True, flow, device, spo2

    def _lower_flow_due(self, when: datetime, spo2: float, target: float) -> bool:
        """Stateful (Issue #3632): True once the SpO2 on oxygen has stayed above
        ``target + down_margin_spo2`` for ``down_hours`` over at least
        ``down_min_readings`` readings and the flow is above the minimum."""
        rules = oxygen_course_rules()
        if self.flow is None or spo2 <= target + rules.down_margin_spo2:
            self.high_since, self.high_readings = None, 0
            return False
        if self.high_since is None:
            self.high_since = when
        self.high_readings += 1
        return (
            self.flow > rules.min_flow_lpm
            and self.high_readings >= rules.down_min_readings
            and when - self.high_since >= timedelta(hours=rules.down_hours)
        )

    def state(self) -> O2Draw:
        return (True, self.flow, self.device) if self.on else (False, None, "")
