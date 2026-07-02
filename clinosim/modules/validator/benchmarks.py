"""Statistical realism benchmarks (Tier 1).

Compares generated data distributions against published real-world statistics.
Run after a full simulation to validate realism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median

from clinosim.modules._shared import is_jp
from clinosim.types.output import CIFDataset


@dataclass
class BenchmarkResult:
    name: str
    metric: str
    generated_value: float
    expected_value: float
    expected_range: tuple[float, float]
    status: str = ""  # "pass" | "warn" | "fail"
    deviation_pct: float = 0.0

    def __post_init__(self) -> None:
        lo, hi = self.expected_range
        if lo <= self.generated_value <= hi:
            self.status = "pass"
        elif lo * 0.5 <= self.generated_value <= hi * 1.5:
            self.status = "warn"
        else:
            self.status = "fail"
        if self.expected_value != 0:
            self.deviation_pct = abs(self.generated_value - self.expected_value) / self.expected_value * 100


@dataclass
class BenchmarkReport:
    results: list[BenchmarkResult] = field(default_factory=list)

    def add(self, result: BenchmarkResult) -> None:
        self.results.append(result)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "pass")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")

    @property
    def pass_rate(self) -> float:
        return self.pass_count / max(1, len(self.results))

    def summary(self) -> str:
        return (
            f"Benchmarks: {len(self.results)} total, "
            f"{self.pass_count} pass, {self.warn_count} warn, {self.fail_count} fail "
            f"({self.pass_rate:.0%} pass rate)"
        )


def run_benchmarks(dataset: CIFDataset, country: str = "JP") -> BenchmarkReport:
    """Run Tier 1 statistical benchmarks against generated data."""
    report = BenchmarkReport()
    patients = dataset.patients

    if not patients:
        return report

    # --- Patient demographics ---
    ages = [p.patient.age for p in patients]
    report.add(BenchmarkResult(
        name="mean_age",
        metric="Mean age of admitted pneumonia patients",
        generated_value=mean(ages),
        expected_value=72,
        expected_range=(60, 82),
    ))

    male_ratio = sum(1 for p in patients if p.patient.sex == "M") / len(patients)
    report.add(BenchmarkResult(
        name="male_ratio",
        metric="Male ratio",
        generated_value=male_ratio,
        expected_value=0.55,
        expected_range=(0.40, 0.70),
    ))

    # --- Length of stay (inpatient only) ---
    los_days = []
    for p in patients:
        for enc in p.encounters:
            if enc.encounter_type.value == "inpatient" and enc.discharge_datetime and enc.admission_datetime:
                los = (enc.discharge_datetime - enc.admission_datetime).days
                if los > 0:
                    los_days.append(los)

    if los_days:
        report.add(BenchmarkResult(
            name="median_los",
            metric="Median LOS (days)",
            generated_value=median(los_days),
            expected_value=14 if is_jp(country) else 4.5,
            expected_range=(10, 20) if is_jp(country) else (3, 7),
        ))

        report.add(BenchmarkResult(
            name="mean_los",
            metric="Mean LOS (days)",
            generated_value=mean(los_days),
            expected_value=15 if is_jp(country) else 5,
            expected_range=(10, 22) if is_jp(country) else (3, 8),
        ))

    # --- Data volume per patient ---
    labs_per_patient = [len(p.lab_results) for p in patients]
    vitals_per_patient = [len(p.vital_signs) for p in patients]

    report.add(BenchmarkResult(
        name="mean_labs_per_patient",
        metric="Mean lab results per patient",
        generated_value=mean(labs_per_patient),
        expected_value=50,
        expected_range=(20, 100),
    ))

    report.add(BenchmarkResult(
        name="mean_vitals_per_patient",
        metric="Mean vital sign sets per patient",
        generated_value=mean(vitals_per_patient),
        expected_value=42,
        expected_range=(15, 80),
    ))

    return report
