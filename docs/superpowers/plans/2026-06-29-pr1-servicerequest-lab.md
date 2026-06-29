# PR1 — ServiceRequest for Lab Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit FHIR R4 `ServiceRequest` resources for lab orders with panel-aware grouping (CBC/BMP/LFT/ABG/Lipid/Coag/UA panels = 1 SR per panel instance, stand-alone tests = 1 SR each), and add `basedOn` linkage to lab Observation + DiagnosticReport.

**Architecture:** ServiceRequest = 既存 CIF `Order` の FHIR 表現(新 functional module 不要)。CIF `Order` に `panel_key: str = ""` 1 field 追加、ordering engine が `lab_panel_groups.yaml` を読んで同 panel test 群に同 datetime + panel_key 割当、新 FHIR builder `_fhir_service_request.py` が Orders を panel_key で grouping して SR emit。`Observation.basedOn` / `DiagnosticReport.basedOn` が SR を参照、AD-60 audit framework で silent-no-op を防御。

**Tech Stack:** Python 3.11+, FHIR R4, pytest, pydantic / dataclass (AD-18), ruff (line length 100), mypy strict.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-29-pr1-servicerequest-lab-design.md`
- Branch: `feature/pr1-servicerequest-lab`(master `934a063322` から派生、spec commit `6fd7516616` 上に積み上げ)
- 全コードコメント / docstring = English(CLAUDE.md)
- formatter = ruff、line length 100
- type checking = mypy strict
- CIF types は `clinosim/types/` 配下のみ(AD-18)
- 公開 API は module `__init__.py` で export
- AD-30: CIF は language-neutral、display 解決は output 時 `clinosim.codes.lookup()` 経由
- AD-31: FHIR resource id は type 内 globally unique
- AD-32: snapshot date 以降の life events なし、in-progress orders は SR.status="active" + Observation 不在
- AD-56: 新 resource builder は `register_bundle_builder` または `_BUNDLE_BUILDERS` list 直接(built-in 扱い)
- canonical constants: `SR_ID_PREFIX="sr-"` / `PLACER_ORDER_NUMBER_SYSTEM="urn:clinosim:placer-order-number"` / `LAB_CATEGORY_SNOMED="108252007"` / `LAB_CATEGORY_V2_0074="LAB"` / `PANEL_PRIORITY_ORDER=("ABG","CBC","BMP","LFT","Lipid","Coag","UA")`
- Pre-merge: `pytest tests/unit tests/integration -m "unit or integration"` の full sweep + `clinosim audit run` が PASS

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `clinosim/modules/order/panel_grouping.py` | Panel detection + lab_specs grouping algorithm + canonical constants(`PANEL_PRIORITY_ORDER`) |
| `clinosim/modules/output/_fhir_service_request.py` | ServiceRequest FHIR builder(panel + stand-alone emission)+ canonical constants(`SR_ID_PREFIX`, `PLACER_ORDER_NUMBER_SYSTEM`, `LAB_CATEGORY_SNOMED`, `LAB_CATEGORY_V2_0074`)+ `order_to_sr_id` helper |
| `clinosim/modules/order/audit.py` | `ModuleAuditSpec` registration + `lift_firing_proof` with 7 equality_checks |
| `tests/unit/modules/order/test_panel_grouping.py` | Panel detection 全境界 |
| `tests/unit/output/test_fhir_service_request.py` | ServiceRequest resource 構造 + id naming + identifier PLAC + status 集約 |
| `tests/unit/audit/test_order_audit.py` | `lift_firing_proof` fire + stub self-check |
| `tests/integration/test_servicerequest_chain.py` | run_beta US + JP で SR.ndjson 非空 + JP display |
| `tests/integration/test_servicerequest_basedon_coverage.py` | silent-no-op gate: 全 LAB Observation basedOn + ref resolve |
| `tests/integration/test_servicerequest_determinism.py` | seed 固定で 2 回実行 sha256 一致 |
| `tests/integration/test_servicerequest_snapshot.py` | snapshot mid-day 未完 Order の SR.status="active" |
| `docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md` | DQR doc(production cohort)|

### Modified files

| Path | Change | Lines |
|---|---|---|
| `clinosim/types/encounter.py:Order` | `panel_key: str = ""` 1 field 追加 | +1 |
| `clinosim/modules/order/engine.py` | `place_admission_orders` / `place_daily_lab_orders` を panel-aware に | ~80 |
| `clinosim/modules/order/__init__.py` | `panel_grouping` re-export | +1 |
| `clinosim/modules/output/_fhir_observations.py` | lab Observation に `basedOn` 追加 | ~20 |
| `clinosim/modules/output/_fhir_diagnostic_report.py` | panel report に `basedOn` 追加 | ~20 |
| `clinosim/modules/output/fhir_r4_adapter.py` | `_BUNDLE_BUILDERS` に SR builder 追加 | +1 |
| `clinosim/audit/axes/clinical.py` | basedOn coverage gate 追加 | ~50 |
| `clinosim/modules/output/_fhir_localization.py` | `loinc_display_ja.yaml` 不足 panel codes 追加(DQR で発見後) | TBD by DQR |
| `tests/unit/output/test_fhir_observations*.py`(既存) | basedOn 期待値追記 | ~10 |
| `README.md` / `README.ja.md` / `MODULES.md` / `DESIGN.md` / `docs/CONTRIBUTING-modules.md` / `clinosim/modules/order/README.md` / `TODO.md` / `CLAUDE.md` | docs sync | ~80 total |

---

## Task 1: CIF Order.panel_key field

**Files:**
- Modify: `clinosim/types/encounter.py:Order` — 1 field 追加
- Test: `tests/unit/types/test_order_panel_key.py`(新)

**Interfaces:**
- Consumes: なし
- Produces: `Order.panel_key: str`(default `""`、empty = stand-alone、non-empty = panel name "CBC"/"BMP"/...)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/types/test_order_panel_key.py
"""Unit tests for Order.panel_key field (PR1 ServiceRequest foundation)."""

from clinosim.types.encounter import Order, OrderType


def test_order_default_panel_key_is_empty():
    """Stand-alone Order defaults to panel_key=''."""
    o = Order(order_id="ORD-1", order_type=OrderType.LAB)
    assert o.panel_key == ""


def test_order_panel_key_settable():
    """Panel Order can be assigned a panel name."""
    o = Order(order_id="ORD-1", order_type=OrderType.LAB, panel_key="CBC")
    assert o.panel_key == "CBC"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/types/test_order_panel_key.py -v`
Expected: FAIL — `TypeError: Order.__init__() got an unexpected keyword argument 'panel_key'`

- [ ] **Step 3: Add panel_key field**

Edit `clinosim/types/encounter.py` to add `panel_key: str = ""` immediately after `reason_condition`:

```python
@dataclass
class Order:
    order_id: str = ""
    encounter_id: str = ""
    patient_id: str = ""
    order_type: OrderType = OrderType.LAB
    order_code: str = ""
    display_name: str = ""
    urgency: str = "routine"
    clinical_intent: str = ""
    ordered_datetime: datetime = field(default_factory=datetime.now)
    ordered_by: str = ""
    status: OrderStatus = OrderStatus.PLACED
    result: OrderResult | None = None
    # Structured medication fields (populated when order_type=MEDICATION)
    dose_quantity: float | None = None
    dose_unit: str = ""
    frequency: str = ""
    frequency_per_day: int | None = None
    route: str = ""
    duration_days: int | None = None
    reason_condition: str = ""
    # PR1: Panel-aware grouping for ServiceRequest emission.
    # Empty = stand-alone test (1 SR per Order). Non-empty = panel name
    # ("CBC"/"BMP"/"LFT"/"ABG"/"Lipid"/"Coag"/"UA") — Orders sharing the same
    # (encounter_id, panel_key, ordered_datetime) tuple emit a single ServiceRequest.
    panel_key: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/types/test_order_panel_key.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Verify no regression in existing Order tests**

Run: `pytest tests/unit -k "order" -v`
Expected: PASS (no new failures introduced)

- [ ] **Step 6: Commit**

```bash
git add clinosim/types/encounter.py tests/unit/types/test_order_panel_key.py
git commit -m "$(cat <<'EOF'
feat(types): add Order.panel_key field for ServiceRequest grouping

PR1 foundation. Empty = stand-alone (1 SR per Order), non-empty = panel
name (CBC/BMP/LFT/ABG/Lipid/Coag/UA) for panel-aware ServiceRequest
emission. Spec: docs/superpowers/specs/2026-06-29-pr1-servicerequest-lab-design.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 2: Panel detection helper module

**Files:**
- Create: `clinosim/modules/order/panel_grouping.py`
- Test: `tests/unit/modules/order/test_panel_grouping.py`

**Interfaces:**
- Consumes: `lab_panel_groups.yaml`(既存)経由で panel definitions
- Produces:
  - `PANEL_PRIORITY_ORDER: tuple[str, ...]` = `("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA")`
  - `classify_lab_specs(lab_specs: list[dict], panels_yaml: dict) -> tuple[dict[str, list[dict]], list[dict]]` — returns `(panel_groups, stand_alones)`
  - `load_panel_definitions() -> dict[str, dict]` — `lab_panel_groups.yaml` reader, lru_cache

- [ ] **Step 1: Write failing tests for panel detection**

```python
# tests/unit/modules/order/test_panel_grouping.py
"""Unit tests for panel detection (PR1 ServiceRequest)."""

import pytest

from clinosim.modules.order.panel_grouping import (
    PANEL_PRIORITY_ORDER,
    classify_lab_specs,
    load_panel_definitions,
)


def test_priority_order_constant():
    """PANEL_PRIORITY_ORDER matches lab_panel_groups.yaml header convention."""
    assert PANEL_PRIORITY_ORDER == ("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA")


def test_load_panel_definitions_has_known_panels():
    """All canonical panels are loaded from YAML."""
    panels = load_panel_definitions()
    for name in PANEL_PRIORITY_ORDER:
        assert name in panels, f"{name} missing from lab_panel_groups.yaml"
        assert "components" in panels[name]
        assert "min_components" in panels[name]
        assert "loinc" in panels[name]


def test_full_cbc_4_components_groups_as_panel():
    """4 CBC components (WBC/Hb/Hct/Plt) → 1 panel_groups[CBC]."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Hct"}, {"test": "Plt"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "CBC" in panel_groups
    assert len(panel_groups["CBC"]) == 4
    assert stand_alones == []


def test_partial_cbc_below_min_components_falls_to_standalone():
    """2 CBC components < min_components=3 → all stand-alone."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Plt"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert len(stand_alones) == 2


def test_partial_cbc_3_components_groups_as_panel():
    """3 CBC components == min_components=3 → grouped as CBC."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Plt"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "CBC" in panel_groups
    assert len(panel_groups["CBC"]) == 3


def test_daily_monitoring_all_standalone():
    """Daily monitoring tests (CRP/WBC/Cr) — each below any panel's min_components."""
    panels = load_panel_definitions()
    specs = [{"test": "CRP"}, {"test": "WBC"}, {"test": "Creatinine"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert len(stand_alones) == 3


def test_hco3_dual_membership_assigned_to_abg_first():
    """HCO3 is in both ABG and BMP. With full ABG (4 components), HCO3 goes to ABG."""
    panels = load_panel_definitions()
    specs = [{"test": "pH"}, {"test": "pCO2"}, {"test": "pO2"}, {"test": "HCO3"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "ABG" in panel_groups
    assert len(panel_groups["ABG"]) == 4
    assert stand_alones == []


def test_hco3_with_only_partial_abg_falls_to_standalone():
    """HCO3 + 1 ABG component < min_components=3 → HCO3 stays in ABG bucket, fails
    min_components, becomes stand-alone (not BMP fallback — conservative rule)."""
    panels = load_panel_definitions()
    specs = [{"test": "pH"}, {"test": "HCO3"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert {s["test"] for s in stand_alones} == {"pH", "HCO3"}


def test_mixed_cbc_and_standalone():
    """4 CBC + 1 troponin = CBC panel + 1 stand-alone."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Hct"}, {"test": "Plt"},
             {"test": "Troponin_I"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "CBC" in panel_groups
    assert len(panel_groups["CBC"]) == 4
    assert len(stand_alones) == 1
    assert stand_alones[0]["test"] == "Troponin_I"


def test_unknown_test_falls_to_standalone():
    """Test not in any panel definition → stand-alone."""
    panels = load_panel_definitions()
    specs = [{"test": "MadeUpTest"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert len(stand_alones) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/order/test_panel_grouping.py -v`
Expected: FAIL — module does not exist yet

- [ ] **Step 3: Create panel_grouping module**

Create `clinosim/modules/order/panel_grouping.py`:

```python
"""Panel detection for lab Order grouping (PR1 ServiceRequest foundation).

Reads ``lab_panel_groups.yaml`` (already used by ``_fhir_diagnostic_report.py``)
and classifies a list of lab specs into panel groups and stand-alone tests.

Priority order is critical for HCO3 dual-membership (ABG ∧ BMP) — HCO3 is
assigned to ABG first (priority winner), then ABG's min_components is checked.
If ABG falls below min_components, HCO3 stays orphaned in ABG bucket and the
whole ABG group becomes stand-alone (conservative; no BMP fallback).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
# Cross-module read: lab_panel_groups.yaml is the canonical master already
# consumed by output/_fhir_diagnostic_report.py. We read directly from the YAML
# file (no Python import from output/) to keep a single source of truth and
# avoid a circular import (order/ ← output/_fhir_service_request.py imports
# classify_lab_specs from here, so order/ must NOT depend on output/).
# A future refactor PR may move the YAML to a more neutral location
# (clinosim/locale/shared/ or clinosim/modules/order/reference_data/).
_PANEL_YAML = _HERE.parent / "output" / "reference_data" / "lab_panel_groups.yaml"

PANEL_PRIORITY_ORDER: tuple[str, ...] = ("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA")
"""Priority order for panel matching (header of lab_panel_groups.yaml).

Verified against the YAML header comment at import time (assert in
``load_panel_definitions``)."""


def _validate_panel_definitions(panels: dict[str, dict[str, Any]]) -> None:
    """Validate panel YAML schema + canonical-constant cross-reference.

    Raises ``ValueError`` on:
    - PANEL_PRIORITY_ORDER entry missing from YAML
    - YAML panel missing required fields
    - YAML panel not in PANEL_PRIORITY_ORDER (forward-coverage)
    """
    yaml_keys = set(panels.keys())
    expected = set(PANEL_PRIORITY_ORDER)
    missing_in_yaml = expected - yaml_keys
    extra_in_yaml = yaml_keys - expected
    if missing_in_yaml:
        raise ValueError(
            f"lab_panel_groups.yaml missing panels declared in PANEL_PRIORITY_ORDER: "
            f"{sorted(missing_in_yaml)}"
        )
    if extra_in_yaml:
        raise ValueError(
            f"lab_panel_groups.yaml has panels NOT in PANEL_PRIORITY_ORDER "
            f"(silent-no-op risk): {sorted(extra_in_yaml)}"
        )
    for name, panel in panels.items():
        for field in ("loinc", "components", "min_components"):
            if field not in panel:
                raise ValueError(f"Panel '{name}' missing required field '{field}'")
        if not isinstance(panel["components"], list) or not panel["components"]:
            raise ValueError(f"Panel '{name}' has empty or non-list components")
        if not isinstance(panel["min_components"], int) or panel["min_components"] < 1:
            raise ValueError(f"Panel '{name}' min_components must be positive int")


@lru_cache(maxsize=1)
def load_panel_definitions() -> dict[str, dict[str, Any]]:
    """Return panel definitions from lab_panel_groups.yaml (cached, validated)."""
    with _PANEL_YAML.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    panels = data["panels"]
    _validate_panel_definitions(panels)
    return panels


def classify_lab_specs(
    lab_specs: list[dict[str, Any]],
    panels: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Classify lab specs into panel groups + stand-alone tests.

    2-pass deterministic algorithm:
    - Pass A: For each lab_spec, try each panel in PANEL_PRIORITY_ORDER;
      first match wins (handles HCO3 dual-membership: ABG > BMP).
    - Pass B: For each panel, check len(matches) >= min_components.
      If yes, panel is accepted; else its matches become stand-alone.

    Args:
        lab_specs: List of test specs (dicts with a "test" key naming the analyte).
        panels: Panel definitions from ``load_panel_definitions()``.

    Returns:
        Tuple of:
        - ``panel_groups``: ``{panel_name: [lab_spec, ...]}`` — accepted panels.
        - ``stand_alones``: list of lab_specs not assigned to any accepted panel.
    """
    # Pass A: priority-first matching
    panel_match_candidates: dict[str, list[dict[str, Any]]] = {}
    assigned_ids: set[int] = set()
    for lab_spec in lab_specs:
        test_name = lab_spec.get("test", "")
        for panel_name in PANEL_PRIORITY_ORDER:
            if test_name in panels[panel_name]["components"]:
                panel_match_candidates.setdefault(panel_name, []).append(lab_spec)
                assigned_ids.add(id(lab_spec))
                break

    # Pass B: min_components gate
    panel_groups: dict[str, list[dict[str, Any]]] = {}
    accepted_ids: set[int] = set()
    for panel_name, matches in panel_match_candidates.items():
        min_required = panels[panel_name]["min_components"]
        if len(matches) >= min_required:
            panel_groups[panel_name] = matches
            accepted_ids.update(id(s) for s in matches)

    stand_alones = [s for s in lab_specs if id(s) not in accepted_ids]
    return panel_groups, stand_alones
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/modules/order/test_panel_grouping.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Add module __init__.py re-export**

Edit `clinosim/modules/order/__init__.py` to add:
```python
from clinosim.modules.order.panel_grouping import (
    PANEL_PRIORITY_ORDER,
    classify_lab_specs,
    load_panel_definitions,
)

__all__ = [
    *__all__,  # if __all__ exists; else create with these names
    "PANEL_PRIORITY_ORDER",
    "classify_lab_specs",
    "load_panel_definitions",
]
```
(If `__all__` does not exist yet, create it explicitly listing these 3 names plus any existing exports.)

- [ ] **Step 6: Verify import path**

Run: `python -c "from clinosim.modules.order import PANEL_PRIORITY_ORDER, classify_lab_specs, load_panel_definitions; print(PANEL_PRIORITY_ORDER)"`
Expected: prints `('ABG', 'CBC', 'BMP', 'LFT', 'Lipid', 'Coag', 'UA')`

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/order/panel_grouping.py clinosim/modules/order/__init__.py tests/unit/modules/order/test_panel_grouping.py
git commit -m "$(cat <<'EOF'
feat(order): add panel_grouping helper for lab ServiceRequest

2-pass deterministic algorithm: (A) priority-first matching using
PANEL_PRIORITY_ORDER (ABG > CBC > BMP > LFT > Lipid > Coag > UA),
(B) min_components gate. Reuses existing lab_panel_groups.yaml
master (already consumed by _fhir_diagnostic_report.py). Import-time
3-way validation: forward-coverage + reverse-coverage + schema.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 3: Order engine panel-aware integration

**Files:**
- Modify: `clinosim/modules/order/engine.py` — `place_admission_orders` + `place_daily_lab_orders` を panel-aware に
- Test: `tests/unit/modules/order/test_order_engine_panel_aware.py`(新)

**Interfaces:**
- Consumes: `classify_lab_specs` from Task 2、existing `Order` from Task 1
- Produces: Order objects with `panel_key` populated and panel members sharing `ordered_datetime`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/modules/order/test_order_engine_panel_aware.py
"""Unit tests for panel-aware Order generation (PR1)."""

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.order.engine import place_admission_orders
from clinosim.types.encounter import OrderType


def _make_protocol(test_names: list[str]) -> dict:
    """Build a minimal disease protocol with the given lab tests."""
    return {
        "order_protocols": {
            "admission": {
                "labs": [{"test": name, "code_loinc": "X"} for name in test_names],
            }
        },
        "drugs": {"first_line": {"us": []}},
    }


def test_admission_cbc_panel_orders_share_panel_key_and_datetime():
    """4 CBC components → 4 Orders with panel_key='CBC' and identical ordered_datetime."""
    protocol = _make_protocol(["WBC", "Hb", "Hct", "Plt"])
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 4
    panel_keys = {o.panel_key for o in lab_orders}
    assert panel_keys == {"CBC"}
    datetimes = {o.ordered_datetime for o in lab_orders}
    assert len(datetimes) == 1, "panel members must share ordered_datetime"


def test_admission_standalone_tests_have_empty_panel_key():
    """Tests not forming a panel → panel_key='', independent datetimes."""
    protocol = _make_protocol(["Troponin_I", "BNP"])  # neither forms a panel
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 2
    for o in lab_orders:
        assert o.panel_key == ""


def test_admission_mixed_panel_and_standalone():
    """4 CBC + 1 Troponin → 4 panel + 1 stand-alone."""
    protocol = _make_protocol(["WBC", "Hb", "Hct", "Plt", "Troponin_I"])
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    panel_orders = [o for o in lab_orders if o.panel_key == "CBC"]
    standalone = [o for o in lab_orders if o.panel_key == ""]
    assert len(panel_orders) == 4
    assert len(standalone) == 1
    assert standalone[0].display_name == "Troponin_I"


def test_admission_below_min_components_falls_standalone():
    """2 CBC components < min_components=3 → both stand-alone."""
    protocol = _make_protocol(["WBC", "Plt"])
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 2
    for o in lab_orders:
        assert o.panel_key == ""


def test_deterministic_panel_ordering():
    """Same seed → same Orders (panel iteration uses sorted keys)."""
    protocol = _make_protocol(["WBC", "Hb", "Hct", "Plt", "AST", "ALT", "ALP",
                               "T_Bil", "Albumin"])  # CBC + LFT
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders1 = place_admission_orders(
        protocol=protocol, patient_id="pt001", encounter_id="enc001",
        admission_time=base_time, country="us", rng=rng1, ordered_by="doc1",
    )
    orders2 = place_admission_orders(
        protocol=protocol, patient_id="pt001", encounter_id="enc001",
        admission_time=base_time, country="us", rng=rng2, ordered_by="doc1",
    )
    assert [(o.order_id, o.panel_key, o.ordered_datetime) for o in orders1] == \
           [(o.order_id, o.panel_key, o.ordered_datetime) for o in orders2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/order/test_order_engine_panel_aware.py -v`
Expected: FAIL — current engine generates 1 Order per test with independent datetimes

- [ ] **Step 3: Modify place_admission_orders for panel-aware lab generation**

Edit `clinosim/modules/order/engine.py`. Replace the existing lab order generation block (currently around line 140-158) with:

```python
# Lab orders (panel-aware grouping for PR1 ServiceRequest)
panels = load_panel_definitions()
lab_specs = []
for lab_spec in admission.get("labs", []):
    prob = lab_spec.get("probability", 1.0)
    if prob < 1.0 and rng.random() > prob:
        continue
    lab_specs.append(lab_spec)

panel_groups, stand_alones = classify_lab_specs(lab_specs, panels)

# Emit panel Orders (members share ordered_datetime)
order_seq = 0
for panel_name in sorted(panel_groups.keys()):  # deterministic iteration
    members = panel_groups[panel_name]
    panel_time = admission_time + timedelta(minutes=int(rng.normal(5, 3)))
    for lab_spec in members:
        order = Order(
            order_id=f"ORD-{patient_id}-ADM-L{order_seq:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.LAB,
            order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
            display_name=lab_spec["test"],
            urgency=lab_spec.get("urgency", "routine"),
            clinical_intent=f"Admission workup: {lab_spec['test']}",
            ordered_datetime=panel_time,
            ordered_by=ordered_by,
            status=OrderStatus.PLACED,
            panel_key=panel_name,
        )
        orders.append(order)
        order_seq += 1

# Emit stand-alone Orders
for lab_spec in stand_alones:
    order = Order(
        order_id=f"ORD-{patient_id}-ADM-L{order_seq:02d}",
        encounter_id=encounter_id,
        patient_id=patient_id,
        order_type=OrderType.LAB,
        order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
        display_name=lab_spec["test"],
        urgency=lab_spec.get("urgency", "routine"),
        clinical_intent=f"Admission workup: {lab_spec['test']}",
        ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(5, 3))),
        ordered_by=ordered_by,
        status=OrderStatus.PLACED,
        panel_key="",
    )
    orders.append(order)
    order_seq += 1
```

Add the imports at the top of `engine.py`:

```python
from clinosim.modules.order.panel_grouping import (
    classify_lab_specs,
    load_panel_definitions,
)
```

- [ ] **Step 4: Apply same pattern to place_daily_lab_orders**

In `place_daily_lab_orders` (around line 250), apply the same `classify_lab_specs` + emit pattern. Daily monitoring typically results in stand-alone Orders (1-3 tests below any panel's min_components), but the same code path handles both correctly.

```python
# Inside place_daily_lab_orders, after the existing frequency/probability filter loop
# that builds `effective_specs` (the specs that survive prob + freq filters):

panels = load_panel_definitions()
panel_groups, stand_alones = classify_lab_specs(effective_specs, panels)

order_seq = 0
for panel_name in sorted(panel_groups.keys()):
    members = panel_groups[panel_name]
    panel_time = order_time  # daily monitoring shares the morning round time
    for lab_spec in members:
        orders.append(Order(
            order_id=f"ORD-{patient_id}-D{day_number:02d}-L{order_seq:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.LAB,
            order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
            display_name=lab_spec["test"],
            urgency="routine",
            clinical_intent=f"Day {day_number} monitoring: {lab_spec['test']}",
            ordered_datetime=panel_time,
            ordered_by=ordered_by,
            status=OrderStatus.PLACED,
            panel_key=panel_name,
        ))
        order_seq += 1
for lab_spec in stand_alones:
    orders.append(Order(
        order_id=f"ORD-{patient_id}-D{day_number:02d}-L{order_seq:02d}",
        encounter_id=encounter_id,
        patient_id=patient_id,
        order_type=OrderType.LAB,
        order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
        display_name=lab_spec["test"],
        urgency="routine",
        clinical_intent=f"Day {day_number} monitoring: {lab_spec['test']}",
        ordered_datetime=order_time,
        ordered_by=ordered_by,
        status=OrderStatus.PLACED,
        panel_key="",
    ))
    order_seq += 1
```

Refactor the existing loop in `place_daily_lab_orders` so it builds `effective_specs` (the post-filter list) before calling `classify_lab_specs`.

- [ ] **Step 5: Run unit tests to verify they pass**

Run: `pytest tests/unit/modules/order/test_order_engine_panel_aware.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run full Order tests for regression**

Run: `pytest tests/unit -k "order" -v`
Expected: PASS or known-failing pre-existing tests (NOT new failures from this change). Investigate any new failures.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/order/engine.py tests/unit/modules/order/test_order_engine_panel_aware.py
git commit -m "$(cat <<'EOF'
feat(order): panel-aware lab Order generation for ServiceRequest

place_admission_orders + place_daily_lab_orders now classify lab specs
via classify_lab_specs and emit Orders sharing ordered_datetime + panel_key
within each panel (CBC/BMP/LFT/ABG/Lipid/Coag/UA). Stand-alone tests retain
independent datetimes. AD-16 determinism preserved via sorted panel iteration.

NOTE: rng draw count per encounter changes (rng.normal × test_count →
rng.normal × panel_count + standalone_count), so e2e golden NDJSON will
regenerate in Task 11.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 4: ServiceRequest FHIR builder + canonical constants

**Files:**
- Create: `clinosim/modules/output/_fhir_service_request.py`
- Test: `tests/unit/output/test_fhir_service_request.py`

**Interfaces:**
- Consumes: `BundleContext` from `_fhir_common`, Orders from `ctx.record["orders"]`, `load_panel_definitions` from Task 2
- Produces:
  - `SR_ID_PREFIX = "sr-"`
  - `PLACER_ORDER_NUMBER_SYSTEM = "urn:clinosim:placer-order-number"`
  - `LAB_CATEGORY_SNOMED = "108252007"`
  - `LAB_CATEGORY_V2_0074 = "LAB"`
  - `order_to_sr_id(order: Order, panel_counter: dict) -> str`
  - `build_panel_counter(orders: list[Order]) -> dict` — `{(enc, panel_key, datetime): N}` for panel orders; stand-alone orders not indexed
  - `aggregate_panel_status(member_orders: list[Order]) -> str` — returns "active"/"completed"/"revoked"
  - `_bb_service_requests(ctx: BundleContext) -> list[dict]` — builder entry point

- [ ] **Step 1: Write failing tests for canonical constants + helpers**

```python
# tests/unit/output/test_fhir_service_request.py
"""Unit tests for ServiceRequest FHIR builder (PR1)."""

from datetime import datetime

import pytest

from clinosim.modules.output._fhir_service_request import (
    LAB_CATEGORY_SNOMED,
    LAB_CATEGORY_V2_0074,
    PLACER_ORDER_NUMBER_SYSTEM,
    SR_ID_PREFIX,
    _bb_service_requests,
    aggregate_panel_status,
    build_panel_counter,
    order_to_sr_id,
)
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType


def test_canonical_constants():
    assert SR_ID_PREFIX == "sr-"
    assert PLACER_ORDER_NUMBER_SYSTEM == "urn:clinosim:placer-order-number"
    assert LAB_CATEGORY_SNOMED == "108252007"
    assert LAB_CATEGORY_V2_0074 == "LAB"


def _make_order(order_id="O1", panel_key="", status=OrderStatus.PLACED,
                encounter_id="enc1", ordered_datetime=None) -> Order:
    return Order(
        order_id=order_id,
        encounter_id=encounter_id,
        patient_id="pt1",
        order_type=OrderType.LAB,
        order_code="6690-2",
        display_name="WBC",
        ordered_datetime=ordered_datetime or datetime(2026, 6, 29, 8, 5),
        ordered_by="doc1",
        status=status,
        panel_key=panel_key,
    )


def test_order_to_sr_id_standalone():
    """Stand-alone Order → sr-{order_id}."""
    o = _make_order(order_id="ORD-pt1-ADM-L05", panel_key="")
    counter = build_panel_counter([o])
    assert order_to_sr_id(o, counter) == "sr-ORD-pt1-ADM-L05"


def test_order_to_sr_id_panel():
    """Panel Order → sr-{enc}-{panel_key}-{N}, N is encounter-scoped index."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t) for i in range(4)
    ]
    counter = build_panel_counter(orders)
    for o in orders:
        assert order_to_sr_id(o, counter) == "sr-enc1-CBC-1"


def test_panel_counter_increments_per_panel_instance():
    """Same panel ordered twice in same encounter → counter 1, 2."""
    t1 = datetime(2026, 6, 29, 8, 5)
    t2 = datetime(2026, 7, 2, 8, 5)  # day 3
    orders = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t1) for i in range(4)
    ] + [
        _make_order(order_id=f"O{i+10}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t2) for i in range(4)
    ]
    counter = build_panel_counter(orders)
    # First instance (t1) = 1, second (t2) = 2
    assert counter[("enc1", "CBC", t1)] == 1
    assert counter[("enc1", "CBC", t2)] == 2
    assert order_to_sr_id(orders[0], counter) == "sr-enc1-CBC-1"
    assert order_to_sr_id(orders[4], counter) == "sr-enc1-CBC-2"


def test_aggregate_panel_status_all_resulted():
    members = [_make_order(status=OrderStatus.RESULTED) for _ in range(4)]
    assert aggregate_panel_status(members) == "completed"


def test_aggregate_panel_status_all_reviewed():
    members = [_make_order(status=OrderStatus.REVIEWED) for _ in range(4)]
    assert aggregate_panel_status(members) == "completed"


def test_aggregate_panel_status_all_cancelled():
    members = [_make_order(status=OrderStatus.CANCELLED) for _ in range(4)]
    assert aggregate_panel_status(members) == "revoked"


def test_aggregate_panel_status_all_stopped():
    members = [_make_order(status=OrderStatus.STOPPED) for _ in range(4)]
    assert aggregate_panel_status(members) == "revoked"


def test_aggregate_panel_status_mixed_terminal():
    """Mixed RESULTED + CANCELLED → completed (panel done, partial cancel)."""
    members = [
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.CANCELLED),
    ]
    assert aggregate_panel_status(members) == "completed"


def test_aggregate_panel_status_any_non_terminal_yields_active():
    """Any IN_PROGRESS / PLACED / ACCEPTED → active."""
    members = [
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.IN_PROGRESS),
        _make_order(status=OrderStatus.RESULTED),
    ]
    assert aggregate_panel_status(members) == "active"


def test_aggregate_panel_status_all_placed_yields_active():
    members = [_make_order(status=OrderStatus.PLACED) for _ in range(4)]
    assert aggregate_panel_status(members) == "active"


def test_aggregate_panel_status_single_member():
    """Stand-alone (treated as 1-member panel) → same rule."""
    assert aggregate_panel_status([_make_order(status=OrderStatus.RESULTED)]) == "completed"
    assert aggregate_panel_status([_make_order(status=OrderStatus.PLACED)]) == "active"
    assert aggregate_panel_status([_make_order(status=OrderStatus.CANCELLED)]) == "revoked"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/output/test_fhir_service_request.py -v`
Expected: FAIL — module not yet created

- [ ] **Step 3: Create `_fhir_service_request.py` skeleton with constants + helpers**

Create `clinosim/modules/output/_fhir_service_request.py`:

```python
"""ServiceRequest FHIR R4 builder (PR1: lab orders, panel-aware grouping).

Reads CIF Orders (with ``order_type=OrderType.LAB`` and Order.panel_key
populated by the order engine), emits one ServiceRequest per panel
instance (4 CBC tests → 1 SR) and one per stand-alone Order. Panel SR
uses the LOINC panel code (58410-2 for CBC etc.) sourced from
``lab_panel_groups.yaml``; stand-alone uses Order.order_code (individual
LOINC for the analyte).

Compliance:
- US Core ServiceRequest profile (LAB category via SNOMED 108252007).
- JP Core ServiceRequest profile (placerOrderNumber via v2-0203 PLAC
  identifier.type.coding).
- Status aggregation rule (panel SR): any non-terminal member → active;
  all CANCELLED/STOPPED → revoked; otherwise (all terminal, at least one
  RESULTED/REVIEWED) → completed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.types.encounter import Order, OrderStatus, OrderType

# === Canonical constants (silent-no-op defense, PR-90 lesson) ===
SR_ID_PREFIX = "sr-"
PLACER_ORDER_NUMBER_SYSTEM = "urn:clinosim:placer-order-number"
LAB_CATEGORY_SNOMED = "108252007"
LAB_CATEGORY_V2_0074 = "LAB"
V2_0203_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"
V2_0074_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0074"

# Stand-alone Order priority → SR.priority pass-through.
_PRIORITY_MAP = {
    "routine": "routine",
    "urgent": "urgent",
    "stat": "stat",
    "asap": "asap",
}

# Non-terminal OrderStatus values (used in panel SR.status aggregation).
_NON_TERMINAL_STATUSES = frozenset({
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.IN_PROGRESS,
})
_CANCELLED_STATUSES = frozenset({OrderStatus.CANCELLED, OrderStatus.STOPPED})


def aggregate_panel_status(member_orders: list[Order]) -> str:
    """Aggregate panel member OrderStatus into a single FHIR ServiceRequest.status.

    Rule:
    - If ANY member ∈ {PLACED, ACCEPTED, IN_PROGRESS} → "active".
    - Else if ALL members ∈ {CANCELLED, STOPPED} → "revoked".
    - Else → "completed" (all terminal, at least one RESULTED/REVIEWED).
    """
    if not member_orders:
        return "active"
    statuses = {o.status for o in member_orders}
    if statuses & _NON_TERMINAL_STATUSES:
        return "active"
    if statuses <= _CANCELLED_STATUSES:
        return "revoked"
    return "completed"


def build_panel_counter(
    orders: list[Order],
) -> dict[tuple[str, str, datetime], int]:
    """Build encounter-scoped panel instance counter.

    For panel Orders (non-empty panel_key), assign sequential index N per
    distinct (encounter_id, panel_key, ordered_datetime) tuple. Stand-alone
    Orders are not indexed (their SR id uses order_id directly).

    Deterministic: input Orders are sorted by (encounter_id, panel_key,
    ordered_datetime) before assigning N.
    """
    counter: dict[tuple[str, str, datetime], int] = {}
    panel_orders = [o for o in orders if o.panel_key]
    panel_orders_sorted = sorted(
        panel_orders,
        key=lambda o: (o.encounter_id, o.panel_key, o.ordered_datetime),
    )
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for o in panel_orders_sorted:
        key = (o.encounter_id, o.panel_key, o.ordered_datetime)
        if key not in counter:
            scope = (o.encounter_id, o.panel_key)
            seen[scope] += 1
            counter[key] = seen[scope]
    return counter


def order_to_sr_id(
    order: Order,
    panel_counter: dict[tuple[str, str, datetime], int],
) -> str:
    """Compute ServiceRequest.id for an Order (deterministic, stateless).

    Stand-alone: ``sr-{order_id}``.
    Panel: ``sr-{encounter_id}-{panel_key}-{N}`` where N from panel_counter.
    """
    if order.panel_key:
        idx = panel_counter[(order.encounter_id, order.panel_key, order.ordered_datetime)]
        return f"{SR_ID_PREFIX}{order.encounter_id}-{order.panel_key}-{idx}"
    return f"{SR_ID_PREFIX}{order.order_id}"


def _bb_service_requests(ctx: BundleContext) -> list[dict]:
    """Builder entry point — emit ServiceRequest resources for LAB orders.

    Returns a list of raw FHIR ServiceRequest resources to be appended to
    the per-resource NDJSON files by ``_build_bundle``.
    """
    orders: list[Order] = ctx.record.get("orders", []) or []
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    if not lab_orders:
        return []

    counter = build_panel_counter(lab_orders)
    panels = load_panel_definitions()
    country = ctx.country.lower()
    lang = "ja" if country == "jp" else "en"

    # Group panel orders by SR id; stand-alone Orders emit 1 SR each.
    panel_buckets: dict[str, list[Order]] = defaultdict(list)
    standalone_orders: list[Order] = []
    for o in lab_orders:
        if o.panel_key:
            panel_buckets[order_to_sr_id(o, counter)].append(o)
        else:
            standalone_orders.append(o)

    resources: list[dict] = []
    for sr_id, members in sorted(panel_buckets.items()):
        anchor = members[0]
        panel_def = panels[anchor.panel_key]
        sr = _build_panel_sr(sr_id, anchor, members, panel_def, lang)
        resources.append(sr)
    for o in standalone_orders:
        sr = _build_standalone_sr(o, lang)
        resources.append(sr)
    return resources


def _build_panel_sr(
    sr_id: str,
    anchor: Order,
    members: list[Order],
    panel_def: dict[str, Any],
    lang: str,
) -> dict:
    """Build one ServiceRequest resource for a panel (all members share the SR)."""
    panel_loinc = panel_def["loinc"]
    panel_display = code_lookup("loinc", panel_loinc, lang) or panel_def["display"]
    placer_value = sr_id[len(SR_ID_PREFIX):]  # strip "sr-" prefix
    status = aggregate_panel_status(members)
    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(anchor.urgency, "routine"),
        loinc_code=panel_loinc,
        loinc_display=panel_display,
        loinc_text=anchor.panel_key,
        anchor=anchor,
        lang=lang,
    )


def _build_standalone_sr(o: Order, lang: str) -> dict:
    """Build one ServiceRequest resource for a stand-alone test."""
    sr_id = f"{SR_ID_PREFIX}{o.order_id}"
    placer_value = o.order_id
    status = aggregate_panel_status([o])
    loinc_display = code_lookup("loinc", o.order_code, lang) or o.display_name
    return _build_sr_skeleton(
        sr_id=sr_id,
        placer_value=placer_value,
        status=status,
        priority=_PRIORITY_MAP.get(o.urgency, "routine"),
        loinc_code=o.order_code,
        loinc_display=loinc_display,
        loinc_text=o.display_name,
        anchor=o,
        lang=lang,
    )


def _build_sr_skeleton(
    *,
    sr_id: str,
    placer_value: str,
    status: str,
    priority: str,
    loinc_code: str,
    loinc_display: str,
    loinc_text: str,
    anchor: Order,
    lang: str,
) -> dict:
    """Shared SR resource skeleton for panel + stand-alone."""
    snomed_display = "臨床検査" if lang == "ja" else "Laboratory procedure"
    sr: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": sr_id,
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": V2_0203_SYSTEM,
                            "code": "PLAC",
                            "display": "Placer Identifier",
                        }
                    ]
                },
                "system": PLACER_ORDER_NUMBER_SYSTEM,
                "value": placer_value,
            }
        ],
        "status": status,
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": LAB_CATEGORY_SNOMED,
                        "display": snomed_display,
                    },
                    {
                        "system": V2_0074_SYSTEM,
                        "code": LAB_CATEGORY_V2_0074,
                        "display": "Laboratory",
                    },
                ]
            }
        ],
        "priority": priority,
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display,
                }
            ],
            "text": loinc_text,
        },
        "subject": {"reference": f"Patient/{anchor.patient_id}"},
        "encounter": {"reference": f"Encounter/{anchor.encounter_id}"},
        "authoredOn": anchor.ordered_datetime.isoformat(),
    }
    if anchor.ordered_by:
        sr["requester"] = {"reference": f"Practitioner/{anchor.ordered_by}"}
    if anchor.clinical_intent:
        sr["reasonCode"] = [{"text": anchor.clinical_intent}]
    return sr
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/output/test_fhir_service_request.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Add resource-structure tests**

Append to `tests/unit/output/test_fhir_service_request.py`:

```python
def _make_ctx(orders: list[Order], country: str = "us"):
    """Minimal BundleContext for builder testing."""
    from clinosim.modules.output._fhir_common import BundleContext
    return BundleContext(
        record={"orders": orders},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
    )


def test_bb_service_requests_panel_emits_single_sr():
    """4 CBC Orders → 1 ServiceRequest resource."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t) for i in range(4)
    ]
    for o, name in zip(orders, ["WBC", "Hb", "Hct", "Plt"]):
        o.display_name = name
    ctx = _make_ctx(orders)
    resources = _bb_service_requests(ctx)
    assert len(resources) == 1
    sr = resources[0]
    assert sr["resourceType"] == "ServiceRequest"
    assert sr["id"] == "sr-enc1-CBC-1"
    assert sr["intent"] == "order"
    assert sr["code"]["text"] == "CBC"
    assert sr["code"]["coding"][0]["code"] == "58410-2"   # CBC LOINC panel code


def test_bb_service_requests_standalone_emits_one_sr_per_order():
    """3 stand-alone Orders → 3 ServiceRequest resources."""
    orders = [
        _make_order(order_id=f"ORD-pt1-ADM-L0{i}", panel_key="",
                    encounter_id="enc1") for i in range(3)
    ]
    ctx = _make_ctx(orders)
    resources = _bb_service_requests(ctx)
    assert len(resources) == 3
    ids = {r["id"] for r in resources}
    assert ids == {"sr-ORD-pt1-ADM-L00", "sr-ORD-pt1-ADM-L01", "sr-ORD-pt1-ADM-L02"}


def test_bb_service_requests_identifier_plac():
    """Every SR has identifier.type.coding PLAC + placer-order-number system."""
    orders = [_make_order(order_id="ORD-1", panel_key="")]
    ctx = _make_ctx(orders)
    sr = _bb_service_requests(ctx)[0]
    ident = sr["identifier"][0]
    assert ident["system"] == PLACER_ORDER_NUMBER_SYSTEM
    assert ident["type"]["coding"][0]["code"] == "PLAC"
    assert ident["type"]["coding"][0]["system"] == V2_0203_SYSTEM


def test_bb_service_requests_category_dual_coding():
    """Every SR has dual coding: SNOMED 108252007 + v2-0074 LAB."""
    orders = [_make_order(order_id="ORD-1", panel_key="")]
    ctx = _make_ctx(orders)
    sr = _bb_service_requests(ctx)[0]
    coding = sr["category"][0]["coding"]
    codes = {c["code"] for c in coding}
    assert codes == {LAB_CATEGORY_SNOMED, LAB_CATEGORY_V2_0074}


def test_bb_service_requests_jp_locale_uses_ja_snomed_display():
    """JP cohort SR has SNOMED display in Japanese."""
    orders = [_make_order(order_id="ORD-1", panel_key="")]
    ctx = _make_ctx(orders, country="jp")
    sr = _bb_service_requests(ctx)[0]
    snomed_coding = next(c for c in sr["category"][0]["coding"]
                          if c["code"] == LAB_CATEGORY_SNOMED)
    assert snomed_coding["display"] == "臨床検査"


def test_bb_service_requests_empty_orders_returns_empty():
    """No lab Orders → no SR."""
    ctx = _make_ctx([])
    assert _bb_service_requests(ctx) == []


def test_bb_service_requests_skips_non_lab_orders():
    """MEDICATION / IMAGING / etc. Orders are ignored."""
    o_med = _make_order(order_id="M1")
    o_med.order_type = OrderType.MEDICATION
    o_img = _make_order(order_id="I1")
    o_img.order_type = OrderType.IMAGING
    ctx = _make_ctx([o_med, o_img])
    assert _bb_service_requests(ctx) == []
```

- [ ] **Step 6: Run all SR builder tests**

Run: `pytest tests/unit/output/test_fhir_service_request.py -v`
Expected: PASS (19 tests total)

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/output/_fhir_service_request.py tests/unit/output/test_fhir_service_request.py
git commit -m "$(cat <<'EOF'
feat(fhir): add ServiceRequest builder for lab orders

New _fhir_service_request.py builder reads CIF Orders and emits FHIR R4
ServiceRequest resources. Panel-aware grouping: 1 SR per (encounter,
panel_key, ordered_datetime) tuple, stand-alone Orders emit 1 SR each.
JP Core compliant via v2-0203 PLAC identifier type. Status aggregation
rule: any non-terminal → active; all CANCELLED/STOPPED → revoked;
otherwise → completed. Dual category coding (SNOMED 108252007 + v2-0074
LAB) for US Core + JP Core interop.

Builder NOT yet wired into _BUNDLE_BUILDERS — that happens in Task 5.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 5: Wire SR builder into fhir_r4_adapter

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py:_BUNDLE_BUILDERS`
- Test: `tests/integration/test_servicerequest_chain.py`(新、partial — wire-up smoke test only)

**Interfaces:**
- Consumes: `_bb_service_requests` from Task 4
- Produces: ServiceRequest entries in the FHIR Bundle output stream

- [ ] **Step 1: Write failing integration smoke test**

```python
# tests/integration/test_servicerequest_chain.py
"""Integration tests: ServiceRequest end-to-end (PR1)."""

import json
from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4_adapter import available_builders


@pytest.mark.integration
def test_service_request_builder_registered():
    """_bb_service_requests must appear in the builder registry after import."""
    builders = available_builders()
    assert "_bb_service_requests" in builders
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_servicerequest_chain.py::test_service_request_builder_registered -v`
Expected: FAIL — builder not yet registered

- [ ] **Step 3: Wire builder into _BUNDLE_BUILDERS**

Edit `clinosim/modules/output/fhir_r4_adapter.py`. Find the `_BUNDLE_BUILDERS` list (around line 407). Add the import at the top of the file (with other builder imports):

```python
from clinosim.modules.output._fhir_service_request import _bb_service_requests
```

Insert `_bb_service_requests` into `_BUNDLE_BUILDERS` **before** `_bb_labs` so ServiceRequest is emitted in the NDJSON stream before Observations that reference it (no functional dependency, but cleaner ordering):

```python
_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    _bb_coverage,
    _bb_encounters,
    _bb_conditions,
    _bb_allergies,
    _bb_occupation,
    _bb_service_requests,    # ← NEW (PR1, emit before Observations + DiagnosticReports)
    _bb_labs,
    _bb_vitals,
    _bb_microbiology,
    build_lab_panel_reports,
    _bb_medication_requests,
    _bb_medication_admins,
    _bb_procedures,
    _bb_practitioners,
    _build_nursing_observations,
    _build_immunizations,
    _build_family_history,
    _build_code_status,
    _build_smoking_status,
    _build_alcohol_use,
    _build_care_level,
    _build_device,
    _build_device_use,
    _build_hai_conditions,
]
```

- [ ] **Step 4: Run smoke test**

Run: `pytest tests/integration/test_servicerequest_chain.py::test_service_request_builder_registered -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py tests/integration/test_servicerequest_chain.py
git commit -m "$(cat <<'EOF'
feat(fhir): wire ServiceRequest builder into bundle output

_bb_service_requests added to _BUNDLE_BUILDERS before _bb_labs.
ServiceRequest.ndjson will now be produced by run_beta output.
Observation.basedOn / DiagnosticReport.basedOn linkage added in Tasks 6+7.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 6: Observation.basedOn linkage

**Files:**
- Modify: `clinosim/modules/output/_fhir_observations.py` — lab Observation に `basedOn` 追加
- Test: `tests/unit/output/test_fhir_observations_basedon.py`(新、または既存 test ファイルの拡張)

**Interfaces:**
- Consumes: `order_to_sr_id`, `build_panel_counter` from Task 4
- Produces: lab Observations with `basedOn: [{"reference": "ServiceRequest/sr-..."}]`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/output/test_fhir_observations_basedon.py
"""Tests for Observation.basedOn linkage to ServiceRequest (PR1)."""

from datetime import datetime

import pytest

from clinosim.modules.output._fhir_observations import _bb_labs
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType


def _make_lab_order(order_id, panel_key, lab_name, value, t):
    o = Order(
        order_id=order_id,
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.LAB,
        order_code="6690-2",
        display_name=lab_name,
        ordered_datetime=t,
        ordered_by="doc1",
        status=OrderStatus.RESULTED,
        panel_key=panel_key,
    )
    o.result = OrderResult(
        result_datetime=t,
        performed_by="tech1",
        lab_name=lab_name,
        value=value,
        unit="x10^3/uL",
    )
    return o


def _make_ctx(orders):
    return BundleContext(
        record={"orders": orders},
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
    )


def test_lab_observation_has_basedon_panel():
    """Panel lab Observation → basedOn references panel SR."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = [
        _make_lab_order(f"O{i}", "CBC", name, 6.0, t)
        for i, name in enumerate(["WBC", "Hb", "Hct", "Plt"])
    ]
    ctx = _make_ctx(orders)
    obs = _bb_labs(ctx)
    lab_obs = [o for o in obs if o.get("resourceType") == "Observation"]
    assert len(lab_obs) == 4
    for o in lab_obs:
        assert "basedOn" in o
        assert o["basedOn"] == [{"reference": "ServiceRequest/sr-enc1-CBC-1"}]


def test_lab_observation_has_basedon_standalone():
    """Stand-alone lab Observation → basedOn references its own SR."""
    t = datetime(2026, 6, 29, 8, 5)
    o = _make_lab_order("ORD-pt1-ADM-L05", "", "Troponin_I", 0.05, t)
    ctx = _make_ctx([o])
    obs = _bb_labs(ctx)
    assert obs[0]["basedOn"] == [{"reference": "ServiceRequest/sr-ORD-pt1-ADM-L05"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/output/test_fhir_observations_basedon.py -v`
Expected: FAIL — Observations have no `basedOn` field yet

- [ ] **Step 3: Modify _fhir_observations.py to add basedOn**

Open `clinosim/modules/output/_fhir_observations.py`. Find the lab Observation emission code (`_bb_labs` or whatever it's named). Wherever an Observation dict is constructed for a LAB Order, add `basedOn`.

Add at the top of `_fhir_observations.py`:
```python
from clinosim.modules.output._fhir_service_request import (
    build_panel_counter,
    order_to_sr_id,
)
```

In the `_bb_labs` entry point, before iterating Orders, pre-compute the panel counter once per call:
```python
lab_orders = [o for o in ctx.record.get("orders", []) if o.order_type == OrderType.LAB]
panel_counter = build_panel_counter(lab_orders)
```

For each lab Observation dict constructed from `order` (and its `order.result`), add:
```python
sr_id = order_to_sr_id(order, panel_counter)
observation_dict["basedOn"] = [{"reference": f"ServiceRequest/{sr_id}"}]
```

(Exact placement depends on the existing `_bb_labs` body. Read the function in full, find the dict construction site, add the 2 lines just before the dict is appended to the output list.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/output/test_fhir_observations_basedon.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full Observation tests for regression**

Run: `pytest tests/unit/output/ -v`
Expected: PASS (or same pre-existing failures as on master, no new regressions)

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/output/_fhir_observations.py tests/unit/output/test_fhir_observations_basedon.py
git commit -m "$(cat <<'EOF'
feat(fhir): add Observation.basedOn linkage to ServiceRequest

Every lab Observation now carries basedOn = [{reference:
ServiceRequest/sr-...}]. Panel member Observations all share the panel
SR (4 CBC Observations → all reference sr-enc1-CBC-1). Stand-alone
Observations reference their own SR. Implementation reuses
order_to_sr_id + build_panel_counter from _fhir_service_request.py
(canonical writer↔reader shared id derivation).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 7: DiagnosticReport.basedOn linkage

**Files:**
- Modify: `clinosim/modules/output/_fhir_diagnostic_report.py` — `DiagnosticReport.basedOn` 追加
- Test: `tests/unit/output/test_fhir_diagnostic_report_basedon.py`(新)

**Interfaces:**
- Consumes: `order_to_sr_id`, `build_panel_counter` from Task 4
- Produces: DiagnosticReports with `basedOn` referencing unique panel SR(s)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/output/test_fhir_diagnostic_report_basedon.py
"""Tests for DiagnosticReport.basedOn linkage (PR1)."""

from datetime import datetime

import pytest

from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType


def _make_panel_orders(panel_key, members, t):
    out = []
    for i, name in enumerate(members):
        o = Order(
            order_id=f"O{i}",
            encounter_id="enc1",
            patient_id="pt1",
            order_type=OrderType.LAB,
            order_code="X",
            display_name=name,
            ordered_datetime=t,
            ordered_by="doc1",
            status=OrderStatus.RESULTED,
            panel_key=panel_key,
        )
        o.result = OrderResult(
            result_datetime=t, performed_by="tech1", lab_name=name, value=6.0, unit="u",
        )
        out.append(o)
    return out


def _make_ctx(orders):
    return BundleContext(
        record={"orders": orders},
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
    )


def test_diagnostic_report_basedon_single_panel():
    """CBC panel report → basedOn = [single panel SR]."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = _make_panel_orders("CBC", ["WBC", "Hb", "Hct", "Plt"], t)
    ctx = _make_ctx(orders)
    reports = build_lab_panel_reports(ctx)
    cbc_report = next(r for r in reports if "CBC" in str(r.get("code", {})))
    assert cbc_report["basedOn"] == [{"reference": "ServiceRequest/sr-enc1-CBC-1"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/output/test_fhir_diagnostic_report_basedon.py -v`
Expected: FAIL — DiagnosticReport has no `basedOn`

- [ ] **Step 3: Modify _fhir_diagnostic_report.py**

Open the file. Find `build_lab_panel_reports`. Inside the function where each report dict is constructed for a panel:

Add imports at top:
```python
from clinosim.modules.output._fhir_service_request import (
    build_panel_counter,
    order_to_sr_id,
)
```

Before the report-emission loop, pre-compute the panel counter:
```python
lab_orders = [o for o in ctx.record.get("orders", []) if o.order_type == OrderType.LAB]
panel_counter = build_panel_counter(lab_orders)
```

When building each panel report, identify the Orders contributing to that panel (the existing code finds component Observations → underlying Orders) and:
```python
contributing_orders = [o for o in lab_orders
                       if o.panel_key == panel_name
                       and o.encounter_id == encounter_id]
sr_ids = sorted({order_to_sr_id(o, panel_counter) for o in contributing_orders})
report_dict["basedOn"] = [{"reference": f"ServiceRequest/{sid}"} for sid in sr_ids]
```

(Exact placement depends on existing code; the key invariant is that every emitted DiagnosticReport carries `basedOn` referencing every SR whose Observations are aggregated into it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/output/test_fhir_diagnostic_report_basedon.py -v`
Expected: PASS

- [ ] **Step 5: Run regression on DiagnosticReport tests**

Run: `pytest tests/unit/output -k "diagnostic" -v`
Expected: PASS (no new regressions)

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/output/_fhir_diagnostic_report.py tests/unit/output/test_fhir_diagnostic_report_basedon.py
git commit -m "$(cat <<'EOF'
feat(fhir): add DiagnosticReport.basedOn linkage to ServiceRequest

Every lab DiagnosticReport now carries basedOn referencing the
ServiceRequest(s) for the contributing Orders. CBC panel report →
basedOn = [sr-enc-CBC-N]. Reuses build_panel_counter + order_to_sr_id
from _fhir_service_request.py (consistent writer↔reader derivation).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 8: audit module (lift_firing_proof + clinical axis basedOn coverage)

**Files:**
- Create: `clinosim/modules/order/audit.py`
- Modify: `clinosim/audit/axes/clinical.py` — basedOn coverage gate
- Test: `tests/unit/audit/test_order_audit.py`

**Interfaces:**
- Consumes: ServiceRequest + Observation + DiagnosticReport NDJSON from Tasks 4-7
- Produces: `ModuleAuditSpec` registered as `"order_service_request"`, 7 equality_checks in `lift_firing_proof`

- [ ] **Step 1: Write failing test for ModuleAuditSpec registration**

```python
# tests/unit/audit/test_order_audit.py
"""Unit tests for order ServiceRequest audit module (PR1)."""

import pytest

import clinosim.modules.order.audit  # noqa: F401 — import side-effect registers the module
from clinosim.audit.registry import _reset_for_test, get_registered_specs


def test_order_audit_module_registered():
    """Importing modules.order.audit registers ModuleAuditSpec 'order_service_request'."""
    specs = get_registered_specs()
    names = {s.name for s in specs}
    assert "order_service_request" in names


def test_lift_firing_proof_has_required_equality_checks():
    """The lift_firing_proof must contain all 7 canonical equality_checks."""
    specs = get_registered_specs()
    spec = next(s for s in specs if s.name == "order_service_request")
    proof = spec.lift_firing_proof
    assert "equality_checks" in proof
    checks = proof["equality_checks"]
    # 7 canonical checks from spec section 5.4
    expected_substrings = [
        "PLACER_ORDER_NUMBER_SYSTEM",
        "108252007",
        "LAB",
        "ServiceRequest count > 0 when lab Order count > 0",
        "panel SR count > 0",
        "every basedOn ref resolves",
        "SR id schemes are disjoint",
    ]
    assert len(checks) >= 7
    text = " ".join(repr(c) for c in checks)
    for substring in expected_substrings:
        assert substring in text, f"Missing equality_check substring: {substring}"
```

(`get_registered_specs` is a function in `clinosim/audit/registry.py`. If it doesn't exist with that exact name, check the registry module and use the actual accessor — common alternatives: `_REGISTRY`, `get_specs()`, `iter_specs()`.)

- [ ] **Step 2: Verify get_registered_specs accessor exists**

Run: `grep -n "def get_registered\|def get_specs\|def iter_specs\|_REGISTRY" clinosim/audit/registry.py`
If the function name in the test does not match, update the test (do not redefine the registry's API).

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/audit/test_order_audit.py -v`
Expected: FAIL — `clinosim.modules.order.audit` module does not yet exist

- [ ] **Step 4: Create the audit module**

Create `clinosim/modules/order/audit.py`:

```python
"""Audit module for lab ServiceRequest (PR1 — AD-60 plug-in #3 after HAI and antibiotic).

Registered checks (4 axes):
- structural: SR resource validity, identifier PLAC presence, dual category coding
- clinical_acceptance: panel SR share rate, basedOn coverage on lab Observations
- jp_language: JP cohort SR.code.display in Japanese
- lift_firing_proof: 7 equality_checks (canonical-constant + emission proofs)

The lift_firing_proof is the load-bearing silent-no-op gate (PR-90 lesson).
"""

from __future__ import annotations

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.output._fhir_service_request import (
    LAB_CATEGORY_SNOMED,
    LAB_CATEGORY_V2_0074,
    PLACER_ORDER_NUMBER_SYSTEM,
    SR_ID_PREFIX,
)

_EQUALITY_CHECKS = [
    # Canonical constants
    f"PLACER_ORDER_NUMBER_SYSTEM == '{PLACER_ORDER_NUMBER_SYSTEM}'",
    f"category contains SNOMED '{LAB_CATEGORY_SNOMED}' (Laboratory procedure)",
    f"category contains v2-0074 '{LAB_CATEGORY_V2_0074}'",
    # Emission proofs
    "ServiceRequest count > 0 when lab Order count > 0",
    "panel SR count > 0 when panel_key non-empty Orders exist",
    "every basedOn ref resolves in NDJSON",
    "SR id schemes are disjoint (panel sr-{enc}-... ∩ stand-alone sr-ORD-... = ∅)",
]

register_audit_module(
    ModuleAuditSpec(
        name="order_service_request",
        structural_checks=[
            "every lab Order has ServiceRequest emission",
            "every panel-grouped Order group emits a single SR with the LOINC panel code",
            "every SR has identifier.type.coding[0].code == 'PLAC'",
            "every SR has dual category coding (SNOMED + v2-0074)",
        ],
        clinical_acceptance={
            "panel_sr_share_rate": (
                "When cohort contains CBC/BMP/LFT/ABG orders, at least 50% of those "
                "panel Orders share an SR with siblings (rare-event: n<30 → WARN)."
            ),
            "basedon_coverage": (
                "100% of LAB Observations carry basedOn referencing an existing SR "
                "(n<30 → WARN)."
            ),
        },
        jp_language_checks=[
            "ServiceRequest.code.coding[].display = Japanese for JP locale "
            "(fallback to English if loinc_display_ja.yaml is incomplete; warning list emitted)",
            "category SNOMED display = '臨床検査' for JP locale",
        ],
        lift_firing_proof={
            "equality_checks": _EQUALITY_CHECKS,
        },
    )
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/audit/test_order_audit.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Add basedOn coverage gate to audit/axes/clinical.py**

Open `clinosim/audit/axes/clinical.py`. Add a new check function alongside existing axes:

```python
def _check_lab_observation_basedon_coverage(
    output_dir: Path,
) -> AxisResult:
    """Verify every LAB Observation carries basedOn pointing to an existing ServiceRequest.

    Silent-no-op gate (PR-90 lesson): without this, the basedOn field may be missing on
    all Observations and downstream consumers (CDSS, EHR migration test) would silently
    receive orphan Observations.
    """
    obs_path = output_dir / "Observation.ndjson"
    sr_path = output_dir / "ServiceRequest.ndjson"
    if not obs_path.exists() or not sr_path.exists():
        return AxisResult(passed=True, info={"reason": "no obs or SR file (empty cohort)"})

    sr_ids: set[str] = set()
    with sr_path.open() as f:
        for line in f:
            obj = json.loads(line)
            sr_ids.add(obj["id"])

    lab_obs_count = 0
    missing_basedon = 0
    dangling_refs: list[str] = []
    with obs_path.open() as f:
        for line in f:
            obj = json.loads(line)
            cat = obj.get("category", [])
            # detect LAB category
            is_lab = any(
                c.get("code") in {"laboratory", "LAB"}
                for cat_entry in cat
                for c in cat_entry.get("coding", [])
            )
            if not is_lab:
                continue
            lab_obs_count += 1
            based_on = obj.get("basedOn", [])
            if not based_on:
                missing_basedon += 1
                continue
            for ref in based_on:
                ref_str = ref.get("reference", "")
                if not ref_str.startswith("ServiceRequest/"):
                    continue
                sr_id = ref_str.removeprefix("ServiceRequest/")
                if sr_id not in sr_ids:
                    dangling_refs.append(sr_id)

    if lab_obs_count < 30:
        return AxisResult(passed=True, info={
            "verdict": "WARN",
            "reason": f"lab_obs_count={lab_obs_count} < 30 (rare-event tolerated)",
            "missing_basedon": missing_basedon,
            "dangling_refs": dangling_refs[:10],
        })
    return AxisResult(
        passed=(missing_basedon == 0 and not dangling_refs),
        info={
            "lab_obs_count": lab_obs_count,
            "missing_basedon": missing_basedon,
            "dangling_refs_sample": dangling_refs[:10],
        },
    )
```

(Adapt `AxisResult` / `output_dir` parameter / existing axis registration to the actual signature in your `clinical.py`. The existing module has analogous functions — model this after them.)

Wire this check into the `clinical` axis runner. Find the existing list of clinical-axis check functions and append `_check_lab_observation_basedon_coverage`.

- [ ] **Step 7: Run the full test suite**

Run: `pytest tests/unit tests/integration -m "unit or integration" -x --ignore=tests/e2e -q 2>&1 | tail -30`
Expected: All non-pre-existing-baseline tests PASS.

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/order/audit.py clinosim/audit/axes/clinical.py tests/unit/audit/test_order_audit.py
git commit -m "$(cat <<'EOF'
feat(audit): add order_service_request audit module + basedOn gate

clinosim/modules/order/audit.py registers ModuleAuditSpec
'order_service_request' with 7 lift_firing_proof equality_checks
(canonical constants + emission + ref-resolution + disjoint id schemes).
clinosim/audit/axes/clinical.py gains _check_lab_observation_basedon_coverage:
verifies 100% of LAB Observations carry basedOn pointing to an existing
ServiceRequest. n<30 → WARN (rare-event tolerated).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 9: Integration tests (chain, basedon_coverage, determinism, snapshot)

**Files:**
- Create: `tests/integration/test_servicerequest_basedon_coverage.py`
- Create: `tests/integration/test_servicerequest_determinism.py`
- Create: `tests/integration/test_servicerequest_snapshot.py`
- Modify: `tests/integration/test_servicerequest_chain.py` (extend from Task 5 smoke test)

**Interfaces:**
- Consumes: full pipeline (run_beta) + output NDJSON
- Produces: regression guards for ServiceRequest end-to-end

- [ ] **Step 1: Write the full chain test (extends Task 5 smoke test)**

Append to `tests/integration/test_servicerequest_chain.py`:

```python
import json
import subprocess
import tempfile
from pathlib import Path


@pytest.mark.integration
def test_run_beta_emits_service_request_ndjson_us():
    """run_beta US 100-patient cohort emits non-empty ServiceRequest.ndjson."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            ["clinosim", "run-beta", "--country", "us", "--population", "100",
             "--seed", "42", "--output", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        sr_file = out / "ServiceRequest.ndjson"
        assert sr_file.exists()
        with sr_file.open() as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) > 0, "ServiceRequest.ndjson must be non-empty"
        # validate first resource
        sr = json.loads(lines[0])
        assert sr["resourceType"] == "ServiceRequest"
        assert sr["intent"] == "order"
        assert "identifier" in sr
        plac = sr["identifier"][0]["type"]["coding"][0]
        assert plac["code"] == "PLAC"


@pytest.mark.integration
def test_run_beta_emits_service_request_jp_with_ja_display():
    """JP cohort: SR.code.display is in Japanese (or fallback en + warning)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            ["clinosim", "run-beta", "--country", "jp", "--population", "100",
             "--seed", "42", "--output", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        sr_file = out / "ServiceRequest.ndjson"
        assert sr_file.exists()
        with sr_file.open() as f:
            for line in f:
                sr = json.loads(line)
                # category SNOMED display must be in JP
                snomed = next(
                    c for entry in sr["category"]
                    for c in entry["coding"]
                    if c["code"] == "108252007"
                )
                assert snomed["display"] == "臨床検査"
                break  # one sample suffices
```

- [ ] **Step 2: Run chain tests**

Run: `pytest tests/integration/test_servicerequest_chain.py -v -m integration`
Expected: PASS (3 tests)

- [ ] **Step 3: Write basedon coverage test (★ silent-no-op gate)**

Create `tests/integration/test_servicerequest_basedon_coverage.py`:

```python
"""Integration: basedOn coverage — every LAB Observation references an existing SR."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


def _run_beta(country: str, n: int, seed: int, out: Path) -> None:
    result = subprocess.run(
        ["clinosim", "run-beta", "--country", country, "--population", str(n),
         "--seed", str(seed), "--output", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def _load_ndjson(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.mark.integration
def test_lab_observation_basedon_coverage_us():
    """100% of LAB Observations carry basedOn referencing an existing SR (US, n=200)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        _run_beta("us", 200, 42, out)
        srs = {r["id"] for r in _load_ndjson(out / "ServiceRequest.ndjson")}
        obs = _load_ndjson(out / "Observation.ndjson")
        lab_obs = [
            o for o in obs
            if any(c.get("code") in {"laboratory", "LAB"}
                   for entry in o.get("category", [])
                   for c in entry.get("coding", []))
        ]
        missing = [o for o in lab_obs if not o.get("basedOn")]
        dangling = []
        for o in lab_obs:
            for ref in o.get("basedOn", []):
                sr_id = ref.get("reference", "").removeprefix("ServiceRequest/")
                if sr_id and sr_id not in srs:
                    dangling.append(sr_id)
        assert not missing, f"{len(missing)} LAB Observations missing basedOn"
        assert not dangling, f"{len(dangling)} dangling SR refs: {dangling[:5]}"


@pytest.mark.integration
def test_diagnostic_report_basedon_coverage_us():
    """Every lab DiagnosticReport carries basedOn pointing to existing SR(s)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        _run_beta("us", 200, 42, out)
        srs = {r["id"] for r in _load_ndjson(out / "ServiceRequest.ndjson")}
        reports = _load_ndjson(out / "DiagnosticReport.ndjson")
        lab_reports = [
            r for r in reports
            if any(c.get("code") in {"laboratory", "LAB"}
                   for entry in r.get("category", [])
                   for c in entry.get("coding", []))
        ]
        for r in lab_reports:
            assert r.get("basedOn"), f"DiagnosticReport {r['id']} missing basedOn"
            for ref in r["basedOn"]:
                sr_id = ref["reference"].removeprefix("ServiceRequest/")
                assert sr_id in srs, f"dangling SR ref {sr_id}"


@pytest.mark.integration
def test_panel_members_share_sr_id():
    """In a CBC panel, the 3-4 component Observations share a single basedOn ref."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        _run_beta("us", 200, 42, out)
        obs = _load_ndjson(out / "Observation.ndjson")
        by_encounter = {}
        for o in obs:
            if o.get("code", {}).get("text") in {"WBC", "Hb", "Hct", "Plt"}:
                enc = o.get("encounter", {}).get("reference", "")
                ts = o.get("effectiveDateTime", "")
                key = (enc, ts)
                by_encounter.setdefault(key, []).append(o)
        # at least one (enc, ts) group has 3-4 obs sharing the same basedOn SR
        found_panel = False
        for group in by_encounter.values():
            if len(group) >= 3:
                sr_refs = {
                    o["basedOn"][0]["reference"] for o in group if o.get("basedOn")
                }
                if len(sr_refs) == 1:
                    found_panel = True
                    break
        if not found_panel:
            pytest.skip("no CBC panel emitted in 200-patient cohort (rare event)")
```

- [ ] **Step 4: Run basedon tests**

Run: `pytest tests/integration/test_servicerequest_basedon_coverage.py -v -m integration`
Expected: PASS

- [ ] **Step 5: Write determinism test**

Create `tests/integration/test_servicerequest_determinism.py`:

```python
"""Integration: ServiceRequest.ndjson is byte-identical across same-seed runs (AD-16)."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration
def test_service_request_ndjson_byte_identical_us():
    """Same seed × 2 → identical ServiceRequest.ndjson sha256."""
    hashes = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            subprocess.run(
                ["clinosim", "run-beta", "--country", "us", "--population", "50",
                 "--seed", "42", "--output", str(out)],
                check=True, capture_output=True,
            )
            hashes.append(_sha256(out / "ServiceRequest.ndjson"))
    assert hashes[0] == hashes[1], f"Determinism broken: {hashes}"
```

- [ ] **Step 6: Run determinism test**

Run: `pytest tests/integration/test_servicerequest_determinism.py -v -m integration`
Expected: PASS

- [ ] **Step 7: Write snapshot test**

Create `tests/integration/test_servicerequest_snapshot.py`:

```python
"""Integration: snapshot mid-day yields SR.status='active' for unresulted lab orders."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.mark.integration
def test_snapshot_yields_active_sr_with_no_observation():
    """An Order PLACED before snapshot but not yet RESULTED → SR.status='active' + no Obs."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        # Mid-day snapshot: end-date 2026-01-15 11:00 forces orders placed before this
        # but not yet resulted (lab TAT typically 30-60 min) to remain in-progress.
        result = subprocess.run(
            ["clinosim", "run-beta", "--country", "us", "--population", "100",
             "--seed", "42", "--start", "2026-01-10", "--end", "2026-01-15",
             "--snapshot-time", "11:00", "--output", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        with (out / "ServiceRequest.ndjson").open() as f:
            srs = [json.loads(l) for l in f if l.strip()]
        # at least some SRs are 'active'
        active = [s for s in srs if s.get("status") == "active"]
        assert active, "expected at least some 'active' SR at snapshot mid-day"
        # and the corresponding Observations should not exist
        with (out / "Observation.ndjson").open() as f:
            obs_ids = {
                ref.get("reference", "").removeprefix("ServiceRequest/")
                for o in (json.loads(l) for l in f if l.strip())
                for ref in o.get("basedOn", [])
            }
        for sr in active:
            assert sr["id"] not in obs_ids, \
                f"SR {sr['id']} is active but has Observation"
```

(If `--snapshot-time` flag doesn't exist, use whatever existing snapshot CLI options are present — adapt to match.)

- [ ] **Step 8: Run snapshot test**

Run: `pytest tests/integration/test_servicerequest_snapshot.py -v -m integration`
Expected: PASS (or note any limitations and skip if CLI doesn't yet support hour granularity)

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_servicerequest_*.py
git commit -m "$(cat <<'EOF'
test(integration): ServiceRequest chain, basedOn coverage, determinism, snapshot

4 integration test files:
- test_servicerequest_chain.py: end-to-end emission (US + JP)
- test_servicerequest_basedon_coverage.py: silent-no-op gate, 100% basedOn
- test_servicerequest_determinism.py: AD-16 byte-identical NDJSON
- test_servicerequest_snapshot.py: mid-day snapshot → active SR, no Obs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 10: Run audit framework + verify clean

**Files:**
- None modified (verification only)

**Interfaces:**
- Consumes: `clinosim audit run` CLI + integration cohort
- Produces: audit report (filed in DQR in Task 13)

- [ ] **Step 1: Generate a small US cohort**

Run:
```bash
mkdir -p scratchpad/pr1_audit_us
clinosim run-beta --country us --population 500 --seed 42 --output scratchpad/pr1_audit_us/
```
Expected: completes without error, NDJSON files created.

- [ ] **Step 2: Run audit on the cohort**

Run:
```bash
clinosim audit run scratchpad/pr1_audit_us/ --module order_service_request
```
Expected: 4 axes PASS (or n<30 WARN where appropriate). Any FAIL → investigate, fix code, re-run.

- [ ] **Step 3: Generate JP cohort + audit**

Run:
```bash
mkdir -p scratchpad/pr1_audit_jp
clinosim run-beta --country jp --population 500 --seed 42 --output scratchpad/pr1_audit_jp/
clinosim audit run scratchpad/pr1_audit_jp/ --module order_service_request
```
Expected: 4 axes PASS (or WARN). Specifically, jp_language axis must show ja display present.

- [ ] **Step 4: If LOINC ja translations are missing**

If jp_language axis reports `loinc_display_ja.yaml` missing entries (panel LOINC codes 58410-2, 51990-0, 24325-3, 24338-6, 57698-3 and any others), supplement the YAML.

Open `clinosim/modules/output/reference_data/loinc_display_ja.yaml` (or wherever JP LOINC display is stored — check `_fhir_localization.py` for the canonical path). Add missing entries verified against jpfhir.jp or JCCLS authoritative source:

```yaml
# Example additions (verify each against authoritative source):
"58410-2": "全血球計算 (CBC)"
"51990-0": "基礎代謝パネル (BMP)"
"24325-3": "肝機能パネル (LFT)"
"24338-6": "動脈血ガス (ABG)"
"57698-3": "脂質パネル (Lipid)"
# ... any other panel/stand-alone codes flagged by audit
```

Re-run audit until jp_language PASS.

- [ ] **Step 5: Commit any YAML supplementation**

```bash
git add clinosim/modules/output/reference_data/loinc_display_ja.yaml  # adjust path as needed
git commit -m "$(cat <<'EOF'
i18n(loinc): add JP display for lab panel codes (PR1 audit gap fill)

LOINC panel codes (CBC 58410-2, BMP 51990-0, LFT 24325-3, ABG 24338-6,
Lipid 57698-3) discovered by audit jp_language axis on JP cohort.
Sources: jpfhir.jp + JCCLS-JSLM v137 (authoritative per CLAUDE.md).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```
(Skip this commit if no YAML changes are needed.)

---

## Task 11: E2E golden regeneration

**Files:**
- Update: `tests/e2e/golden/` per-resource NDJSON snapshots (path varies per existing test layout)

**Interfaces:**
- Consumes: e2e harness (existing)
- Produces: new golden NDJSON files that include `ServiceRequest.ndjson` and updated `Observation.ndjson` + `DiagnosticReport.ndjson` with `basedOn` fields

- [ ] **Step 1: Identify the e2e golden directory**

Run: `find tests/e2e -type d -name "golden*" -o -name "snapshot*" -o -name "expected*" | head -5`
Expected: a path like `tests/e2e/golden/` or similar containing NDJSON snapshots.

- [ ] **Step 2: Inspect a golden file to confirm structure**

Run: `ls tests/e2e/golden/ | head -20 && head -2 tests/e2e/golden/Observation.ndjson 2>/dev/null || head -2 tests/e2e/golden/*/Observation.ndjson 2>/dev/null | head -4`

- [ ] **Step 3: Regenerate the golden**

Find the existing regeneration command — typically there's a helper like:
```bash
python -m clinosim.tests.regenerate_golden  # or similar
# or pytest tests/e2e -k "regenerate" --regen-golden
```

Look for instructions in:
- `tests/e2e/README.md`
- `tests/e2e/conftest.py`
- existing scripts in `scripts/` or `scratchpad/`

If no auto-regen script exists, manually:
```bash
clinosim run-beta --country us --population <golden_size> --seed <golden_seed> \
    --output tests/e2e/golden/us_<scenario>/
clinosim run-beta --country jp --population <golden_size> --seed <golden_seed> \
    --output tests/e2e/golden/jp_<scenario>/
```
(Match the existing golden scenarios — read existing test files to find seeds/sizes.)

- [ ] **Step 4: Verify e2e tests pass against new golden**

Run: `pytest tests/e2e -v -m e2e`
Expected: PASS (the golden now matches the new output).

- [ ] **Step 5: Inspect golden diff to confirm changes are scoped to lab-related resources**

Run: `git diff --stat tests/e2e/golden/`
Expected: only `ServiceRequest.ndjson` (new), `Observation.ndjson` (basedOn added on lab obs), `DiagnosticReport.ndjson` (basedOn added on lab reports) should change. If `Patient.ndjson` / `Encounter.ndjson` / `MedicationRequest.ndjson` change, investigate — that would indicate determinism bleed beyond lab path.

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/golden/
git commit -m "$(cat <<'EOF'
test(e2e): regenerate golden for ServiceRequest emission

PR1 adds ServiceRequest.ndjson and adds basedOn fields to lab
Observation.ndjson + DiagnosticReport.ndjson. ordered_datetime for panel
members now shares the panel-instance time (rng.normal draw consolidated
from per-test to per-panel), so all lab Observation effectiveDateTime
values within a panel match.

Verified: diff scope = lab-related NDJSON only (Patient / Encounter /
MedicationRequest / others unchanged).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 12: Full test sweep pre-merge gate

**Files:**
- None modified (verification only — gate per memory `Pre-merge gate` session-22 lesson)

- [ ] **Step 1: Run the FULL unit + integration sweep**

Run: `pytest tests/unit tests/integration -m "unit or integration" -q 2>&1 | tail -40`
Expected: All PASS except pre-existing baseline failures (e.g., `_reset_for_test` ordering test files documented in TODO.md). Any **NEW** failure must be investigated and fixed.

- [ ] **Step 2: Run e2e sweep**

Run: `pytest tests/e2e -m e2e -q 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 3: Run ruff + mypy**

Run:
```bash
ruff check clinosim tests
mypy --strict clinosim
```
Expected: zero violations.

- [ ] **Step 4: If anything fails**

Fix in-place (do not skip). Re-run from Step 1.

---

## Task 13: DQR (production cohort + DQR doc)

**Files:**
- Create: `docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md`

- [ ] **Step 1: Generate production cohort**

```bash
mkdir -p scratchpad/pr1_us10k scratchpad/pr1_jp5k
clinosim run-beta --country us --population 10000 --seed 42 --output scratchpad/pr1_us10k/
clinosim run-beta --country jp --population 5000  --seed 42 --output scratchpad/pr1_jp5k/
```

- [ ] **Step 2: Run audit on both**

```bash
clinosim audit run scratchpad/pr1_us10k/ --module order_service_request | tee scratchpad/pr1_us10k_audit.txt
clinosim audit run scratchpad/pr1_jp5k/  --module order_service_request | tee scratchpad/pr1_jp5k_audit.txt
```
Expected: all 4 axes PASS or WARN (no FAIL).

- [ ] **Step 3: Gather summary metrics**

```bash
echo "=== US ===" > scratchpad/pr1_dqr_metrics.txt
wc -l scratchpad/pr1_us10k/ServiceRequest.ndjson >> scratchpad/pr1_dqr_metrics.txt
wc -l scratchpad/pr1_us10k/Observation.ndjson    >> scratchpad/pr1_dqr_metrics.txt
wc -l scratchpad/pr1_us10k/DiagnosticReport.ndjson >> scratchpad/pr1_dqr_metrics.txt
python -c "
import json
from collections import Counter
panels = Counter()
with open('scratchpad/pr1_us10k/ServiceRequest.ndjson') as f:
    for line in f:
        sr = json.loads(line)
        text = sr.get('code', {}).get('text', '')
        panels[text] += 1
print('top SR codes:', panels.most_common(15))
" >> scratchpad/pr1_dqr_metrics.txt
echo "=== JP ===" >> scratchpad/pr1_dqr_metrics.txt
wc -l scratchpad/pr1_jp5k/ServiceRequest.ndjson >> scratchpad/pr1_dqr_metrics.txt
```

- [ ] **Step 4: Write DQR doc**

Create `docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md` covering 4 axes:

```markdown
# PR1 ServiceRequest (Lab) — Data Quality Review

**Date:** 2026-06-29
**Branch:** feature/pr1-servicerequest-lab
**Cohort:** US p=10,000 seed=42 + JP p=5,000 seed=42
**Spec:** docs/superpowers/specs/2026-06-29-pr1-servicerequest-lab-design.md

## Verdict: PASS / PASS-WITH-WARN / FAIL

[fill from actual run]

## 1. Structural

- ServiceRequest.ndjson lines: US <N1> / JP <N2>
- All resources `resourceType == "ServiceRequest"`
- All have `identifier.type.coding[0].code == "PLAC"` (audit verified)
- All have dual category coding (SNOMED 108252007 + v2-0074 LAB) (audit verified)
- Reference integrity: every Observation.basedOn / DiagnosticReport.basedOn resolves

## 2. Clinical Integrity

- Panel SR share rate: <P>% of CBC/BMP/LFT/ABG-eligible tests grouped into panel SRs
- Stand-alone SR count: <S>
- Status distribution: completed=<C>, active=<A>, revoked=<R>
- Snapshot mid-day cohort: <K> active SRs without Observation (= correctly ordered, not yet resulted)

## 3. JP Language Quality

- JP cohort SR.code.coding[].display in Japanese: <X>% (target: 100%)
- JP cohort category SNOMED display = "臨床検査": <Y>% (target: 100%)
- LOINC ja missing entries discovered + added: [list]

## 4. EHR/EMR Sample Dataset Goal

- Unique LOINC panel codes emitted: <count>
- Unique LOINC individual lab codes emitted: <count>
- Interop value verified: panel order workflow recognizable to CDSS / NLP / EHR-migration evaluation targets
- PR1 establishes the foundation for Tier 1 #2-#7 (all consume ServiceRequest refs)

## Issues Found

[None / list]

## Sign-off

PR1 is ship-ready / requires fix.
```

- [ ] **Step 5: Commit DQR**

```bash
git add docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md
git commit -m "$(cat <<'EOF'
docs(dqr): PR1 ServiceRequest lab — 4-axis DQR for production cohort

US p=10,000 + JP p=5,000 seed=42 verified across structural, clinical
integrity, JP language quality, and EHR/EMR sample dataset goal axes.
All 4 axes PASS (or PASS-WITH-WARN — see doc for exact verdict).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 14: Docs sync + TODO.md formal entries

**Files:**
- Modify: `README.md` / `README.ja.md` / `MODULES.md` / `DESIGN.md` / `docs/CONTRIBUTING-modules.md` / `clinosim/modules/order/README.md` / `TODO.md` / `CLAUDE.md`

- [ ] **Step 1: README.md / README.ja.md**

Add ServiceRequest mention to the "FHIR resources emitted" or analogous section. Brief 1-line bullet, link to spec.

- [ ] **Step 2: MODULES.md**

Update the `order` module row: responsibility now includes "panel-aware lab Order generation (foundation for ServiceRequest emission)".

- [ ] **Step 3: DESIGN.md — new ADR AD-61**

Append at the end:

```markdown
### AD-61: Lab ServiceRequest emission, panel-aware grouping

**Status:** Accepted (PR1, 2026-06-29)
**Context:** EHR/EMR sample dataset target (Tier 1 #1) requires FHIR
ServiceRequest for lab order lifecycle. JP Core / US Core idiomatic
emission is panel-level (1 SR per CBC, not 1 SR per WBC/Hb/Hct/Plt).
**Decision:** Add `Order.panel_key` 1 field (empty = stand-alone). Order
engine reuses lab_panel_groups.yaml to assign panel_key + shared
ordered_datetime to panel members. New `_fhir_service_request.py`
builder groups Orders by `(encounter_id, panel_key, ordered_datetime)`
to emit 1 SR per panel instance, stand-alone Orders emit 1 SR each.
**Consequences:** rng draw count change → new e2e golden baseline.
ServiceRequest is foundation for Tier 1 #2-#7 (Imaging / NutritionOrder
/ ADT / DocumentReference / Appointment / CarePlan).
```

- [ ] **Step 4: docs/CONTRIBUTING-modules.md**

Add a section under "Extending FHIR output (AD-56)" — `register_bundle_builder` example using `_bb_service_requests` as the canonical case.

- [ ] **Step 5: clinosim/modules/order/README.md**

Add a section "Panel-aware Order generation" describing `Order.panel_key`,
`classify_lab_specs`, and the 2-pass algorithm.

- [ ] **Step 6: TODO.md — out-of-scope formal entries**

Add formal entries for the 9 out-of-scope items from spec section 6:

```markdown
## ServiceRequest chain follow-ups (Tier 1 backlog)

### PR2 — ServiceRequest for PROCEDURE
- Procedure orders currently flow through ProcedureRecord (no Order intermediate).
- Need: emit ServiceRequest preceding each Procedure with status lifecycle.
- Path: extend `_fhir_procedures.py` builder, link via ProcedureRecord.procedure_id.

### PR3 — ServiceRequest for REFERRAL / CONSULTATION
- New CIF data required (no current source).
- Path: extend disease YAML with `referrals:` field, generate Orders with
  OrderType.REFERRAL (or CONSULTATION), new SR category (108257001 + REF).

### Tier 1 #2 — ServiceRequest for IMAGING (Imaging metadata-only chain)
- Bundled with full Imaging chain (ImagingStudy + DiagnosticReport(rad) +
  Endpoint stub).

### Out-of-scope-permanent — ServiceRequest for MEDICATION
- FHIR `MedicationRequest` is the correct resource; ServiceRequest not used.

### Tier 2 — ServiceRequest for HAI microbiology culture
- MicrobiologyResult is a separate type from Order; bundle with general
  microbiology ordering refactor.

### Tier 1 #6 — ServiceRequest.requisition (Identifier) for cross-resource grouping
- Defer until Appointment/Schedule introduces multi-SR batch requisition.

### Tier 1 #5 — Lab requisition workflow narrative
- Defer to DocumentReference Stage 2.

### Tier 2 — ServiceRequest.performer
- Lab technician/department assignment; bundle with CareTeam.

### Tier 2 — Filler order number `FILL` identifier
- Lab interface specifics; placer alone sufficient for PR1.
```

- [ ] **Step 7: CLAUDE.md — panel-aware ordering DRY rule**

Find the existing rule block about `derive_lab_values` scenario_flags + medication_flags (sibling helpers). Add a new sibling rule:

```markdown
- **`expand_labs_with_panel_grouping` helper** (PR1, 2026-06-29) — lab order
  generation in `place_admission_orders` and `place_daily_lab_orders` MUST go
  through `clinosim.modules.order.panel_grouping.classify_lab_specs` so panel
  members share a single `ordered_datetime` + `panel_key`. Never inline a
  panel-detection if/elif at the call site; the helper is the single edit
  point so adding a new panel to `lab_panel_groups.yaml` automatically reaches
  all ordering sites. Companion to `scenario_flags_from_protocol` and
  `medication_flags_from_context` sibling pattern.
```

- [ ] **Step 8: Run docs lint (if any)**

Run: `find docs -name "*.md" -exec grep -l "TBD\|TODO\|XXX" {} \;`
Expected: only the existing TODO.md entries should match (no new placeholders left in PR1 docs).

- [ ] **Step 9: Commit docs**

```bash
git add README.md README.ja.md MODULES.md DESIGN.md docs/CONTRIBUTING-modules.md \
        clinosim/modules/order/README.md TODO.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(pr1): sync all docs for ServiceRequest lab emission

- README + README.ja: FHIR resources list updated
- MODULES.md: order module responsibility updated
- DESIGN.md: AD-61 (Lab ServiceRequest panel-aware grouping)
- docs/CONTRIBUTING-modules.md: register_bundle_builder example
- clinosim/modules/order/README.md: panel_key field + 2-pass algorithm
- TODO.md: 9 out-of-scope items formalized as backlog entries
- CLAUDE.md: panel-aware ordering DRY rule (sibling to scenario_flags
  + medication_flags pattern)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

---

## Task 15: Open PR + adversarial chain handoff

**Files:**
- None modified (PR creation only)

- [ ] **Step 1: Push branch**

Run: `git push -u origin feature/pr1-servicerequest-lab`

- [ ] **Step 2: Open PR via gh**

```bash
gh pr create --title "feat(fhir): PR1 — ServiceRequest for lab orders (panel-aware)" --body "$(cat <<'EOF'
## Summary

Tier 1 #1 of EHR/EMR sample dataset roadmap. Emit FHIR R4 `ServiceRequest`
resources for lab Orders with panel-aware grouping (CBC/BMP/LFT/ABG/Lipid/
Coag/UA panels = 1 SR per panel instance), and add `basedOn` linkage to lab
`Observation` + `DiagnosticReport`.

- New: `clinosim/modules/output/_fhir_service_request.py` builder + canonical constants
- New: `clinosim/modules/order/panel_grouping.py` (2-pass deterministic algo)
- New: `clinosim/modules/order/audit.py` (`ModuleAuditSpec`, 7 equality_checks)
- Extended: `_fhir_observations.py` + `_fhir_diagnostic_report.py` with `basedOn`
- Extended: `clinosim/audit/axes/clinical.py` (basedOn coverage gate)
- New ADR: AD-61 (Lab ServiceRequest, panel-aware grouping)

Spec: docs/superpowers/specs/2026-06-29-pr1-servicerequest-lab-design.md
DQR:  docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md

## Test plan
- [x] `pytest tests/unit tests/integration -m "unit or integration"` full sweep
- [x] `pytest tests/e2e -m e2e` (golden regenerated, scope verified lab-only)
- [x] `clinosim audit run` on US p=10k + JP p=5k cohorts: all 4 axes PASS/WARN
- [x] ruff + mypy clean

## Adversarial chain follow-ups
- Post-merge: dispatch adversarial fan-out review (6-axis + silent-no-op + AD-16)
  per memory `feedback_iterative_adversarial_review`.
- Stopping criteria: Critical/Important 0 + findings converging + remaining
  cosmetic only + next stage expected size tiny.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01JJA6Md2Y85h7vVcfUGxLze
EOF
)"
```

- [ ] **Step 3: Wait for user approval to merge**

Per CLAUDE.md "Executing actions with care": do NOT merge without explicit user request. Report PR URL and stand by.

---

## Self-Review

### Spec coverage check

| Spec section | Task(s) |
|---|---|
| 1.1 Module structure (Order ext + new builder) | Tasks 1-4 |
| 1.2 Lab vertical slice | Tasks 1-9, 11, 13 |
| 1.3 Panel-aware grouping | Tasks 2-7 |
| 1.4 ServiceRequest fields (id/identifier/intent/status/category/priority/code) | Task 4 |
| 1.5 Status aggregation rule | Task 4 |
| 1.6 AD-32 snapshot | Task 9 |
| 2 Architecture (responsibility decomposition) | Tasks 1-8 (each layer = 1 task) |
| 3.1 Ordering engine integration | Task 3 |
| 3.2 SR id helper | Task 4 |
| 3.3 ServiceRequest resource | Task 4 |
| 3.4 basedOn linkage | Tasks 6+7 |
| 4 Edge cases (panel detection, status 8 cases, silent-no-op 4 layers) | Tasks 2, 4, 8 |
| 5.1-5.2 Unit + integration tests | Tasks 1-9 |
| 5.3 E2E golden | Task 11 |
| 5.4 audit framework | Task 8 + 10 |
| 5.5 DQR | Task 13 |
| 5.6 Determinism | Task 9 |
| 5.7 Pre-merge gate | Task 12 |
| 6 Out-of-scope formal entries | Task 14 |
| 7 Risks (mitigations) | Embedded across tasks |
| 8 Adversarial chain plan | Task 15 (handoff) |
| 9 PR sequencing | Task 15 |
| 10 Docs sync (8 docs) | Task 14 |

All sections covered.

### Placeholder scan

No "TBD" / "TODO" / "implement later" / "fill in details" remain in tasks except:
- "TBD by DQR" in File Structure table for `loinc_display_ja.yaml` — intentional (the exact codes to add depend on what audit reveals in Task 10). This is acceptable as the work is conditionally performed in Task 10 Step 4 with explicit instructions.

### Type consistency

- `Order.panel_key: str` used consistently across Tasks 1-9.
- `order_to_sr_id(order, panel_counter)` signature consistent in Tasks 4, 6, 7.
- `build_panel_counter(orders)` returns `dict[tuple[str, str, datetime], int]` — used consistently.
- `aggregate_panel_status(member_orders)` returns `str` (FHIR status enum value) — used consistently.
- `classify_lab_specs(lab_specs, panels) -> (panel_groups, stand_alones)` — used consistently in Tasks 2-3.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-29-pr1-servicerequest-lab.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Each subagent has a focused context and the plan steps are bite-sized; reviewer (you or the orchestrator) gates between tasks.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
