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

__all__ = ["OxygenCourse", "OxygenCourseRules", "oxygen_course_rules"]

# (on, flow L/min, device) as _o2_for returns them.
O2Draw = tuple[bool, float | None, str]


class OxygenCourseRules(BaseModel):
    """Schema of ``reference_data/oxygen_course.yaml`` (Issue #3469)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wean_hours: float = Field(gt=0)
    wean_margin_spo2: float = Field(ge=0)
    wean_min_readings: int = Field(ge=1)


@functools.cache
def oxygen_course_rules() -> OxygenCourseRules:
    """The validated oxygen weaning rules."""
    return OxygenCourseRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "oxygen_course.yaml")
    )


@dataclass
class OxygenCourse:
    """Oxygen state carried across the readings of a stay (chronological)."""

    on: bool = False
    flow: float | None = None
    device: str = ""
    stable_since: datetime | None = None  # first of the current run of satisfactory room-air readings
    stable_readings: int = 0

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
        below ``target``. Returns (on, flow, device, recorded SpO2)."""
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
