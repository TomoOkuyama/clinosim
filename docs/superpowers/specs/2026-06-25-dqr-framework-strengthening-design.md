# clinosim audit: Phase 1 — DQR framework strengthening

**Date**: 2026-06-25
**Author**: Tomo Okuyama (with Claude Opus 4.7)
**Status**: APPROVED — ready for plan
**Predecessor**: PR #90 (Phase 3a HAI lift) + xhigh code-review hardening (commit `4dd36a55`)
**Successor candidates**: per-Module audit plug-ins for Phase 3b (antibiotic empirical / WBC-CRP decay) + Phase 3c (mortality / sepsis cascade)

---

## 1. Motivation

PR #90 (Phase 3a HAI WBC + CRP lift) was opened with all three existing
verification gates green:

- **691 unit + integration tests PASS** (canary tests constructed `HAIEvent`
  with UPPERCASE `hai_type`, accidentally matching the YAML keys — no
  end-to-end enricher-path coverage).
- **byte-diff 37/37 NDJSON IDENTICAL** at p=2000 (HAI is CDC NHSN
  rare-event; 0 HAI events at p=2000 → lift code never exercised).
- **3-axis DQR PASS** at p=10k US + p=5k JP, including a CAUTI cohort
  delta of +2,135 WBC / +50.4 CRP that met pre-registered acceptance
  thresholds.

A workflow-backed xhigh code review then surfaced 13 confirmed + 2
plausible bugs. The critical one: **the YAML had UPPERCASE `hai_type`
keys (`CLABSI`/`VAP`/`CAUTI`) while the enricher writes lowercase
(`clabsi`/`cauti`/`vap`), so `lift_table.get(ev.hai_type, 0.0)` always
returned 0.0 in production**. The entire Phase 3a lift was a silent
no-op. The DQR's +2,135 WBC / +50.4 CRP CAUTI delta was a **UTI
disease-state confounder** (UTI patients have elevated WBC + CRP
regardless of any HAI lift), not the lift code.

The post-PR-90 hardening commit (`4dd36a55`) fixed all 15 findings, but
the underlying gap remains: **none of clinosim's existing verification
gates can catch "fully-implemented feature, silently no-op in
production" bugs once the cohort-level metric is plausibly confounded
with disease state**.

This spec defines a unified `clinosim audit` framework that absorbs the
existing 3-axis DQR scripts and adds a fourth axis — **silent_no_op
gate** — specifically designed to catch the PR-90 class of bug. The
framework is the new primary gate for "new feature / realism
improvement" PRs.

### Scope decisions (from brainstorming 2026-06-25)

| Decision | Choice | Rationale |
|---|---|---|
| Framework location | `clinosim/audit/` package + Module-agnostic generic engine | Promotes verification from `scratchpad/` to first-class subsystem. New Modules inherit the framework for free. |
| Run interface | CLI command `clinosim audit` | Discoverable, parallel to `clinosim generate` / `clinosim validate`. |
| Scope vs existing DQR | **Super-set** — absorbs structural + clinical + JP language axes, adds silent_no_op axis | Single ship-ready gate; per-event theoretical verification cohabits with cohort baseline so disease confound is detectable inside one report. |
| Check ownership | Co-located per-Module `clinosim/modules/<name>/audit.py` | Module owner maintains audit checks alongside the feature. Adding a new HAI type / analyte = one PR touches module + audit together. Aligns with CLAUDE.md "module independence" rule. |
| byte-diff scope | **Out** (separate refactor-PR mechanic) | byte-diff is for "no behavior change" verification; mixing it with audit would require master regeneration logic inside the CLI. |

---

## 2. Architecture

```
┌─ clinosim/audit/ (framework) ─────────────────────────────────┐
│  cli.py            `clinosim audit run` entry                 │
│  engine.py         AuditEngine.run() orchestration            │
│  registry.py       register_audit_module() (called at import) │
│  types.py          AuditResult / AuditFinding / AuditAxis     │
│  reporter.py       Markdown rendering → docs/reviews/         │
│  axes/                                                        │
│    structural.py   FHIR resource integrity                    │
│    clinical.py     cohort baselines + per-event theoretical   │
│    jp_language.py  display localization                       │
│    silent_no_op.py fired counter / constants / firing proof   │
└───────────────────────────────────────────────────────────────┘
                              ↑ imports
┌─ clinosim/modules/<name>/audit.py (per-Module plug-in) ───────┐
│  register_audit_module(name="hai", ...)                       │
│  - canonical_constants                                        │
│  - yaml_keys_to_validate                                      │
│  - cohort_filter                                              │
│  - per_event_check  (closed-form theoretical delta callable)  │
│  - lift_firing_proof  (synthetic record builder)              │
│  - structural_obs_codes                                       │
│  - clinical_acceptance                                        │
└───────────────────────────────────────────────────────────────┘
                              ↑ called by
┌─ user invocation ─────────────────────────────────────────────┐
│  $ clinosim audit run -d ./output                             │
│    → AuditEngine.discover() (import all modules/<name>/audit) │
│    → engine.run(cohort, axes=["structural","clinical",        │
│                                "jp_language","silent_no_op"]) │
│    → reporter.render(result) → markdown report                │
│    → exit code = 0 if all PASS, 1 if any FAIL                 │
└───────────────────────────────────────────────────────────────┘
```

**Invariants**:
- Modules without `audit.py` are silently skipped (no audit for nothing).
- An axis with no per-Module data is reported as "N/A" (not PASS — to make
  missing coverage visible).
- The CLI never modifies generated output; it only reads.
- The CLI never network-fetches code-system data; all authoritative
  lookups go through `clinosim.codes` which is already offline.

---

## 3. Module-agnostic engine

### 3.1 `clinosim/audit/registry.py`

```python
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class ModuleAuditSpec:
    """The per-Module contract. Filled by each modules/<name>/audit.py.

    Every field is optional — the audit engine treats absent fields as
    "this axis has no Module-specific data" and skips with N/A status."""
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
    """Register a module's audit. Last-wins (test override friendly)."""
    _MODULES[spec.name] = spec

def discover() -> None:
    """Walk clinosim/modules/*/audit.py and importlib.import_module each
    one. Import side-effects call register_audit_module(). Modules
    without an audit.py file are silently skipped. Repeated calls are
    idempotent (importlib caches and register_audit_module is last-wins).
    """
    from importlib import import_module
    from pathlib import Path
    modules_root = Path(__file__).parent.parent / "modules"
    for audit_file in sorted(modules_root.glob("*/audit.py")):
        module_name = audit_file.parent.name
        import_module(f"clinosim.modules.{module_name}.audit")


def get_registered() -> dict[str, ModuleAuditSpec]:
    """Returns a copy of the current registry (for engine + tests)."""
    return dict(_MODULES)
```

### 3.2 `clinosim/audit/engine.py`

```python
_BUILTIN_AXES = ("structural", "clinical", "jp_language", "silent_no_op")
_AXIS_RUNNERS = {
    "structural": clinosim.audit.axes.structural.run,
    "clinical": clinosim.audit.axes.clinical.run,
    "jp_language": clinosim.audit.axes.jp_language.run,
    "silent_no_op": clinosim.audit.axes.silent_no_op.run,
}


class AuditEngine:
    def __init__(
        self,
        cohort_dir: Path,
        modules: list[str] | None = None,    # None → all registered
        axes: list[str] | None = None,       # None → all built-in
    ):
        self.cohort_dir = cohort_dir
        self.module_filter = modules
        self.axis_filter = axes

    def run(self) -> AuditResult:
        discover()
        registered = get_registered()
        selected = (
            registered if self.module_filter is None
            else {k: v for k, v in registered.items() if k in self.module_filter}
        )
        axes_to_run = self.axis_filter or list(_BUILTIN_AXES)

        result = AuditResult(
            cohort_dir=self.cohort_dir,
            modules=list(selected),
            axes=axes_to_run,
        )
        cohort = Cohort.open(self.cohort_dir)  # lazy NDJSON reader

        for axis in axes_to_run:
            for module_name, spec in selected.items():
                axis_result = _AXIS_RUNNERS[axis](spec, cohort)
                result.add(axis, module_name, axis_result)
        return result
```

### 3.3 Axis APIs (in `clinosim/audit/axes/`)

Each axis module exposes `def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult`. The `Cohort` object is a thin wrapper that lazily reads NDJSON files from a directory.

- `structural.py` — reads spec.structural_obs_codes, checks refRange + interpretation 100%, code system integrity, id uniqueness, reference integrity, display ≠ code.
- `clinical.py` — uses spec.cohort_filter to split HAI / non-HAI cohorts, computes baseline + cohort medians, compares against spec.clinical_acceptance. **Plus**: if spec.per_event_check is present, for each HAI cohort obs, computes theoretical delta from the per-day state snapshot (read from the CIF JSON physiological_states field) and compares against observed delta. Reports per-event histogram.
- `jp_language.py` — US output 非-ASCII = 0 in display fields; JP output display fields contain Japanese characters for the codes in spec.structural_obs_codes.
- `silent_no_op.py` — for each spec:
  1. **fired counter**: how many emissions of this Module's outputs were generated? (HAI events count from extensions["hai"], Condition codes, etc.) — 0 → axis FAIL with rare-event explanation only if cohort_size < threshold.
  2. **canonical constants cross-check**: for each (yaml_file, key_path), load YAML, verify every key is in spec.canonical_constants — FAIL if drift detected.
  3. **lift-firing proof**: call spec.lift_firing_proof() if present, run the result through the actual production code path, assert observed delta matches expected within tolerance.

---

## 4. Co-located per-Module audit.py

Example for `clinosim/modules/hai/audit.py`:

```python
from datetime import datetime
from types import SimpleNamespace

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.hai import HAI_TYPES
from clinosim.modules.hai.lab_lift import _hai_lift_delta, apply_hai_lab_lift
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderType
from clinosim.types.hai import HAIEvent


def _hai_cohort_filter(record):
    """Return the HAI type ("clabsi"/"cauti"/"vap") if this record has at
    least one HAI event, else None."""
    for ev in (record.extensions or {}).get("hai") or []:
        return ev.hai_type
    return None


def _make_synthetic_cauti_proof():
    """Build a minimal record with one CAUTI HAIEvent and expected delta.

    The audit engine will:
      1. Run apply_hai_lab_lift(record, ...) on the returned record.
      2. Compare obs.value before/after against expected_delta.
      3. FAIL the silent_no_op axis if observed - baseline != expected.

    This is the load-bearing verification PR-90 was missing."""
    state = PhysiologicalState(inflammation_level=0.4)
    history = [state] * 7
    admission = datetime(2026, 1, 8, 0)

    wbc_obs = OrderResult(
        result_datetime=datetime(2026, 1, 12, 8),
        lab_name="WBC", value=11760.0,
    )
    wbc_order = Order(
        order_id="o-wbc", order_type=OrderType.LAB, display_name="WBC",
        ordered_datetime=datetime(2026, 1, 12, 6, 30),
    )
    wbc_order.result = wbc_obs

    record = SimpleNamespace(
        patient=SimpleNamespace(sex="M"),
        extensions={"hai": [HAIEvent(
            hai_id="h1", encounter_id="enc-1", hai_type="cauti",
            source_device_id="d1", icd10_code="T83.511A",
            snomed_code="68566005", onset_date="2026-01-10",
            organism_snomed="112283007", culture_specimen_id="s1",
        )]},
        lab_results=[wbc_obs], orders=[wbc_order],
    )
    encounter = SimpleNamespace(encounter_id="enc-1")
    expected_wbc_delta = _hai_lift_delta(state, "WBC", 0.20, draw_hour=6)
    return {
        "record": record,
        "encounter": encounter,
        "state_history": history,
        "admission_time": admission,
        "apply_fn": apply_hai_lab_lift,
        "expected_deltas": {wbc_obs: expected_wbc_delta},
    }


register_audit_module(ModuleAuditSpec(
    name="hai",
    canonical_constants={"hai_type": HAI_TYPES},
    yaml_keys_to_validate={
        "modules/hai/reference_data/hai_lab_lift.yaml": ("hai_lift",),
    },
    cohort_filter=_hai_cohort_filter,
    per_event_check={
        "WBC": lambda state, lift, hour: _hai_lift_delta(state, "WBC", lift, hour),
        "CRP": lambda state, lift, hour: _hai_lift_delta(state, "CRP", lift, hour),
    },
    lift_firing_proof=_make_synthetic_cauti_proof,
    structural_obs_codes={
        "WBC": ("6690-2", "2A010"),
        "CRP": ("1988-5", "5C070"),
    },
    clinical_acceptance={
        "cauti": {"WBC_delta_p50": 1500, "CRP_delta_p50": 25},
        "clabsi": {"WBC_delta_p50": 3000, "CRP_delta_p50": 50},
        "vap": {"WBC_delta_p50": 3000, "CRP_delta_p50": 50},
    },
))
```

---

## 5. CLI design

```
clinosim audit <subcommand> [options]

Subcommands:
  run     Run the audit framework (full + Markdown report)
  smoke   Fast plumbing check (silent_no_op axis only, p=2000, no generate)
  list    List discovered Modules and their available checks

Examples:
  # Audit pre-generated cohort
  clinosim audit run -d ./output

  # Generate cohort + audit in one pass
  clinosim audit run --generate --us-pop 10000 --jp-pop 5000

  # Audit one Module
  clinosim audit run -d ./output --module hai

  # Audit one axis (fast silent_no_op gate)
  clinosim audit run -d ./output --axis silent_no_op

  # Write Markdown report
  clinosim audit run -d ./output --report docs/reviews/2026-XX-XX-<topic>-audit.md

  # CI plumbing smoke (fast, no large generation)
  clinosim audit smoke

Exit codes:
  0   all axes PASS
  1   one or more axes FAIL
  2   CLI error (bad args, missing cohort, etc.)
```

---

## 6. Failure modes + reporting

### Severity model

Each `AuditFinding` has a severity:

- **FAIL** — gate-blocking. Engine exit code = 1. Examples:
  - refRange + interpretation coverage < 100% on any analyte in
    `spec.structural_obs_codes`.
  - Any YAML key in `spec.yaml_keys_to_validate` is not present in the
    matching `spec.canonical_constants` set.
  - `lift_firing_proof` returns a record whose observed delta differs from
    the expected delta by more than the per-analyte tolerance: WBC ±2.0
    (integer precision + draw-hour rounding), CRP ±0.5.
  - Per-event observed-vs-theoretical: more than 25% of paired (observed,
    theoretical) deltas differ by more than 30% of the theoretical value.
  - `fired_counter = 0` AND `cohort_size >= rare_event_threshold` where
    `rare_event_threshold = 1 / per_day_risk * 200` (200× the expected
    inverse of the rare-event rate — i.e. at least 200 expected events,
    so 0 fired is unambiguous failure).
- **WARN** — surface but don't fail (exit code unchanged). Examples:
  - `fired_counter < 5` but cohort below `rare_event_threshold`: acceptable
    rare-event outcome, but mitigated only if `lift_firing_proof` also
    PASSes. If `lift_firing_proof` is absent for this Module, the WARN
    upgrades to FAIL.
  - cohort baseline shift > 20% vs prior baseline (Phase 2 backlog;
    Phase 1 emits this as INFO only since no prior baseline is stored).
- **INFO** — record for traceability, never affects exit code. Examples:
  per-event delta histogram, fired-counter per HAI type, cohort medians,
  proof-script numerical breakdown.

### Tolerances at a glance

| Check | Tolerance |
|---|---|
| Lift-firing proof — WBC observed vs expected | ±2.0 (integer precision + ±1 draw-hour effect) |
| Lift-firing proof — CRP observed vs expected | ±0.5 |
| Per-event observed-vs-theoretical — pair-level | within 30% of theoretical |
| Per-event observed-vs-theoretical — cohort-level | ≤ 25% of pairs outside per-pair tolerance |
| Fired counter — rare-event threshold | 200 × (1 / per_day_risk) — e.g. CDC NHSN 0.001/day → 200,000 device-days; never hit at production cohort sizes, so any fired_counter = 0 with cohort < 200k device-days is WARN, not FAIL |

### Markdown report shape

```markdown
# Audit Report — 2026-06-25T13:00:00Z

**Cohort**: US p=10000 + JP p=5000, seed=42
**Modules**: hai
**Axes**: structural, clinical, jp_language, silent_no_op

## Summary

| Module | structural | clinical | jp_language | silent_no_op |
|---|---|---|---|---|
| hai | PASS | PASS | PASS | PASS |

## hai (4/4 PASS)

### Axis 1: structural — PASS
- WBC n=39,292 (LOINC 6690-2 + JLAC10 2A010): refRange+interp 100%
- CRP n=16,533 (LOINC 1988-5 + JLAC10 5C070): refRange+interp 100%

### Axis 2: clinical — PASS
- Baseline (non-HAI inpatient) WBC p50=12,029, CRP p50=23.6
- CAUTI cohort (n=11): WBC delta_p50=+2,135 (need ≥1,500), CRP delta_p50=+50.4 (need ≥25) — PASS
- CLABSI/VAP rare-event (n<5) — WARN (mitigated by lift_firing_proof below)
- Per-event observed-vs-theoretical: median absolute error 8.3% for WBC, 5.1% for CRP

### Axis 3: jp_language — PASS
- US: 0 non-ASCII display violations
- JP: WBC display localised 4,957/4,957; CRP 1,957/1,957

### Axis 4: silent_no_op — PASS
- Fired counter: HAI events emitted = 4 (US) + 0 (JP, P(X=0)≈0.71 acceptable)
- Canonical constants cross-check: hai_lift.yaml keys ∈ HAI_TYPES ✓
- Lift-firing proof (CAUTI synthetic): WBC observed delta = expected (within 1.5)

## Conclusion: PR-ready (4/4 axes PASS)
```

---

## 7. Tests

### Unit tests (`tests/unit/test_audit_*.py`)

- `test_audit_registry.py` — register_audit_module + discover roundtrip; last-wins; no-module → empty
- `test_audit_engine.py` — engine selects modules + axes; missing data → N/A; aggregation
- `test_axis_structural.py` — refRange detection, code system, id uniqueness, ref integrity
- `test_axis_clinical.py` — cohort split, baseline medians, per-event theoretical comparison, tolerance bands
- `test_axis_jp_language.py` — US non-ASCII detection, JP localized display detection
- `test_axis_silent_no_op.py` — fired counter zero behavior, canonical constants drift detection, lift_firing_proof delta verification
- `test_reporter.py` — Markdown shape, severity classification

### Integration tests

- `test_audit_end_to_end.py` — run engine on a tiny synthetic FHIR cohort (p=50) end-to-end, assert all 4 axes produce expected output, Markdown report file written
- `test_audit_hai_module.py` — register the actual HAI module audit, run against a small generated cohort, assert lift_firing_proof PASSes and HAI cohort delta is detected (or N/A if 0 events at this scale)

### Regression
- Full pytest suite passes (existing 685 tests)
- `clinosim audit smoke` runs in < 30 seconds

---

## 8. Migration of existing scripts

| Existing | Action |
|---|---|
| `scratchpad/phase3a_dqr.py` | **Delete** — superseded by `clinosim audit run --module hai` |
| `scratchpad/phase3a_lift_fired_proof.py` | **Move** — `_make_synthetic_cauti_proof` becomes part of `modules/hai/audit.py` |
| `scratchpad/phase3a_byte_diff.py` | **Keep** — byte-diff is a separate refactor mechanic, not in audit scope |
| `scratchpad/phase3a_dqr*.log`, `*_results.md` | **Keep** (PR-90 evidence, historical) |
| `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review*.md` | **Keep** (PR-90 evidence) |
| `docs/CONTRIBUTING-modules.md` PR verification guide | **Refactor** — new feature row → `clinosim audit run` (was "3-axis DQR + lift-firing proof") |

---

## 9. byte-diff invariant

- `clinosim/audit/` is a new package; does not touch simulation paths.
- No existing tests modified except the integration test file
  `tests/integration/test_hai_forced_e2e.py` (Phase 3a regression guard
  for the run_forced bug) which keeps passing.
- byte-diff at p=2000 against master must remain 37/37 IDENTICAL.

---

## 10. Docs sync (本 PR 同梱)

| Doc | 変更 |
|---|---|
| `MODULES.md` | New layer: "Verification" — clinosim/audit/ |
| `docs/CONTRIBUTING-modules.md` | PR 検証ガイド refresh: new feature 行 → `clinosim audit run`; add "Module audit.py boilerplate" sub-section |
| `.github/TEMPLATE_MODULE_README.md` | New "Audit" section in the canonical README template |
| `CLAUDE.md` | "DQR audits must drive the enricher path" line replaced with: "Verification gate is `clinosim audit run` — Modules co-locate their audit checks in `clinosim/modules/<name>/audit.py`" |
| `README.md` / `README.ja.md` | Quality & Compliance section: replace "3-axis DQR" mentions with "`clinosim audit run`"; first audit run report linked |
| `DESIGN.md` | New AD entry for the audit framework (registry + co-located checks + 4 axes) |
| `TODO.md` | Mark "DQR audit-script strengthening" done; add per-Module audit.py backlog for Phase 3b/c |
| `docs/reviews/2026-06-25-clinosim-audit-baseline.md` | First Markdown report from the new framework (baseline at master after merge) |

---

## 11. Out of scope (Phase 2+ backlog)

| 項目 | Phase | Reason |
|---|---|---|
| Per-Module audit.py for Phase 3b/c Modules (antibiotic / decay / mortality) | Phase 3b/c PRs | Each Module's own PR adds its audit alongside its feature |
| CI integration (`clinosim audit smoke` on every PR) | follow-up | Requires CI workflow file edit; framework Phase 1 ships standalone |
| HTML report rendering | follow-up | Markdown is sufficient for PR evidence |
| Audit diff vs prior baseline (e.g. "CRP cohort median shifted 12% vs prior run") | Phase 2 | Requires persisting prior baselines; cohort acceptance still works without it |
| Per-Module byte-diff orchestration | not planned | byte-diff is a refactor-PR mechanic, intentionally separate from audit |
| Web UI / interactive report | not planned | YAGNI; Markdown is enough |

---

## 12. Design decisions table (4-axis evaluation)

| Decision | Choice | Data quality | Clinical integrity | Maintainability | Concept fit |
|---|---|---|---|---|---|
| `clinosim/audit/` package + co-located Module checks | (B) + (A) | ◎ | ◎ | ◎ | ◎ |
| `clinosim audit` CLI | (A) | ◎ | ○ | ◎ | ◎ |
| Super-set DQR + silent_no_op | (B) | ◎ | ◎ | ○ (heavier) | ◎ |
| Per-event theoretical verification | new | ◎ | ◎ | ○ | ◎ |
| Fired counter | new | ◎ | ○ | ◎ | ◎ |
| Canonical constants cross-check | new | ◎ | ○ | ◎ | ◎ |
| Markdown report (not HTML/UI) | YAGNI | ○ | ○ | ◎ | ◎ |
| byte-diff stays out of audit scope | YAGNI | ○ | △ | ◎ | ◎ |

---

## 13. Open questions

なし。設計確定。

---

## 14. References

- xhigh review lesson memory: `feedback_xhigh_review_lessons`
- Phase 3a spec: `docs/superpowers/specs/2026-06-25-phase3a-hai-lab-lift-design.md`
- Phase 3a post-fix DQR: `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review-post-fix.md`
- AD-56 enricher registry: `DESIGN.md` AD-56
- AD-58 output adapter registry: `DESIGN.md` AD-58
- Existing 3-axis DQR script (to be superseded): `scratchpad/phase3a_dqr.py`
- Existing lift-firing proof (to be promoted): `scratchpad/phase3a_lift_fired_proof.py`
