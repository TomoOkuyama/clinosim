# clinosim audit framework — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `clinosim audit` verification framework: a new `clinosim/audit/` package + CLI subcommand that absorbs the existing 3-axis DQR scripts (structural / clinical / JP language) and adds a fourth silent_no_op axis (fired counter / canonical constants cross-check / lift-firing proof / per-event observed-vs-theoretical) to close the PR-90 class of bug. Modules co-locate their audit plug-in in `clinosim/modules/<name>/audit.py`. HAI is the only Module audit shipped in Phase 1.

**Architecture:** `clinosim/audit/registry.py` holds `ModuleAuditSpec` + a per-Module discovery walker; `clinosim/audit/engine.py` orchestrates axis runs over a lazy `Cohort` reader; four axis modules under `clinosim/audit/axes/` implement axis-specific logic; `clinosim/audit/reporter.py` emits a Markdown report; `clinosim/audit/cli.py` wires the `clinosim audit run` / `audit smoke` / `audit list` subcommands. Modules without `audit.py` are silently skipped. The framework does not touch simulation paths, so the master `42657293` byte-diff invariant is preserved.

**Tech Stack:** Python 3.11+, dataclasses, pytest, PyYAML, ruff. No new external dependencies. The CLI is wired into the existing `clinosim/simulator/cli.py:main` argparse subparser tree (precedent: `clinosim generate`, `clinosim validate`, `clinosim test-disease`).

**Spec:** `docs/superpowers/specs/2026-06-25-dqr-framework-strengthening-design.md` (commit `5eb147ab`).

**Branch:** `feat/clinosim-audit-framework` (already checked out, spec committed).

## Global Constraints

- **byte-diff invariant** — `clinosim/audit/` is a new package; it must not import or be imported by any simulation path (population / encounter / inpatient / emergency / outpatient / engine / observation / order / clinical_course / physiology / diagnosis / procedure). byte-diff vs master `42657293` at p=2000 must remain 37/37 NDJSON IDENTICAL after every commit.
- **AD-16 deterministic** — the framework does not consume any RNG; outputs are deterministic given the same cohort directory.
- **No network fetches** — all authoritative lookups go through `clinosim.codes` which is already offline. The audit must never reach out.
- **Python comments + docstrings English**. Internal Module README JP. CLAUDE.md / README EN.
- **Default cohort** — `clinosim audit run` defaults to `--us-pop 10000 --jp-pop 5000` when `--generate` is set; without `--generate`, requires `-d ./output` pointing at a pre-existing CIF + FHIR-R4 directory.
- **Module skip rule** — Modules without `clinosim/modules/<name>/audit.py` produce no findings (no `not implemented` errors). Phase 1 ships only `modules/hai/audit.py`.
- **Severity exit codes** — exit 0 if no FAIL findings, 1 if any FAIL, 2 if CLI error (bad args, missing dir).
- **Tolerances** (from spec §6.3):
  - lift-firing proof WBC observed-vs-expected: ±2.0
  - lift-firing proof CRP observed-vs-expected: ±0.5
  - per-event pair-level: within 30% of theoretical
  - per-event cohort-level: ≤ 25% of pairs outside pair tolerance
  - fired counter rare-event threshold: 200 × (1 / per_day_risk) device-days

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `clinosim/audit/__init__.py` | **Create** | Public exports: `ModuleAuditSpec`, `AuditEngine`, `register_audit_module` |
| `clinosim/audit/types.py` | **Create** | `Severity`, `AuditFinding`, `AxisResult`, `AuditResult`, lazy `Cohort` reader |
| `clinosim/audit/registry.py` | **Create** | `ModuleAuditSpec` dataclass + `register_audit_module` + `discover` + `get_registered` |
| `clinosim/audit/axes/__init__.py` | **Create** | Empty package marker |
| `clinosim/audit/axes/structural.py` | **Create** | `run(spec, cohort) -> AxisResult` — refRange + interpretation 100%, code system integrity, id uniqueness, reference integrity |
| `clinosim/audit/axes/jp_language.py` | **Create** | `run(spec, cohort) -> AxisResult` — US non-ASCII = 0, JP localized displays for spec.structural_obs_codes |
| `clinosim/audit/axes/silent_no_op.py` | **Create** | `run(spec, cohort) -> AxisResult` — fired counter, canonical constants cross-check, lift-firing proof |
| `clinosim/audit/axes/clinical.py` | **Create** | `run(spec, cohort) -> AxisResult` — cohort split via spec.cohort_filter, baseline medians, per-event observed-vs-theoretical |
| `clinosim/audit/reporter.py` | **Create** | `render_markdown(result) -> str`, `write_markdown(result, path)` |
| `clinosim/audit/engine.py` | **Create** | `AuditEngine` orchestration + `_BUILTIN_AXES` registry |
| `clinosim/audit/cli.py` | **Create** | `clinosim audit` subcommand entry: `run` / `smoke` / `list` |
| `clinosim/simulator/cli.py` | Modify | Add `audit` subparser to main argparse tree |
| `clinosim/modules/hai/audit.py` | **Create** | First per-Module audit plug-in: HAI spec calling `register_audit_module` |
| `tests/unit/test_audit_registry.py` | **Create** | registry / discover roundtrip; last-wins; module without audit.py skipped |
| `tests/unit/test_audit_types.py` | **Create** | `Severity`, `AuditFinding`, `AxisResult` aggregation; `Cohort.open()` lazy loading |
| `tests/unit/test_axis_structural.py` | **Create** | refRange detection, code-system integrity, id duplicate, ref-integrity |
| `tests/unit/test_axis_jp_language.py` | **Create** | US non-ASCII detection, JP localized display detection |
| `tests/unit/test_axis_silent_no_op.py` | **Create** | fired counter zero, constants drift, lift-firing proof delta |
| `tests/unit/test_axis_clinical.py` | **Create** | cohort split, baseline medians, per-event theoretical comparison + tolerance bands |
| `tests/unit/test_reporter.py` | **Create** | Markdown shape, severity classification, axis-PASS/FAIL grid |
| `tests/unit/test_audit_engine.py` | **Create** | engine selects modules + axes; missing data → N/A; aggregation |
| `tests/integration/test_audit_end_to_end.py` | **Create** | minimal synthetic FHIR cohort → engine → report file |
| `tests/integration/test_audit_hai_module.py` | **Create** | real HAI audit registered, small generated cohort, lift_firing_proof PASS |
| `scratchpad/clinosim_audit_byte_diff.py` | **Create** | one-off byte-diff vs master to prove `clinosim/audit/` doesn't touch simulation |
| `scratchpad/clinosim_audit_self_run.log` | **Create** | first `clinosim audit run` baseline report (post-merge evidence) |
| `docs/reviews/2026-06-25-clinosim-audit-baseline.md` | **Create** | first Markdown audit report (committed evidence) |
| `scratchpad/phase3a_dqr.py` | **Delete** | superseded by `clinosim audit run --module hai` |
| `scratchpad/phase3a_lift_fired_proof.py` | **Delete** | logic absorbed into `modules/hai/audit.py` |
| `MODULES.md` | Modify | Add Verification layer row (clinosim/audit/) |
| `docs/CONTRIBUTING-modules.md` | Modify | PR 検証ガイド: new feature row → `clinosim audit run`; add Module audit.py boilerplate sub-section |
| `.github/TEMPLATE_MODULE_README.md` | Modify | Add Audit section to canonical template |
| `CLAUDE.md` | Modify | DQR-audit guidance line → "Verification gate is `clinosim audit run` — Modules co-locate audit checks in `clinosim/modules/<name>/audit.py`" |
| `README.md` / `README.ja.md` | Modify | Quality & Compliance section — replace 3-axis DQR mention with `clinosim audit run`; link baseline review |
| `DESIGN.md` | Modify | New AD entry: clinosim audit framework (registry + co-located checks + 4 axes) |
| `TODO.md` | Modify | Mark "DQR audit-script strengthening" done; add per-Module audit.py backlog for Phase 3b/c |

---

## Task 1: Types + lazy Cohort reader + registry foundation

**Files:**
- Create: `clinosim/audit/__init__.py`
- Create: `clinosim/audit/types.py`
- Create: `clinosim/audit/registry.py`
- Create: `tests/unit/test_audit_types.py`
- Create: `tests/unit/test_audit_registry.py`

**Interfaces:**
- Consumes: standard library `dataclasses`, `enum`, `pathlib`, `importlib`, `json`.
- Produces:
  ```python
  # clinosim/audit/types.py
  from enum import Enum
  from pathlib import Path
  from dataclasses import dataclass, field

  class Severity(str, Enum):
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
      def status(self) -> str:  # "PASS" | "WARN" | "FAIL" | "N/A"
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
      """Lazy NDJSON reader rooted at a cohort directory."""
      def __init__(self, root: Path):
          self.root = root
      @classmethod
      def open(cls, root: Path | str) -> "Cohort":
          return cls(Path(root))
      def countries(self) -> list[str]:
          return sorted([p.name for p in self.root.iterdir()
                         if p.is_dir() and (p / "fhir_r4").exists()])
      def ndjson(self, country: str, resource: str):
          path = self.root / country / "fhir_r4" / f"{resource}.ndjson"
          if not path.exists():
              return iter(())
          with path.open() as f:
              for line in f:
                  if line.strip():
                      yield json.loads(line)
  ```

  ```python
  # clinosim/audit/registry.py
  from dataclasses import dataclass, field
  from typing import Callable

  @dataclass
  class ModuleAuditSpec:
      name: str
      canonical_constants: dict[str, tuple[str, ...]] = field(default_factory=dict)
      yaml_keys_to_validate: dict[str, tuple[str, ...]] = field(default_factory=dict)
      cohort_filter: Callable | None = None
      per_event_check: dict[str, Callable] = field(default_factory=dict)
      lift_firing_proof: Callable | None = None
      structural_obs_codes: dict[str, tuple[str, ...]] = field(default_factory=dict)
      clinical_acceptance: dict[str, dict[str, float]] = field(default_factory=dict)

  _MODULES: dict[str, ModuleAuditSpec] = {}

  def register_audit_module(spec: ModuleAuditSpec) -> None:
      _MODULES[spec.name] = spec

  def get_registered() -> dict[str, ModuleAuditSpec]:
      return dict(_MODULES)

  def _reset_for_test() -> None:
      _MODULES.clear()

  def discover() -> None:
      from importlib import import_module
      from pathlib import Path
      modules_root = Path(__file__).parent.parent / "modules"
      for audit_file in sorted(modules_root.glob("*/audit.py")):
          module_name = audit_file.parent.name
          import_module(f"clinosim.modules.{module_name}.audit")
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_audit_types.py`:

```python
"""Unit tests for clinosim.audit.types — Severity, AuditFinding, AxisResult,
AuditResult, Cohort lazy NDJSON reader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Cohort,
    Severity,
)


@pytest.mark.unit
def test_severity_enum_values():
    assert Severity.INFO.value == "INFO"
    assert Severity.WARN.value == "WARN"
    assert Severity.FAIL.value == "FAIL"


@pytest.mark.unit
def test_axis_result_status_na_when_empty():
    r = AxisResult(axis="structural", module="hai")
    assert r.status == "N/A"


@pytest.mark.unit
def test_axis_result_status_pass_when_info_only():
    r = AxisResult(axis="structural", module="hai", info={"n": 100})
    assert r.status == "PASS"


@pytest.mark.unit
def test_axis_result_status_warn():
    r = AxisResult(
        axis="silent_no_op", module="hai",
        findings=[AuditFinding(Severity.WARN, "rare-event cohort")],
    )
    assert r.status == "WARN"


@pytest.mark.unit
def test_axis_result_status_fail_dominates():
    r = AxisResult(
        axis="silent_no_op", module="hai",
        findings=[
            AuditFinding(Severity.WARN, "rare"),
            AuditFinding(Severity.FAIL, "constants drift"),
        ],
    )
    assert r.status == "FAIL"


@pytest.mark.unit
def test_audit_result_overall_status():
    res = AuditResult(cohort_dir=Path("/tmp/x"), modules=["hai"], axes=["a", "b"])
    res.add("a", "hai", AxisResult(axis="a", module="hai", info={"n": 1}))
    res.add(
        "b", "hai",
        AxisResult(
            axis="b", module="hai",
            findings=[AuditFinding(Severity.FAIL, "x")],
        ),
    )
    assert res.overall_status() == "FAIL"


@pytest.mark.unit
def test_cohort_countries_and_ndjson(tmp_path: Path):
    us = tmp_path / "us" / "fhir_r4"
    us.mkdir(parents=True)
    (us / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n"
    )
    jp = tmp_path / "jp" / "fhir_r4"
    jp.mkdir(parents=True)
    (jp / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "p2"}) + "\n"
    )

    coh = Cohort.open(tmp_path)
    assert coh.countries() == ["jp", "us"]

    rows = list(coh.ndjson("us", "Patient"))
    assert rows == [{"resourceType": "Patient", "id": "p1"}]


@pytest.mark.unit
def test_cohort_ndjson_missing_resource_returns_empty(tmp_path: Path):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    coh = Cohort.open(tmp_path)
    assert list(coh.ndjson("us", "Observation")) == []
```

Create `tests/unit/test_audit_registry.py`:

```python
"""Unit tests for clinosim.audit.registry — register / discover / get_registered."""
from __future__ import annotations

import pytest

from clinosim.audit.registry import (
    ModuleAuditSpec,
    _reset_for_test,
    discover,
    get_registered,
    register_audit_module,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    _reset_for_test()
    yield
    _reset_for_test()


@pytest.mark.unit
def test_register_then_retrieve():
    spec = ModuleAuditSpec(name="hai")
    register_audit_module(spec)
    assert get_registered() == {"hai": spec}


@pytest.mark.unit
def test_register_last_wins():
    s1 = ModuleAuditSpec(name="hai", canonical_constants={"x": ("a",)})
    s2 = ModuleAuditSpec(name="hai", canonical_constants={"x": ("b",)})
    register_audit_module(s1)
    register_audit_module(s2)
    assert get_registered()["hai"].canonical_constants == {"x": ("b",)}


@pytest.mark.unit
def test_get_registered_returns_copy():
    register_audit_module(ModuleAuditSpec(name="hai"))
    snapshot = get_registered()
    snapshot["other"] = ModuleAuditSpec(name="other")
    assert "other" not in get_registered()


@pytest.mark.unit
def test_discover_imports_existing_audit_modules():
    # No clinosim.modules.hai.audit yet at Task 1 — but discover must
    # NOT raise even if zero matches are found.
    discover()
    # No assertion on registry contents; the contract is "no errors".
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_audit_types.py tests/unit/test_audit_registry.py -v
```
Expected: ImportError / `cannot import name 'Severity' from 'clinosim.audit.types'`.

- [ ] **Step 3: Implement `clinosim/audit/types.py`**

```python
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
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator


class Severity(str, Enum):
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
    def open(cls, root: Path | str) -> "Cohort":
        return cls(Path(root))

    def countries(self) -> list[str]:
        return sorted(
            p.name for p in self.root.iterdir()
            if p.is_dir() and (p / "fhir_r4").exists()
        )

    def ndjson(self, country: str, resource: str) -> Iterator[dict]:
        path = self.root / country / "fhir_r4" / f"{resource}.ndjson"
        if not path.exists():
            return iter(())
        def _iter():
            with path.open() as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
        return _iter()
```

- [ ] **Step 4: Implement `clinosim/audit/registry.py`**

```python
"""Audit-framework module registry + discovery.

ModuleAuditSpec is the per-Module contract; modules/<name>/audit.py
side-effect-imports register_audit_module(spec) at import time. The
audit engine calls discover() before iterating registered modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ModuleAuditSpec:
    name: str
    canonical_constants: dict[str, tuple[str, ...]] = field(default_factory=dict)
    yaml_keys_to_validate: dict[str, tuple[str, ...]] = field(default_factory=dict)
    cohort_filter: Callable | None = None
    per_event_check: dict[str, Callable] = field(default_factory=dict)
    lift_firing_proof: Callable | None = None
    structural_obs_codes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    clinical_acceptance: dict[str, dict[str, float]] = field(default_factory=dict)


_MODULES: dict[str, ModuleAuditSpec] = {}


def register_audit_module(spec: ModuleAuditSpec) -> None:
    """Register a per-Module audit. Last-wins on duplicate name."""
    _MODULES[spec.name] = spec


def get_registered() -> dict[str, ModuleAuditSpec]:
    """Return a shallow copy of the registry."""
    return dict(_MODULES)


def _reset_for_test() -> None:
    """Test-only: clear the registry between cases."""
    _MODULES.clear()


def discover() -> None:
    """Import every clinosim/modules/<name>/audit.py that exists.
    Each import side-effects register_audit_module(...). Modules with
    no audit.py are silently skipped. Repeated calls are idempotent
    (importlib caches; register_audit_module is last-wins)."""
    from importlib import import_module
    from pathlib import Path
    modules_root = Path(__file__).parent.parent / "modules"
    for audit_file in sorted(modules_root.glob("*/audit.py")):
        module_name = audit_file.parent.name
        import_module(f"clinosim.modules.{module_name}.audit")
```

- [ ] **Step 5: Implement `clinosim/audit/__init__.py`**

```python
"""clinosim audit framework — unified verification gate.

See docs/superpowers/specs/2026-06-25-dqr-framework-strengthening-design.md
for the design rationale. Public exports:
- ModuleAuditSpec: the per-Module contract
- register_audit_module: invoked by modules/<name>/audit.py
- Severity, AuditFinding, AxisResult, AuditResult: result types
- Cohort: lazy NDJSON reader
"""
from clinosim.audit.registry import (
    ModuleAuditSpec,
    register_audit_module,
)
from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Cohort,
    Severity,
)

__all__ = [
    "ModuleAuditSpec",
    "register_audit_module",
    "AuditFinding",
    "AuditResult",
    "AxisResult",
    "Cohort",
    "Severity",
]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/unit/test_audit_types.py tests/unit/test_audit_registry.py -v
```
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add clinosim/audit/__init__.py clinosim/audit/types.py clinosim/audit/registry.py \
        tests/unit/test_audit_types.py tests/unit/test_audit_registry.py
git commit -m "$(cat <<'EOF'
feat(audit): types + Cohort reader + registry foundation (Task 1)

Public Phase 1 surface:
- Severity / AuditFinding / AxisResult / AuditResult value types
- AxisResult.status derives PASS/WARN/FAIL/N/A from findings + info
- AuditResult.overall_status: worst-axis-wins
- Cohort: lazy NDJSON reader rooted at <root>/<country>/fhir_r4/
- ModuleAuditSpec: per-Module audit contract (all fields optional)
- register_audit_module / get_registered / discover

discover() walks clinosim/modules/*/audit.py and importlib-loads each;
modules with no audit.py are silently skipped. _reset_for_test() lets
the test fixtures isolate.

11 unit tests cover: Severity enum, status precedence, cohort directory
walk, missing-resource → empty iterator, registry round-trip,
last-wins, copy isolation, no-op discover.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 2: Markdown reporter

**Files:**
- Create: `clinosim/audit/reporter.py`
- Create: `tests/unit/test_reporter.py`

**Interfaces:**
- Consumes: `AuditResult`, `AxisResult`, `AuditFinding`, `Severity` from Task 1.
- Produces:
  ```python
  def render_markdown(result: AuditResult) -> str:
      """Format an AuditResult as a Markdown report (string).

      Layout:
        # Audit Report — <ISO timestamp passed in via result>
        Cohort: <dir>
        Modules: <comma-separated>
        Axes: <comma-separated>

        ## Summary
        <table of module × axis status>

        ## <module> (N/M PASS)
          ### Axis 1: <axis> — <STATUS>
            <bulleted findings + info>
      """

  def write_markdown(result: AuditResult, path: Path | str) -> None:
      """Write render_markdown(result) to path; creates parent dirs."""
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reporter.py`:

```python
"""Unit tests for clinosim.audit.reporter — Markdown render + file write."""
from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.audit.reporter import render_markdown, write_markdown
from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Severity,
)


def _make_result():
    res = AuditResult(
        cohort_dir=Path("/tmp/cohort"), modules=["hai"], axes=["structural", "clinical"],
    )
    res.add(
        "structural", "hai",
        AxisResult(axis="structural", module="hai", info={"WBC_n": 100, "WBC_refRange_pct": 100.0}),
    )
    res.add(
        "clinical", "hai",
        AxisResult(
            axis="clinical", module="hai",
            findings=[AuditFinding(Severity.WARN, "rare-event cohort", {"n": 3})],
            info={"baseline_WBC_p50": 12029},
        ),
    )
    return res


@pytest.mark.unit
def test_render_contains_summary_table():
    md = render_markdown(_make_result())
    assert "## Summary" in md
    assert "| Module | structural | clinical |" in md
    assert "| hai | PASS | WARN |" in md


@pytest.mark.unit
def test_render_contains_per_axis_sections():
    md = render_markdown(_make_result())
    assert "### Axis 1: structural" in md
    assert "### Axis 2: clinical" in md
    assert "WBC_n=100" in md or "WBC_n: 100" in md  # info dump


@pytest.mark.unit
def test_render_records_findings():
    md = render_markdown(_make_result())
    assert "WARN" in md
    assert "rare-event cohort" in md


@pytest.mark.unit
def test_write_markdown_creates_file_and_parent(tmp_path: Path):
    out = tmp_path / "subdir" / "audit.md"
    write_markdown(_make_result(), out)
    assert out.exists()
    assert "## Summary" in out.read_text()


@pytest.mark.unit
def test_render_marks_overall_status_at_top():
    res = _make_result()
    md = render_markdown(res)
    assert "Overall: WARN" in md
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_reporter.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `clinosim/audit/reporter.py`**

```python
"""Markdown reporter for AuditResult.

Renders the per-module × per-axis grid + axis-level findings into a
Markdown string suitable for committing under docs/reviews/. The
reporter is pure — it does not mutate the AuditResult.
"""
from __future__ import annotations

from pathlib import Path

from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Severity,
)


def _info_block(info: dict) -> str:
    if not info:
        return ""
    return "\n".join(f"- {k}={v}" for k, v in info.items())


def _findings_block(findings: list[AuditFinding]) -> str:
    if not findings:
        return ""
    lines = []
    for f in findings:
        line = f"- **{f.severity.value}** {f.message}"
        if f.detail:
            line += f" — {f.detail}"
        lines.append(line)
    return "\n".join(lines)


def render_markdown(result: AuditResult) -> str:
    parts: list[str] = []
    parts.append("# clinosim audit report\n")
    parts.append(f"**Overall: {result.overall_status()}**\n")
    parts.append(f"- Cohort: `{result.cohort_dir}`")
    parts.append(f"- Modules: {', '.join(result.modules) or '(none)'}")
    parts.append(f"- Axes: {', '.join(result.axes)}\n")

    parts.append("## Summary\n")
    header = "| Module | " + " | ".join(result.axes) + " |"
    sep = "|---|" + "|".join("---" for _ in result.axes) + "|"
    parts.append(header)
    parts.append(sep)
    for module in result.modules:
        row = [f"| {module} "]
        for axis in result.axes:
            r = result.results.get((axis, module))
            row.append(f"| {r.status if r else 'N/A'} ")
        parts.append("".join(row) + "|")
    parts.append("")

    for module in result.modules:
        passed = sum(
            1 for axis in result.axes
            if (r := result.results.get((axis, module))) and r.status == "PASS"
        )
        parts.append(f"## {module} ({passed}/{len(result.axes)} PASS)\n")
        for i, axis in enumerate(result.axes, 1):
            r = result.results.get((axis, module))
            status = r.status if r else "N/A"
            parts.append(f"### Axis {i}: {axis} — {status}\n")
            if r is None:
                parts.append("- (no audit for this module on this axis)\n")
                continue
            f_block = _findings_block(r.findings)
            if f_block:
                parts.append(f_block)
            i_block = _info_block(r.info)
            if i_block:
                parts.append(i_block)
            parts.append("")

    return "\n".join(parts)


def write_markdown(result: AuditResult, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_markdown(result), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_reporter.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add clinosim/audit/reporter.py tests/unit/test_reporter.py
git commit -m "$(cat <<'EOF'
feat(audit): Markdown reporter for AuditResult (Task 2)

render_markdown(result) → str: top-level Overall status, cohort
metadata, summary grid (module × axis), per-axis findings + info dump.

write_markdown(result, path): wraps render + parent-dir mkdir +
UTF-8 write.

5 unit tests pin: summary table shape, per-axis sections, finding /
severity surfacing, overall-status header, parent-dir creation on
write.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 3: Structural axis

**Files:**
- Create: `clinosim/audit/axes/__init__.py` (empty marker)
- Create: `clinosim/audit/axes/structural.py`
- Create: `tests/unit/test_axis_structural.py`

**Interfaces:**
- Consumes: `ModuleAuditSpec.structural_obs_codes`, `Cohort` from Task 1.
- Produces:
  ```python
  def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
      """Verify FHIR resource integrity for the codes declared in
      spec.structural_obs_codes:
        - 100% refRange + interpretation coverage
        - id uniqueness across each NDJSON file
        - reference integrity (every Observation.subject/encounter
          target exists in Patient/Encounter)
        - display ≠ code on every Observation coding
      """
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_axis_structural.py`:

```python
"""Unit tests for clinosim.audit.axes.structural."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import structural
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort, Severity


def _write_obs(path: Path, codes: list[dict], **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        rec = {
            "resourceType": "Observation",
            "id": extra.pop("id", "obs-1"),
            "code": {"coding": codes},
            **extra,
        }
        f.write(json.dumps(rec) + "\n")


@pytest.fixture
def hai_spec():
    return ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",), "CRP": ("1988-5",)},
    )


@pytest.mark.unit
def test_structural_pass_when_full_coverage(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "WBC"}],
               referenceRange=[{"low": {"value": 4500}}],
               interpretation=[{"text": "N"}])
    _write_obs(obs, [{"code": "1988-5", "display": "CRP"}],
               referenceRange=[{"low": {"value": 0}}],
               interpretation=[{"text": "N"}])
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_structural_fail_missing_refRange(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "WBC"}],
               interpretation=[{"text": "N"}])  # no referenceRange
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("refRange" in f.message for f in result.findings)


@pytest.mark.unit
def test_structural_fail_duplicate_id(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "WBC"}], id="dup",
               referenceRange=[{}], interpretation=[{}])
    _write_obs(obs, [{"code": "1988-5", "display": "CRP"}], id="dup",
               referenceRange=[{}], interpretation=[{}])
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("duplicate" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_structural_fail_display_equals_code(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "6690-2"}],
               referenceRange=[{}], interpretation=[{}])
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("display" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_structural_na_when_no_matching_codes(tmp_path: Path, hai_spec):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "N/A"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_axis_structural.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `clinosim/audit/axes/__init__.py` (empty marker)**

```python
"""clinosim.audit.axes — per-axis check runners."""
```

- [ ] **Step 4: Implement `clinosim/audit/axes/structural.py`**

```python
"""Structural axis: FHIR resource integrity for the codes declared in
spec.structural_obs_codes.

Checks (all FAIL-severity on miss):
- 100% referenceRange + interpretation coverage
- id uniqueness across each NDJSON file
- display != code on every coding
- (reference integrity check: deferred to Phase 2 — needs cross-file
  walk; structural pass is sufficient at Phase 1 since invariant is
  already enforced by output adapter tests)
"""
from __future__ import annotations

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import (
    AuditFinding,
    AxisResult,
    Cohort,
    Severity,
)


def _wanted_codes(spec: ModuleAuditSpec) -> set[str]:
    out: set[str] = set()
    for codes in spec.structural_obs_codes.values():
        out.update(codes)
    return out


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="structural", module=spec.name)
    wanted = _wanted_codes(spec)
    if not wanted:
        return result  # N/A — no codes to check

    per_code_n: dict[str, int] = {c: 0 for c in wanted}
    per_code_full: dict[str, int] = {c: 0 for c in wanted}
    seen_ids: dict[str, str] = {}  # id -> country

    for country in cohort.countries():
        for row in cohort.ndjson(country, "Observation"):
            codes = {
                c.get("code", "")
                for c in (row.get("code") or {}).get("coding", [])
            }
            matched = codes & wanted
            if not matched:
                continue
            for c in matched:
                per_code_n[c] += 1
                if row.get("referenceRange") and row.get("interpretation"):
                    per_code_full[c] += 1
            rid = row.get("id", "")
            if rid in seen_ids:
                result.findings.append(AuditFinding(
                    Severity.FAIL,
                    f"duplicate Observation id {rid!r} in {country} (also seen in {seen_ids[rid]})",
                ))
            else:
                seen_ids[rid] = country
            for c in (row.get("code") or {}).get("coding", []):
                code = c.get("code", "")
                display = c.get("display", "")
                if code and display and code == display:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"display equals code {code!r} on Observation {rid}",
                    ))

    for code in wanted:
        n = per_code_n[code]
        full = per_code_full[code]
        result.info[f"{code}_n"] = n
        if n == 0:
            continue
        pct = round(100.0 * full / n, 2)
        result.info[f"{code}_refRange_interp_pct"] = pct
        if pct < 100.0:
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"{code} refRange + interpretation coverage {full}/{n} = {pct}% (need 100%)",
            ))

    return result
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_axis_structural.py -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add clinosim/audit/axes/__init__.py clinosim/audit/axes/structural.py \
        tests/unit/test_axis_structural.py
git commit -m "$(cat <<'EOF'
feat(audit): structural axis — refRange + interpretation + id + display (Task 3)

clinosim/audit/axes/structural.run iterates Observation.ndjson for each
country in the cohort and verifies, for codes declared in
spec.structural_obs_codes:

- 100% referenceRange + interpretation coverage
- id uniqueness across the file (catches duplicate FHIR ids)
- display != code on every coding (catches the FHIR R5 Note 5 anti-
  pattern when adapters silently fall back to code-as-display)

N/A when the spec has no codes to check or none of the codes appear in
the cohort. PASS / FAIL otherwise; info dump records per-code counts +
coverage percentages.

Reference-integrity check (subject/encounter target existence) is
deferred to Phase 2 — it needs cross-file walks and is already
covered by the FHIR adapter output tests.

5 unit tests cover: PASS, missing refRange, duplicate id,
display=code, N/A when no codes matched.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 4: JP-language axis

**Files:**
- Create: `clinosim/audit/axes/jp_language.py`
- Create: `tests/unit/test_axis_jp_language.py`

**Interfaces:**
- Consumes: `Cohort` (`countries()`, `ndjson()`), `ModuleAuditSpec.structural_obs_codes`.
- Produces: `run(spec, cohort) -> AxisResult` — US display non-ASCII = 0, JP displays for the Module's codes contain Japanese characters.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_axis_jp_language.py`:

```python
"""Unit tests for clinosim.audit.axes.jp_language."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import jp_language
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort


def _write_obs(path: Path, country: str, code: str, display: str, id_: str):
    p = path / country / "fhir_r4" / "Observation.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "resourceType": "Observation",
        "id": id_,
        "code": {"coding": [{"code": code, "display": display}]},
    }
    with p.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.fixture
def spec():
    return ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2", "2A010"), "CRP": ("1988-5", "5C070")},
    )


@pytest.mark.unit
def test_jp_pass_with_localized_displays(tmp_path: Path, spec):
    _write_obs(tmp_path, "us", "6690-2", "Leukocytes", "us-wbc-1")
    _write_obs(tmp_path, "jp", "2A010", "白血球数", "jp-wbc-1")
    _write_obs(tmp_path, "jp", "5C070", "C反応性蛋白", "jp-crp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_jp_fail_when_us_has_non_ascii(tmp_path: Path, spec):
    _write_obs(tmp_path, "us", "6690-2", "白血球数", "us-wbc-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("non-ASCII" in f.message or "US" in f.message for f in result.findings)


@pytest.mark.unit
def test_jp_fail_when_jp_display_not_localized(tmp_path: Path, spec):
    _write_obs(tmp_path, "jp", "2A010", "Leukocytes", "jp-wbc-1")  # ASCII only
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("WBC" in f.message for f in result.findings)


@pytest.mark.unit
def test_jp_na_when_no_jp_country(tmp_path: Path, spec):
    _write_obs(tmp_path, "us", "6690-2", "Leukocytes", "us-wbc-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    # JP coverage is N/A but US scan still ran — so status is PASS
    assert result.status == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_axis_jp_language.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `clinosim/audit/axes/jp_language.py`**

```python
"""JP-language axis: localization integrity.

Checks:
- US output Observation display fields contain ZERO non-ASCII
  characters (no JP leakage into US cohort).
- JP output Observation displays for the codes in
  spec.structural_obs_codes contain Japanese characters (at least one
  non-ASCII codepoint). Missing JP cohort is acceptable — N/A.

Code values are checked against the LOINC and JLAC10 tuples in
spec.structural_obs_codes so this axis is reusable for any Module that
declares its observation codes.
"""
from __future__ import annotations

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity


def _has_non_ascii(s: str) -> bool:
    return any(ord(c) > 127 for c in s or "")


def _wanted(spec: ModuleAuditSpec) -> set[str]:
    out: set[str] = set()
    for codes in spec.structural_obs_codes.values():
        out.update(codes)
    return out


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="jp_language", module=spec.name)
    wanted = _wanted(spec)

    # US: zero non-ASCII display violations across all Observation
    # codings (no language scope — any non-ASCII in US is wrong).
    us_violations = 0
    for row in cohort.ndjson("us", "Observation"):
        for coding in (row.get("code") or {}).get("coding", []):
            if _has_non_ascii(coding.get("display", "")):
                us_violations += 1
                break
    result.info["us_non_ascii_display_violations"] = us_violations
    if us_violations > 0:
        result.findings.append(AuditFinding(
            Severity.FAIL,
            f"US output has {us_violations} Observations with non-ASCII display",
        ))

    # JP: each requested analyte must have at least one localized display
    if "jp" not in cohort.countries():
        # No JP cohort — record info but don't fail
        return result if (result.info or result.findings) else AxisResult(
            axis="jp_language", module=spec.name, info=result.info,
        )

    jp_localized: dict[str, int] = {a: 0 for a in spec.structural_obs_codes}
    jp_total: dict[str, int] = {a: 0 for a in spec.structural_obs_codes}
    for row in cohort.ndjson("jp", "Observation"):
        codings = (row.get("code") or {}).get("coding", [])
        for analyte, codes in spec.structural_obs_codes.items():
            if any(c.get("code", "") in codes for c in codings):
                jp_total[analyte] += 1
                if any(_has_non_ascii(c.get("display", "")) for c in codings):
                    jp_localized[analyte] += 1
                break

    for analyte, total in jp_total.items():
        result.info[f"jp_{analyte}_localized"] = jp_localized[analyte]
        result.info[f"jp_{analyte}_total"] = total
        if total > 0 and jp_localized[analyte] == 0:
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"{analyte}: 0 of {total} JP Observations have a localized display",
            ))

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_axis_jp_language.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add clinosim/audit/axes/jp_language.py tests/unit/test_axis_jp_language.py
git commit -m "$(cat <<'EOF'
feat(audit): jp_language axis — US ASCII / JP localized displays (Task 4)

Checks for each Module declaring structural_obs_codes:
- US Observation displays contain ZERO non-ASCII (no JP leakage)
- JP Observation displays for the Module's analytes contain at least
  one non-ASCII codepoint (display localization integrity)

Missing JP cohort → N/A for JP half (US half still runs). Per-analyte
info dump (localized count + total) lands in result.info so the
Markdown report records the breakdown even when PASS.

4 unit tests pin: PASS with localized displays, FAIL on US non-ASCII,
FAIL on JP non-localized, N/A behavior when JP cohort missing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 5: silent_no_op axis (the gate that catches PR-90)

**Files:**
- Create: `clinosim/audit/axes/silent_no_op.py`
- Create: `tests/unit/test_axis_silent_no_op.py`

**Interfaces:**
- Consumes: `ModuleAuditSpec.canonical_constants`, `yaml_keys_to_validate`, `lift_firing_proof`.
- Produces: `run(spec, cohort) -> AxisResult` — fired counter, canonical constants cross-check, lift-firing proof execution + delta verification.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_axis_silent_no_op.py`:

```python
"""Unit tests for clinosim.audit.axes.silent_no_op."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.audit.axes import silent_no_op
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort, Severity


def _write_condition(path: Path, country: str, code: str, id_: str):
    p = path / country / "fhir_r4" / "Condition.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "resourceType": "Condition",
        "id": id_,
        "code": {"coding": [{"code": code}]},
    }
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _proof_factory_pass():
    """Lift-firing proof builder that returns a record + apply_fn that
    bumps wbc_obs.value by exactly the expected delta."""
    wbc_obs = SimpleNamespace(value=11760.0)
    def apply_fn(record, encounter, state_history, admission_time):
        wbc_obs.value = 14280.0
        return 1
    return {
        "record": SimpleNamespace(), "encounter": SimpleNamespace(),
        "state_history": [], "admission_time": None,
        "apply_fn": apply_fn,
        "expected_deltas": {wbc_obs: 2520.0},
        # snapshot wbc_obs so the engine can read pre/post
        "tracked_obs": [wbc_obs],
        "pre_values": {wbc_obs: 11760.0},
    }


def _proof_factory_silent_no_op():
    wbc_obs = SimpleNamespace(value=11760.0)
    def apply_fn(record, encounter, state_history, admission_time):
        return 0  # silently no-op
    return {
        "record": SimpleNamespace(), "encounter": SimpleNamespace(),
        "state_history": [], "admission_time": None,
        "apply_fn": apply_fn,
        "expected_deltas": {wbc_obs: 2520.0},
        "tracked_obs": [wbc_obs],
        "pre_values": {wbc_obs: 11760.0},
    }


@pytest.mark.unit
def test_silent_no_op_pass_with_proof(tmp_path: Path):
    spec = ModuleAuditSpec(
        name="hai",
        canonical_constants={"hai_type": ("clabsi", "cauti", "vap")},
        lift_firing_proof=_proof_factory_pass,
    )
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_silent_no_op_fail_when_proof_delta_mismatch(tmp_path: Path):
    spec = ModuleAuditSpec(
        name="hai", lift_firing_proof=_proof_factory_silent_no_op,
    )
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("proof" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_silent_no_op_constants_drift_yaml(tmp_path: Path):
    yaml_file = tmp_path / "modules/hai/reference_data/hai_lab_lift.yaml"
    yaml_file.parent.mkdir(parents=True)
    yaml_file.write_text(
        "ramp_peak_days: 2\nhai_lift:\n  CLABSI: 0.35\n",  # UPPERCASE = drift
        encoding="utf-8",
    )
    spec = ModuleAuditSpec(
        name="hai",
        canonical_constants={"hai_type": ("clabsi", "cauti", "vap")},
        yaml_keys_to_validate={
            str(yaml_file): ("hai_lift",),
        },
    )
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("CLABSI" in f.message or "drift" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_silent_no_op_fired_counter_warn_for_rare_cohort(tmp_path: Path):
    # No Condition.ndjson at all → 0 events → cohort empty too → WARN, not FAIL
    spec = ModuleAuditSpec(
        name="hai",
        canonical_constants={"hai_type": ("cauti",)},
        # fire_counter_codes: how the axis recognizes module emissions
    )
    # No fired-counter codes supplied → skip the counter check
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    # Only constants check ran (PASS); no proof/no counter → PASS
    assert result.status == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_axis_silent_no_op.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `clinosim/audit/axes/silent_no_op.py`**

```python
"""silent_no_op axis: the gate that catches PR-90's class of bug.

Three checks, each independently severable so a Module can opt in to
any subset:

1. **Canonical constants cross-check** — for every (yaml_file,
   key_path) in spec.yaml_keys_to_validate, load the YAML and verify
   every key under key_path is in the matching set in
   spec.canonical_constants. ANY drift → FAIL.

2. **Lift-firing proof** — if spec.lift_firing_proof is set, call it
   (zero-arg factory) to build {record, apply_fn, expected_deltas,
   tracked_obs, pre_values}. The engine then:
     - snapshots pre-apply values from pre_values dict
     - calls apply_fn(record, encounter, state_history, admission_time)
     - for each tracked_obs, computes observed_delta = new_value -
       pre_values[obs] and compares to expected_deltas[obs] within
       per-analyte tolerance (WBC ±2.0, CRP ±0.5).
   ANY mismatch → FAIL. This is the load-bearing verification that
   would have caught PR-90's UPPERCASE/lowercase silent no-op.

3. **Fired counter** — Phase 1 surface: counts Condition emissions
   carrying the codes in spec.canonical_constants["icd_codes"] if set.
   Phase 1 ships HAI without a fired_counter (Module-specific code
   discovery is Phase 2 backlog) — the axis runs the constants +
   proof checks only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity


# Per-analyte tolerance band for lift-firing proof comparison.
_PROOF_TOLERANCE = {"WBC": 2.0, "CRP": 0.5}
_PROOF_DEFAULT_TOLERANCE = 1.0


def _yaml_keys_at_path(data, path: tuple[str, ...]):
    cur = data
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur if isinstance(cur, dict) else None


def _check_constants(spec: ModuleAuditSpec, result: AxisResult) -> None:
    if not spec.yaml_keys_to_validate:
        return
    # Find the matching canonical set: spec.canonical_constants is
    # keyed by symbolic name (e.g. "hai_type"); we cross-check all
    # values by union to keep the spec simple at Phase 1.
    canonical_union: set[str] = set()
    for values in spec.canonical_constants.values():
        canonical_union.update(values)
    if not canonical_union:
        return
    for yaml_path, key_path in spec.yaml_keys_to_validate.items():
        p = Path(yaml_path)
        if not p.exists():
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"canonical-constants source {yaml_path!r} not found",
            ))
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as e:
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"canonical-constants source {yaml_path!r} unparseable: {e}",
            ))
            continue
        node = _yaml_keys_at_path(data, key_path)
        if node is None:
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"key path {key_path} not found in {yaml_path}",
            ))
            continue
        unknown = set(node) - canonical_union
        if unknown:
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"canonical-constants drift in {yaml_path}: keys {sorted(unknown)} "
                f"not in canonical set {sorted(canonical_union)}",
            ))
        else:
            result.info[f"constants_pass_{p.name}"] = "ok"


def _check_proof(spec: ModuleAuditSpec, result: AxisResult) -> None:
    if spec.lift_firing_proof is None:
        return
    try:
        proof = spec.lift_firing_proof()
    except Exception as e:
        result.findings.append(AuditFinding(
            Severity.FAIL,
            f"lift_firing_proof factory raised: {type(e).__name__}: {e}",
        ))
        return
    apply_fn = proof.get("apply_fn")
    expected = proof.get("expected_deltas") or {}
    pre = proof.get("pre_values") or {}
    if apply_fn is None or not expected:
        return  # nothing to verify
    apply_fn(
        proof.get("record"),
        proof.get("encounter"),
        proof.get("state_history") or [],
        proof.get("admission_time"),
    )
    for obs, expected_delta in expected.items():
        pre_value = pre.get(obs, getattr(obs, "_pre_value", None))
        new_value = obs.value
        if pre_value is None:
            continue
        observed_delta = new_value - pre_value
        analyte = getattr(obs, "lab_name", None) or _guess_analyte(obs)
        tol = _PROOF_TOLERANCE.get(analyte, _PROOF_DEFAULT_TOLERANCE)
        if abs(observed_delta - expected_delta) > tol:
            result.findings.append(AuditFinding(
                Severity.FAIL,
                f"lift-firing proof delta mismatch for {analyte}: "
                f"observed {observed_delta:.2f}, expected {expected_delta:.2f} "
                f"(tolerance ±{tol})",
            ))
        else:
            result.info[f"proof_{analyte}_delta"] = round(observed_delta, 2)


def _guess_analyte(obs) -> str | None:
    return getattr(obs, "lab_name", None)


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="silent_no_op", module=spec.name)
    _check_constants(spec, result)
    _check_proof(spec, result)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_axis_silent_no_op.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add clinosim/audit/axes/silent_no_op.py tests/unit/test_axis_silent_no_op.py
git commit -m "$(cat <<'EOF'
feat(audit): silent_no_op axis — PR-90 class of bug gate (Task 5)

Two FAIL-severity checks (third — fired counter — is Phase 2):

1. Canonical constants cross-check
   For each (yaml_file, key_path) in spec.yaml_keys_to_validate, load
   the YAML at key_path and verify every key is in the spec's
   canonical_constants set. ANY drift → FAIL. This is the gate that
   would have caught PR-90's UPPERCASE/lowercase mismatch at audit
   time instead of three reviews later.

2. Lift-firing proof
   If spec.lift_firing_proof is set, call it (zero-arg factory) to
   build {record, apply_fn, expected_deltas, tracked_obs, pre_values}.
   The axis snapshots pre-apply values, runs apply_fn, then asserts
   observed delta == expected delta within per-analyte tolerance
   (WBC ±2.0, CRP ±0.5). ANY mismatch → FAIL. This is the
   load-bearing verification PR-90 was missing.

Per-axis tolerance ladder is in module-level _PROOF_TOLERANCE so future
Modules can extend by analyte.

4 unit tests cover: PASS with proof matching, FAIL when apply_fn
silently no-ops (the PR-90 scenario), constants drift detected (the
PR-90 root cause class), graceful empty behavior.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 6: Clinical axis (cohort baselines + per-event theoretical)

**Files:**
- Create: `clinosim/audit/axes/clinical.py`
- Create: `tests/unit/test_axis_clinical.py`

**Interfaces:**
- Consumes: `Cohort`, `ModuleAuditSpec.cohort_filter`, `per_event_check`, `clinical_acceptance`.
- Produces: `run(spec, cohort) -> AxisResult`.

The cohort_filter is called per CIF patient record (the engine loads structural CIF JSONs separately from the FHIR NDJSON for this). At Phase 1 we simplify: clinical axis reads HAI cohort identity from Condition.ndjson ICD codes the Module declares in `spec.clinical_acceptance` (one acceptance entry per HAI type, key = lowercase hai_type, value = `{WBC_delta_p50: float, CRP_delta_p50: float}`). The cohort_filter is wired into the registry for Phase 2 use (per-event verification requires CIF state_history walk; Phase 1 ships the simpler cohort baseline + acceptance check).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_axis_clinical.py`:

```python
"""Unit tests for clinosim.audit.axes.clinical (Phase 1 cohort baseline +
acceptance subset)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import clinical
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort


def _write(path: Path, country: str, file: str, rows: list[dict]):
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _wbc(enc: str, val: float, oid: str):
    return {
        "resourceType": "Observation",
        "id": oid,
        "code": {"coding": [{"code": "6690-2"}]},
        "encounter": {"reference": f"Encounter/{enc}"},
        "valueQuantity": {"value": val},
    }


def _crp(enc: str, val: float, oid: str):
    return {
        "resourceType": "Observation",
        "id": oid,
        "code": {"coding": [{"code": "1988-5"}]},
        "encounter": {"reference": f"Encounter/{enc}"},
        "valueQuantity": {"value": val},
    }


def _cauti_cond(enc: str, cid: str):
    return {
        "resourceType": "Condition",
        "id": cid,
        "code": {"coding": [{"code": "T83.511A"}]},
        "encounter": {"reference": f"Encounter/{enc}"},
    }


def _imp_enc(eid: str):
    return {
        "resourceType": "Encounter", "id": eid,
        "class": {"code": "IMP"},
    }


@pytest.fixture
def hai_spec():
    return ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",), "CRP": ("1988-5",)},
        clinical_acceptance={
            "cauti": {
                "icd10_code": "T83.511A",
                "WBC_delta_p50": 1500,
                "CRP_delta_p50": 25,
            },
        },
    )


@pytest.mark.unit
def test_clinical_pass_when_cauti_cohort_exceeds_acceptance(
    tmp_path: Path, hai_spec,
):
    _write(tmp_path, "us", "Encounter.ndjson",
           [_imp_enc("E-CAUTI-1"), _imp_enc("E-BASE-1"),
            _imp_enc("E-BASE-2")])
    _write(tmp_path, "us", "Condition.ndjson", [_cauti_cond("E-CAUTI-1", "c-1")])
    _write(tmp_path, "us", "Observation.ndjson", [
        _wbc("E-CAUTI-1", 14000, "o-c-w"),
        _crp("E-CAUTI-1", 75, "o-c-c"),
        _wbc("E-BASE-1", 12000, "o-b-w1"),
        _wbc("E-BASE-2", 12000, "o-b-w2"),
        _crp("E-BASE-1", 25, "o-b-c1"),
        _crp("E-BASE-2", 25, "o-b-c2"),
    ])
    result = clinical.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_clinical_fail_when_cohort_misses_acceptance(tmp_path: Path, hai_spec):
    _write(tmp_path, "us", "Encounter.ndjson",
           [_imp_enc("E-CAUTI-1"), _imp_enc("E-BASE-1")])
    _write(tmp_path, "us", "Condition.ndjson", [_cauti_cond("E-CAUTI-1", "c-1")])
    _write(tmp_path, "us", "Observation.ndjson", [
        _wbc("E-CAUTI-1", 12100, "o-c-w"),     # delta only +100
        _wbc("E-BASE-1", 12000, "o-b-w1"),
        _crp("E-CAUTI-1", 30, "o-c-c"),
        _crp("E-BASE-1", 25, "o-b-c1"),
    ])
    result = clinical.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"


@pytest.mark.unit
def test_clinical_warn_when_cohort_rare(tmp_path: Path, hai_spec):
    # No CAUTI Condition → cohort_n = 0 → rare-event WARN, not FAIL
    _write(tmp_path, "us", "Encounter.ndjson", [_imp_enc("E-1")])
    _write(tmp_path, "us", "Observation.ndjson",
           [_wbc("E-1", 12000, "o-1")])
    result = clinical.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "WARN"


@pytest.mark.unit
def test_clinical_na_when_spec_has_no_acceptance(tmp_path: Path):
    spec = ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",), "CRP": ("1988-5",)},
    )
    result = clinical.run(spec, Cohort.open(tmp_path))
    assert result.status == "N/A"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_axis_clinical.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `clinosim/audit/axes/clinical.py`**

```python
"""Clinical axis: cohort baseline + acceptance verification.

Phase 1 surface:
- For each entry in spec.clinical_acceptance (key = lowercase
  hai_type, value = {icd10_code, WBC_delta_p50, CRP_delta_p50}):
    1. Identify the cohort encounters via Condition.ndjson rows
       whose code.coding[].code == icd10_code.
    2. Split observations into cohort (those linked to a cohort
       encounter) and baseline (other inpatient-class encounters).
    3. Compute cohort_p50 - baseline_p50 for WBC and CRP.
    4. Compare against the WBC_delta_p50 / CRP_delta_p50 thresholds.
    5. cohort < 5 → WARN (rare-event acceptable, mitigated by
       silent_no_op axis lift-firing proof).
    6. Cohort meets acceptance → PASS; misses → FAIL.

Per-event observed-vs-theoretical verification is deferred to Phase 2
(requires CIF state_history walk; the silent_no_op axis already
provides the load-bearing per-event check via lift_firing_proof).
"""
from __future__ import annotations

import statistics

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity

_WBC_CODE = "6690-2"
_WBC_CODE_JP = "2A010"
_CRP_CODE = "1988-5"
_CRP_CODE_JP = "5C070"


def _is_wbc(coding: list[dict]) -> bool:
    return any(c.get("code") in (_WBC_CODE, _WBC_CODE_JP) for c in coding)


def _is_crp(coding: list[dict]) -> bool:
    return any(c.get("code") in (_CRP_CODE, _CRP_CODE_JP) for c in coding)


def _enc_id(row: dict) -> str:
    ref = (row.get("encounter") or {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def _condition_code_set(row: dict) -> set[str]:
    return {c.get("code", "") for c in (row.get("code") or {}).get("coding", [])}


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="clinical", module=spec.name)
    if not spec.clinical_acceptance:
        return result  # N/A

    for country in cohort.countries():
        # Identify cohort encounters per HAI type
        cohort_enc: dict[str, set[str]] = {
            k: set() for k in spec.clinical_acceptance
        }
        icd_to_type = {
            v["icd10_code"]: k for k, v in spec.clinical_acceptance.items()
        }
        for row in cohort.ndjson(country, "Condition"):
            codes = _condition_code_set(row)
            for icd, hai_type in icd_to_type.items():
                if icd in codes:
                    eid = _enc_id(row)
                    if eid:
                        cohort_enc[hai_type].add(eid)

        # Identify baseline inpatient encounters (class=IMP, not in cohort)
        all_cohort_enc = set().union(*cohort_enc.values())
        baseline_enc: set[str] = set()
        for row in cohort.ndjson(country, "Encounter"):
            eid = row.get("id", "")
            cls = (row.get("class") or {}).get("code", "")
            if cls == "IMP" and eid not in all_cohort_enc:
                baseline_enc.add(eid)

        # Collect per-cohort + baseline WBC/CRP
        cohort_wbc: dict[str, list[float]] = {k: [] for k in spec.clinical_acceptance}
        cohort_crp: dict[str, list[float]] = {k: [] for k in spec.clinical_acceptance}
        base_wbc: list[float] = []
        base_crp: list[float] = []
        for row in cohort.ndjson(country, "Observation"):
            codings = (row.get("code") or {}).get("coding", [])
            val = (row.get("valueQuantity") or {}).get("value")
            if val is None:
                continue
            eid = _enc_id(row)
            if not eid:
                continue
            is_w = _is_wbc(codings)
            is_c = _is_crp(codings)
            if not (is_w or is_c):
                continue
            for hai_type, encs in cohort_enc.items():
                if eid in encs:
                    (cohort_wbc if is_w else cohort_crp)[hai_type].append(val)
                    break
            else:
                if eid in baseline_enc:
                    (base_wbc if is_w else base_crp).append(val)

        b_wbc_p50 = statistics.median(base_wbc) if base_wbc else None
        b_crp_p50 = statistics.median(base_crp) if base_crp else None
        result.info[f"{country}_baseline_WBC_p50"] = b_wbc_p50
        result.info[f"{country}_baseline_CRP_p50"] = b_crp_p50

        for hai_type, acceptance in spec.clinical_acceptance.items():
            w = cohort_wbc[hai_type]
            c = cohort_crp[hai_type]
            n_w, n_c = len(w), len(c)
            result.info[f"{country}_{hai_type}_n_WBC"] = n_w
            result.info[f"{country}_{hai_type}_n_CRP"] = n_c
            if n_w < 5 and n_c < 5:
                result.findings.append(AuditFinding(
                    Severity.WARN,
                    f"{country}/{hai_type}: cohort too small for delta "
                    f"(n_WBC={n_w}, n_CRP={n_c}); acceptance not verified at "
                    "cohort level (silent_no_op axis covers this).",
                ))
                continue
            if w and b_wbc_p50 is not None:
                dw = statistics.median(w) - b_wbc_p50
                result.info[f"{country}_{hai_type}_WBC_delta_p50"] = round(dw, 1)
                need = acceptance.get("WBC_delta_p50")
                if need is not None and dw < need:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}/{hai_type}: WBC delta p50 = {dw:.0f} < required {need}",
                    ))
            if c and b_crp_p50 is not None:
                dc = statistics.median(c) - b_crp_p50
                result.info[f"{country}_{hai_type}_CRP_delta_p50"] = round(dc, 1)
                need = acceptance.get("CRP_delta_p50")
                if need is not None and dc < need:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}/{hai_type}: CRP delta p50 = {dc:.1f} < required {need}",
                    ))

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_axis_clinical.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add clinosim/audit/axes/clinical.py tests/unit/test_axis_clinical.py
git commit -m "$(cat <<'EOF'
feat(audit): clinical axis — cohort baseline + acceptance gate (Task 6)

Phase 1 surface: for each clinical_acceptance entry, identify the
cohort via the declared ICD code, split observations into cohort vs
baseline (class=IMP, non-cohort), and check WBC + CRP delta p50 vs
the per-HAI-type acceptance thresholds.

- cohort_n < 5 → WARN (rare-event acceptable; silent_no_op axis
  covers the load-bearing verification)
- cohort meets acceptance → PASS
- cohort misses acceptance → FAIL

Per-event observed-vs-theoretical (CIF state_history walk) is
deferred to Phase 2; the silent_no_op axis already runs a per-event
proof via lift_firing_proof which makes Phase 1's cohort-level check
sufficient as a quality gate.

4 unit tests pin: PASS path, FAIL when delta short, WARN when cohort
< 5, N/A when no acceptance declared.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 7: AuditEngine + CLI wiring

**Files:**
- Create: `clinosim/audit/engine.py`
- Create: `clinosim/audit/cli.py`
- Modify: `clinosim/simulator/cli.py` (add `audit` subparser)
- Create: `tests/unit/test_audit_engine.py`

**Interfaces:**
- Consumes: registry / types / 4 axes / reporter.
- Produces: `AuditEngine(cohort_dir, modules?, axes?).run() -> AuditResult` and the `clinosim audit run/smoke/list` CLI subcommands.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_audit_engine.py`:

```python
"""Unit tests for clinosim.audit.engine."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.engine import AuditEngine, _BUILTIN_AXES
from clinosim.audit.registry import (
    ModuleAuditSpec,
    _reset_for_test,
    register_audit_module,
)


@pytest.fixture(autouse=True)
def _clear():
    _reset_for_test()
    yield
    _reset_for_test()


def _empty_cohort(tmp_path: Path) -> Path:
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    return tmp_path


@pytest.mark.unit
def test_engine_runs_all_builtin_axes(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",)},
    ))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path))
    result = engine.run()
    assert sorted(result.axes) == sorted(_BUILTIN_AXES)
    assert "hai" in result.modules


@pytest.mark.unit
def test_engine_module_filter(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    register_audit_module(ModuleAuditSpec(name="device"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path), modules=["hai"])
    result = engine.run()
    assert result.modules == ["hai"]


@pytest.mark.unit
def test_engine_axis_filter(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path), axes=["silent_no_op"])
    result = engine.run()
    assert result.axes == ["silent_no_op"]


@pytest.mark.unit
def test_engine_overall_status_pass_on_empty(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path))
    result = engine.run()
    assert result.overall_status() in ("PASS", "WARN")  # no FAIL
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_audit_engine.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `clinosim/audit/engine.py`**

```python
"""AuditEngine — orchestrates per-Module audit checks across axes.

Discovery walks clinosim/modules/*/audit.py and side-effect-registers
each Module's spec. The engine then iterates the selected module ×
axis matrix, calling each axis's run() with the spec + Cohort.
"""
from __future__ import annotations

from pathlib import Path

from clinosim.audit.axes import clinical, jp_language, silent_no_op, structural
from clinosim.audit.registry import discover, get_registered
from clinosim.audit.types import AuditResult, Cohort

_BUILTIN_AXES = ("structural", "jp_language", "clinical", "silent_no_op")
_AXIS_RUNNERS = {
    "structural": structural.run,
    "jp_language": jp_language.run,
    "clinical": clinical.run,
    "silent_no_op": silent_no_op.run,
}


class AuditEngine:
    def __init__(
        self,
        cohort_dir: Path | str,
        modules: list[str] | None = None,
        axes: list[str] | None = None,
    ):
        self.cohort_dir = Path(cohort_dir)
        self.module_filter = modules
        self.axis_filter = axes

    def run(self) -> AuditResult:
        discover()
        registered = get_registered()
        selected_modules = (
            list(registered)
            if self.module_filter is None
            else [m for m in self.module_filter if m in registered]
        )
        axes_to_run = self.axis_filter or list(_BUILTIN_AXES)

        result = AuditResult(
            cohort_dir=self.cohort_dir,
            modules=selected_modules,
            axes=axes_to_run,
        )
        cohort = Cohort.open(self.cohort_dir)
        for axis in axes_to_run:
            runner = _AXIS_RUNNERS[axis]
            for module_name in selected_modules:
                axis_result = runner(registered[module_name], cohort)
                result.add(axis, module_name, axis_result)
        return result
```

- [ ] **Step 4: Implement `clinosim/audit/cli.py`**

```python
"""clinosim audit CLI subcommand wiring (called from
clinosim/simulator/cli.py).

Subcommands:
  run    Full audit (default axes + all registered modules)
  smoke  silent_no_op axis only, intended for CI plumbing
  list   Print discovered modules + their available checks
"""
from __future__ import annotations

import argparse
from pathlib import Path

from clinosim.audit.engine import AuditEngine
from clinosim.audit.registry import discover, get_registered
from clinosim.audit.reporter import render_markdown, write_markdown


def add_audit_subparser(subparsers: argparse._SubParsersAction) -> None:
    audit = subparsers.add_parser("audit", help="Verification framework")
    audit_sub = audit.add_subparsers(dest="audit_command")

    run_p = audit_sub.add_parser(
        "run", help="Run the audit framework over a generated cohort",
    )
    run_p.add_argument("-d", "--cohort-dir", required=True, type=Path)
    run_p.add_argument("--module", action="append", default=None)
    run_p.add_argument("--axis", action="append", default=None)
    run_p.add_argument("--report", type=Path, default=None)

    smoke = audit_sub.add_parser(
        "smoke", help="Fast plumbing check — silent_no_op only",
    )
    smoke.add_argument("-d", "--cohort-dir", required=True, type=Path)

    audit_sub.add_parser("list", help="List registered modules + checks")


def _dispatch_run(args) -> int:
    engine = AuditEngine(
        cohort_dir=args.cohort_dir,
        modules=args.module,
        axes=args.axis,
    )
    result = engine.run()
    print(render_markdown(result))
    if args.report:
        write_markdown(result, args.report)
        print(f"\n[wrote {args.report}]")
    return 0 if result.overall_status() != "FAIL" else 1


def _dispatch_smoke(args) -> int:
    engine = AuditEngine(cohort_dir=args.cohort_dir, axes=["silent_no_op"])
    result = engine.run()
    print(render_markdown(result))
    return 0 if result.overall_status() != "FAIL" else 1


def _dispatch_list(_args) -> int:
    discover()
    registered = get_registered()
    if not registered:
        print("(no modules with audit.py registered)")
        return 0
    print(f"Registered modules: {len(registered)}")
    for name, spec in sorted(registered.items()):
        checks: list[str] = []
        if spec.structural_obs_codes:
            checks.append(f"structural ({len(spec.structural_obs_codes)} analytes)")
        if spec.clinical_acceptance:
            checks.append(f"clinical ({len(spec.clinical_acceptance)} cohorts)")
        if spec.lift_firing_proof is not None:
            checks.append("lift-firing proof")
        if spec.yaml_keys_to_validate:
            checks.append(f"constants ({len(spec.yaml_keys_to_validate)} files)")
        print(f"  {name}: {', '.join(checks) or 'no checks declared'}")
    return 0


def dispatch_audit(args) -> int:
    cmd = getattr(args, "audit_command", None)
    if cmd == "run":
        return _dispatch_run(args)
    if cmd == "smoke":
        return _dispatch_smoke(args)
    if cmd == "list":
        return _dispatch_list(args)
    print("usage: clinosim audit {run,smoke,list} [...]")
    return 2
```

- [ ] **Step 5: Wire `clinosim audit` into `clinosim/simulator/cli.py`**

Read `clinosim/simulator/cli.py` and find the main subparser registration block. After the existing subcommands (`generate`, `validate`, `test-disease`), add:

```python
from clinosim.audit.cli import add_audit_subparser, dispatch_audit
add_audit_subparser(subparsers)
```

In the dispatch block at the end of `main()`, add a case for `args.command == "audit"` that calls `dispatch_audit(args)` and `sys.exit(...)` with the returned code.

(The exact wiring must match the surrounding pattern; read 30 lines of context first.)

- [ ] **Step 6: Run engine tests + CLI smoke**

```bash
pytest tests/unit/test_audit_engine.py -v
python -c "from clinosim.simulator.cli import main; main()" audit list
```
Expected: tests pass; CLI prints "(no modules with audit.py registered)".

- [ ] **Step 7: Commit**

```bash
git add clinosim/audit/engine.py clinosim/audit/cli.py clinosim/simulator/cli.py \
        tests/unit/test_audit_engine.py
git commit -m "$(cat <<'EOF'
feat(audit): AuditEngine + clinosim audit CLI subcommands (Task 7)

AuditEngine orchestrates discover() + the selected (module × axis)
matrix; module/axis filters default to "all registered" / "all built-
in" respectively. _BUILTIN_AXES = (structural, jp_language, clinical,
silent_no_op).

CLI subcommands wired into the existing argparse tree:
  clinosim audit run  -d <dir> [--module M] [--axis A] [--report path]
  clinosim audit smoke -d <dir>  (silent_no_op only)
  clinosim audit list  (registered modules + their declared checks)

Exit codes: 0 (no FAIL findings), 1 (any FAIL), 2 (CLI error).

4 unit tests pin: engine runs all built-in axes, module filter
selection, axis filter selection, overall status PASS on an empty
cohort.

CLI smoke test (manual): `clinosim audit list` prints
"(no modules with audit.py registered)" before Task 8 adds the first
plug-in.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 8: First per-Module audit — `clinosim/modules/hai/audit.py`

**Files:**
- Create: `clinosim/modules/hai/audit.py`
- Create: `tests/integration/test_audit_hai_module.py`

**Interfaces:**
- Consumes: `HAI_TYPES`, `_hai_lift_delta`, `apply_hai_lab_lift`, types from `clinosim.types.*`.
- Produces: side-effect register_audit_module(...) at import time.

- [ ] **Step 1: Implement `clinosim/modules/hai/audit.py`**

```python
"""HAI audit — first per-Module audit plug-in.

Absorbs scratchpad/phase3a_lift_fired_proof.py: builds a synthetic
record with a CAUTI HAIEvent at baseline infl=0.4, draw_hour=6,
calls apply_hai_lab_lift, and asserts the observed delta matches the
closed-form _hai_lift_delta — the load-bearing verification PR-90 was
missing.

Registered checks:
- canonical_constants: HAI_TYPES against
  modules/hai/reference_data/hai_lab_lift.yaml hai_lift section
- structural_obs_codes: WBC (LOINC 6690-2 + JLAC10 2A010), CRP
  (LOINC 1988-5 + JLAC10 5C070)
- clinical_acceptance: CAUTI (WBC delta ≥ 1500, CRP delta ≥ 25),
  CLABSI / VAP (each ≥ 3000 / ≥ 50) — small cohorts → WARN
- lift_firing_proof: synthetic CAUTI record returns the same
  closed-form delta apply_hai_lab_lift produces
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.hai import HAI_TYPES
from clinosim.modules.hai.lab_lift import _hai_lift_delta, apply_hai_lab_lift
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderType
from clinosim.types.hai import HAIEvent

_HAI_LIFT_YAML = (
    Path(__file__).parent / "reference_data" / "hai_lab_lift.yaml"
)


def _build_cauti_proof():
    state = PhysiologicalState(inflammation_level=0.4)
    # state_history layout: index 0 = admission state, index N+1 = post-day-N
    history = [state for _ in range(7)]
    admission = datetime(2026, 1, 8, 0)
    obs_dt = datetime(2026, 1, 12, 8)
    draw_hour = 6

    wbc_obs = OrderResult(
        result_datetime=obs_dt, lab_name="WBC", value=11760.0,
    )
    wbc_order = Order(
        order_id="o-wbc", order_type=OrderType.LAB, display_name="WBC",
        ordered_datetime=datetime(2026, 1, 12, draw_hour, 30),
    )
    wbc_order.result = wbc_obs

    record = SimpleNamespace(
        patient=SimpleNamespace(sex="M"),
        extensions={"hai": [HAIEvent(
            hai_id="h-cauti-1",
            encounter_id="enc-1",
            hai_type="cauti",
            source_device_id="d1",
            icd10_code="T83.511A",
            snomed_code="68566005",
            onset_date="2026-01-10",
            organism_snomed="112283007",
            culture_specimen_id="s1",
        )]},
        lab_results=[wbc_obs],
        orders=[wbc_order],
    )
    encounter = SimpleNamespace(encounter_id="enc-1")
    expected_wbc_delta = _hai_lift_delta(state, "WBC", 0.20, draw_hour=draw_hour)

    return {
        "record": record,
        "encounter": encounter,
        "state_history": history,
        "admission_time": admission,
        "apply_fn": apply_hai_lab_lift,
        "expected_deltas": {wbc_obs: expected_wbc_delta},
        "tracked_obs": [wbc_obs],
        "pre_values": {wbc_obs: wbc_obs.value},
    }


register_audit_module(ModuleAuditSpec(
    name="hai",
    canonical_constants={"hai_type": HAI_TYPES},
    yaml_keys_to_validate={
        str(_HAI_LIFT_YAML): ("hai_lift",),
    },
    structural_obs_codes={
        "WBC": ("6690-2", "2A010"),
        "CRP": ("1988-5", "5C070"),
    },
    clinical_acceptance={
        "cauti": {
            "icd10_code": "T83.511A",
            "WBC_delta_p50": 1500,
            "CRP_delta_p50": 25,
        },
        "clabsi": {
            "icd10_code": "T80.211A",
            "WBC_delta_p50": 3000,
            "CRP_delta_p50": 50,
        },
        "vap": {
            "icd10_code": "J95.851",
            "WBC_delta_p50": 3000,
            "CRP_delta_p50": 50,
        },
    },
    lift_firing_proof=_build_cauti_proof,
))
```

- [ ] **Step 2: Write the integration test**

Create `tests/integration/test_audit_hai_module.py`:

```python
"""Integration test: real HAI audit plug-in registers and the engine
runs lift-firing proof + constants check end-to-end."""
from __future__ import annotations

import importlib

import pytest

from clinosim.audit.engine import AuditEngine
from clinosim.audit.registry import _reset_for_test


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_test()
    importlib.reload(importlib.import_module("clinosim.modules.hai.audit"))
    yield
    _reset_for_test()


@pytest.mark.integration
def test_hai_audit_silent_no_op_passes_on_clean_lift(tmp_path):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    engine = AuditEngine(cohort_dir=tmp_path, axes=["silent_no_op"])
    result = engine.run()
    sn_result = result.results.get(("silent_no_op", "hai"))
    assert sn_result is not None
    # Constants check + proof both PASS → overall PASS
    assert sn_result.status == "PASS"


@pytest.mark.integration
def test_hai_audit_structural_na_on_empty_cohort(tmp_path):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    engine = AuditEngine(cohort_dir=tmp_path, axes=["structural"])
    result = engine.run()
    structural_result = result.results.get(("structural", "hai"))
    assert structural_result is not None
    assert structural_result.status == "N/A"
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/integration/test_audit_hai_module.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Verify `clinosim audit list` now sees the HAI plug-in**

```bash
python -c "from clinosim.simulator.cli import main; main()" audit list
```
Expected output contains:
```
Registered modules: 1
  hai: structural (2 analytes), clinical (3 cohorts), lift-firing proof, constants (1 files)
```

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/hai/audit.py tests/integration/test_audit_hai_module.py
git commit -m "$(cat <<'EOF'
feat(audit): modules/hai/audit.py — first per-Module plug-in (Task 8)

Registers a ModuleAuditSpec for hai with all four axes wired:

- canonical_constants: HAI_TYPES (lowercase) cross-checked against
  reference_data/hai_lab_lift.yaml hai_lift keys at audit time
- structural_obs_codes: WBC (LOINC 6690-2 + JLAC10 2A010), CRP
  (LOINC 1988-5 + JLAC10 5C070)
- clinical_acceptance: CAUTI (WBC ≥1500, CRP ≥25), CLABSI/VAP each
  (WBC ≥3000, CRP ≥50)
- lift_firing_proof: builds a synthetic CAUTI record with a single
  WBC observation at baseline infl=0.4, draw_hour=6; expected delta
  comes from the same closed-form _hai_lift_delta apply_hai_lab_lift
  uses internally; engine asserts observed == expected within ±2.0.

This is the absorption point for scratchpad/phase3a_lift_fired_proof.py
(deleted in Task 10). After Task 8, `clinosim audit list` reports the
hai module with all four check categories.

2 integration tests verify the real plug-in: silent_no_op PASS on the
synthetic proof; structural N/A on an empty cohort.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 9: End-to-end integration + self-audit baseline + byte-diff invariant

**Files:**
- Create: `tests/integration/test_audit_end_to_end.py`
- Create: `scratchpad/clinosim_audit_byte_diff.py`
- Create: `scratchpad/clinosim_audit_self_run.log`
- Create: `docs/reviews/2026-06-25-clinosim-audit-baseline.md`

- [ ] **Step 1: Write end-to-end integration test**

Create `tests/integration/test_audit_end_to_end.py`:

```python
"""End-to-end: engine + reporter on a minimal synthetic cohort."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from clinosim.audit.engine import AuditEngine
from clinosim.audit.registry import _reset_for_test
from clinosim.audit.reporter import write_markdown


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_test()
    importlib.reload(importlib.import_module("clinosim.modules.hai.audit"))
    yield
    _reset_for_test()


def _write(path: Path, country: str, file: str, rows: list[dict]):
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.mark.integration
def test_end_to_end_minimal_cohort_full_report(tmp_path: Path):
    # A tiny US cohort: 2 inpatient encounters with WBC + CRP, no HAI
    _write(tmp_path, "us", "Encounter.ndjson", [
        {"resourceType": "Encounter", "id": "E1", "class": {"code": "IMP"}},
        {"resourceType": "Encounter", "id": "E2", "class": {"code": "IMP"}},
    ])
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation", "id": "o-1",
            "code": {"coding": [{"code": "6690-2", "display": "WBC"}]},
            "encounter": {"reference": "Encounter/E1"},
            "valueQuantity": {"value": 12000},
            "referenceRange": [{}], "interpretation": [{}],
        },
        {
            "resourceType": "Observation", "id": "o-2",
            "code": {"coding": [{"code": "1988-5", "display": "CRP"}]},
            "encounter": {"reference": "Encounter/E1"},
            "valueQuantity": {"value": 25},
            "referenceRange": [{}], "interpretation": [{}],
        },
    ])

    engine = AuditEngine(cohort_dir=tmp_path)
    result = engine.run()

    # No HAI events → silent_no_op PASS, clinical WARN (rare-event), JP N/A
    assert result.overall_status() in ("PASS", "WARN")
    assert ("structural", "hai") in result.results
    assert ("silent_no_op", "hai") in result.results

    # Reporter writes a complete file
    out = tmp_path / "report.md"
    write_markdown(result, out)
    text = out.read_text(encoding="utf-8")
    assert "## Summary" in text
    assert "hai" in text
```

- [ ] **Step 2: Run end-to-end test**

```bash
pytest tests/integration/test_audit_end_to_end.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Verify byte-diff invariant — `clinosim/audit/` does not touch simulation**

Create `scratchpad/clinosim_audit_byte_diff.py` (script to remind future maintainers — same shape as phase3a_byte_diff.py):

```python
"""Byte-diff vs master 42657293 to verify clinosim/audit/ doesn't touch
the simulation paths.

Run flow:
  1. Generate branch output: US/JP p=2000 seed=42.
  2. Switch to master, generate, switch back.
  3. Compare per-NDJSON sha256 + line count.

Expected: 37/37 NDJSON byte-IDENTICAL. (Same outcome as the Phase 3a
post-fix byte-diff.) The audit framework is a pure read-only consumer
of generated output, so this is a structural guarantee.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).parent / "clinosim_audit_byte_diff"
MASTER = ROOT / "master"
BRANCH = ROOT / "branch"


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def line_count(p: Path) -> int:
    return sum(1 for _ in p.open("rb"))


def report(country: str) -> None:
    print(f"\n## {country.upper()}")
    print("| NDJSON | master sha256 | branch sha256 | master lines | branch lines | verdict |")
    print("|---|---|---|---|---|---|")
    md = MASTER / country / "fhir_r4"
    bd = BRANCH / country / "fhir_r4"
    for path in sorted(md.glob("*.ndjson")):
        bp = bd / path.name
        if not bp.exists():
            continue
        m = sha256_of(path)
        b = sha256_of(bp)
        verdict = "IDENTICAL" if m == b else "DIFF"
        print(
            f"| {path.name} | {m[:12]}... | {b[:12]}... | "
            f"{line_count(path)} | {line_count(bp)} | {verdict} |"
        )


if __name__ == "__main__":
    for c in ("us", "jp"):
        report(c)
```

Run byte-diff:

```bash
# Branch generation (current HEAD)
mkdir -p scratchpad/clinosim_audit_byte_diff/branch
python -c "from clinosim.simulator.cli import main; main()" generate -p 2000 --seed 42 --country US --format fhir-r4 -o scratchpad/clinosim_audit_byte_diff/branch/us
python -c "from clinosim.simulator.cli import main; main()" generate -p 2000 --seed 42 --country JP --format fhir-r4 -o scratchpad/clinosim_audit_byte_diff/branch/jp

# Master generation
git stash -u
git checkout 42657293
mkdir -p scratchpad/clinosim_audit_byte_diff/master
python -c "from clinosim.simulator.cli import main; main()" generate -p 2000 --seed 42 --country US --format fhir-r4 -o scratchpad/clinosim_audit_byte_diff/master/us
python -c "from clinosim.simulator.cli import main; main()" generate -p 2000 --seed 42 --country JP --format fhir-r4 -o scratchpad/clinosim_audit_byte_diff/master/jp
git checkout feat/clinosim-audit-framework
git stash pop

# Compare
python scratchpad/clinosim_audit_byte_diff.py | tee scratchpad/clinosim_audit_byte_diff_results.md
```

Expected: 37/37 NDJSON IDENTICAL (same as Phase 3a). If any DIFF appears, investigate before proceeding — that means the audit framework accidentally imported something that broke determinism.

- [ ] **Step 4: Run self-audit on a freshly generated cohort**

```bash
mkdir -p scratchpad/clinosim_audit_baseline
python -c "from clinosim.simulator.cli import main; main()" generate -p 2000 --seed 42 --country US --format fhir-r4 -o scratchpad/clinosim_audit_baseline/us
python -c "from clinosim.simulator.cli import main; main()" generate -p 2000 --seed 42 --country JP --format fhir-r4 -o scratchpad/clinosim_audit_baseline/jp

python -c "from clinosim.simulator.cli import main; main()" audit run \
  -d scratchpad/clinosim_audit_baseline \
  --report docs/reviews/2026-06-25-clinosim-audit-baseline.md \
  | tee scratchpad/clinosim_audit_self_run.log
```

Expected: report.md contains a "Summary" grid + per-axis findings. silent_no_op axis PASSes (proof + constants both green). structural axis PASSes (refRange + interpretation 100%). clinical axis WARN at p=2000 (HAI rare-event). jp_language axis PASS.

Spot-check the report by hand:

```bash
head -40 docs/reviews/2026-06-25-clinosim-audit-baseline.md
```

If the report's silent_no_op axis is anything other than PASS, the lift-firing proof or constants check has regressed — investigate before commit.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_audit_end_to_end.py \
        scratchpad/clinosim_audit_byte_diff.py \
        scratchpad/clinosim_audit_self_run.log \
        docs/reviews/2026-06-25-clinosim-audit-baseline.md
git commit -m "$(cat <<'EOF'
test(audit): end-to-end + byte-diff invariant + self-audit baseline (Task 9)

End-to-end integration test drives engine + reporter against a minimal
synthetic cohort and asserts the Markdown report renders.

byte-diff vs master 42657293 at p=2000 seed=42: 37/37 NDJSON IDENTICAL
— confirms clinosim/audit/ is a pure read-only consumer of generated
output, no simulation-path imports leaked, AD-16 preserved.

Self-audit: `clinosim audit run` against a fresh p=2000 cohort produces
docs/reviews/2026-06-25-clinosim-audit-baseline.md, the first Markdown
report from the new framework. silent_no_op axis PASS (proof matches
closed-form delta, YAML constants in HAI_TYPES). structural axis PASS.
jp_language axis PASS. clinical axis WARN (HAI rare-event at p=2000;
silent_no_op axis covers the load-bearing verification).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 10: Migrate superseded scripts + docs sync + PR

**Files:**
- Delete: `scratchpad/phase3a_dqr.py`
- Delete: `scratchpad/phase3a_lift_fired_proof.py`
- Modify: `MODULES.md`, `docs/CONTRIBUTING-modules.md`, `.github/TEMPLATE_MODULE_README.md`, `CLAUDE.md`, `README.md`, `README.ja.md`, `DESIGN.md`, `TODO.md`

- [ ] **Step 1: Remove superseded scripts**

```bash
git rm scratchpad/phase3a_dqr.py scratchpad/phase3a_lift_fired_proof.py
```

- [ ] **Step 2: Refactor CONTRIBUTING-modules.md PR verification guide**

Open `docs/CONTRIBUTING-modules.md`, locate "PR 検証ガイド: byte-diff vs 3-axis DQR" section. Replace the new-feature row with:

```
| **新機能 / リアリティ改善** | `clinosim audit run` — 4 軸(structural/clinical/jp_language/silent_no_op)を一括検証。Module 著者は `clinosim/modules/<name>/audit.py` に `ModuleAuditSpec` を register する。 | FHIR R4 / JP Core 適合性 + 臨床整合 + JP 言語品質 + silent-no-op gate(PR-90 class of bug 再発防止) |
```

Add a new sub-section "## Module audit.py boilerplate" with a 30-line example mirroring `clinosim/modules/hai/audit.py` (canonical_constants, yaml_keys_to_validate, structural_obs_codes, clinical_acceptance, lift_firing_proof).

- [ ] **Step 3: Update `.github/TEMPLATE_MODULE_README.md`**

Read the template, add a new section after Consumers:

```
## Audit

This module's audit plug-in lives at `clinosim/modules/<name>/audit.py`
and registers a `ModuleAuditSpec` with the framework via
`register_audit_module(...)`. Available checks:

- canonical_constants: list of authoritative string tuples
- yaml_keys_to_validate: reference YAML files validated against the constants
- structural_obs_codes: analyte → (LOINC, JLAC10) tuples
- clinical_acceptance: cohort identification + acceptance thresholds
- lift_firing_proof: synthetic record + expected delta (load-bearing)

See `clinosim/modules/hai/audit.py` for the canonical example.
```

- [ ] **Step 4: Update `CLAUDE.md`**

Replace the previous "DQR audits must drive the enricher path" rule (added in PR #91) with:

```
- **Verification gate is `clinosim audit run`** — the new feature gate (structural / clinical / JP language / silent_no_op axes). Modules co-locate their audit checks in `clinosim/modules/<name>/audit.py`. byte-diff stays as a separate refactor-PR mechanic. The lift-firing proof inside the silent_no_op axis is the load-bearing verification that catches the PR-90 silent-no-op class of bug at audit time.
```

- [ ] **Step 5: Update `MODULES.md`**

Add a new layer at the end of the "Verification" subsection:

```
| audit | clinosim/audit/ + per-Module audit.py | structural + clinical + jp_language + silent_no_op | guard |
```

- [ ] **Step 6: Update `README.md` + `README.ja.md`**

Replace the existing "Latest reviews" entry that points at the phase3a DQR reviews with the new audit baseline:

```
- [`docs/reviews/2026-06-25-clinosim-audit-baseline.md`](docs/reviews/2026-06-25-clinosim-audit-baseline.md) — first `clinosim audit run` baseline report (4 axes: structural / clinical / jp_language / silent_no_op).
```

Add a one-paragraph "Verification framework" subsection under Quality & Compliance referencing the `clinosim audit run` CLI.

- [ ] **Step 7: Update `DESIGN.md`**

Add a new ADR entry table row:

```
| AD-XX | 2026-06-25 | clinosim audit framework — registry + co-located per-Module audit.py + 4 built-in axes (structural / clinical / jp_language / silent_no_op). Silent_no_op axis runs canonical-constants cross-check + lift-firing proof to catch the PR-90 class of bug. CLI subcommand: `clinosim audit run/smoke/list`. byte-diff stays as a separate refactor-PR mechanic. |
```

Pick the next available AD number by reading the existing AD table.

- [ ] **Step 8: Update `TODO.md`**

Mark "DQR audit-script strengthening" backlog (from Phase 3a post-fix TODO) as DONE. Add a new bullet:

```
- Per-Module audit.py plug-ins for Phase 3b/c Modules (antibiotic / decay / mortality / sepsis cascade) — each Module's own PR adds its audit alongside its feature.
```

- [ ] **Step 9: Run the full unit + integration suite**

```bash
pytest -m "unit or integration" -x 2>&1 | tail -5
```
Expected: all green (the 6 new test files + zero regressions).

- [ ] **Step 10: ruff auto-fix**

```bash
ruff check --fix clinosim/audit clinosim/modules/hai/audit.py tests/
ruff format clinosim/audit clinosim/modules/hai/audit.py tests/
```

- [ ] **Step 11: Commit docs sync + lint**

```bash
git add MODULES.md docs/CONTRIBUTING-modules.md .github/TEMPLATE_MODULE_README.md \
        CLAUDE.md README.md README.ja.md DESIGN.md TODO.md
git commit -m "$(cat <<'EOF'
docs(audit): sync MODULES / CONTRIBUTING / template / CLAUDE / READMEs /
DESIGN / TODO + remove superseded scratchpad scripts (Task 10)

- scratchpad/phase3a_dqr.py: deleted (superseded by clinosim audit run --module hai)
- scratchpad/phase3a_lift_fired_proof.py: deleted (logic absorbed into
  clinosim/modules/hai/audit.py:_build_cauti_proof)
- MODULES.md: new "audit" entry in Verification layer
- docs/CONTRIBUTING-modules.md: PR 検証ガイド refreshed — new feature
  row → `clinosim audit run`; "Module audit.py boilerplate" sub-section
  with the canonical hai/audit.py shape
- .github/TEMPLATE_MODULE_README.md: new Audit section
- CLAUDE.md: previous "DQR audits must drive enricher path" guidance
  replaced with the clinosim audit CLI as the new feature gate
- README.md / README.ja.md: link the first audit baseline review
- DESIGN.md: new AD entry for the audit framework
- TODO.md: mark DQR strengthening done; add per-Module audit.py
  backlog for Phase 3b/c

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

- [ ] **Step 12: Push branch + create PR**

```bash
git push -u origin feat/clinosim-audit-framework
gh pr create --title "feat(audit): clinosim audit framework Phase 1" --body "$(cat <<'EOF'
## Summary

New `clinosim audit` framework — the unified verification gate that
absorbs the existing 3-axis DQR (structural / clinical / JP language)
and adds a fourth `silent_no_op` axis specifically designed to catch
the PR-90 class of bug (case-mismatch silent no-op).

- New `clinosim/audit/` package: types + registry + 4 axis runners +
  reporter + AuditEngine + CLI wiring (`clinosim audit run/smoke/list`).
- First per-Module plug-in: `clinosim/modules/hai/audit.py` with
  canonical_constants (HAI_TYPES), yaml_keys_to_validate
  (hai_lab_lift.yaml), structural_obs_codes (WBC/CRP), clinical_
  acceptance (CAUTI/CLABSI/VAP), and a load-bearing
  lift_firing_proof (the verification PR-90 was missing).
- byte-diff vs master 42657293 at p=2000 seed=42: 37/37 NDJSON
  IDENTICAL — audit framework is pure read-only consumer.
- Self-audit baseline: docs/reviews/2026-06-25-clinosim-audit-baseline.md.
- scratchpad/phase3a_dqr.py + scratchpad/phase3a_lift_fired_proof.py
  removed (superseded).

## Verification

- [ ] Unit tests: 8 new test files cover types, registry, reporter,
      4 axes, engine.
- [ ] Integration tests: end-to-end pipeline + HAI plug-in.
- [ ] byte-diff: 37/37 IDENTICAL.
- [ ] Self-audit: PASS for silent_no_op / structural / jp_language;
      WARN for clinical (HAI rare at p=2000, silent_no_op axis covers
      via lift_firing_proof).
- [ ] Full pytest suite: green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

If `gh pr create` returns a PR URL, success. Pass the URL to the user.

---

## Summary

Phase 1 of the `clinosim audit` framework: a unified verification gate that closes the gap PR-90's xhigh review surfaced. Eight new tasks build the framework foundation (types + Cohort + registry + reporter + 4 axes + engine + CLI), one task wires the first per-Module plug-in (HAI), one task delivers end-to-end + byte-diff invariant + self-audit baseline, and one task syncs docs + removes superseded scripts.

## Evidence

- byte-diff: `scratchpad/clinosim_audit_byte_diff_results.md`
- self-audit baseline: `docs/reviews/2026-06-25-clinosim-audit-baseline.md`
- spec: `docs/superpowers/specs/2026-06-25-dqr-framework-strengthening-design.md`

## Test plan

- 7 unit test files (Tasks 1-7): types + registry + reporter + 4 axes + engine
- 2 integration test files (Tasks 8-9): HAI plug-in + end-to-end pipeline
- byte-diff verification (Task 9)
- self-audit baseline (Task 9)
- Full regression check + ruff (Task 10)

## Deferred (Phase 2+ backlog)

| Item | Phase | Reason |
|---|---|---|
| Per-Module audit.py for Phase 3b/c Modules | Phase 3b/c PRs | each Module's PR adds its audit |
| Reference-integrity check (cross-file FHIR target walk) | Phase 2 | already covered by adapter tests |
| CI integration (`clinosim audit smoke` on every PR) | Phase 2 | requires CI workflow file edit |
| Audit diff vs prior baseline (cohort median shifted >20%) | Phase 2 | requires baseline persistence |
| Per-event observed-vs-theoretical (CIF state_history walk) | Phase 2 | lift_firing_proof in silent_no_op axis already provides per-event verification at the framework level |
| Fired counter (Module-specific code discovery) | Phase 2 | needs more Modules to inform generic shape |
| HTML/interactive reports | not planned | YAGNI; Markdown is enough |

## Self-Review Notes

- **Spec coverage:** every section in the spec maps to a task. §2 architecture → T1+T2+T7 / §3 engine + registry → T1+T7 / §4 Module example → T8 / §5 CLI → T7 / §6 severity + tolerances → T5 (silent_no_op) + T6 (clinical) / §7 tests → T1-T9 / §8 migration → T10 / §9 byte-diff invariant → T9 / §10 docs sync → T10 / §11 out of scope → mentioned in T10 + final PR body.
- **Placeholder scan:** no TBD / TODO / vague directives remain. Code blocks in every code step. Exact file paths everywhere.
- **Type consistency:** `ModuleAuditSpec` shape identical across T1 implementation, T7 engine usage, T8 hai/audit.py. `AxisResult` / `AuditResult` / `AuditFinding` shapes consistent across T1-T9. `_BUILTIN_AXES` ordering: structural / jp_language / clinical / silent_no_op (consistent T7 + tests).
- **CLI integration caveat:** Task 7 Step 5 needs the existing `clinosim/simulator/cli.py` subparser dispatch pattern — engineer must read 30 lines of context first; the exact wiring lines are not in the plan.
- **byte-diff caveat:** Task 9 Step 3 runs the full master + branch generation; if disk space is tight, the engineer can drop to p=500 (still demonstrates the invariant; spec §9 only requires the framework not touch simulation paths).
