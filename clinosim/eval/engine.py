"""Eval engine — orchestrates 3-axis scoring over a cohort directory.

Reuses :class:`clinosim.audit.types.Cohort` for NDJSON loading (so a
directory produced by ``clinosim generate --format fhir`` is directly
consumable — both the multi-country layout ``<root>/<country>/fhir_r4/``
and the flat ``<root>/fhir_r4/`` layout are supported).

Each axis is a plain function::

    def run(cohort: Cohort, country: str) -> list[EvalCheck]

that returns one :class:`EvalCheck` per named check. The engine then
computes the axis score = 100 × Σ(passing weight) / Σ(total weight),
where WARN counts as 0.5 pass. The overall score is the arithmetic
mean of the axis scores.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from clinosim.audit.types import Cohort


class Outcome(StrEnum):
    """Outcome of a single check on a cohort."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NA = "N/A"

    def to_pass_weight(self) -> float:
        """Fraction of the check's weight that counts toward the axis score."""
        if self is Outcome.PASS:
            return 1.0
        if self is Outcome.WARN:
            return 0.5
        # FAIL / NA contribute zero.
        return 0.0


class Severity(StrEnum):
    """Weight-encoded severity level of a check."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"

    @property
    def weight(self) -> int:
        return {"critical": 3, "major": 2, "minor": 1}[self.value]


@dataclass
class EvalCheck:
    """One named check within one axis."""

    name: str
    outcome: Outcome
    severity: Severity
    message: str
    detail: dict = field(default_factory=dict)

    @property
    def weight(self) -> int:
        return self.severity.weight

    def to_dict(self) -> dict:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        d["severity"] = self.severity.value
        d["weight"] = self.weight
        return d


@dataclass
class EvalAxisResult:
    """All checks for one axis, plus the computed score."""

    axis: str
    country: str
    checks: list[EvalCheck] = field(default_factory=list)

    @property
    def score(self) -> float:
        total_weight = sum(c.weight for c in self.checks)
        if total_weight == 0:
            return 0.0
        pass_weight = sum(c.outcome.to_pass_weight() * c.weight for c in self.checks)
        return round(100.0 * pass_weight / total_weight, 1)

    @property
    def status(self) -> str:
        if any(c.outcome is Outcome.FAIL for c in self.checks):
            return "FAIL"
        if any(c.outcome is Outcome.WARN for c in self.checks):
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        return {
            "axis": self.axis,
            "country": self.country,
            "score": self.score,
            "status": self.status,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class EvalReport:
    """Full evaluation report — all axes, all countries in the cohort."""

    cohort_dir: str
    generated_at: str
    resource_counts: dict[str, dict[str, int]]  # country → resource → count
    axes: list[EvalAxisResult] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.axes:
            return 0.0
        return round(sum(a.score for a in self.axes) / len(self.axes), 1)

    @property
    def overall_status(self) -> str:
        statuses = [a.status for a in self.axes]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        return {
            "eval_version": _EVAL_REPORT_VERSION,
            "cohort_dir": self.cohort_dir,
            "generated_at": self.generated_at,
            "resource_counts": self.resource_counts,
            "overall_score": self.overall_score,
            "overall_status": self.overall_status,
            "axes": [a.to_dict() for a in self.axes],
        }


_EVAL_REPORT_VERSION = "1"


AxisRunner = Callable[[Cohort, str], list[EvalCheck]]


class EvalEngine:
    """Orchestrates the 3 axes over a cohort directory."""

    def __init__(
        self,
        cohort_dir: Path | str,
        axes: dict[str, AxisRunner] | None = None,
        countries: list[str] | None = None,
    ):
        self.cohort_dir = Path(cohort_dir)
        # Lazy import to keep the top-level `clinosim.eval` import cheap.
        if axes is None:
            from clinosim.eval.axes import clinical, locale, structural

            axes = {
                "structural": structural.run,
                "clinical": clinical.run,
                "locale": locale.run,
            }
        self.axes = axes
        self.country_filter = countries

    def run(self) -> EvalReport:
        cohort = Cohort.open(self.cohort_dir)
        countries = cohort.countries()
        if self.country_filter is not None:
            countries = [c for c in countries if c in self.country_filter or c == ""]
        if not countries:
            raise FileNotFoundError(f"cohort at {self.cohort_dir} contains no fhir_r4/ output")

        resource_counts: dict[str, dict[str, int]] = {}
        axis_results: list[EvalAxisResult] = []

        for country in countries:
            resource_counts[country or "_flat"] = _count_resources(cohort, country)
            for axis_name, runner in self.axes.items():
                checks = runner(cohort, country)
                axis_results.append(EvalAxisResult(axis=axis_name, country=country or "_flat", checks=checks))

        return EvalReport(
            cohort_dir=str(self.cohort_dir),
            generated_at=datetime.now(UTC).isoformat(),
            resource_counts=resource_counts,
            axes=axis_results,
        )


def _count_resources(cohort: Cohort, country: str) -> dict[str, int]:
    """Return {resourceType: count} by counting NDJSON lines."""
    base = cohort.root / country / "fhir_r4"
    if not base.exists():
        return {}
    counts: dict[str, int] = {}
    for path in sorted(base.glob("*.ndjson")):
        with path.open() as f:
            counts[path.stem] = sum(1 for _ in f)
    return counts
