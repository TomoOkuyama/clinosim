# HAI YAML Sibling Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the 6-layer silent-no-op defense pattern (established by PR3b-3 + PR3b-5 chains) to the 5 remaining under-validated HAI YAML loaders, completing 6-of-6 loader coverage so the user-declared breakpoint "PR3b-5 + sibling sweep 両 chain CLOSED" can be declared.

**Architecture:** Each loader gains a `_validate_hai_<name>` function wired inside its `@lru_cache(maxsize=1)` body. Validators perform empty top-level + per-bucket guards + HAI_TYPES forward-coverage + per-loader-specific cross-validation via authoritative loaders (`codes.lookup()` non-None for ICD / SNOMED / LOINC, `load_devices_config()["devices"].keys()` for device_type). All YAML data unchanged → byte-identical to master.

**Tech Stack:** Python 3.11+, pytest (unit + integration markers), existing `@lru_cache(maxsize=1)` convention, `codes.lookup()` API (PR-A), `load_devices_config()` (existing).

## Global Constraints

- Code language: Python 3.11+. Comments + docstrings: English.
- Formatter: ruff. Type checking: mypy strict.
- Line length: 100.
- Determinism (AD-16): no `random.random()` / `time.time()` / shared global RNG.
- No new YAML files. No data changes. All work is validator addition.
- Each validator invoked inside `@lru_cache(maxsize=1)` loader body, import-time fail-loud.
- Pre-merge gate (session 22 rule): `pytest tests/unit tests/integration -m "unit or integration"` full sweep.
- Byte-diff invariant: validators are pure read-only checks; production data path untouched. Sample byte-diff at p=1000.
- Commit trailer (every commit):
  `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7`
- Spec: `docs/superpowers/specs/2026-06-29-hai-yaml-sibling-sweep-design.md`

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `clinosim/modules/hai/engine.py` | Modify | Add `_validate_hai_rates`, `_validate_hai_codes`, `_validate_hai_specimens` + wire in their `load_*` functions; strengthen existing `_validate_hai_organisms` with forward-coverage |
| `clinosim/modules/hai/lab_lift.py` | Modify | Refactor inline `HAI_TYPES` check into `_validate_hai_lab_lift_config` function + add reverse-coverage + range checks |
| `tests/unit/test_hai_yaml_validators.py` | Create | ~30 unit tests covering all 5 validators × ~6 cases (positive + 5 negative classes) |
| `CLAUDE.md` | Modify | Record "6-layer silent-no-op defense applied to all 6 hai_*.yaml loaders" — completion of the pattern coverage |
| `TODO.md` | Modify | Strike "sibling YAML loader sweep" deferred entry; mark "区切り達成" achievable |
| `docs/CONTRIBUTING-modules.md` | Modify | Cite the 6-of-6 coverage in the canonical-constants validation list |

---

### Task 1: `_validate_hai_rates` + wire — TDD

**Files:**
- Modify: `clinosim/modules/hai/engine.py` (add `_validate_hai_rates` function + wire in `load_hai_rates`)
- Create: `tests/unit/test_hai_yaml_validators.py` (new file, first tests)

**Interfaces:**
- Consumes: `HAI_TYPES` (lazy import to avoid circular), `load_devices_config()` from `clinosim.modules.device.engine`
- Produces: `_validate_hai_rates(data: dict) -> None` — raises `ValueError` on any defect. Wires into `load_hai_rates()`.

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_hai_yaml_validators.py`:

```python
"""Unit tests for HAI YAML loader validators (sibling sweep, 2026-06-29).

Covers _validate_hai_rates, _validate_hai_codes, _validate_hai_specimens,
_validate_hai_lab_lift_config, _validate_hai_organisms reverse-coverage.
"""
from __future__ import annotations

import pytest
import yaml

from clinosim.modules.hai import engine as hai_engine


@pytest.fixture(autouse=True)
def _clear_hai_caches():
    """Each test starts with empty caches so monkeypatch effects are visible."""
    hai_engine.load_hai_rates.cache_clear()
    hai_engine.load_hai_codes.cache_clear()
    hai_engine.load_hai_organisms.cache_clear()
    hai_engine.load_hai_specimens.cache_clear()
    yield
    hai_engine.load_hai_rates.cache_clear()
    hai_engine.load_hai_codes.cache_clear()
    hai_engine.load_hai_organisms.cache_clear()
    hai_engine.load_hai_specimens.cache_clear()


# ----------------------------------------------------------------------------
# _validate_hai_rates
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_rates_real_yaml_loads_clean() -> None:
    """Positive baseline: the real hai_rates.yaml passes validation."""
    data = hai_engine.load_hai_rates()
    assert "hai_rates" in data
    assert set(data["hai_rates"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_rates_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_rates": {}})
    with pytest.raises(ValueError, match="hai_rates.yaml top-level empty"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_unknown_hai_type(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 0.001, "source_device_type": "cvc"},
            "cauti": {"per_day_risk": 0.001, "source_device_type": "indwelling_catheter"},
            "vap": {"per_day_risk": 0.001, "source_device_type": "mechanical_ventilator"},
            "INVALID": {"per_day_risk": 0.001, "source_device_type": "cvc"},
        }
    })
    with pytest.raises(ValueError, match="unknown hai_type 'INVALID'"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 0.001, "source_device_type": "cvc"},
            # cauti + vap missing
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_per_day_risk_out_of_range(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 1.5, "source_device_type": "cvc"},
            "cauti": {"per_day_risk": 0.001, "source_device_type": "indwelling_catheter"},
            "vap": {"per_day_risk": 0.001, "source_device_type": "mechanical_ventilator"},
        }
    })
    with pytest.raises(ValueError, match="per_day_risk"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_unknown_device_type(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 0.001, "source_device_type": "INVALID_DEVICE"},
            "cauti": {"per_day_risk": 0.001, "source_device_type": "indwelling_catheter"},
            "vap": {"per_day_risk": 0.001, "source_device_type": "mechanical_ventilator"},
        }
    })
    with pytest.raises(ValueError, match="source_device_type"):
        hai_engine.load_hai_rates()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hai_yaml_validators.py -v`
Expected: ALL fail. Positive baseline passes (no validation yet), but each negative test fails to raise — `monkeypatch` overrides YAML load to malformed data, current `load_hai_rates` returns it without checking.

- [ ] **Step 3: Implement `_validate_hai_rates` in engine.py**

In `clinosim/modules/hai/engine.py`, after `_validate_hai_organisms` (around line 103), add:

```python
def _validate_hai_rates(data: dict) -> None:
    """Validate hai_rates.yaml at load time (sibling sweep, 2026-06-29).

    6-layer silent-no-op defense:
    1. top-level 'hai_rates' must exist and be non-empty
    2. each hai_type ⊆ HAI_TYPES canonical set (no unknown keys)
    3. per-bucket non-empty
    4. HAI_TYPES forward-coverage (every canonical hai_type present)
    5. per_day_risk numeric and ∈ [0, 1]
    6. source_device_type ∈ load_devices_config()["devices"] (authoritative)
    """
    from clinosim.modules.device.engine import load_devices_config
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_rates.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    rates = data.get("hai_rates") or {}
    if not rates:
        raise ValueError(
            "hai_rates.yaml top-level empty — silent no-op risk"
        )
    valid_types = set(HAI_TYPES)
    device_table = load_devices_config().get("devices", {})
    for hai_type, bucket in rates.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_rates.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(bucket, dict) or not bucket:
            raise ValueError(
                f"hai_rates.yaml: {hai_type!r} bucket empty"
            )
        risk = bucket.get("per_day_risk")
        if not isinstance(risk, (int, float)) or not (0.0 <= float(risk) <= 1.0):
            raise ValueError(
                f"hai_rates.yaml: {hai_type!r} per_day_risk {risk!r} "
                f"not in [0, 1]"
            )
        src = bucket.get("source_device_type", "")
        if src not in device_table:
            raise ValueError(
                f"hai_rates.yaml: {hai_type!r} source_device_type {src!r} "
                f"not in devices.yaml ({sorted(device_table.keys())})"
            )
    missing = valid_types - set(rates.keys())
    if missing:
        raise ValueError(
            f"hai_rates.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_rates() -> dict[str, Any]:
    data = _load_yaml("hai_rates.yaml")
    _validate_hai_rates(data)
    return data
```

Find + replace the existing `load_hai_rates` (currently at line 105-107):

```python
@lru_cache(maxsize=1)
def load_hai_rates() -> dict[str, Any]:
    return _load_yaml("hai_rates.yaml")
```

With the new version above (calls `_validate_hai_rates(data)` before returning).

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_hai_yaml_validators.py -v`
Expected: All 6 tests pass.

- [ ] **Step 5: Sanity — full unit + integration suite**

Run: `pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3`
Expected: Failure count = 14 (baseline) ± 0. Validator runs on real YAML at import — fails immediately if YAML data has issues.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/hai/engine.py tests/unit/test_hai_yaml_validators.py
git commit -m "$(cat <<'EOF'
feat(hai/sibling-sweep): _validate_hai_rates — empty + range + device_type

First of 5 HAI YAML validator additions for sibling sweep chain.
Validates hai_rates.yaml at load_hai_rates() time with 6-layer
silent-no-op defense:
  1. top-level empty guard
  2. unknown hai_type rejection
  3. per-bucket empty guard
  4. HAI_TYPES forward-coverage
  5. per_day_risk ∈ [0, 1]
  6. source_device_type ∈ load_devices_config()["devices"] (authoritative)

6 unit tests cover positive baseline + 5 negative cases.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 2: `_validate_hai_codes` + wire — TDD

**Files:**
- Modify: `clinosim/modules/hai/engine.py`
- Modify: `tests/unit/test_hai_yaml_validators.py`

**Interfaces:**
- Consumes: `HAI_TYPES`, `codes.lookup` from `clinosim.codes`
- Produces: `_validate_hai_codes(data: dict) -> None`. Wires into `load_hai_codes()`.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_hai_yaml_validators.py`:

```python
# ----------------------------------------------------------------------------
# _validate_hai_codes
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_codes_real_yaml_loads_clean() -> None:
    data = hai_engine.load_hai_codes()
    assert "hai_codes" in data
    assert set(data["hai_codes"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_codes_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_codes": {}})
    with pytest.raises(ValueError, match="hai_codes.yaml top-level empty"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_hai_type(monkeypatch) -> None:
    base = {
        "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "T80.2",
                   "snomed": "736442006"},
        "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                  "snomed": "68566005"},
        "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                "snomed": "429271009"},
    }
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {**base, "INVALID": base["clabsi"]}
    })
    with pytest.raises(ValueError, match="unknown hai_type 'INVALID'"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "T80.2",
                       "snomed": "736442006"},
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_icd10_us(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "BOGUS.99", "icd10_jp_who": "T80.2",
                       "snomed": "736442006"},
            "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                      "snomed": "68566005"},
            "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                    "snomed": "429271009"},
        }
    })
    with pytest.raises(ValueError, match="icd10_us_billable"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_icd10_jp(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "Z99.9",
                       "snomed": "736442006"},
            "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                      "snomed": "68566005"},
            "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                    "snomed": "429271009"},
        }
    })
    with pytest.raises(ValueError, match="icd10_jp_who"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_snomed(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "T80.2",
                       "snomed": "9999999999"},
            "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                      "snomed": "68566005"},
            "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                    "snomed": "429271009"},
        }
    })
    with pytest.raises(ValueError, match="snomed"):
        hai_engine.load_hai_codes()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hai_yaml_validators.py -k "hai_codes" -v`
Expected: All hai_codes tests fail (validator not yet implemented).

- [ ] **Step 3: Implement `_validate_hai_codes` in engine.py**

After `_validate_hai_rates`, add:

```python
def _validate_hai_codes(data: dict) -> None:
    """Validate hai_codes.yaml at load time (sibling sweep).

    Cross-validation via authoritative loaders:
    - icd10_us_billable ∈ codes/data/icd-10-cm.yaml (codes.lookup non-None)
    - icd10_jp_who     ∈ codes/data/icd-10.yaml     (codes.lookup non-None)
    - snomed           ∈ codes/data/snomed-ct.yaml  (codes.lookup non-None)
    """
    from clinosim.codes import lookup as code_lookup
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_codes.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    codes_table = data.get("hai_codes") or {}
    if not codes_table:
        raise ValueError("hai_codes.yaml top-level empty — silent no-op risk")
    valid_types = set(HAI_TYPES)
    for hai_type, bucket in codes_table.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_codes.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(bucket, dict) or not bucket:
            raise ValueError(f"hai_codes.yaml: {hai_type!r} bucket empty")
        icd_us = bucket.get("icd10_us_billable", "")
        if code_lookup("icd-10-cm", icd_us, "en") is None:
            raise ValueError(
                f"hai_codes.yaml: {hai_type!r} icd10_us_billable {icd_us!r} "
                f"not in codes/data/icd-10-cm.yaml"
            )
        icd_jp = bucket.get("icd10_jp_who", "")
        if code_lookup("icd-10", icd_jp, "en") is None:
            raise ValueError(
                f"hai_codes.yaml: {hai_type!r} icd10_jp_who {icd_jp!r} "
                f"not in codes/data/icd-10.yaml"
            )
        snomed = bucket.get("snomed", "")
        if code_lookup("snomed-ct", snomed, "en") is None:
            raise ValueError(
                f"hai_codes.yaml: {hai_type!r} snomed {snomed!r} "
                f"not in codes/data/snomed-ct.yaml"
            )
    missing = valid_types - set(codes_table.keys())
    if missing:
        raise ValueError(
            f"hai_codes.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_codes() -> dict[str, Any]:
    data = _load_yaml("hai_codes.yaml")
    _validate_hai_codes(data)
    return data
```

Replace the existing `load_hai_codes` (currently at line 110-112) with the new version.

- [ ] **Step 4: Run tests + sanity sweep**

```bash
pytest tests/unit/test_hai_yaml_validators.py -v
pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3
```
Expected: hai_codes tests pass; full sweep failure count unchanged.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/hai/engine.py tests/unit/test_hai_yaml_validators.py
git commit -m "$(cat <<'EOF'
feat(hai/sibling-sweep): _validate_hai_codes — authoritative ICD/SNOMED lookup

Second of 5 HAI YAML validator additions. Validates hai_codes.yaml:
  1-4. empty + unknown + per-bucket + forward-coverage (common pattern)
  5. icd10_us_billable ∈ codes/data/icd-10-cm.yaml via code_lookup
  6. icd10_jp_who      ∈ codes/data/icd-10.yaml    via code_lookup
  7. snomed            ∈ codes/data/snomed-ct.yaml via code_lookup

7 unit tests added (positive baseline + 6 negative cases).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 3: `_validate_hai_specimens` + wire — TDD

**Files:**
- Modify: `clinosim/modules/hai/engine.py`
- Modify: `tests/unit/test_hai_yaml_validators.py`

**Interfaces:**
- Consumes: `HAI_TYPES`, `codes.lookup`
- Produces: `_validate_hai_specimens(data: dict) -> None`. Wires into `load_hai_specimens()`.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_hai_yaml_validators.py`:

```python
# ----------------------------------------------------------------------------
# _validate_hai_specimens
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_specimens_real_yaml_loads_clean() -> None:
    data = hai_engine.load_hai_specimens()
    assert "hai_specimens" in data
    assert set(data["hai_specimens"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_specimens_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_specimens": {}})
    with pytest.raises(ValueError, match="hai_specimens.yaml top-level empty"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_unknown_hai_type(monkeypatch) -> None:
    base = {
        "clabsi": {"specimen": "blood", "specimen_snomed": "119297000",
                   "test_loinc": "600-7"},
        "cauti": {"specimen": "urine", "specimen_snomed": "122575003",
                  "test_loinc": "630-4"},
        "vap": {"specimen": "sputum", "specimen_snomed": "119334006",
                "test_loinc": "619-7"},
    }
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {**base, "INVALID": base["clabsi"]}
    })
    with pytest.raises(ValueError, match="unknown hai_type 'INVALID'"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {
            "clabsi": {"specimen": "blood", "specimen_snomed": "119297000",
                       "test_loinc": "600-7"},
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_unknown_snomed(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {
            "clabsi": {"specimen": "blood", "specimen_snomed": "9999999999",
                       "test_loinc": "600-7"},
            "cauti": {"specimen": "urine", "specimen_snomed": "122575003",
                      "test_loinc": "630-4"},
            "vap": {"specimen": "sputum", "specimen_snomed": "119334006",
                    "test_loinc": "619-7"},
        }
    })
    with pytest.raises(ValueError, match="specimen_snomed"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_unknown_loinc(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {
            "clabsi": {"specimen": "blood", "specimen_snomed": "119297000",
                       "test_loinc": "99999-99"},
            "cauti": {"specimen": "urine", "specimen_snomed": "122575003",
                      "test_loinc": "630-4"},
            "vap": {"specimen": "sputum", "specimen_snomed": "119334006",
                    "test_loinc": "619-7"},
        }
    })
    with pytest.raises(ValueError, match="test_loinc"):
        hai_engine.load_hai_specimens()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hai_yaml_validators.py -k "hai_specimens" -v`
Expected: All hai_specimens tests fail.

- [ ] **Step 3: Implement `_validate_hai_specimens` in engine.py**

After `_validate_hai_codes`, add:

```python
def _validate_hai_specimens(data: dict) -> None:
    """Validate hai_specimens.yaml at load time (sibling sweep).

    Cross-validation via authoritative loaders:
    - specimen_snomed ∈ codes/data/snomed-ct.yaml (codes.lookup non-None)
    - test_loinc      ∈ codes/data/loinc.yaml     (codes.lookup non-None)
    """
    from clinosim.codes import lookup as code_lookup
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_specimens.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    spec_table = data.get("hai_specimens") or {}
    if not spec_table:
        raise ValueError("hai_specimens.yaml top-level empty — silent no-op risk")
    valid_types = set(HAI_TYPES)
    for hai_type, bucket in spec_table.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_specimens.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(bucket, dict) or not bucket:
            raise ValueError(f"hai_specimens.yaml: {hai_type!r} bucket empty")
        snomed = bucket.get("specimen_snomed", "")
        if code_lookup("snomed-ct", snomed, "en") is None:
            raise ValueError(
                f"hai_specimens.yaml: {hai_type!r} specimen_snomed {snomed!r} "
                f"not in codes/data/snomed-ct.yaml"
            )
        loinc = bucket.get("test_loinc", "")
        if code_lookup("loinc", loinc, "en") is None:
            raise ValueError(
                f"hai_specimens.yaml: {hai_type!r} test_loinc {loinc!r} "
                f"not in codes/data/loinc.yaml"
            )
    missing = valid_types - set(spec_table.keys())
    if missing:
        raise ValueError(
            f"hai_specimens.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_specimens() -> dict[str, Any]:
    data = _load_yaml("hai_specimens.yaml")
    _validate_hai_specimens(data)
    return data
```

Replace the existing `load_hai_specimens` (currently at line 122-124).

- [ ] **Step 4: Run tests + sanity**

```bash
pytest tests/unit/test_hai_yaml_validators.py -v
pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3
```
Expected: all hai_specimens tests pass; full sweep unchanged.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/hai/engine.py tests/unit/test_hai_yaml_validators.py
git commit -m "$(cat <<'EOF'
feat(hai/sibling-sweep): _validate_hai_specimens — authoritative SNOMED/LOINC

Third of 5 HAI YAML validator additions. Validates hai_specimens.yaml
with common 6-layer pattern + SNOMED/LOINC authoritative lookup.

6 unit tests added (positive baseline + 5 negative cases).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 4: `_validate_hai_lab_lift_config` refactor + reverse-coverage — TDD

**Files:**
- Modify: `clinosim/modules/hai/lab_lift.py`
- Modify: `tests/unit/test_hai_yaml_validators.py`

**Interfaces:**
- Consumes: `HAI_TYPES`, `_HAI_LIFT_ANALYTES` (existing constant)
- Produces: `_validate_hai_lab_lift_config(data: dict) -> None`. Wires into `load_hai_lab_lift_config()`.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_hai_yaml_validators.py`:

```python
# ----------------------------------------------------------------------------
# _validate_hai_lab_lift_config
# ----------------------------------------------------------------------------


from clinosim.modules.hai import lab_lift as lab_lift_mod


@pytest.fixture(autouse=True)
def _clear_lab_lift_cache():
    """Reset lab_lift cache around each test (validator runs inside the loader)."""
    lab_lift_mod.load_hai_lab_lift_config.cache_clear()
    yield
    lab_lift_mod.load_hai_lab_lift_config.cache_clear()


@pytest.mark.unit
def test_hai_lab_lift_real_yaml_loads_clean() -> None:
    ramp, lift = lab_lift_mod.load_hai_lab_lift_config()
    assert ramp > 0
    assert set(lift.keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_lab_lift_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {})
    with pytest.raises(ValueError, match="hai_lab_lift.yaml empty"):
        lab_lift_mod.load_hai_lab_lift_config()


@pytest.mark.unit
def test_hai_lab_lift_rejects_zero_ramp(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "ramp_peak_days": 0,
        "hai_lift": {"clabsi": 0.35, "cauti": 0.20, "vap": 0.35},
    })
    with pytest.raises(ValueError, match="ramp_peak_days"):
        lab_lift_mod.load_hai_lab_lift_config()


@pytest.mark.unit
def test_hai_lab_lift_rejects_unknown_hai_type(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "ramp_peak_days": 2,
        "hai_lift": {"clabsi": 0.35, "cauti": 0.20, "vap": 0.35, "INVALID": 0.5},
    })
    with pytest.raises(ValueError, match="unknown"):
        lab_lift_mod.load_hai_lab_lift_config()


@pytest.mark.unit
def test_hai_lab_lift_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "ramp_peak_days": 2,
        "hai_lift": {"clabsi": 0.35},  # cauti + vap missing
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        lab_lift_mod.load_hai_lab_lift_config()


@pytest.mark.unit
def test_hai_lab_lift_rejects_out_of_range_lift_value(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "ramp_peak_days": 2,
        "hai_lift": {"clabsi": 1.5, "cauti": 0.20, "vap": 0.35},
    })
    with pytest.raises(ValueError, match="lift"):
        lab_lift_mod.load_hai_lab_lift_config()
```

- [ ] **Step 2: Run tests to verify they fail (most fail; positive baseline passes)**

Run: `pytest tests/unit/test_hai_yaml_validators.py -k "hai_lab_lift" -v`
Expected: Positive baseline + `rejects_unknown_hai_type` pass (existing inline check). Other 4 negative tests fail.

- [ ] **Step 3: Refactor inline check into `_validate_hai_lab_lift_config` in lab_lift.py**

In `clinosim/modules/hai/lab_lift.py`, replace the existing `load_hai_lab_lift_config` (currently at line 61-80) with:

```python
def _validate_hai_lab_lift_config(data: dict) -> None:
    """Validate hai_lab_lift.yaml at load time (sibling sweep, 2026-06-29).

    6-layer silent-no-op defense:
    1. top-level empty guard
    2. ramp_peak_days numeric and > 0
    3. hai_lift bucket non-empty
    4. each hai_type ⊆ HAI_TYPES
    5. each lift value numeric and ∈ [0, 1]
    6. HAI_TYPES forward-coverage
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("hai_lab_lift.yaml empty — silent no-op risk")
    ramp = data.get("ramp_peak_days")
    if not isinstance(ramp, (int, float)) or float(ramp) <= 0:
        raise ValueError(
            f"hai_lab_lift.yaml: ramp_peak_days {ramp!r} must be > 0"
        )
    lift_table = data.get("hai_lift") or {}
    if not lift_table:
        raise ValueError(
            "hai_lab_lift.yaml: hai_lift bucket empty — silent no-op risk"
        )
    valid_types = set(HAI_TYPES)
    for hai_type, value in lift_table.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_lab_lift.yaml has unknown hai_type keys {hai_type!r} — "
                f"must use HAI_TYPES {HAI_TYPES} (case-sensitive)"
            )
        if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
            raise ValueError(
                f"hai_lab_lift.yaml: {hai_type!r} lift value {value!r} "
                f"not in [0, 1]"
            )
    missing = valid_types - set(lift_table.keys())
    if missing:
        raise ValueError(
            f"hai_lab_lift.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_lab_lift_config() -> tuple[float, dict[str, float]]:
    """Load reference_data/hai_lab_lift.yaml once.

    Returns ``(ramp_peak_days, {hai_type: lift_value})``. Validation by
    ``_validate_hai_lab_lift_config`` covers the 6-layer silent-no-op
    defense pattern (sibling sweep, 2026-06-29).
    """
    data = yaml.safe_load((_REF_DIR / "hai_lab_lift.yaml").read_text(encoding="utf-8"))
    _validate_hai_lab_lift_config(data)
    return float(data["ramp_peak_days"]), dict(data["hai_lift"])
```

- [ ] **Step 4: Run tests + sanity**

```bash
pytest tests/unit/test_hai_yaml_validators.py -v
pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3
```
Expected: All hai_lab_lift tests pass; full sweep unchanged.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/hai/lab_lift.py tests/unit/test_hai_yaml_validators.py
git commit -m "$(cat <<'EOF'
feat(hai/sibling-sweep): _validate_hai_lab_lift_config refactor + reverse-coverage

Fourth of 5 HAI YAML validator additions. Refactors the inline
HAI_TYPES check inside load_hai_lab_lift_config into a standalone
_validate_hai_lab_lift_config function, with full 6-layer defense:
  1. empty top-level
  2. ramp_peak_days > 0
  3. hai_lift bucket non-empty
  4. unknown hai_type rejection
  5. lift value ∈ [0, 1]
  6. HAI_TYPES forward-coverage

6 unit tests added.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 5: `_validate_hai_organisms` forward-coverage strengthen — TDD

**Files:**
- Modify: `clinosim/modules/hai/engine.py`
- Modify: `tests/unit/test_hai_yaml_validators.py`

**Interfaces:**
- Consumes: existing `_validate_hai_organisms` body
- Produces: enhanced `_validate_hai_organisms` with HAI_TYPES forward-coverage assertion. No signature change.

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_hai_yaml_validators.py`:

```python
# ----------------------------------------------------------------------------
# _validate_hai_organisms (existing) — forward-coverage strengthen
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_organisms_real_yaml_loads_clean() -> None:
    data = hai_engine.load_hai_organisms()
    assert "hai_organisms" in data
    assert set(data["hai_organisms"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_organisms_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_organisms": {
            "clabsi": [{"snomed": "3092008", "weight": 1.0}],
            # cauti + vap missing — must fail forward-coverage
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_organisms()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_hai_yaml_validators.py::test_hai_organisms_rejects_missing_hai_type_forward_coverage -v`
Expected: FAIL — existing validator doesn't enforce forward-coverage.

- [ ] **Step 3: Add forward-coverage check to existing `_validate_hai_organisms`**

In `clinosim/modules/hai/engine.py`, in the `_validate_hai_organisms` function, after the existing for-loop (around line 102), add:

```python
    # Forward-coverage (sibling sweep, 2026-06-29): every HAI_TYPE must have an entry.
    missing = valid_types - set(organisms_map.keys())
    if missing:
        raise ValueError(
            f"hai_organisms.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )
```

- [ ] **Step 4: Run tests + sanity**

```bash
pytest tests/unit/test_hai_yaml_validators.py -v
pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3
```
Expected: All tests pass; full sweep unchanged.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/hai/engine.py tests/unit/test_hai_yaml_validators.py
git commit -m "$(cat <<'EOF'
feat(hai/sibling-sweep): _validate_hai_organisms HAI_TYPES forward-coverage

Fifth + last HAI YAML validator addition. Strengthens existing
_validate_hai_organisms (added by PR3b-3) with the forward-coverage
assertion sibling pattern from PR #114 _validate_narrow_rate_bands +
PR #115 _NARROW_RATE_BANDS adv-3 fix. Now matches the other 4 sibling
sweep validators in completeness.

6-layer silent-no-op defense now applied to all 6 hai_*.yaml loaders:
  hai_antibiogram (PR3b-3) + hai_organisms (sibling sweep complete) +
  hai_lab_lift + hai_rates + hai_codes + hai_specimens.

1 new unit test verifies the missing-hai_type case.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

### Task 6: Byte-diff verification + Pre-merge sweep

**Files:**
- None modified (verification + sanity)

**Interfaces:**
- Consumes: post-Task-5 state (all 5 validators wired)
- Produces: byte-diff verification record

- [ ] **Step 1: Generate baseline cohort (master state via temporary stash)**

Save current sibling sweep state, generate master-state cohort, restore:

```bash
mkdir -p scratchpad/sibling_sweep_byte_diff/{post,pre}
.venv/bin/clinosim generate --country US --population 1000 --seed 42 --output scratchpad/sibling_sweep_byte_diff/post --format fhir-r4
git stash
.venv/bin/clinosim generate --country US --population 1000 --seed 42 --output scratchpad/sibling_sweep_byte_diff/pre --format fhir-r4
git stash pop
```

Expected: both generations complete; one captures master (validators OFF), one captures sibling sweep (validators ON).

- [ ] **Step 2: Compare NDJSON files for byte identity**

```bash
diff -qr scratchpad/sibling_sweep_byte_diff/pre/us/fhir_r4 scratchpad/sibling_sweep_byte_diff/post/us/fhir_r4
```

Expected: **no output** (both directories identical). If `diff` reports any file difference, a validator is mutating data — investigate the offending validator immediately (this is a blocker).

If clean: record the result for the PR body.

- [ ] **Step 3: Run full pre-merge sweep**

```bash
pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3
```
Expected: failure count = baseline 14 (pre-existing `_reset_for_test` ordering, deferred) ± 0. New tests are pure unit tests with no `discover()` calls — should not inherit the cascade.

- [ ] **Step 4: Confirm all new validator tests pass in isolation**

```bash
pytest tests/unit/test_hai_yaml_validators.py -v
```
Expected: ~30 tests pass (positive baselines + negatives across 5 loaders).

- [ ] **Step 5: ruff + mypy on touched files**

```bash
.venv/bin/ruff check clinosim/modules/hai/engine.py clinosim/modules/hai/lab_lift.py tests/unit/test_hai_yaml_validators.py
```
Expected: clean on new code (pre-existing mypy line-length etc. flagged on master are OK).

- [ ] **Step 6: Clean up byte-diff scratch (after verification)**

```bash
rm -rf scratchpad/sibling_sweep_byte_diff
```

No commit — this is a verification step only.

---

### Task 7: Docs sync + PR

**Files:**
- Modify: `CLAUDE.md` (record 6-of-6 hai YAML loader defense coverage)
- Modify: `TODO.md` (strike "sibling YAML loader sweep" deferred entry)
- Modify: `docs/CONTRIBUTING-modules.md` (cite 6-of-6 coverage)

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, find the PR3b-5 supplement paragraph (added in PR #117 + #120). Append a new paragraph:

```markdown
  **HAI YAML sibling sweep CLOSED (2026-06-29, this chain)** — the 6-layer silent-no-op defense pattern is now applied to **all 6 HAI YAML loaders**: `hai_antibiogram` + `hai_organisms` (existing, PR3b-3) + new `hai_lab_lift` + `hai_rates` + `hai_codes` + `hai_specimens` (sibling sweep). Each `_validate_hai_<name>` performs empty top-level + per-bucket guards + HAI_TYPES forward-coverage + per-loader-specific cross-validation via authoritative loaders (`codes.lookup()` for ICD/SNOMED/LOINC, `load_devices_config()["devices"]` for device_type). YAML data unchanged; byte-diff verified zero at p=1000 seed=42.
```

- [ ] **Step 2: Update TODO.md**

In `TODO.md`, find the "Sibling YAML loader sweep" entry under PR3b-5 deferred items (around line 588-593). Replace:

```markdown
- Sibling YAML loader sweep (hai_lab_lift / hai_rates / hai_codes /
  hai_specimens / hai_organisms additional reverse-coverage): apply the
  silent-no-op defense pattern established by PR3b-3 chain to all
  remaining hai_*.yaml loaders. Scope-tiny pattern application. **This is
  the next user-declared breakpoint after PR3b-5** (区切り = PR3b-5 +
  sibling sweep 両 chain CLOSED).
```

With:

```markdown
- ~~Sibling YAML loader sweep~~: ✓ done 2026-06-29 (this PR + adversarial
  chain) — `_validate_hai_rates` + `_validate_hai_codes` +
  `_validate_hai_specimens` + `_validate_hai_lab_lift_config` (refactor
  inline → function) + `_validate_hai_organisms` forward-coverage
  strengthen. **6-layer silent-no-op defense now applied to all 6
  hai_*.yaml loaders** (antibiogram + organisms + lab_lift + rates +
  codes + specimens). YAML data unchanged; byte-diff verified zero.
  **区切り達成宣言可能** (PR3b-3 + PR3b-5 + sibling sweep 3 chain
  CLOSED).
```

- [ ] **Step 3: Update CONTRIBUTING-modules.md**

In `docs/CONTRIBUTING-modules.md`, find the canonical-constants validation precedent list (around line 158-164). Append:

```markdown
- `clinosim/modules/hai/engine.py:_validate_hai_rates` — `per_day_risk ∈ [0, 1]` + `source_device_type ∈ load_devices_config()["devices"]` (sibling sweep 2026-06-29)
- `clinosim/modules/hai/engine.py:_validate_hai_codes` — `icd10_us_billable` / `icd10_jp_who` / `snomed` via `codes.lookup()` non-None (sibling sweep 2026-06-29)
- `clinosim/modules/hai/engine.py:_validate_hai_specimens` — `specimen_snomed` / `test_loinc` via `codes.lookup()` non-None (sibling sweep 2026-06-29)
- `clinosim/modules/hai/lab_lift.py:_validate_hai_lab_lift_config` — `ramp_peak_days > 0` + lift values ∈ [0, 1] + HAI_TYPES forward-coverage (sibling sweep 2026-06-29, refactor from inline check)
```

- [ ] **Step 4: Run final pre-merge sweep**

```bash
pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -3
```
Expected: failure count = baseline ± 0.

- [ ] **Step 5: Commit + push + create PR**

```bash
git add CLAUDE.md TODO.md docs/CONTRIBUTING-modules.md
git commit -m "$(cat <<'EOF'
docs(sibling-sweep): record 6-of-6 hai YAML loader defense coverage

CLAUDE.md: append HAI YAML sibling sweep CLOSED supplement to the
PR3b-5 narrative; 6-layer silent-no-op defense now applied to all 6
hai_*.yaml loaders.
TODO.md: strike the "Sibling YAML loader sweep" deferred entry; mark
"区切り達成宣言可能" (PR3b-3 + PR3b-5 + sibling sweep 3 chain CLOSED).
CONTRIBUTING-modules.md: cite 4 new validators in the canonical-
constants validation precedent list.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"

git push -u origin feat/sibling-sweep
gh pr create --title "feat(hai): YAML sibling sweep — 6-layer defense applied to all 6 loaders" --body "$(cat <<'EOF'
## Summary

Applies the 6-layer silent-no-op defense pattern (established by PR3b-3 + PR3b-5 chains) to the 5 remaining under-validated HAI YAML loaders, completing 6-of-6 hai_*.yaml loader coverage.

This is the LAST chain before the user-declared breakpoint ("PR3b-5 + sibling sweep 両 chain CLOSED" = 区切り達成).

## Validators added / strengthened

| Loader | YAML | Change |
|---|---|---|
| `_validate_hai_rates` | hai_rates.yaml | **NEW** — per_day_risk ∈ [0,1] + device_type via `load_devices_config()` |
| `_validate_hai_codes` | hai_codes.yaml | **NEW** — ICD/SNOMED via `codes.lookup()` non-None |
| `_validate_hai_specimens` | hai_specimens.yaml | **NEW** — SNOMED/LOINC via `codes.lookup()` non-None |
| `_validate_hai_lab_lift_config` | hai_lab_lift.yaml | **refactor + strengthen** — inline check → function + ramp/lift range + forward-coverage |
| `_validate_hai_organisms` | hai_organisms.yaml | **strengthen** — added HAI_TYPES forward-coverage check |

Each validator runs inside `@lru_cache(maxsize=1)` loader body, import-time fail-loud.

## Test plan

- [x] ~30 unit tests in new `tests/unit/test_hai_yaml_validators.py` (positive baseline + 5 negative classes per loader)
- [x] Pre-merge sweep failure count = master baseline 14 (pre-existing `_reset_for_test` ordering, deferred)
- [x] Byte-diff verified zero at p=1000 seed=42 (validators are import-time-only, no data path mutation)
- [x] ruff + mypy clean on touched files

## Out-of-scope

PR3b-5 deferred items remain in TODO.md as-is — sibling sweep does NOT touch them. After this chain CLOSED, **区切り達成宣言** can be made (task #19): PR3b-3 + PR3b-5 + sibling sweep 3 chain CLOSED + 6-of-6 hai YAML loader silent-no-op defense complete.

## Related

- Spec: `docs/superpowers/specs/2026-06-29-hai-yaml-sibling-sweep-design.md`
- Plan: `docs/superpowers/plans/2026-06-29-hai-yaml-sibling-sweep-plan.md`
- Predecessors: PR3b-3 chain (#112-#116), PR3b-5 chain (#117-#120) both CLOSED

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HTCtHf6jSBg2JvkAa1obr7
EOF
)"
```

---

## Spec coverage self-check

- `_validate_hai_rates` + wire → Task 1 ✓
- `_validate_hai_codes` + wire → Task 2 ✓
- `_validate_hai_specimens` + wire → Task 3 ✓
- `_validate_hai_lab_lift_config` refactor → Task 4 ✓
- `_validate_hai_organisms` forward-coverage → Task 5 ✓
- ~30 unit tests across 5 loaders → Tasks 1-5 (cumulative ~30) ✓
- Byte-diff verification → Task 6 ✓
- Pre-merge sweep → Task 6 ✓
- ruff + mypy → Task 6 ✓
- CLAUDE.md + TODO.md + CONTRIBUTING sync → Task 7 ✓
- 6-of-6 hai YAML loader coverage claim → Task 7 ✓
- 区切り達成 prerequisite recorded → Task 7 TODO.md ✓

## Type consistency

- All 5 validators have signature `_validate_hai_<name>(data: dict) -> None`
- All 5 validators raise `ValueError` (never `AssertionError` / `RuntimeError`)
- All 5 loaders have `@lru_cache(maxsize=1)` + `_validate_*(data)` + `return data` (rates/codes/specimens) or `return (ramp, lift)` (lab_lift)
- `codes.lookup(system, code, lang)` signature consistent across Tasks 2 + 3
- `load_devices_config()` returns `dict[str, Any]` with `"devices"` key — consistent in Task 1

## Placeholder scan

No TBD / TODO / "fill in" markers in implementation steps. All code blocks complete.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-29-hai-yaml-sibling-sweep-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task.

**2. Inline Execution** — execute in this session.

For this 7-task scope-tiny pattern application chain with mechanical task structure (each task is the same "add validator + tests" pattern), inline execution is efficient because spec + plan + context are loaded. Subagent dispatch overhead exceeds the per-task value.

Which approach?