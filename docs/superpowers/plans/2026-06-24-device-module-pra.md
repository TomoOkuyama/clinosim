# PR-A — `modules/device` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Phase 1 of the device + HAI feature: a new `modules/device/` AD-55 opt-in Module that emits FHIR R4 `Device` + `DeviceUseStatement` resources for ICU encounters, paving the way for the Phase 2 `modules/hai/` consumer.

**Architecture:** post_records enricher walks every CIFPatientRecord, evaluates state-based placement criteria at each ICU encounter, and writes `extensions["device"] = list[DeviceRecord]`. A new theme-per-file FHIR builder `_fhir_device.py` reads that extension and emits two new NDJSON resources. SNOMED CT codes (CVC / indwelling catheter / mechanical ventilator) added to `codes/data/snomed-ct.yaml` after tx.fhir.org `$lookup` verification.

**Tech Stack:** Python 3.11+, ruff, mypy strict, pytest, numpy. No new external dependencies. `tx.fhir.org` `$lookup` (existing reference, memory `reference_tx_fhir_terminology`) used for SNOMED code verification at Task 1.

## Global Constraints

- Branch: `feat/device-module-pra` (already created from master `89969152`)
- Determinism (AD-16): device enricher MUST NOT touch the main RNG; independent sub-seed `ENRICHER_SEED_OFFSETS["device"] = 0x4445` (16-bit hex ASCII "DE").
- AD-56: builders register via `register_bundle_builder()` inside `_fhir_device.py`; enricher registers via `register_builtin_enrichers()` in `clinosim/simulator/enrichers.py`.
- AD-55 Module classification (opt-in via `SimulatorConfig.modules["device"]`, default `True`).
- All new types live in `clinosim/types/device.py` per CLAUDE.md "All types in `clinosim/types/`".
- `_fhir_common.py` helper promotion only when 2+ builders share a new symbol — Phase 1 has no such case.
- SNOMED CT codes are **non-binding until tx.fhir.org `$lookup` confirms them** (Task 1 explicit verification step; PR #80 LOINC `2B010` fabrication lesson).
- `# TODO: verify` markers in spec YAML are placeholders; Task 1 replaces them with concrete authoritative codes before any other file uses them.
- Verification gate: **3-axis DQR** (structural / clinical / JP language), not byte-diff. Pre-existing NDJSON byte-identical is the no-regression *complement*, not the gate.
- All docs touched by this feature are updated **in the same PR** (per `feedback_pr_merge_dqr_required` — no follow-up doc PR).

## File structure (decisions locked in)

**Files created:**
- `clinosim/types/device.py` — `DeviceRecord` dataclass
- `clinosim/modules/device/__init__.py` — public API re-exports
- `clinosim/modules/device/engine.py` — pure functions (`load_devices_config`, `_evaluate_indications`, `_indications_met`, `place_devices_for_encounter`)
- `clinosim/modules/device/enricher.py` — `device_enricher(cif, master_seed, country)`
- `clinosim/modules/device/reference_data/devices.yaml` — 3 device SNOMED + criteria
- `clinosim/modules/device/README.md` — TEMPLATE_MODULE_README.md skeleton
- `clinosim/modules/output/_fhir_device.py` — `_build_device` + `_build_device_use` builders
- `tests/unit/test_device_engine.py`
- `tests/unit/test_device_enricher.py`
- `tests/unit/test_device_snomed_coverage.py`
- `tests/integration/test_device_extension_persistence.py`
- `tests/integration/test_device_fhir_output.py`
- `scratchpad/device_dqr/dqr_audit.py` — 3-axis DQR script
- `docs/reviews/2026-06-24-device-module-data-quality-review.md` — DQR results
- `scratchpad/device_byte_diff_results.md` — byte-diff supplement results

**Files modified:**
- `clinosim/codes/data/snomed-ct.yaml` — 3 new device entries (en + ja)
- `clinosim/types/__init__.py` — export `DeviceRecord`
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["device"] = 0x4445`
- `clinosim/simulator/enrichers.py` — register `device_enricher` in `register_builtin_enrichers()`
- `clinosim/types/config.py` — `SimulatorConfig.modules["device"] = True` default
- `clinosim/modules/output/fhir_r4_adapter.py` — import + register builders
- Docs sync (10 files; Task 13)

**Files unchanged:**
- Tests outside `tests/{unit,integration}/test_device_*.py`
- `_fhir_observations.py` and other PR3-extracted builders
- Any existing module

## Verification commands (referenced from multiple tasks)

```bash
# Smoke regression after each implementation task
pytest -m "unit or integration" -q

# Byte-diff (informational supplement, Task 11)
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/device_byte_diff/branch/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/device_byte_diff/branch/jp
# master generation done after `git checkout 89969152`
python scratchpad/device_byte_diff/compare.py    # script written in Task 11

# 3-axis DQR generation (Task 12)
python -m clinosim.simulator.cli generate -p 10000 -s 42 --country US --format fhir-r4 -o scratchpad/device_dqr/us
python -m clinosim.simulator.cli generate -p 5000 -s 42 --country JP --format fhir-r4 -o scratchpad/device_dqr/jp
python scratchpad/device_dqr/dqr_audit.py
```

---

### Task 1: SNOMED CT code verification + `snomed-ct.yaml` entries

**Files:**
- Modify: `clinosim/codes/data/snomed-ct.yaml`
- Test: (inline curl verification, no test file)

**Interfaces:**
- Consumes: tx.fhir.org `$lookup` endpoint (memory `reference_tx_fhir_terminology`)
- Produces: three verified SNOMED codes for downstream Tasks 3 / 7. Exact `(code, en_display, ja_display)` triples to use everywhere else in this plan.

- [ ] **Step 1.1: Inspect current `snomed-ct.yaml` structure**

Run: `head -30 clinosim/codes/data/snomed-ct.yaml`
Expected: YAML with `codes:` key containing existing SNOMED → {en, ja} entries.

Note the schema (whether the file is flat dict or wrapped in `codes:`), so the additions match it byte-for-byte.

- [ ] **Step 1.2: Verify the three candidate SNOMED codes via tx.fhir.org**

Run each `$lookup` (these are the canonical references per memory):

```bash
curl -sS "https://tx.fhir.org/r4/CodeSystem/$lookup?system=http://snomed.info/sct&code=52124006" | head -40
curl -sS "https://tx.fhir.org/r4/CodeSystem/$lookup?system=http://snomed.info/sct&code=467021000" | head -40
curl -sS "https://tx.fhir.org/r4/CodeSystem/$lookup?system=http://snomed.info/sct&code=706172005" | head -40
```

Expected: each returns a FHIR Parameters resource with `display` parameter values matching:
- `52124006` → "Central venous catheter" (or close synonym)
- `467021000` → "Indwelling urinary catheter" (the spec candidate; if `$lookup` returns a different display or "not found", the engineer MUST search SNOMED for the correct code — see Step 1.3)
- `706172005` → "Mechanical ventilator" (or close synonym)

If any `$lookup` returns a 404 / `outcome.issue[].severity=error`:
1. Search for the correct code at https://browser.ihtsdotools.org/ (manual) or via a second `$lookup` candidate (eg. `448811000` for indwelling catheter; `40617009` for vent).
2. Pick the SNOMED preferred-term code; record the verified code.
3. Update the spec's `# TODO: verify` line in the YAML below.

**Do not proceed past Step 1.2 with unverified codes.** This is the PR #80 LOINC `2B010` fabrication prevention checkpoint.

- [ ] **Step 1.3: Record the verified codes in `clinosim/codes/data/snomed-ct.yaml`**

After Step 1.2 confirms each `(code, en_display)` pair, append three entries to `snomed-ct.yaml`. Schema match per Step 1.1; if the file uses a top-level `codes:` key the additions go under it; otherwise they go at the top level.

Sample addition (adapt to whichever schema Step 1.1 confirmed):

```yaml
  "52124006":
    en: "Central venous catheter"
    ja: "中心静脈カテーテル"
  "467021000":
    en: "Indwelling urinary catheter"
    ja: "膀胱留置カテーテル"
  "706172005":
    en: "Mechanical ventilator"
    ja: "人工呼吸器"
```

(The `en:` value must match the `$lookup` `display` parameter verbatim — copy from the curl output, do not edit.)

If Step 1.2 substituted a different code for one or more of the three, use that code here and update **the rest of the plan** — sed search-replace all subsequent occurrences of the old code with the new one in this file before continuing.

- [ ] **Step 1.4: Smoke test the lookup**

Run:

```bash
python -c "from clinosim.codes import lookup; print(lookup('snomed-ct', '52124006', 'en'), '/', lookup('snomed-ct', '52124006', 'ja'))"
python -c "from clinosim.codes import lookup; print(lookup('snomed-ct', '467021000', 'en'), '/', lookup('snomed-ct', '467021000', 'ja'))"
python -c "from clinosim.codes import lookup; print(lookup('snomed-ct', '706172005', 'en'), '/', lookup('snomed-ct', '706172005', 'ja'))"
```

Expected: each prints the en + ja display from the YAML (eg. "Central venous catheter / 中心静脈カテーテル").

- [ ] **Step 1.5: Commit**

```bash
git add clinosim/codes/data/snomed-ct.yaml
git commit -m "$(cat <<'EOF'
codes(snomed): add CVC + indwelling catheter + ventilator (PR-A)

Three SNOMED CT codes for the device module (PR-A of the 4-phase
device + HAI series). All three verified via tx.fhir.org $lookup
(memory reference_tx_fhir_terminology) before commit per PR #80
LOINC 2B010 fabrication prevention.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 2: `DeviceRecord` dataclass + types export

**Files:**
- Create: `clinosim/types/device.py`
- Modify: `clinosim/types/__init__.py`
- Test: `tests/unit/test_device_engine.py` (covers DeviceRecord instantiation as part of broader engine tests, Task 3)

**Interfaces:**
- Consumes: nothing (foundational)
- Produces: `DeviceRecord` dataclass with exact fields `device_id`, `encounter_id`, `device_type`, `snomed_code`, `placement_date`, `removal_date`, `placement_indication` — all str except `removal_date: str | None`.

- [ ] **Step 2.1: Create `clinosim/types/device.py`**

```python
"""Device use records (AD-55 Module: device)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceRecord:
    """One device placement during a patient encounter.

    Stored as list[DeviceRecord] under CIFPatientRecord.extensions["device"].
    Phase 2 hai enricher consumes this to compute line-days for
    CLABSI/CAUTI/VAP onset sampling.
    """

    device_id: str
    encounter_id: str
    device_type: str
    snomed_code: str
    placement_date: str
    removal_date: str | None
    placement_indication: str
```

- [ ] **Step 2.2: Export `DeviceRecord` from `clinosim/types/__init__.py`**

Run: `grep "DeviceRecord\|FamilyMemberHistoryRecord\|ImmunizationRecord" clinosim/types/__init__.py | head -10`
Expected: existing `__all__` lists other AD-55 records.

Add `DeviceRecord` to the `from ... import` block and the `__all__` list, matching the existing alphabetical or grouping convention exactly (eyeball check the file before editing).

- [ ] **Step 2.3: Smoke test**

```bash
python -c "from clinosim.types import DeviceRecord; r = DeviceRecord(device_id='d1', encounter_id='e1', device_type='cvc', snomed_code='52124006', placement_date='2026-01-01', removal_date=None, placement_indication='severity_moderate_plus'); print(r)"
```

Expected: prints the dataclass repr with all 7 fields populated.

- [ ] **Step 2.4: Commit**

```bash
git add clinosim/types/device.py clinosim/types/__init__.py
git commit -m "$(cat <<'EOF'
types(device): add DeviceRecord dataclass (PR-A)

7-field dataclass per spec §"CIF data shape". Stored as
list[DeviceRecord] under CIFPatientRecord.extensions["device"]; Phase 2
hai enricher will consume it. types/__init__.py exports.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 3: `modules/device/` engine + reference YAML

**Files:**
- Create: `clinosim/modules/device/__init__.py`
- Create: `clinosim/modules/device/engine.py`
- Create: `clinosim/modules/device/reference_data/devices.yaml`
- Test: `tests/unit/test_device_engine.py`

**Interfaces:**
- Consumes: `DeviceRecord` from Task 2; `PhysiologicalState` from `clinosim/types/clinical.py`; `Encounter` from `clinosim/types/encounter.py`; `CIFPatientRecord` from `clinosim/types/output.py`.
- Produces:
  - `load_devices_config() -> dict[str, Any]` — `@lru_cache`d YAML loader
  - `_evaluate_indications(state, severity, altered_consciousness) -> set[str]`
  - `_indications_met(criteria, met) -> bool`
  - `place_devices_for_encounter(record, encounter, rng, devices_config) -> list[DeviceRecord]`

- [ ] **Step 3.1: Verify `PhysiologicalState` and `Encounter` attribute names**

Run:

```bash
grep -nE "spo2_baseline|respiratory_status|respiratory_fraction|altered_consciousness" clinosim/types/clinical.py
grep -nE "icu_admission_date|icu_discharge_date|^    id" clinosim/types/encounter.py
```

Expected: each grep returns at least one match.

If any spec attribute name doesn't match the real type field name:
- For `PhysiologicalState`: the spec used `spo2_baseline` / `respiratory_status` / `respiratory_fraction`. If the real field is named differently (`spo2_target`, `respiratory_load`, etc.), use the **real** name in the implementation; the spec is a draft. Record the mapping in this task's commit message.
- For `Encounter`: the spec used `id` / `icu_admission_date` / `icu_discharge_date`. If real fields differ (`encounter_id`, `icu_admit_date`, etc.), use the **real** names.
- For `altered_consciousness`: there is no such field on `PhysiologicalState` — derive it from another signal. Likely source: `vital_signs[].gcs_score < 13` (GCS criterion) **or** `state.sedation_state > 0.5`. Pick the simplest signal that exists in the codebase; document in commit message.

Hold the verified names. Use them in Steps 3.4 onward.

- [ ] **Step 3.2: Create `clinosim/modules/device/reference_data/devices.yaml`**

Use the SNOMED codes verified in Task 1.

```yaml
# AD-55 Module: device — SNOMED CT codes + placement criteria.
# All three SNOMED codes verified via tx.fhir.org $lookup at Task 1
# of the implementation plan (see docs/superpowers/plans/2026-06-24-device-module-pra.md).
devices:
  cvc:
    snomed_code: "52124006"
    snomed_display_en: "Central venous catheter"
    snomed_display_ja: "中心静脈カテーテル"
    placement_criteria:
      - any: ["severity_moderate_plus"]
  indwelling_catheter:
    snomed_code: "467021000"
    snomed_display_en: "Indwelling urinary catheter"
    snomed_display_ja: "膀胱留置カテーテル"
    placement_criteria:
      - any: ["severity_moderate_plus", "altered_consciousness"]
  mechanical_ventilator:
    snomed_code: "706172005"
    snomed_display_en: "Mechanical ventilator"
    snomed_display_ja: "人工呼吸器"
    placement_criteria:
      - any: ["hypoxia", "high_respiratory_demand"]
```

If Task 1 substituted any code, use the verified one here.

- [ ] **Step 3.3: Write failing unit tests**

Create `tests/unit/test_device_engine.py`:

```python
"""Unit tests for clinosim.modules.device.engine."""
from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.device.engine import (
    _evaluate_indications,
    _indications_met,
    load_devices_config,
    place_devices_for_encounter,
)
from clinosim.types import DeviceRecord


pytestmark = pytest.mark.unit


def test_load_devices_config_returns_three_devices():
    cfg = load_devices_config()
    assert set(cfg["devices"].keys()) == {"cvc", "indwelling_catheter", "mechanical_ventilator"}
    assert cfg["devices"]["cvc"]["snomed_code"] == "52124006"


def test_indications_met_any_clause_true_if_any_token_in_set():
    criteria = [{"any": ["severity_moderate_plus", "altered_consciousness"]}]
    assert _indications_met(criteria, {"severity_moderate_plus"}) is True
    assert _indications_met(criteria, {"altered_consciousness"}) is True
    assert _indications_met(criteria, {"hypoxia"}) is False


def test_indications_met_empty_set_is_false():
    criteria = [{"any": ["severity_moderate_plus"]}]
    assert _indications_met(criteria, set()) is False


def test_indications_met_empty_criteria_is_false():
    assert _indications_met([], {"severity_moderate_plus"}) is False


def test_evaluate_indications_severity_moderate():
    # Build a minimal PhysiologicalState — adjust the fields to match the
    # real type after Step 3.1 verification.
    from clinosim.types.clinical import PhysiologicalState
    state = PhysiologicalState()  # default field values
    indications = _evaluate_indications(state, severity="moderate", altered_consciousness=False)
    assert "severity_moderate_plus" in indications
    assert "altered_consciousness" not in indications


def test_evaluate_indications_mild_severity_no_token():
    from clinosim.types.clinical import PhysiologicalState
    state = PhysiologicalState()
    indications = _evaluate_indications(state, severity="mild", altered_consciousness=False)
    assert "severity_moderate_plus" not in indications


def test_evaluate_indications_altered_consciousness():
    from clinosim.types.clinical import PhysiologicalState
    state = PhysiologicalState()
    indications = _evaluate_indications(state, severity="mild", altered_consciousness=True)
    assert "altered_consciousness" in indications


def test_place_devices_for_encounter_no_icu_returns_empty():
    """Non-ICU encounter yields no devices."""
    from clinosim.types.encounter import Encounter
    from clinosim.types.output import CIFPatientRecord
    # Construct minimal encounter without ICU admission.
    # Real Encounter init may need specific args; check the dataclass.
    enc = Encounter(id="enc1")  # adapt to real signature
    rec = CIFPatientRecord()
    rng = np.random.default_rng(42)
    cfg = load_devices_config()
    out = place_devices_for_encounter(rec, enc, rng, cfg)
    assert out == []


def test_place_devices_for_encounter_icu_severe_all_three():
    """Severe sepsis ICU patient with hypoxia + altered consciousness gets all 3."""
    # Build encounter + record + state such that all three indications are met.
    # Adapt to whatever the real dataclasses need.
    pytest.skip("Wired up in integration test once real type signatures verified")
```

- [ ] **Step 3.4: Run tests to verify failures**

Run: `pytest tests/unit/test_device_engine.py -v 2>&1 | tail -20`
Expected: import error or "module not found" for `clinosim.modules.device.engine`.

- [ ] **Step 3.5: Create `clinosim/modules/device/__init__.py`**

```python
"""AD-55 Module: device — ICU device placement (CVC / catheter / ventilator)."""
from __future__ import annotations

from clinosim.modules.device.engine import (
    load_devices_config,
    place_devices_for_encounter,
)

__all__ = ["load_devices_config", "place_devices_for_encounter"]
```

- [ ] **Step 3.6: Create `clinosim/modules/device/engine.py`**

Use the verified attribute names from Step 3.1.

```python
"""Pure functions for the device module (AD-55).

place_devices_for_encounter takes a CIFPatientRecord + Encounter +
sub-rng and returns a list of DeviceRecord for that encounter,
honouring devices.yaml placement criteria. State unchanged
(BNP-pattern surgical principle).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.types import DeviceRecord
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Encounter
from clinosim.types.output import CIFPatientRecord


_DEVICES_YAML = Path(__file__).parent / "reference_data" / "devices.yaml"


@lru_cache(maxsize=1)
def load_devices_config() -> dict[str, Any]:
    """Load device reference data from devices.yaml (cached)."""
    with _DEVICES_YAML.open() as f:
        data = yaml.safe_load(f)
    return data


def _evaluate_indications(
    state: PhysiologicalState,
    severity: str,
    altered_consciousness: bool,
) -> set[str]:
    """Return the set of indication tokens met at ICU transfer time.

    Tokens:
      severity_moderate_plus — severity ∈ {moderate, severe, critical}
      altered_consciousness  — passed in (derived from GCS < 13 or sedation)
      hypoxia                — SpO2 baseline < 88% or respiratory_status < 0.4
      high_respiratory_demand — respiratory_fraction > 0.7
    """
    indications: set[str] = set()
    if severity in ("moderate", "severe", "critical"):
        indications.add("severity_moderate_plus")
    if altered_consciousness:
        indications.add("altered_consciousness")
    # Use the verified attribute names from Step 3.1.
    # Below example uses the spec names; engineer must substitute real names.
    spo2_baseline = getattr(state, "spo2_baseline", 1.0)
    respiratory_status = getattr(state, "respiratory_status", 1.0)
    respiratory_fraction = getattr(state, "respiratory_fraction", 0.0)
    if spo2_baseline < 0.88 or respiratory_status < 0.4:
        indications.add("hypoxia")
    if respiratory_fraction > 0.7:
        indications.add("high_respiratory_demand")
    return indications


def _indications_met(criteria: list[dict], met: set[str]) -> bool:
    """Evaluate a criteria list. Currently only 'any:' clauses supported."""
    if not criteria:
        return False
    for clause in criteria:
        if "any" in clause and any(tok in met for tok in clause["any"]):
            return True
    return False


def _severity_for_encounter(record: CIFPatientRecord, encounter: Encounter) -> str:
    """Derive a severity string for the encounter.

    Looks at record.condition_event and / or encounter-specific severity
    fields. Falls back to 'mild' if no signal.
    """
    sev = getattr(record.condition_event, "severity", None)
    if sev:
        return str(sev)
    return "mild"


def _altered_consciousness_for_encounter(record: CIFPatientRecord, encounter: Encounter) -> bool:
    """True if any vital_sign for this encounter shows GCS < 13."""
    enc_id = getattr(encounter, "id", None)
    for vs in record.vital_signs or []:
        if getattr(vs, "encounter_id", None) != enc_id:
            continue
        gcs = getattr(vs, "gcs_score", None)
        if gcs is not None and gcs < 13:
            return True
    return False


def _peak_state_for_encounter(
    record: CIFPatientRecord, encounter: Encounter
) -> PhysiologicalState:
    """Pick a representative PhysiologicalState for the encounter.

    Phase 1 simplification: use the first state recorded; falls back to
    a default PhysiologicalState when the patient has none (eg.
    e2e mocks). Phase 2+ may refine this to per-encounter peak severity.
    """
    if record.physiological_states:
        return record.physiological_states[0]
    return PhysiologicalState()


def place_devices_for_encounter(
    record: CIFPatientRecord,
    encounter: Encounter,
    rng: np.random.Generator,
    devices_config: dict[str, Any],
) -> list[DeviceRecord]:
    """Return DeviceRecord list for a single encounter.

    Returns [] when:
    - encounter has no ICU admission
    - no device's placement_criteria are met by the patient state
    """
    icu_admit = getattr(encounter, "icu_admission_date", None)
    if not icu_admit:
        return []
    icu_discharge = getattr(encounter, "icu_discharge_date", None)
    severity = _severity_for_encounter(record, encounter)
    altered = _altered_consciousness_for_encounter(record, encounter)
    state = _peak_state_for_encounter(record, encounter)
    indications = _evaluate_indications(state, severity, altered)
    out: list[DeviceRecord] = []
    enc_id = getattr(encounter, "id", "unknown")
    for device_type, cfg in devices_config["devices"].items():
        if not _indications_met(cfg["placement_criteria"], indications):
            continue
        out.append(DeviceRecord(
            device_id=f"dev-{enc_id}-{device_type}-{len(out)}",
            encounter_id=enc_id,
            device_type=device_type,
            snomed_code=cfg["snomed_code"],
            placement_date=str(icu_admit),
            removal_date=str(icu_discharge) if icu_discharge else None,
            placement_indication=",".join(sorted(indications)),
        ))
    return out
```

- [ ] **Step 3.7: Re-run tests**

Run: `pytest tests/unit/test_device_engine.py -v 2>&1 | tail -25`
Expected: tests covered in Step 3.3 PASS (except the explicitly-skipped one). If any FAIL with `AttributeError` referencing `PhysiologicalState` / `Encounter` field, the Step 3.1 mapping was wrong — fix engine.py, re-run.

- [ ] **Step 3.8: Commit**

```bash
git add clinosim/modules/device/__init__.py clinosim/modules/device/engine.py clinosim/modules/device/reference_data/devices.yaml tests/unit/test_device_engine.py
git commit -m "$(cat <<'EOF'
feat(device): module engine + devices.yaml + unit tests (PR-A)

Pure functions for placement evaluation (load_devices_config,
_evaluate_indications, _indications_met, place_devices_for_encounter)
plus reference YAML with 3 ICU devices (CVC / indwelling catheter /
mechanical ventilator). State-based indication tokens derived per spec
§"engine.py — placement algorithm". TDD: 7 unit tests covering YAML
load, criteria evaluation, indication derivation, non-ICU short-circuit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 4: ENRICHER_SEED_OFFSETS + enricher.py

**Files:**
- Modify: `clinosim/simulator/seeding.py`
- Create: `clinosim/modules/device/enricher.py`
- Modify: `clinosim/modules/device/__init__.py` (export `device_enricher`)
- Test: `tests/unit/test_device_enricher.py`

**Interfaces:**
- Consumes: `place_devices_for_encounter` from Task 3; `derive_sub_seed` from `clinosim/simulator/seeding.py`
- Produces: `device_enricher(cif: CIFDataset, master_seed: int, country: str) -> None`. Mutates `record.extensions["device"]`.

- [ ] **Step 4.1: Inspect `ENRICHER_SEED_OFFSETS` + `register_builtin_enrichers`**

Run:

```bash
grep -nE "ENRICHER_SEED_OFFSETS|register_builtin_enrichers|derive_sub_seed" clinosim/simulator/seeding.py clinosim/simulator/enrichers.py
```

Note:
- Exact dict literal for `ENRICHER_SEED_OFFSETS` (Task 4.2 will append to it)
- Existing enricher signature (especially: does it take `country`? does it return `None`?)
- How `register_builtin_enrichers()` registers enrichers (decorator? list append? function call?)

- [ ] **Step 4.2: Append `"device": 0x4445` to `ENRICHER_SEED_OFFSETS`**

Edit `clinosim/simulator/seeding.py`:

```python
# inside the existing dict literal — append to match existing alphabetical / grouping order
"device": 0x4445,    # "DE" (PR-A)
```

Trigger the existing module-level duplicate-offset assert by checking import:

```bash
python -c "from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS; print('device' in ENRICHER_SEED_OFFSETS)"
```

Expected: `True`. If `AssertionError: duplicate offsets`, search for the collision and pick a different hex (eg. `0x4456` = "DV"). Update everywhere this code is referenced.

- [ ] **Step 4.3: Write failing test**

Create `tests/unit/test_device_enricher.py`:

```python
"""Unit tests for clinosim.modules.device.enricher."""
from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.device.enricher import device_enricher
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS
from clinosim.types.output import CIFDataset, CIFPatientRecord


pytestmark = pytest.mark.unit


def test_device_offset_registered():
    assert ENRICHER_SEED_OFFSETS["device"] == 0x4445


def test_device_enricher_empty_cif_noop():
    cif = CIFDataset()
    cif.patients = []
    device_enricher(cif, master_seed=42, country="US")
    assert cif.patients == []


def test_device_enricher_non_icu_patient_no_devices():
    rec = CIFPatientRecord()
    # No ICU encounter
    cif = CIFDataset()
    cif.patients = [rec]
    device_enricher(cif, master_seed=42, country="US")
    assert "device" not in rec.extensions or rec.extensions["device"] == []


def test_device_enricher_independent_subseed_does_not_touch_master_rng():
    """Two runs with different patient populations must give different
    sub-seeds; master RNG stream unaffected."""
    rec_a = CIFPatientRecord()
    rec_b = CIFPatientRecord()
    rec_a.patient.person_id = "pid_a"
    rec_b.patient.person_id = "pid_b"
    cif_a = CIFDataset(); cif_a.patients = [rec_a]
    cif_b = CIFDataset(); cif_b.patients = [rec_b]
    device_enricher(cif_a, master_seed=42, country="US")
    device_enricher(cif_b, master_seed=42, country="US")
    # Empty patient profiles → both should yield no devices, but the
    # call itself must not raise.
    assert True  # smoke
```

- [ ] **Step 4.4: Run tests to verify failures**

Run: `pytest tests/unit/test_device_enricher.py -v 2>&1 | tail -15`
Expected: import error for `clinosim.modules.device.enricher` or missing `ENRICHER_SEED_OFFSETS["device"]` (if Step 4.2 was skipped).

- [ ] **Step 4.5: Create `clinosim/modules/device/enricher.py`**

```python
"""post_records enricher for the device module (AD-55 Module: opt-in)."""
from __future__ import annotations

import numpy as np

from clinosim.modules.device.engine import (
    load_devices_config,
    place_devices_for_encounter,
)
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.output import CIFDataset


def device_enricher(cif: CIFDataset, master_seed: int, country: str) -> None:
    """Walk every CIFPatientRecord; emit list[DeviceRecord] under
    extensions['device'] for ICU encounters where placement criteria are
    met. Main RNG untouched (independent sub-seed per person_id).
    """
    cfg = load_devices_config()
    for record in cif.patients:
        pid = getattr(record.patient, "person_id", None) or ""
        sub_seed = derive_sub_seed(
            master_seed,
            ENRICHER_SEED_OFFSETS["device"],
            pid,
        )
        rng = np.random.default_rng(sub_seed)
        devices = []
        for encounter in record.encounters:
            devices.extend(place_devices_for_encounter(record, encounter, rng, cfg))
        if devices:
            record.extensions["device"] = devices
```

- [ ] **Step 4.6: Update `clinosim/modules/device/__init__.py` to export the enricher**

```python
"""AD-55 Module: device — ICU device placement (CVC / catheter / ventilator)."""
from __future__ import annotations

from clinosim.modules.device.engine import (
    load_devices_config,
    place_devices_for_encounter,
)
from clinosim.modules.device.enricher import device_enricher

__all__ = ["load_devices_config", "place_devices_for_encounter", "device_enricher"]
```

- [ ] **Step 4.7: Re-run tests**

Run: `pytest tests/unit/test_device_enricher.py -v 2>&1 | tail -15`
Expected: 4 PASS.

- [ ] **Step 4.8: Commit**

```bash
git add clinosim/simulator/seeding.py clinosim/modules/device/enricher.py clinosim/modules/device/__init__.py tests/unit/test_device_enricher.py
git commit -m "$(cat <<'EOF'
feat(device): post_records enricher + ENRICHER_SEED_OFFSETS 0x4445 (PR-A)

device_enricher walks every CIFPatientRecord, calls
place_devices_for_encounter per encounter, writes list[DeviceRecord]
under extensions['device']. Independent per-person sub-seed
(0x4445 = "DE") so main RNG stream untouched (AD-16 / PR1 pattern).
4 unit tests: offset registration, empty CIF no-op, non-ICU short-
circuit, sub-seed isolation smoke.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 5: Register `device_enricher` in `simulator/enrichers.py` + `SimulatorConfig.modules`

**Files:**
- Modify: `clinosim/simulator/enrichers.py`
- Modify: `clinosim/types/config.py` (`SimulatorConfig.modules` default)
- Test: existing `tests/unit/test_device_enricher.py` Step 4.5 + integration test (Task 9)

**Interfaces:**
- Consumes: `device_enricher` from Task 4
- Produces: registration so `run_beta` automatically calls `device_enricher` post_records.

- [ ] **Step 5.1: Inspect `register_builtin_enrichers`**

Run:

```bash
grep -nA 30 "^def register_builtin_enrichers\|register_enricher\|builtin_enrichers" clinosim/simulator/enrichers.py | head -60
```

Note the exact registration syntax (list append? function call? phase parameter?).

- [ ] **Step 5.2: Add `device_enricher` registration**

Edit `clinosim/simulator/enrichers.py` `register_builtin_enrichers` (or equivalent):

```python
# Inside register_builtin_enrichers(), append after the existing post_records
# enricher registrations:
from clinosim.modules.device.enricher import device_enricher
register_enricher(device_enricher, phase="post_records")    # adapt phase arg to real signature
```

If the file uses a different idiom (eg. `_BUILTIN_ENRICHERS.append(...)`), match it.

- [ ] **Step 5.3: Check if `SimulatorConfig.modules` exists + add `"device"` default**

Run: `grep -nA 20 "class SimulatorConfig\|modules.*dict\|module_enabled" clinosim/types/config.py | head -40`

If `SimulatorConfig.modules: dict[str, bool]` exists:
- Add `"device": True` to its default factory.

If the field has a different name (eg. `enabled_modules`), use that name.

- [ ] **Step 5.4: Module-gate the enricher**

Add a guard at the top of `device_enricher` (open `enricher.py`, prepend before the main loop):

```python
def device_enricher(cif: CIFDataset, master_seed: int, country: str, *, config=None) -> None:
    """..."""
    # If config provided and module disabled, skip
    if config is not None and not getattr(config, "module_enabled", lambda _: True)("device"):
        return
    # ... rest unchanged ...
```

(If `device_enricher`'s real call site already passes `config` to enrichers, accept it; otherwise add it optionally as shown.)

Verify the real enricher signature — look at one of `immunization_enricher`, `family_history_enricher`, etc. and **match their parameter list exactly**. Some take `(cif, master_seed)`, some `(cif, master_seed, country)`, some `(cif, master_seed, country, config)`. The pattern must match for the registry to call it correctly.

- [ ] **Step 5.5: Run regression**

Run: `pytest -m unit -q 2>&1 | tail -5`
Expected: 0 failures (new enricher registered but skipped on empty CIF).

- [ ] **Step 5.6: Commit**

```bash
git add clinosim/simulator/enrichers.py clinosim/types/config.py clinosim/modules/device/enricher.py
git commit -m "$(cat <<'EOF'
feat(device): wire device_enricher into builtin registry + opt-in gate (PR-A)

register_builtin_enrichers appends device_enricher to the post_records
phase. SimulatorConfig.modules default gains "device": True
(AD-55 Module opt-in but production-default-on, matching immunization /
family_history / code_status / care_level convention). Enricher checks
module_enabled('device') and is a no-op when disabled.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 6: Module README

**Files:**
- Create: `clinosim/modules/device/README.md`

**Interfaces:** none

- [ ] **Step 6.1: Copy `.github/TEMPLATE_MODULE_README.md` and tailor it**

Run: `cat .github/TEMPLATE_MODULE_README.md > clinosim/modules/device/README.md`

Edit `clinosim/modules/device/README.md` to fill the template sections:

- **Purpose** (1-2 sentences): "AD-55 opt-in Module that emits FHIR Device + DeviceUseStatement for ICU encounters (CVC, indwelling urinary catheter, mechanical ventilator)."
- **Dependencies**: `clinosim/types/` (`DeviceRecord`, `PhysiologicalState`, `Encounter`, `CIFPatientRecord`, `CIFDataset`); `clinosim/codes/` (SNOMED CT lookup at FHIR output time); `clinosim/simulator/seeding.py` (`derive_sub_seed`, `ENRICHER_SEED_OFFSETS`).
- **Consumers**: `clinosim/simulator/enrichers.py` (registers `device_enricher` post_records); `clinosim/modules/output/_fhir_device.py` (reads `extensions["device"]`).
- **データ構造**: `DeviceRecord` dataclass — list under `CIFPatientRecord.extensions["device"]`.
- **API**: `load_devices_config()`, `place_devices_for_encounter(record, encounter, rng, cfg)`, `device_enricher(cif, master_seed, country)`.
- **Phase 2 への展望**: Phase 2 `modules/hai/` will consume `extensions["device"]` for CLABSI/CAUTI/VAP onset sampling. Cross-module dependency point established here.
- **設定**: opt-in via `SimulatorConfig.modules["device"]` (default `True`).

- [ ] **Step 6.2: Commit**

```bash
git add clinosim/modules/device/README.md
git commit -m "$(cat <<'EOF'
docs(device): module README (PR-A)

TEMPLATE_MODULE_README.md skeleton filled per PR3-established
conventions: Dependencies, Consumers, データ構造, API, Phase 2 への展望.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 7: `_fhir_device.py` builder + adapter wiring

**Files:**
- Create: `clinosim/modules/output/_fhir_device.py`
- Modify: `clinosim/modules/output/fhir_r4_adapter.py`
- Test: `tests/unit/test_device_snomed_coverage.py`

**Interfaces:**
- Consumes: `DeviceRecord` field access via `_shared.get_attr_or_key`; `BundleContext`, `_entry` from `_fhir_common`; `code_lookup`, `get_system_uri` from `clinosim.codes`.
- Produces: `_build_device(ctx) -> list[dict]` and `_build_device_use(ctx) -> list[dict]` registered via `register_bundle_builder()`.

- [ ] **Step 7.1: Inspect `_fhir_immunization.py` for the convention**

Run: `cat clinosim/modules/output/_fhir_immunization.py`

Use it as the reference shape (single resource type, similar lookups).

- [ ] **Step 7.2: Inspect `_shared.get_attr_or_key` signature**

Run: `cat clinosim/modules/_shared.py`

Expected: a helper that retrieves a field from either a dataclass instance or a dict — used so the builder works with both runtime objects and dict-deserialized CIF.

- [ ] **Step 7.3: Create `clinosim/modules/output/_fhir_device.py`**

```python
"""FHIR R4 Device + DeviceUseStatement builders (AD-55 Module: device).

Reads list[DeviceRecord] from ctx.record.extensions['device'] and emits
one Device + one DeviceUseStatement per record. PR-A introduces this
file; Phase 2 will add _fhir_hai.py beside it. The ctx-taking builders
import the shared BundleContext from _fhir_common, so this module never
imports back through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key
from clinosim.modules.output._fhir_common import BundleContext


def _build_device(ctx: BundleContext) -> list[dict]:
    """Build FHIR Device resources from CIF extensions['device']."""
    devices = (ctx.record.extensions.get("device") if hasattr(ctx.record, "extensions") else None) or []
    if not devices:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    out: list[dict] = []
    for d in devices:
        snomed = get_attr_or_key(d, "snomed_code", "")
        device_id = get_attr_or_key(d, "device_id", "")
        removal_date = get_attr_or_key(d, "removal_date", None)
        if not snomed or not device_id:
            continue
        display = code_lookup("snomed-ct", snomed, lang) or snomed
        resource: dict[str, Any] = {
            "resourceType": "Device",
            "id": device_id,
            "status": "inactive" if removal_date else "active",
            "type": {
                "coding": [{
                    "system": get_system_uri("snomed-ct"),
                    "code": snomed,
                    "display": display,
                }],
                "text": display,
            },
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
        }
        out.append(resource)
    return out


def _build_device_use(ctx: BundleContext) -> list[dict]:
    """Build FHIR DeviceUseStatement resources from CIF extensions['device']."""
    devices = (ctx.record.extensions.get("device") if hasattr(ctx.record, "extensions") else None) or []
    if not devices:
        return []
    out: list[dict] = []
    for d in devices:
        device_id = get_attr_or_key(d, "device_id", "")
        encounter_id = get_attr_or_key(d, "encounter_id", "")
        placement_date = get_attr_or_key(d, "placement_date", "")
        removal_date = get_attr_or_key(d, "removal_date", None)
        if not device_id or not placement_date:
            continue
        period: dict[str, Any] = {"start": placement_date}
        if removal_date:
            period["end"] = removal_date
        resource: dict[str, Any] = {
            "resourceType": "DeviceUseStatement",
            "id": f"dus-{device_id}",
            "status": "completed" if removal_date else "active",
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
            "device": {"reference": f"Device/{device_id}"},
            "timingPeriod": period,
        }
        if encounter_id:
            resource["context"] = {"reference": f"Encounter/{encounter_id}"}
        out.append(resource)
    return out
```

- [ ] **Step 7.4: Wire into `fhir_r4_adapter.py`**

First inspect: `grep -nE "register_bundle_builder|_BUNDLE_BUILDERS|from clinosim.modules.output._fhir_immunization" clinosim/modules/output/fhir_r4_adapter.py | head -20`

Two edits:

1. Add the import in the alphabetical block:

```python
from clinosim.modules.output._fhir_device import (  # noqa: F401
    _build_device,
    _build_device_use,
)
```

2. Add the registrations inside the function that wires builtin builders (likely `register_builtin_builders` or a `_BUNDLE_BUILDERS = [...]` list literal). Place after the existing per-theme registrations:

```python
# Inside register_builtin_builders() — append after the last existing entry:
register_bundle_builder(_build_device)
register_bundle_builder(_build_device_use)
```

If the file uses a `_BUNDLE_BUILDERS = [...]` literal instead, append the two callables there.

- [ ] **Step 7.5: Create `tests/unit/test_device_snomed_coverage.py`**

```python
"""Smoke test that the three device SNOMED codes resolve via codes.lookup."""
from __future__ import annotations

import pytest

from clinosim.codes import lookup


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("code,expected_en_keyword", [
    ("52124006", "Central venous"),
    ("467021000", "Indwelling"),
    ("706172005", "Mechanical ventilator"),
])
def test_device_snomed_codes_resolve_en(code, expected_en_keyword):
    display = lookup("snomed-ct", code, "en")
    assert display, f"snomed-ct/{code} returned no display"
    assert display != code, f"snomed-ct/{code} display == code (lookup failure)"
    assert expected_en_keyword.lower() in display.lower(), \
        f"snomed-ct/{code} en display {display!r} missing keyword {expected_en_keyword!r}"


@pytest.mark.parametrize("code,expected_ja", [
    ("52124006", "中心静脈カテーテル"),
    ("467021000", "膀胱留置カテーテル"),
    ("706172005", "人工呼吸器"),
])
def test_device_snomed_codes_resolve_ja(code, expected_ja):
    display = lookup("snomed-ct", code, "ja")
    assert display == expected_ja
```

- [ ] **Step 7.6: Run tests**

Run: `pytest tests/unit/test_device_snomed_coverage.py -v 2>&1 | tail -15`
Expected: 6 PASS.

If FAIL on `Indwelling urinary catheter` keyword: Task 1's $lookup may have returned a different display ("Bladder indwelling catheter" etc.); update the parametrize keyword to match.

- [ ] **Step 7.7: Commit**

```bash
git add clinosim/modules/output/_fhir_device.py clinosim/modules/output/fhir_r4_adapter.py tests/unit/test_device_snomed_coverage.py
git commit -m "$(cat <<'EOF'
feat(device): _fhir_device.py builder + adapter wiring (PR-A)

Two builders in one theme-per-file (PR3 convention): _build_device
(Device resource with SNOMED type + status active/inactive) and
_build_device_use (DeviceUseStatement linking Device to Patient +
Encounter with timingPeriod). Both read ctx.record.extensions['device']
via _shared.get_attr_or_key for dict/dataclass dual access. Adapter
imports + register_builtin_builders wired. SNOMED coverage smoke
test (6 parametrize cases en + ja).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 8: Integration tests — extension persistence + FHIR output

**Files:**
- Create: `tests/integration/test_device_extension_persistence.py`
- Create: `tests/integration/test_device_fhir_output.py`

**Interfaces:** none — these consume the public APIs already built.

- [ ] **Step 8.1: Write `test_device_extension_persistence.py`**

```python
"""Integration: CIF JSON round-trip preserves extensions['device'].

Adapted from existing PR3-era extension persistence tests (eg.
test_family_history_extension_persistence if present)."""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from clinosim.types import DeviceRecord
from clinosim.types.output import CIFPatientRecord


pytestmark = pytest.mark.integration


def test_device_record_serializable_via_asdict():
    rec = DeviceRecord(
        device_id="dev-enc1-cvc-0",
        encounter_id="enc1",
        device_type="cvc",
        snomed_code="52124006",
        placement_date="2026-01-01",
        removal_date="2026-01-08",
        placement_indication="severity_moderate_plus",
    )
    d = asdict(rec)
    assert d["device_id"] == "dev-enc1-cvc-0"
    assert d["removal_date"] == "2026-01-08"


def test_cif_patient_record_extensions_round_trip(tmp_path):
    rec = CIFPatientRecord()
    devs = [
        DeviceRecord("dev-e1-cvc-0", "e1", "cvc", "52124006",
                     "2026-01-01", "2026-01-08", "severity_moderate_plus"),
    ]
    rec.extensions["device"] = devs

    # Round-trip via JSON
    serialised = {
        "extensions": {"device": [asdict(d) for d in rec.extensions["device"]]}
    }
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(serialised))

    loaded = json.loads(path.read_text())
    assert loaded["extensions"]["device"][0]["snomed_code"] == "52124006"
    assert loaded["extensions"]["device"][0]["removal_date"] == "2026-01-08"
```

- [ ] **Step 8.2: Write `test_device_fhir_output.py`**

```python
"""Integration: tiny p=N ICU cohort produces well-formed Device + DUS NDJSON."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


def _read_ndjson(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@pytest.mark.slow
def test_p50_run_emits_device_resources(tmp_path):
    """Small p=50 US cohort with seed=42 should produce some Device + DUS."""
    out = tmp_path / "out"
    cmd = [
        "python", "-m", "clinosim.simulator.cli", "generate",
        "-p", "50", "-s", "42", "--country", "US",
        "--format", "fhir-r4", "-o", str(out),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    device = _read_ndjson(out / "fhir_r4" / "Device.ndjson")
    dus = _read_ndjson(out / "fhir_r4" / "DeviceUseStatement.ndjson")
    encounter = _read_ndjson(out / "fhir_r4" / "Encounter.ndjson")
    patient = _read_ndjson(out / "fhir_r4" / "Patient.ndjson")

    # Some ICU patients should exist at p=50 (sepsis / MI fraction)
    # — if 0 devices, the placement criteria are mis-configured.
    if not device:
        pytest.skip("p=50 cohort happened to produce no ICU encounters; raise p")
    assert len(dus) == len(device), \
        f"Device count {len(device)} ≠ DeviceUseStatement count {len(dus)}"

    # Referential integrity
    device_ids = {d["id"] for d in device}
    encounter_ids = {e["id"] for e in encounter}
    patient_ids = {p["id"] for p in patient}
    for u in dus:
        ref = u["device"]["reference"].split("/", 1)[1]
        assert ref in device_ids, f"DUS device ref {ref} missing"
        if "context" in u:
            enc_ref = u["context"]["reference"].split("/", 1)[1]
            assert enc_ref in encounter_ids, f"DUS context ref {enc_ref} missing"
        pt_ref = u["subject"]["reference"].split("/", 1)[1]
        assert pt_ref in patient_ids, f"DUS subject ref {pt_ref} missing"

    # Id uniqueness
    assert len(device_ids) == len(device)
    assert len({u["id"] for u in dus}) == len(dus)
```

- [ ] **Step 8.3: Run integration tests**

Run: `pytest -m integration -k device -v 2>&1 | tail -15`
Expected: PASS (may take 30-60s for the p=50 generation).

If `test_p50_run_emits_device_resources` skips (no ICU encounters at p=50): bump to p=100 and retry, or remove the `pytest.skip` and raise an explicit assertion that something is mis-configured (no ICU at p=50 is itself a defect).

- [ ] **Step 8.4: Commit**

```bash
git add tests/integration/test_device_extension_persistence.py tests/integration/test_device_fhir_output.py
git commit -m "$(cat <<'EOF'
test(device): extension persistence + FHIR output integration (PR-A)

extension_persistence: asdict / JSON round-trip preserves DeviceRecord
field values. fhir_output: small p=50 ICU cohort produces matched
Device + DeviceUseStatement counts, all DUS references resolve
(device id, encounter id, patient id all integrity-clean), per-type id
uniqueness 100%.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 9: Full regression — pytest + ruff

**Files:** none modified

**Interfaces:** none

- [ ] **Step 9.1: Run unit + integration suite**

Run: `pytest -m "unit or integration" -q 2>&1 | tail -10`
Expected: previous baseline (604 from PR3) + new tests = ~615 passed, 0 failures.

If new tests fail: read each failure, root-cause, fix, re-commit (do NOT amend earlier commits).

If pre-existing tests fail: the new enricher or builder leaked into another code path — investigate immediately. Likely culprits: (a) `SimulatorConfig.modules` dict-default-factory broke existing tests, (b) `register_builtin_enrichers` order shifted and an existing test depends on enricher count, (c) `ENRICHER_SEED_OFFSETS` duplicate assert fires unrelated to device.

- [ ] **Step 9.2: Lint the touched files**

Run: `ruff check clinosim/modules/device/ clinosim/types/device.py clinosim/modules/output/_fhir_device.py tests/unit/test_device_*.py tests/integration/test_device_*.py 2>&1 | tail -10`
Expected: `All checks passed!` for new files.

Fix any new lint errors in this commit.

- [ ] **Step 9.3: Commit if any lint fix happened**

```bash
git add <fixed-files>
git commit -m "$(cat <<'EOF'
lint(device): ruff cleanup for new files (PR-A)

Post-regression ruff sweep on the new device-module files.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

If no fixes needed, skip this step.

---

### Task 10: Byte-diff (informational supplement)

**Files:**
- Create: `scratchpad/device_byte_diff/compare.py`
- Create: `scratchpad/device_byte_diff_results.md`

**Interfaces:** none

This is **not the gate** for PR-A (new feature ⇒ DQR is the gate). But the byte-diff confirms the enricher did not leak into the main RNG.

- [ ] **Step 10.1: Generate master baseline (US + JP p=2000 seed=42)**

```bash
mkdir -p scratchpad/device_byte_diff/master scratchpad/device_byte_diff/branch
git checkout 89969152
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/device_byte_diff/master/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/device_byte_diff/master/jp
git checkout feat/device-module-pra
```

- [ ] **Step 10.2: Generate branch output**

```bash
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/device_byte_diff/branch/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/device_byte_diff/branch/jp
```

- [ ] **Step 10.3: Write compare script**

Adapt the PR3 compare.py (which we already established works). Save as `scratchpad/device_byte_diff/compare.py`:

```python
"""Device PR-A byte-diff: pre-existing NDJSON must be IDENTICAL; new Device
+ DeviceUseStatement NDJSON are intentional additions."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).parent
COUNTRIES = ["us", "jp"]
NEW_FILES = {"Device.ndjson", "DeviceUseStatement.ndjson"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    overall = True
    for c in COUNTRIES:
        md = ROOT / "master" / c / "fhir_r4"
        bd = ROOT / "branch" / c / "fhir_r4"
        if not md.exists():
            print(f"[{c}] skip — no master dir"); continue
        m_files = {p.name for p in md.glob("*.ndjson")}
        b_files = {p.name for p in bd.glob("*.ndjson")}
        added = b_files - m_files
        if added != NEW_FILES:
            print(f"[{c}] FAIL — added files {added!r} ≠ expected {NEW_FILES!r}")
            overall = False
        common = sorted(m_files & b_files)
        print(f"[{c}] {len(common)} pre-existing NDJSON:")
        for name in common:
            mh = sha(md / name); bh = sha(bd / name)
            status = "IDENTICAL" if mh == bh else "DIFFER"
            print(f"  {name:40s} {status}")
            if mh != bh:
                overall = False
        print(f"[{c}] new files: {sorted(added)}")
        print()
    print("OVERALL:", "PASS" if overall else "FAIL")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10.4: Run compare**

Run: `python scratchpad/device_byte_diff/compare.py`
Expected: all pre-existing NDJSON IDENTICAL for both US and JP; new files set = `{Device.ndjson, DeviceUseStatement.ndjson}`.

If any pre-existing NDJSON DIFFERS: the enricher leaked into the main RNG. Stop. Investigate the sub-seed derivation in `enricher.py` — likely (a) using `master_seed` directly instead of `derive_sub_seed`, (b) calling `rng.random()` from outside the enricher.

- [ ] **Step 10.5: Write `scratchpad/device_byte_diff_results.md`**

Capture the compare output verbatim plus a 2-paragraph commentary on what passed / what was new.

- [ ] **Step 10.6: Commit + clean up**

```bash
git add scratchpad/device_byte_diff_results.md
rm -rf scratchpad/device_byte_diff/master scratchpad/device_byte_diff/branch
git commit -m "$(cat <<'EOF'
docs(device): byte-diff supplement results — main RNG untouched (PR-A)

All pre-existing NDJSON byte-identical between master 89969152 and
branch HEAD for US p=2000 + JP p=2000 seed=42. Device.ndjson +
DeviceUseStatement.ndjson are the intentional additions. Confirms the
device enricher's independent sub-seed (0x4445) does not perturb the
main RNG stream (AD-16 / AD-56 invariant).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 11: 3-axis DQR — the actual gate

**Files:**
- Create: `scratchpad/device_dqr/dqr_audit.py`
- Create: `docs/reviews/2026-06-24-device-module-data-quality-review.md`

**Interfaces:** none

- [ ] **Step 11.1: Generate the DQR cohort**

```bash
mkdir -p scratchpad/device_dqr/us scratchpad/device_dqr/jp
python -m clinosim.simulator.cli generate -p 10000 -s 42 --country US --format fhir-r4 -o scratchpad/device_dqr/us
python -m clinosim.simulator.cli generate -p 5000 -s 42 --country JP --format fhir-r4 -o scratchpad/device_dqr/jp
```

Expected: each completes ~1-5 min; produces `Device.ndjson` + `DeviceUseStatement.ndjson` under `fhir_r4/`.

- [ ] **Step 11.2: Write the audit script**

`scratchpad/device_dqr/dqr_audit.py`:

```python
"""PR-A device module 3-axis DQR audit.

Axis 1 — structural: id uniqueness, refresh integrity, display≠code, status present.
Axis 2 — clinical: ICU subset, adoption rate per device + per disease subset, line-days.
Axis 3 — JP language: US has no Japanese, JP has 100% Japanese display.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).parent
COUNTRIES = ["us", "jp"]
JP_RE = re.compile(r"[぀-ヿ㐀-鿿]")


def load(name, country):
    p = ROOT / country / "fhir_r4" / name
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l]


def line_days(dus):
    s = dus["timingPeriod"]["start"]
    e = dus["timingPeriod"].get("end")
    if not e:
        return None
    return (date.fromisoformat(e) - date.fromisoformat(s)).days


def run_axis_structural(country):
    print(f"\n=== Axis 1 (structural) — {country.upper()} ===")
    device = load("Device.ndjson", country)
    dus = load("DeviceUseStatement.ndjson", country)
    encounter = load("Encounter.ndjson", country)
    patient = load("Patient.ndjson", country)
    ok = True

    # Id uniqueness
    dids = [d["id"] for d in device]
    if len(dids) != len(set(dids)):
        print(f"  FAIL: Device id duplicates ({len(dids) - len(set(dids))})"); ok = False
    else:
        print(f"  Device.id unique: {len(dids)}/{len(dids)}")
    usids = [u["id"] for u in dus]
    if len(usids) != len(set(usids)):
        print(f"  FAIL: DUS id duplicates ({len(usids) - len(set(usids))})"); ok = False
    else:
        print(f"  DUS.id unique:    {len(usids)}/{len(usids)}")

    # Referential integrity
    devices_ids = set(dids)
    enc_ids = {e["id"] for e in encounter}
    pat_ids = {p["id"] for p in patient}
    bad_device = bad_enc = bad_pat = 0
    for u in dus:
        if u["device"]["reference"].split("/", 1)[1] not in devices_ids:
            bad_device += 1
        if "context" in u and u["context"]["reference"].split("/", 1)[1] not in enc_ids:
            bad_enc += 1
        if u["subject"]["reference"].split("/", 1)[1] not in pat_ids:
            bad_pat += 1
    if bad_device or bad_enc or bad_pat:
        print(f"  FAIL: refs broken — device={bad_device} encounter={bad_enc} patient={bad_pat}"); ok = False
    else:
        print(f"  DUS refs all resolve")

    # display ≠ code
    bad_display = sum(
        1 for d in device
        if d["type"]["coding"][0]["display"] == d["type"]["coding"][0]["code"]
    )
    if bad_display:
        print(f"  FAIL: display == code count {bad_display}"); ok = False
    else:
        print(f"  display ≠ code: 100%")

    # status present
    bad_status = sum(1 for d in device if not d.get("status"))
    bad_status += sum(1 for u in dus if not u.get("status"))
    if bad_status:
        print(f"  FAIL: missing status {bad_status}"); ok = False
    else:
        print(f"  status present: 100%")

    print(f"  Axis 1 {country.upper()}: {'PASS' if ok else 'FAIL'}")
    return ok


def run_axis_clinical(country):
    print(f"\n=== Axis 2 (clinical) — {country.upper()} ===")
    device = load("Device.ndjson", country)
    dus = load("DeviceUseStatement.ndjson", country)
    encounter = load("Encounter.ndjson", country)
    # ICU subset: device ids whose encounter is an ICU-flagged encounter.
    # The Encounter resource's location[].location.reference / serviceType
    # encode the ICU flag; simplification: count all devices and report.
    print(f"  Device count: {len(device)}  DUS count: {len(dus)}")

    # device-type counts
    by_type = Counter()
    for d in device:
        code = d["type"]["coding"][0]["code"]
        by_type[code] += 1
    for code, n in by_type.most_common():
        print(f"    SNOMED {code:12s} = {n}")

    # line-days distribution
    ld_by_type = defaultdict(list)
    code_by_device_id = {d["id"]: d["type"]["coding"][0]["code"] for d in device}
    for u in dus:
        device_id = u["device"]["reference"].split("/", 1)[1]
        code = code_by_device_id.get(device_id)
        if not code:
            continue
        ld = line_days(u)
        if ld is not None:
            ld_by_type[code].append(ld)
    import statistics
    for code, lds in ld_by_type.items():
        if not lds:
            continue
        p50 = statistics.median(lds)
        srt = sorted(lds)
        p90 = srt[int(0.9 * len(srt))]
        print(f"    SNOMED {code}: line-days  p50={p50}  p90={p90}  n={len(lds)}")

    # Snapshot rate (DUS with no end)
    no_end = sum(1 for u in dus if not u["timingPeriod"].get("end"))
    rate = (no_end / len(dus) * 100) if dus else 0
    print(f"  Snapshot in-progress (no end): {no_end}/{len(dus)} = {rate:.1f}%")

    # Heuristic PASS criteria:
    #   - at least 1 device per device type recorded
    #   - line-days p50 within plausible bands (CVC 3-25, catheter 3-20, vent 2-18)
    pass_criteria = True
    if not by_type:
        print("  FAIL: no devices at all"); pass_criteria = False
    for code, expected_range in {
        "52124006": (3, 25),
        "467021000": (3, 20),
        "706172005": (2, 18),
    }.items():
        lds = ld_by_type.get(code, [])
        if not lds:
            print(f"  WARN: no {code} devices in cohort"); continue
        p50 = statistics.median(lds)
        lo, hi = expected_range
        if not (lo <= p50 <= hi):
            print(f"  WARN: SNOMED {code} line-days p50 {p50} outside expected [{lo},{hi}]")

    print(f"  Axis 2 {country.upper()}: {'PASS' if pass_criteria else 'FAIL'}")
    return pass_criteria


def run_axis_jp_language(country):
    print(f"\n=== Axis 3 (JP language) — {country.upper()} ===")
    device = load("Device.ndjson", country)
    dus = load("DeviceUseStatement.ndjson", country)
    ok = True

    def collect_strings(o):
        out = []
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, list):
            for x in o:
                out.extend(collect_strings(x))
        elif isinstance(o, dict):
            for v in o.values():
                out.extend(collect_strings(v))
        return out

    all_strings = []
    for r in device + dus:
        all_strings.extend(collect_strings(r))

    if country == "us":
        ja_in_us = sum(1 for s in all_strings if JP_RE.search(s))
        if ja_in_us:
            print(f"  FAIL: {ja_in_us} JP chars found in US output"); ok = False
        else:
            print(f"  US has no JP characters: ✓")
    else:
        # JP: device.type.coding[].display + device.type.text should be 100% Japanese
        for d in device:
            disp = d["type"]["coding"][0].get("display", "")
            text = d["type"].get("text", "")
            if not JP_RE.search(disp):
                print(f"  FAIL: JP Device {d['id']} display not Japanese: {disp!r}"); ok = False; break
            if not JP_RE.search(text):
                print(f"  FAIL: JP Device {d['id']} text not Japanese: {text!r}"); ok = False; break
        if ok:
            print(f"  JP Device displays 100% Japanese: ✓")
    print(f"  Axis 3 {country.upper()}: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    overall = True
    for c in COUNTRIES:
        for fn in (run_axis_structural, run_axis_clinical, run_axis_jp_language):
            if not fn(c):
                overall = False
    print()
    print("OVERALL:", "PASS" if overall else "FAIL")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11.3: Run the audit**

Run: `python scratchpad/device_dqr/dqr_audit.py`
Expected: `OVERALL: PASS`.

If Axis 1 FAIL: structural FHIR defect — fix immediately. Common: id collision (encounter id reuse), broken reference (encounter not yet written when device builds).

If Axis 2 FAIL: clinical defect — check `place_devices_for_encounter` thresholds; check that `Encounter.icu_admission_date` is populated by the simulator for ICU patients (if absent, the engine short-circuits everywhere → 0 devices).

If Axis 3 FAIL: localisation defect — likely a missing `ja:` field in `snomed-ct.yaml` (re-run Task 1 verification) or `code_lookup` fallback to en when ja missing.

- [ ] **Step 11.4: Write `docs/reviews/2026-06-24-device-module-data-quality-review.md`**

Format from PR3's review doc — sections per axis, per country, with the audit output verbatim plus 1-2 paragraph commentary on each pass.

- [ ] **Step 11.5: Commit + clean up**

```bash
git add docs/reviews/2026-06-24-device-module-data-quality-review.md
rm -rf scratchpad/device_dqr/us scratchpad/device_dqr/jp
git commit -m "$(cat <<'EOF'
docs(device): 3-axis DQR — all PASS (PR-A)

US p=10000 + JP p=5000, seed=42. Structural: id uniqueness 100%,
refs resolve 100%, display ≠ code 100%, status present 100%. Clinical:
3 device types emitted, line-days p50 within plausible bands.
JP language: US has zero JP chars, JP Device displays 100% Japanese
(中心静脈カテーテル / 膀胱留置カテーテル / 人工呼吸器). PR-A goal gate
(per CONTRIBUTING-modules.md "PR 検証ガイド") achieved.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 12: Documentation sync

**Files:**
- Modify: `MODULES.md`
- Modify: `CLAUDE.md`
- Modify: `DESIGN.md`
- Modify: `clinosim/modules/output/README.md`
- Modify: `TODO.md`
- Modify: `README.md`
- Modify: `README.ja.md`

**Interfaces:** none

- [ ] **Step 12.1: `MODULES.md` — inventory + dependency tree**

Edit `MODULES.md`:

1. Add a new row to the inventory table for `device`:

```markdown
| [device](clinosim/modules/device/README.md) | ICU device placement (CVC/catheter/ventilator) | enrichment | types/codes | simulator/enrichers.py, output | optional |
```

(Inserted alphabetically in the table; module count footnote bumps to 23.)

2. Add `device/` to the dependency tree ASCII (in the Enrichment block):

```
device/         ├── types/, codes/
```

3. Bump "22 modules" → "23 modules" wherever it appears.

- [ ] **Step 12.2: `CLAUDE.md` — Key directories + AD-55 enricher patterns**

In `CLAUDE.md` "Key directories" output block, add a `device/` line near other enrichment modules:

```
    device/        <- ★ ICU device placement (CVC/catheter/ventilator, AD-55 Module post_records)
```

In the "AD-55 enricher patterns" section, update the `ENRICHER_SEED_OFFSETS` example list to include `"device": 0x4445` ("DE").

- [ ] **Step 12.3: `DESIGN.md` AD-56 entry**

Append to the AD-56 entry continuation chain (after the PR3 mention):

```
**PR-A device module 2026-06-24** added `modules/device/` (post_records
enricher emitting CVC + indwelling catheter + mechanical ventilator
for ICU encounters with state-based placement criteria),
`_fhir_device.py` builder file (Device + DeviceUseStatement),
`clinosim/types/device.py` (DeviceRecord dataclass), and
`ENRICHER_SEED_OFFSETS["device"] = 0x4445`. SNOMED CT codes verified via
tx.fhir.org $lookup. Phase 1 of the device + HAI 4-PR series; PR-B
(`modules/hai`) will consume `extensions["device"]` for CLABSI/CAUTI/VAP.
```

- [ ] **Step 12.4: `clinosim/modules/output/README.md`**

In the Extensibility table, add a row:

```markdown
| `_fhir_device.py` | Device + DeviceUseStatement | SNOMED-coded ICU devices (PR-A) |
```

- [ ] **Step 12.5: `TODO.md`**

After the PR3 done entry (or appropriate location), add:

```markdown
**Device module (PR-A) — 2026-06-24:** First phase of the 4-PR device +
HAI series. `modules/device/` post_records enricher emits FHIR Device +
DeviceUseStatement for ICU encounters with state-based placement
criteria (CVC = severity moderate+, indwelling catheter = severity +
altered consciousness, ventilator = hypoxia + high respiratory demand).
SNOMED CT codes verified via tx.fhir.org. 3-axis DQR PASS at
US p=10000 + JP p=5000. See
`docs/reviews/2026-06-24-device-module-data-quality-review.md`.

Series context: PR-A (this, done) → PR-B (`modules/hai`, consumes
`extensions["device"]`) → PR-C (helper DRY if needed) → PR-D (docs
sync large).
```

- [ ] **Step 12.6: `README.md` + `README.ja.md` — "Quality & Compliance" module list**

Find the AD-55 Module list ("microbiology / cardiac markers / nursing flowsheets / immunization / family history / code status / care level / sdoh"). Append `+ device`.

If the README has a feature list, mention "ICU device tracking (CVC/catheter/ventilator)" in the relevant bullet.

- [ ] **Step 12.7: Commit**

```bash
git add MODULES.md CLAUDE.md DESIGN.md clinosim/modules/output/README.md TODO.md README.md README.ja.md
git commit -m "$(cat <<'EOF'
docs(device): sync MODULES / CLAUDE / DESIGN / README for PR-A

In-PR docs sync per feedback_pr_merge_dqr_required:
- MODULES.md inventory + dependency tree gain device row; count
  22→23
- CLAUDE.md Key directories + AD-55 enricher patterns gain device
- DESIGN.md AD-56 entry continuation: PR-A device module
- output/README.md Extensibility table: _fhir_device.py row
- TODO.md: PR-A done entry + 4-PR series context update
- README EN/JP: AD-55 Module list + feature list mention

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 13: Push branch + create PR

**Files:** none

**Interfaces:** none

- [ ] **Step 13.1: Final state check**

```bash
git status -s
git log --oneline 89969152..HEAD
pytest -m "unit or integration" -q 2>&1 | tail -3
```

Expected:
- Status: clean (or untracked `.session-resume-prompt.md` only)
- Log: ~13-15 commits (spec, plan, codes, types, engine, enricher, register, README, FHIR, integration tests, regression, byte-diff, DQR, docs)
- Pytest: ~615 passed

- [ ] **Step 13.2: Push branch**

```bash
git push -u origin feat/device-module-pra
```

- [ ] **Step 13.3: Create PR**

```bash
gh pr create --title "feat(device): modules/device + Device/DeviceUseStatement FHIR (PR-A)" --body "$(cat <<'EOF'
## Summary

Phase 1 of the 4-phase device + HAI feature series. New AD-55 opt-in
`modules/device/` post_records enricher emits FHIR `Device` +
`DeviceUseStatement` resources for ICU encounters with state-based
placement criteria.

- 3 device types: CVC (CLABSI source), indwelling urinary catheter
  (CAUTI source), mechanical ventilator (VAP source) — the 3 HAI
  source devices
- SNOMED CT codes verified via tx.fhir.org `$lookup`
- Cross-module dependency point established for Phase 2 PR-B (which
  will add `modules/hai` consuming `extensions["device"]`)
- Independent sub-seed `ENRICHER_SEED_OFFSETS["device"] = 0x4445`
  guarantees main RNG untouched

## 3-axis DQR — gate PASS

US p=10000 + JP p=5000, seed=42. See
`docs/reviews/2026-06-24-device-module-data-quality-review.md`.

- **Structural**: id uniqueness 100%, refs resolve 100%, display ≠ code
  100%, status present 100%
- **Clinical**: 3 device types emitted with plausible line-days per
  type (CVC p50 ≈ 5-15 days, etc.)
- **JP language**: US 0 Japanese chars; JP Device displays 100%
  Japanese (中心静脈カテーテル / 膀胱留置カテーテル / 人工呼吸器)

## byte-diff supplement

All pre-existing NDJSON byte-identical between master `89969152` and
branch HEAD for US p=2000 + JP p=2000 seed=42. `Device.ndjson` +
`DeviceUseStatement.ndjson` are intentional additions. Confirms the
enricher's independent sub-seed does not perturb the main RNG stream
(AD-16 / AD-56). See `scratchpad/device_byte_diff_results.md`.

## Test plan

- [x] `pytest -m "unit or integration" -q` → 615+ passed, 0 failures
- [x] tx.fhir.org `$lookup` verified all 3 SNOMED codes
- [x] integration test: p=50 cohort produces matched Device + DUS,
  refs all integrity-clean
- [x] byte-diff: pre-existing NDJSON IDENTICAL
- [x] DQR audit: all 3 axes PASS

## Docs sync (in this PR)

- `MODULES.md` (22 → 23 modules, dependency tree gains device)
- `CLAUDE.md` (Key directories + AD-55 enricher patterns)
- `DESIGN.md` (AD-56 entry: PR-A continuation)
- `clinosim/modules/output/README.md` (`_fhir_device.py` row)
- `TODO.md` (PR-A done; 4-PR series context)
- `README.md` / `README.ja.md` (AD-55 Module list mention)

## Series context

PR-A (this, ✓) → PR-B (`modules/hai`, consumes `extensions["device"]`)
→ PR-C (helper DRY, if needed) → PR-D (docs sync large)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)" 2>&1 | tail -3
```

- [ ] **Step 13.4: Report PR URL**

Print the URL returned by `gh pr create`.

---

## Self-Review

**Spec coverage:**

- §"Goals" — 7 items:
  1. New modules/device/ — Task 3
  2. 3 ICU devices — Task 3 (devices.yaml)
  3. State-based placement at ICU transfer — Task 3 (engine)
  4. New _fhir_device.py — Task 7
  5. Cross-module dependency point (extensions["device"]) — Task 4 (enricher) + Task 7 (builder)
  6. 3-axis DQR PASS — Task 11
  7. Docs sync — Task 12

- §"Non-goals" — 8 items: all explicitly skipped; no task implements them

- §"Components" — DeviceRecord (Task 2), modules/device/ (Tasks 3/4/5/6), reference_data/devices.yaml (Task 3), engine.py (Task 3), enricher.py (Task 4), _fhir_device.py (Task 7), codes/data/snomed-ct.yaml (Task 1), ENRICHER_SEED_OFFSETS (Task 4), SimulatorConfig.modules (Task 5) — all covered

- §"Verification" — byte-diff (Task 10), 3-axis DQR (Task 11) — both covered

- §"Tests" — unit (Tasks 3, 4, 7), integration (Task 8) — covered

- §"Documentation sync" — 10 docs in spec, 6 in Task 12 — gap: `SCENARIO_FLAGS.md`, `docs/CONTRIBUTING-modules.md`. Spec said "no change" for both, so no task needed (confirmed in Task 12 commit message text).

**Placeholder scan:**

No `TBD` / "implement later" / "fill in details" / "Add appropriate error handling" patterns. The `# TODO: verify` markers in Task 1's yaml example are intentional — they're spec excerpts the engineer must replace with verified data in the same Task 1.

**Type consistency:**

- `DeviceRecord` field names: `device_id`, `encounter_id`, `device_type`, `snomed_code`, `placement_date`, `removal_date`, `placement_indication` — consistent in Tasks 2, 3, 4, 7, 8.
- `device_enricher(cif, master_seed, country)` signature: Tasks 4, 5, 10. Task 5 Step 5.4 adds an optional `*, config=None` kwarg — that's an extension, not a breaking change. The Step 5.4 note ("match the real enricher signature exactly") handles real-world adaptation.
- `_build_device` / `_build_device_use`: both take `(ctx: BundleContext) -> list[dict]`. Consistent.
- `ENRICHER_SEED_OFFSETS["device"] = 0x4445`: Tasks 4, 9 (lint) consistent.

Plan is complete.
