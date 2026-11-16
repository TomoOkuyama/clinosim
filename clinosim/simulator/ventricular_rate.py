"""The ventricular rate of an arrhythmia stay (Issue #3274).

A protocol that declares ``ventricular_rate`` (``VentricularRateSpec``; atrial
fibrillation with rapid ventricular response) records a heart rate that
follows the ventricular response, not the sinus baseline: the presenting rate
of the severity until the first given rate-control dose, then a linear fall
to the controlled rate over the course archetype's hours to control. The
vitals pass it to ``derive_observed_vitals(ventricular_rate=...)``, which
records the higher of it and the physiology-derived rate.

Both rates are hash draws keyed on the encounter (``sha_normal``): no stream
draw is added, and the ED arrival vitals and the stay's vitals see the same
presenting rate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from clinosim.codes.drugs import drug_classes
from clinosim.determinism import sha_normal
from clinosim.modules.disease.protocol import RateBand, VentricularRateSpec
from clinosim.types.encounter import MedicationAdministration

_SECONDS_PER_HOUR = 3600.0


def _banded(band: RateBand, salt: str) -> float:
    return min(band.max, max(band.min, sha_normal(salt, band.mean, band.sd)))


def presenting_ventricular_rate(spec: VentricularRateSpec, severity: str, encounter_id: str) -> float:
    """The encounter's ventricular rate before rate control (beats/min). The
    protocol validator guarantees a band for every severity it samples."""
    return _banded(spec.presenting_bpm[severity], f"ventricular-rate-presenting|{encounter_id}")


def first_rate_control_dose(spec: VentricularRateSpec, mars: Iterable[MedicationAdministration]) -> datetime | None:
    """Time of the earliest given dose of a ``rate_control_classes`` drug in
    ``mars``; None when none was given."""
    classes = set(spec.rate_control_classes)
    times = [
        m.actual_datetime or m.scheduled_datetime
        for m in mars
        if m.status == "given" and classes & set(drug_classes(m.drug_id or m.drug_name))
    ]
    return min(times) if times else None


@dataclass(frozen=True)
class VentricularRateCourse:
    """The ventricular rate of one stay over time."""

    presenting: float
    controlled: float
    first_dose: datetime | None
    hours_to_control: float

    @classmethod
    def build(
        cls,
        spec: VentricularRateSpec,
        severity: str,
        archetype: str,
        encounter_id: str,
        first_dose: datetime | None,
    ) -> VentricularRateCourse:
        return cls(
            presenting=presenting_ventricular_rate(spec, severity, encounter_id),
            controlled=_banded(spec.controlled_bpm, f"ventricular-rate-controlled|{encounter_id}"),
            first_dose=first_dose,
            hours_to_control=spec.hours_to_control_for(archetype),
        )

    def at(self, when: datetime) -> float:
        """The ventricular rate at ``when`` (beats/min)."""
        if self.first_dose is None or when <= self.first_dose:
            return self.presenting
        elapsed = (when - self.first_dose).total_seconds() / _SECONDS_PER_HOUR
        fraction = min(1.0, elapsed / self.hours_to_control)
        return self.presenting + (self.controlled - self.presenting) * fraction
