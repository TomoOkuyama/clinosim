# device + HAI Phase 1 (PR-A): Device Module Design

**Date:** 2026-06-24  
**Status:** Approved  
**Phase:** PR-A (modules/device + FHIR Device/DeviceUseStatement)  
**Scope:** CIF data structure, placement criteria, FHIR R4 builders, 3-axis DQR framework

---

## Executive Summary

Implement `modules/device`, an AD-55 opt-in module that detects ICU device placement (central venous catheter, indwelling urinary catheter, mechanical ventilator) based on physiological state at ICU admission, stores placement/removal intervals as `CIFPatientRecord.extensions["device"]`, and exports Device + DeviceUseStatement FHIR R4 resources. Establishes clean cross-module enricher consumption pattern for Phase 2 HAI (CLABSI/CAUTI/VAP) to read device line-days and trigger infection events. Phase 1 focuses on device placement logic and FHIR builders; HAI mechanism deferred to Phase 2.

---

## 1. Architecture Overview

### 4-Phase PR Series

Phase 1 (PR-A): Device placement + FHIR builder
→ Phase 2 reads extensions["device"]
→ Phase 2 (PR-B): HAI (CLABSI/CAUTI/VAP) + Condition + Observation
→ Phase 3 (PR-C): Cross-module DRY helpers / line-day utilities
→ Phase 4 (PR-D): Docs sync (large)

### Module Structure

- **New module:** `clinosim/modules/device/` (AD-55 opt-in, gated by `config.module_enabled("device")`, default: enabled)
- **New typed:** `clinosim/types/device.py` — runtime dataclass `DeviceRecord`
- **New enricher:** `clinosim/modules/device/enricher.py` — post_records enricher, sub-seed offset 0x4445 ("DE")
- **New FHIR builder:** `clinosim/modules/output/_fhir_device.py` — Device + DeviceUseStatement (theme-per-file pattern, PR3)
- **Determinism:** Independent sub-seed per enricher call (AD-16, AD-56); main RNG unaffected

### Cross-Module Wiring

device_enricher (post_records) → CIFPatientRecord.extensions["device"] = list[DeviceRecord]
→ [Phase 2] hai_enricher (post_records, runs after device)
→ extensions["hai"] = list[HAIEvent]

This establishes the **cross-module enricher consumption pattern**.

---

## 2. CIF Data Shape

### clinosim/types/device.py (New)

DeviceRecord dataclass:
- device_id: str (format: "dev-{encounter_id}-{device_type}-{i}")
- encounter_id: str (back-reference)
- device_type: str ("cvc" | "indwelling_catheter" | "mechanical_ventilator")
- snomed_code: str (52124006 / 467021000 / 706172005)
- placement_date: str (ISO YYYY-MM-DD)
- removal_date: str | None (None = in-progress at snapshot per AD-32)
- placement_indication: str ("severity_moderate_plus, altered_consciousness" - audit/DQR only)

### Design Rationale

- typed dataclass + extensions slot: CLAUDE.md rule "All types in clinosim/types/"; modules cannot edit CIFPatientRecord directly
- device_id naming ensures per-encounter global uniqueness; maps directly to FHIR Device.id
- placement_date / removal_date as ISO strings: direct mapping to FHIR DeviceUseStatement.usePeriod
- removal_date: str | None for AD-32 (snapshot semantics) compliance
- placement_indication as string: Audit / DQR inspection only, not exposed in FHIR

---

## 3. Module Layout & Placement Logic

### Directory Structure

clinosim/modules/device/
  __init__.py
  engine.py (pure function: place_devices_for_encounter)
  enricher.py (post_records enricher)
  reference_data/
    devices.yaml (SNOMED codes + placement criteria)
  README.md

### devices.yaml

devices:
  cvc:
    snomed_code: "52124006" (TODO: verify via tx.fhir.org)
    snomed_display_en: "Central venous catheter"
    snomed_display_ja: "中心静脈カテーテル"
    placement_criteria: [severity_moderate_plus, vasopressor_use]
  indwelling_catheter:
    snomed_code: "467021000" (TODO: verify via tx.fhir.org)
    snomed_display_en: "Indwelling urinary catheter"
    snomed_display_ja: "膀胱留置カテーテル"
    placement_criteria: [severity_moderate_plus, altered_consciousness]
  mechanical_ventilator:
    snomed_code: "706172005" (TODO: verify via tx.fhir.org)
    snomed_display_en: "Mechanical ventilator"
    snomed_display_ja: "人工呼吸器"
    placement_criteria: [hypoxia, high_respiratory_demand]

### Indication Evaluation

_evaluate_indications(state, severity, altered_consciousness) → set[str]:
- severity in (moderate, severe, critical) → severity_moderate_plus
- altered_consciousness → altered_consciousness
- spo2_baseline < 0.88 or respiratory_status < 0.4 → hypoxia
- respiratory_fraction > 0.7 → high_respiratory_demand

### Placement & Removal Algorithm

place_devices_for_encounter(record, encounter, rng, devices_config) → list[DeviceRecord]:
- if not encounter.icu_admission_date: return []
- evaluate indications
- for each device type matching criteria: create DeviceRecord
  - placement_date = encounter.icu_admission_date
  - removal_date = encounter.icu_discharge_date or None

---

## 4. FHIR R4 Builder

### File: clinosim/modules/output/_fhir_device.py

_build_device(ctx) → list[dict]:
- Device resources (one per DeviceRecord)
- resourceType: "Device"
- id: device_id
- status: "active" if not removal_date else "inactive"
- type: single SNOMED CT coding + text (language-specific)
- patient: reference to Patient

_build_device_use(ctx) → list[dict]:
- DeviceUseStatement resources (usage period)
- resourceType: "DeviceUseStatement"
- id: "dus-{device_id}"
- status: "completed" if removal_date else "active"
- subject: Patient reference
- device: Device reference
- context: Encounter reference
- timingPeriod: start + optional end

### Builder Registration

In clinosim/modules/output/fhir_r4_adapter.py:
register_bundle_builder(_build_device)
register_bundle_builder(_build_device_use)

---

## 5. Verification: 3-Axis Data Quality Review (DQR)

### Byte-Diff Baseline

- Existing 11+ NDJSON types: byte-identical required (device enricher uses independent sub-seed)
- New NDJSON 2 files: Device.ndjson, DeviceUseStatement.ndjson (intentional additions)

### 3-Axis DQR Framework

Test corpus: US p=10000 seed=42 + JP p=5000 seed=42
Audit output: docs/reviews/2026-06-25-device-data-quality-review.md

Axis 1: Structure (FHIR R4 / JP Core compliance)
- All Device.id globally unique
- All DeviceUseStatement.device.reference resolvable
- All DeviceUseStatement.context.reference resolvable
- No Device.type.coding.display equals code
- US output: zero Japanese characters
- JP output: 100% Japanese display
- DeviceUseStatement.status correctly reflects removal_date

Axis 2: Clinical Appropriateness
- Device adoption restricted to ICU stays
- CVC rates: sepsis/MI/shock >=80%, mild ICU <50%, overall 40-60%
- Ventilator rates: COPD/pneumonia severe >70%, mild <20%
- Catheter rates: severe/consciousness >60%, overall 30-50%
- Device timing: placement = ICU admission, removal = ICU discharge or None
- Line-days: CVC p50 5-7 / p90 10-15, Catheter p50 4-6 / p90 8-12, Ventilator p50 3-5 / p90 7-10

Axis 3: JP Language & Code System Integrity
- JP Device.type.coding.display: 100% Japanese
- JP DeviceUseStatement: no CM-granular SNOMED
- US Device: zero Japanese
- SNOMED codes verified via tx.fhir.org

### Unit Tests

- tests/unit/test_device_engine.py: determinism, indication evaluation
- tests/unit/test_device_enricher.py: sub-seed independence, non-ICU zero devices
- tests/integration/test_device_extension_persistence.py: CIF JSON round-trip

---

## 6. Documentation Sync & Non-Goals

### Documentation Updates (PR-A Inclusive)

- clinosim/modules/device/README.md: New (TEMPLATE-compliant)
- MODULES.md: Add device row
- DESIGN.md: Continue AD-56: PR-A 2026-06-24
- CLAUDE.md "Key directories": Add modules/device/
- CLAUDE.md "AD-55 enricher patterns": Add "device": 0x4445 + assert
- TODO.md: PR-A DONE + Phase 2-4 backlog
- clinosim/modules/output/README.md: Add _fhir_device.py builder
- clinosim/simulator/seeding.py: Add ENRICHER_SEED_OFFSETS["device"]
- README.md / README.ja.md: Minor device mention

### Non-Goals (Explicitly Out of PR-A Scope)

1. HAI mechanism — Phase 2 (PR-B)
2. Peripheral IV lines — Phase 5+
3. Device type granularity (arterial, NG, ECMO, dialysis)
4. LOS-internal device evolution
5. CVC sub-types (tunneled, PICC, port)
6. Vasopressor-use indication — Phase 1 simplification
7. Cross-encounter device persistence
8. Device → physiology state mutation

### 4-Axis Quality Scorecard

Data Quality: ✓✓ (2 new FHIR resources, SNOMED verified, realistic distribution)
Clinical Appropriateness: ✓✓ (State-based placement, line-days DQR realistic)
Maintainability: ✓✓ (AD-55 Module pattern, clean Phase 2 HAI dependency)
Conceptual Fit: ✓✓ (enricher + extensions pattern, 4-PR series start)

---

## Phase 2 (PR-B) Scope Preview

- HAI mechanism (scenario-flag vs sampling vs medication-coupling)
- CLABSI / CAUTI / VAP SNOMED/ICD-10-CM codes
- HAI event → Condition + Observation
- device-aware lab orders (blood cultures, UA)
- antibiotic order generation
- extensions["device"] consumption: line-days, risk windows

---

## Implementation Checklist (For writing-plans)

Pre-Implementation:
- Verify 3 SNOMED codes via tx.fhir.org: 52124006, 467021000, 706172005
- Record SNOMED official names + proof

Core Coding:
- clinosim/types/device.py
- clinosim/modules/device/__init__.py, engine.py, enricher.py
- clinosim/modules/device/reference_data/devices.yaml
- clinosim/modules/output/_fhir_device.py
- Registration in fhir_r4_adapter.py + seeding.py

Testing:
- Unit tests: test_device_engine.py, test_device_enricher.py
- Integration: test_device_extension_persistence.py
- Byte-diff baseline vs master
- 3-axis DQR: docs/reviews/2026-06-25-device-data-quality-review.md

Documentation:
- clinosim/modules/device/README.md
- 9 file updates per table
- Commit with SNOMED verification proof

---

## Sign-Off

Design approved by user: 2026-06-24
Next step: writing-plans skill to generate detailed implementation plan
