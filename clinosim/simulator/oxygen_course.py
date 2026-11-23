"""The supplemental-oxygen course of one stay (Issue #3469).

A patient is on oxygen or not, and stays so until weaned: the on / off state,
device and flow are carried across the readings of a stay instead of being
decided afresh from each noisy room-air SpO2. Oxygen starts at the first
reading below the target (device and flow from the draw that reading made),
is titrated up only while the SpO2 on oxygen is still below the target, and
is stopped once the room-air SpO2 has stayed at or above the target plus a
margin for ``wean_hours`` (``reference_data/oxygen_course.yaml``). Everything
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

__all__ = ["OxygenCourse", "OxygenCourseRules", "VentilationRules", "oxygen_course_rules", "round_oxygen_flow"]

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


class OxygenCourseRules(BaseModel):
    """Schema of ``reference_data/oxygen_course.yaml`` (Issues #3469, #3535)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wean_hours: float = Field(gt=0)
    wean_margin_spo2: float = Field(ge=0)
    wean_min_readings: int = Field(ge=1)
    flow_step_lpm: float = Field(gt=0)
    ventilation: VentilationRules


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


@dataclass
class OxygenCourse:
    """Oxygen state carried across the readings of a stay (chronological)."""

    on: bool = False
    flow: float | None = None
    device: str = ""
    stable_since: datetime | None = None  # first of the current run of satisfactory room-air readings
    stable_readings: int = 0
    # Issue #3535: the ventilated period (intubation .. extubation); ``None``
    # until intubated / while not yet extubated.
    ventilated_since: datetime | None = None
    ventilated_until: datetime | None = None
    extubation_ready_days: int = 0

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
        self.ventilated_since, self.ventilated_until = when, None
        self.on, self.flow, self.device = True, None, rules.device
        self.stable_since, self.stable_readings, self.extubation_ready_days = None, 0, 0

    def end_ventilation(self, when: datetime) -> None:
        """Extubated at ``when``: oxygen continues on the post-extubation
        device and is weaned by the usual rules."""
        rules = oxygen_course_rules().ventilation
        self.ventilated_until = when
        self.on, self.flow, self.device = True, rules.post_extubation_flow_lpm, rules.post_extubation_device
        self.stable_since, self.stable_readings = None, 0

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
        raised to the draw's (never lowered) while the SpO2 on oxygen is still
        below ``target``. Returns (on, flow, device, recorded SpO2). While
        ventilated (Issue #3535) the device is the ventilator and the SpO2 is
        raised as by ``ventilation.equivalent_flow_lpm``."""
        if self.ventilated_at(when):
            vent = oxygen_course_rules().ventilation
            return True, None, vent.device, spo2_on_oxygen(room_air_spo2, vent.equivalent_flow_lpm)
        on, flow, device = self.observe(when, room_air_spo2, target, draw)
        if not on:
            return False, None, "", room_air_spo2
        spo2 = spo2_on_oxygen(room_air_spo2, flow or 0.0)
        d_flow = draw[1]
        if spo2 < target and draw[0] and d_flow is not None and (flow is None or d_flow > flow):
            self.flow, self.device = d_flow, draw[2]
            flow, device = self.flow, self.device
            spo2 = spo2_on_oxygen(room_air_spo2, flow)
        return True, flow, device, spo2

    def state(self) -> O2Draw:
        return (True, self.flow, self.device) if self.on else (False, None, "")
