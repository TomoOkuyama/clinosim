# HAI YAML Sibling Sweep — Design

**Date**: 2026-06-29
**Author**: Tomo Okuyama + Claude (Opus 4.7)
**Status**: Draft (pending user approval)
**Branch**: `feat/sibling-sweep` (created)
**Predecessors**: PR3b-3 D1+D2 chain (#112-#116) + PR3b-5 chain (#117-#120) both CLOSED

## Why

The 6-layer silent-no-op defense pattern established progressively
through PR3b-3 + PR3b-5 chains is partially applied to HAI YAML loaders:

| YAML | Loader | `@lru_cache` | `_validate_*` |
|---|---|---|---|
| `hai_antibiogram.yaml` | `__init__.py:load_hai_antibiogram` | ✓ | ✓ (3-way + empty guards, PR3b-3) |
| `hai_organisms.yaml` | `engine.py:load_hai_organisms` | ✓ | ✓ `_validate_hai_organisms` (forward only) |
| `hai_lab_lift.yaml` | `lab_lift.py:load_hai_lab_lift_config` | ✓ | △ inline `HAI_TYPES` check only |
| `hai_rates.yaml` | `engine.py:load_hai_rates` | ✓ | ✗ NONE |
| `hai_codes.yaml` | `engine.py:load_hai_codes` | ✓ | ✗ NONE |
| `hai_specimens.yaml` | `engine.py:load_hai_specimens` | ✓ | ✗ NONE |

3 loaders have zero validation; 1 has only inline minimal check; 1 has
validation but lacks reverse-coverage. The user-declared breakpoint
("PR3b-5 + sibling sweep 両 chain CLOSED") requires applying the
defense pattern to all 6 HAI loaders before declaring "区切り達成".

This is the **last chain** before the breakpoint declaration (task #19).

## What is included

For each of the 5 under-validated loaders, add `_validate_hai_<name>`
following the established pattern from PR3b-3 `_validate_hai_antibiogram`:

1. **Empty top-level guard** (I2 pattern from PR #114)
2. **Per-hai_type bucket empty guard** (adv-2 finding from PR #114)
3. **HAI_TYPES forward-coverage** (every HAI_TYPE has an entry)
4. **HAI_TYPES set-membership** (no unknown hai_type)
5. **Per-loader-specific cross-validation** via authoritative loaders:
   - `hai_rates`: `per_day_risk ∈ [0, 1]` + `source_device_type ∈ load_devices_config()["devices"].keys()`
   - `hai_codes`: ICD/SNOMED codes validated via `codes.lookup()` non-None
   - `hai_specimens`: SNOMED/LOINC codes validated via `codes.lookup()` non-None
   - `hai_lab_lift`: `ramp_peak_days > 0` + `lift_value ∈ [0, 1]` + `_HAI_LIFT_ANALYTES` consistency
   - `hai_organisms`: existing weight checks + reverse-coverage strengthen

Each validator invoked inside the `@lru_cache(maxsize=1)` loader,
import-time fail-loud (validators-before-register pattern from PR #114).

## What is explicitly out-of-scope

- **PR3b-5 deferred items remain in TODO.md as-is** — sibling sweep does NOT touch them. (PR3b-4 WBC/CRP decay, audit registry ordering, NHSN clinical-accuracy verification, etc.)
- **canonical constants `DEVICE_TYPES`**: not introduced. `load_devices_config()["devices"].keys()` IS the canonical (devices.yaml is SoT). If a future PR needs a cross-module constant, that's its scope.
- **`hai_antibiogram.yaml`**: already fully validated by PR3b-3 + chain fixes; no changes.
- **byte-diff invariant**: YAML data unchanged; validators are import-time-only. Expected byte-identical to master.

## Architecture

### Common validator skeleton (5 loaders)

```python
def _validate_hai_<name>(data: dict) -> None:
    """6-layer silent-no-op defense applied to hai_<name>.yaml."""
    table = data.get("hai_<name>") or {}
    if not table:
        raise ValueError("hai_<name>.yaml top-level empty — silent no-op risk")

    valid_hai_types = set(HAI_TYPES)
    for hai_type, bucket in table.items():
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"hai_<name>.yaml: unknown hai_type {hai_type!r}, "
                f"expected {sorted(valid_hai_types)}"
            )
        if not bucket:
            raise ValueError(f"hai_<name>.yaml: {hai_type!r} bucket empty")
        # ... loader-specific cross-validation ...

    # Forward-coverage: every HAI_TYPE must have an entry
    missing = valid_hai_types - set(table.keys())
    if missing:
        raise ValueError(
            f"hai_<name>.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )
```

### Per-loader cross-validation specifics

**`_validate_hai_rates`** (engine.py, new):

```python
# bucket = {"per_day_risk": float, "source_device_type": str}
risk = bucket.get("per_day_risk")
if not isinstance(risk, (int, float)) or not (0.0 <= risk <= 1.0):
    raise ValueError(f"hai_rates.yaml: {hai_type!r} per_day_risk {risk!r} not in [0, 1]")

from clinosim.modules.device.engine import load_devices_config  # local import
device_table = load_devices_config().get("devices", {})
src = bucket.get("source_device_type", "")
if src not in device_table:
    raise ValueError(
        f"hai_rates.yaml: {hai_type!r} source_device_type {src!r} "
        f"not in devices.yaml ({sorted(device_table.keys())})"
    )
```

**`_validate_hai_codes`** (engine.py, new):

```python
# bucket = {"icd10_us_billable": "...", "icd10_jp_who": "...", "snomed": "...", ...}
from clinosim.codes import lookup as code_lookup  # local import
if code_lookup("icd-10-cm", bucket.get("icd10_us_billable", ""), "en") is None:
    raise ValueError(...)
if code_lookup("icd-10", bucket.get("icd10_jp_who", ""), "en") is None:
    raise ValueError(...)
if code_lookup("snomed-ct", bucket.get("snomed", ""), "en") is None:
    raise ValueError(...)
```

**`_validate_hai_specimens`** (engine.py, new):

```python
# bucket = {"specimen": "...", "specimen_snomed": "...", "test_loinc": "..."}
from clinosim.codes import lookup as code_lookup  # local import
if code_lookup("snomed-ct", bucket.get("specimen_snomed", ""), "en") is None:
    raise ValueError(...)
if code_lookup("loinc", bucket.get("test_loinc", ""), "en") is None:
    raise ValueError(...)
```

**`_validate_hai_lab_lift_config`** (lab_lift.py, refactor inline → function):

```python
# data = {"ramp_peak_days": int/float, "hai_lift": {hai_type: float, ...}}
if not data:
    raise ValueError("hai_lab_lift.yaml empty — silent no-op risk")
ramp = data.get("ramp_peak_days")
if not isinstance(ramp, (int, float)) or ramp <= 0:
    raise ValueError(f"hai_lab_lift.yaml: ramp_peak_days {ramp!r} must be > 0")
lift_table = data.get("hai_lift") or {}
if not lift_table:
    raise ValueError("hai_lab_lift.yaml: hai_lift bucket empty")
valid_hai_types = set(HAI_TYPES)
for hai_type, value in lift_table.items():
    if hai_type not in valid_hai_types:
        raise ValueError(...)
    if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
        raise ValueError(...)
missing = valid_hai_types - set(lift_table.keys())
if missing:
    raise ValueError(...)
```

**`_validate_hai_organisms`** (engine.py, existing) — strengthen with
explicit `HAI_TYPES` forward-coverage assertion (currently checks
membership per-iteration but doesn't assert every HAI_TYPE is present).

### Loader integration

Each `load_hai_<name>` function (existing) calls `_validate_hai_<name>(data)`
inside the `@lru_cache(maxsize=1)` body, before returning. Validators run
once per process (cache-level memoization). Failure raises at first
caller; subsequent callers get the cached error via the cache miss
retry — actually `lru_cache` does NOT cache exceptions, so each call
re-validates until it succeeds. This is acceptable for import-time use.

## Testing

### Unit (`tests/unit/test_hai_yaml_validators.py`, new file)

Per loader (5 × ~6 = ~30 tests):
- positive baseline (real YAML loads cleanly)
- empty top-level → ValueError
- per-bucket empty → ValueError
- unknown hai_type → ValueError
- missing HAI_TYPE (forward-coverage) → ValueError
- per-loader-specific cross-validation negatives:
  - `hai_rates`: invalid device_type, out-of-range per_day_risk
  - `hai_codes`: invalid ICD-10-CM, ICD-10, SNOMED
  - `hai_specimens`: invalid SNOMED, LOINC
  - `hai_lab_lift`: invalid ramp, invalid lift value
  - `hai_organisms`: existing tests stay

Test harness uses `monkeypatch.setattr(yaml, "safe_load", lambda f: <fixture>)`
to inject malformed data without touching real YAML files. Each test
ends with `load_hai_<name>.cache_clear()` in a `try/finally`.

### Integration

No new integration tests required — the 5 validators are pure functions
and unit-test isolation is sufficient. Existing integration tests
(`test_antibiotic_audit.py` etc.) continue to load real YAMLs which
must pass all 5 validators at import time. If any fixture YAML doesn't
satisfy the new validators, the existing test suite fails immediately —
this is the load-bearing regression net.

### Pre-merge gate

`pytest tests/unit tests/integration -m "unit or integration"` — full
sweep. Failure count = baseline 14 (`_reset_for_test` ordering, deferred)
+ new tests' inheritance (expected +0 since new tests are pure unit, no
`discover()` calls).

### Byte-diff invariant

```bash
.venv/bin/clinosim generate --country US --population 1000 --seed 42 --output scratchpad/sibling_baseline --format fhir-r4
git stash
.venv/bin/clinosim generate --country US --population 1000 --seed 42 --output scratchpad/sibling_master --format fhir-r4
git stash pop
diff -r scratchpad/sibling_baseline/us/fhir_r4/ scratchpad/sibling_master/us/fhir_r4/
```

Expected: zero diff (validation is import-time-only, no data path
touched). If diff appears, a validator is incorrectly mutating data —
investigate before merging.

## Convergence criteria — complete closure

This PR's chain closes when:

1. All 5 validators implemented + wired in their loaders
2. ~30 unit tests cover all positive + negative cases
3. Byte-diff verified zero (sample p=1000)
4. Pre-merge sweep fail count unchanged from baseline
5. Post-merge 4-stage adversarial fan-out converged
6. CLAUDE.md + TODO.md updated to record "6-layer silent-no-op defense
   applied to all hai_*.yaml" (= 6/6 loaders fully validated)

After this chain closes, the **breakpoint declaration** (task #19) records:

- PR3b-3 chain CLOSED + PR3b-5 chain CLOSED + sibling sweep CLOSED
- 6-layer silent-no-op defense complete (`_validate_*` on all hai_*.yaml)
- データ品質 / 臨床整合性 axis approximation = 0 (PR3b-5 RESOLVED)
- メンテ性 axis 完成
- session 23 record + 「区切り達成」section in memory

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Existing YAML data fails new validators (real bug surfaced) | Each validator is mechanical pattern application; if real YAML fails it's a genuine data bug worth fixing. Pre-merge sweep will catch it immediately. |
| `codes.lookup()` import creates circular dependency with codes module | local import inside validator function (PR3b-3 precedent). |
| `load_devices_config()` import creates circular dependency with device module | local import inside `_validate_hai_rates`. |
| `lru_cache` doesn't cache exceptions → re-validation cost | Acceptable: validators run at import time once per stable YAML; failure is loud and immediate. |
| Adversarial review finds gaps in pattern application | Expected; that's the load-bearing 4-stage chain purpose. |

## Expected PR count

Typical = 3 PR (main + adv-1 fix + docs convergence record).
Best = 2 PR. Worst = 4 PR. Matches scope-tiny pattern application
(PR-B1 chain = 4 PR, PR3b-5 chain = 4 PR).

## Successor

After sibling sweep CLOSED, **task #19 「区切り達成宣言」** =
post-session record:
- All 3 chains converged
- 6-layer defense complete
- TODO.md formal entries cover all remaining backlog
- Memory file session 23 + 区切り達成 supplement
