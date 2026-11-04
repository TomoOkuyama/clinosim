"""Audit-framework value types + lazy Cohort reader.

This module defines:
- Severity: gate-blocking classification (INFO / WARN / FAIL)
- AuditFinding: one observation produced by an axis check
- AxisResult: aggregate for (axis, module); status derives from findings + info
- AuditResult: aggregate across (axis, module) pairs; overall_status = worst
- Cohort: lazy NDJSON reader rooted at a FHIR R4 cohort directory
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class AuditFinding:
    severity: Severity
    message: str
    detail: dict | None = None


@dataclass
class AxisResult:
    axis: str
    module: str
    findings: list[AuditFinding] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.findings and not self.info:
            return "N/A"
        if any(f.severity == Severity.FAIL for f in self.findings):
            return "FAIL"
        if any(f.severity == Severity.WARN for f in self.findings):
            return "WARN"
        return "PASS"


@dataclass
class AuditResult:
    cohort_dir: Path
    modules: list[str]
    axes: list[str]
    results: dict[tuple[str, str], AxisResult] = field(default_factory=dict)

    def add(self, axis: str, module: str, result: AxisResult) -> None:
        self.results[(axis, module)] = result

    def overall_status(self) -> str:
        statuses = [r.status for r in self.results.values()]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"


class Cohort:
    """Lazy NDJSON reader rooted at a cohort directory. Expected layout:
    <root>/<country>/fhir_r4/<ResourceType>.ndjson
    """

    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def open(cls, root: Path | str) -> Cohort:
        return cls(Path(root))

    def countries(self) -> list[str]:
        if not self.root.exists():
            return []
        multi = sorted(p.name for p in self.root.iterdir() if p.is_dir() and (p / "fhir_r4").exists())
        if multi:
            return multi
        # Flat layout: single-country cohort generated without country subdir
        # (e.g. <root>/fhir_r4/*.ndjson). Return "" so ndjson("", resource)
        # resolves to root/fhir_r4/ (Path / "" / "..." = Path / "..." on POSIX).
        if (self.root / "fhir_r4").exists():
            return [""]
        return []

    def ndjson(self, country: str, resource: str, *, skip_malformed: bool = False) -> Iterator[dict]:
        """Rows of ``<ResourceType>.ndjson`` (empty when the file is absent)."""
        path = self.root / country / "fhir_r4" / f"{resource}.ndjson"
        if not path.exists():
            return iter(())
        return iter_ndjson(path, skip_malformed=skip_malformed)

    def resource_files(self, country: str) -> list[Path]:
        """Every ``*.ndjson`` of the country's FHIR output, sorted."""
        base = self.root / country / "fhir_r4"
        if not base.exists():
            return []
        return sorted(base.glob("*.ndjson"))


def iter_ndjson(path: Path, *, skip_malformed: bool = False) -> Iterator[dict]:
    """Rows of one NDJSON file, skipping blank lines. A malformed line raises
    ``json.JSONDecodeError`` unless ``skip_malformed`` is set (Issue #2518)."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if not skip_malformed:
                    raise
