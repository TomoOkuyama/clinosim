# P2-13 PR1: JP-CLINS 6 Information Items Profile URL Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** country=JP の FHIR Bulk Export に、6 情報(傷病名 / アレルギー / 感染症 / 検査 / 処方 / 処置)対応 resource type ごとに JP-CLINS eCS profile URL を追加 emit する。既存 JP Core profile URL 出力と共存(重ね付け)、Observation は category=laboratory のみ、Condition は感染症(ICD-10 A/B chapter)判別で 2 profile 分岐。

**Architecture:** 既存 `_apply_jp_core_profile` の直後に `_apply_jp_clins_profile` を呼ぶ層を追加。既存 builder 群と `_build_bundle` は変更なし、idempotent + additive。`_JP_CLINS_PROFILES` dict を単一の source of truth として登録。

**Tech Stack:** Python 3.11+, pytest(unit + integration), 既存 FHIR R4 adapter, `clinosim.codes` code lookup

## Global Constraints

- **Determinism (AD-16)**:新規 RNG 導入なし。既存 seed 経路は変更しない → PR1 は byte-diff invariant 上 profile URL 追加分のみ変化(意図的)。`scripts/reproduce.sh` の baseline は PR1 land 時点で再生成し、baseline 更新をコミットに含める。
- **JP Core 併存**:既存 `_apply_jp_core_profile` の出力を維持したまま、`_apply_jp_clins_profile` を追加 layer として重ねる。既存の `_JP_CORE_PROFILES` dict は変更しない。
- **Idempotent**:`meta.profile[]` に既に同 URL があれば append しない。複数回呼ばれても副作用なし。
- **country ゲート**:country="JP" 時のみ apply。country="US" の Bundle は byte-identical(既存 reproduce.sh gate と一致)。
- **URL canonical form**:`http://jpfhir.jp/fhir/clins/StructureDefinition/<Name>` 形式。URL は Python constant に固定、YAML 化しない(spec 内 URL リスト = single source of truth)。
- **感染症判別**:ICD-10 A00-B99 chapter に base code(3 桁)が入る Condition のみ `JP_Condition_Infection_eCS` を追加 emit(通常の `JP_Condition_eCS` も併存)。仕様書 §3.1 の判定基準を採用。
- **Observation フィルタ**:`category.coding[].code == "laboratory"` の Observation のみ `JP_Observation_LabResult_eCS` を追加 emit(vital signs 等は対象外)。
- **DiagnosticReport フィルタ**:`category.coding[].code == "LAB"` or system=hl7-diagnostic-service-sections の LAB のみ対象。
- **反復 adversarial review**(`feedback_iterative_adversarial_review`):PR1 land 前に 1 段 adversarial pass 実施、silent-no-op class の bug を封じる。

## File Structure

**Modify:**
- `clinosim/modules/output/fhir_r4_adapter.py` — `_JP_CLINS_PROFILES` dict、`_apply_jp_clins_profile` 関数、`_is_lab_observation`、`_is_lab_diagnostic_report`、`_is_infection_condition` helper、`_build_bundle` 内で `_apply_jp_core_profile` の直後に呼ぶ 1 行追加
- `tests/unit/test_completeness_invariants.py` — JP-CLINS profile emission gate 追加(全 country=JP Bundle で 6 情報 profile URL が対応 resource に出ていること)

**Create:**
- `tests/unit/test_jp_clins_profile_emit.py` — JP-CLINS profile URL emission の単体テスト集
- `tests/integration/test_jp_clins_pr1_end_to_end.py` — p=100 seed=42 country=JP 実生成 → 6 情報 profile URL 存在率 100%、country=US 出力に URL 混入なし、reference 整合

**No new module directory / no YAML this PR.** URL 定義は Python constant のみ(single source of truth in adapter)。

---

### Task 1: URL canonical form 一次照会 + spec appendix 追加

**Files:**
- Modify: `docs/superpowers/specs/2026-07-12-p2-13-jp-clins-design.md`(§3.1.1 の canonical URL に一次リンク + verification note を追加)

**Interfaces:**
- Consumes: なし
- Produces: `_JP_CLINS_PROFILES` に使う exact URL(後続 Task 2 が import)

- [ ] **Step 1: jpfhir.jp v2025.4 の JP-CLINS eCS StructureDefinition URL を fetch**

Run: `curl -s "https://jpfhir.jp/fhir/clins/" | head -200` and browse to StructureDefinition index. 6 情報対応 profile の canonical URL を確認。

Expected: 以下 6 profile の canonical URL 確定
- Condition: `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_eCS`
- Condition (infection): `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_Infection_eCS`
- AllergyIntolerance: `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_AllergyIntolerance_eCS`
- Observation (lab): `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Observation_LabResult_eCS`
- DiagnosticReport (lab): `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_DiagnosticReport_LabResult_eCS`
- MedicationRequest: `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_MedicationRequest_eCS`
- Procedure: `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Procedure_eCS`

もし公式 URL が上と異なる場合、下記のドキュメント更新 + Task 2 の `_JP_CLINS_PROFILES` 値を差し替える。fetch 不能 or URL が jpfhir.jp v2025.4 に登録されていない場合、Task 1 はブロック → user に確認要求。

- [ ] **Step 2: spec § 3.1.1 に「URL verified against jpfhir.jp v2025.4 on 2026-07-12」note と fetch source URL を追記**

Edit `docs/superpowers/specs/2026-07-12-p2-13-jp-clins-design.md`:

`_JP_CLINS_PROFILES` の code block 直下に以下を追記:

```
> **URL verification (2026-07-12)**: 上記 canonical URL 群は jpfhir.jp v2025.4 の JP-CLINS StructureDefinition index(https://jpfhir.jp/fhir/clins/)から照合。fetch 時のスナップショット URL リスト は `docs/superpowers/plans/2026-07-12-p2-13-jp-clins-pr1-6-info-profiles.md` Task 1 参照。
```

- [ ] **Step 3: commit spec update**

```bash
git add docs/superpowers/specs/2026-07-12-p2-13-jp-clins-design.md
git commit -m "docs(spec): P2-13 pin JP-CLINS canonical URLs against jpfhir.jp v2025.4

URL verified against jpfhir.jp/fhir/clins/ StructureDefinition index
on 2026-07-12. Records source snapshot as PR1 Task 1.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 2: `_JP_CLINS_PROFILES` dict + `_apply_jp_clins_profile` helper (TDD)

**Files:**
- Create: `tests/unit/test_jp_clins_profile_emit.py`
- Modify: `clinosim/modules/output/fhir_r4_adapter.py`(dict + helper 追加)

**Interfaces:**
- Consumes: Task 1 の canonical URLs
- Produces:
  - `_JP_CLINS_PROFILES: dict[str, list[str]]` — resource type → JP-CLINS profile URL リスト
  - `_apply_jp_clins_profile(resource: dict) -> None` — idempotent、`meta.profile[]` に URL を append(同 URL 存在時は skip)
  - `_INFECTION_ICD_PREFIXES: tuple[str, ...]` — `("A", "B")`(ICD-10 感染症 chapter)
  - `_is_infection_condition(resource: dict) -> bool`
  - `_is_lab_observation(resource: dict) -> bool`
  - `_is_lab_diagnostic_report(resource: dict) -> bool`

- [ ] **Step 1: Write failing test for base cases**

Create `tests/unit/test_jp_clins_profile_emit.py`:

```python
"""Unit tests for JP-CLINS eCS profile URL emission (P2-13 PR1)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _JP_CLINS_PROFILES,
    _apply_jp_clins_profile,
    _is_infection_condition,
    _is_lab_diagnostic_report,
    _is_lab_observation,
)


@pytest.mark.unit
class TestApplyJpClinsProfile:
    def test_allergy_gets_ecs_profile(self):
        r = {"resourceType": "AllergyIntolerance"}
        _apply_jp_clins_profile(r)
        assert r["meta"]["profile"] == [
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_AllergyIntolerance_eCS"
        ]

    def test_medication_request_gets_ecs_profile(self):
        r = {"resourceType": "MedicationRequest"}
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_MedicationRequest_eCS"
            in r["meta"]["profile"]
        )

    def test_procedure_gets_ecs_profile(self):
        r = {"resourceType": "Procedure"}
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Procedure_eCS"
            in r["meta"]["profile"]
        )

    def test_idempotent_no_duplicate(self):
        r = {"resourceType": "AllergyIntolerance"}
        _apply_jp_clins_profile(r)
        _apply_jp_clins_profile(r)
        _apply_jp_clins_profile(r)
        profs = r["meta"]["profile"]
        assert len(profs) == 1

    def test_unregistered_resource_type_noop(self):
        r = {"resourceType": "Encounter"}
        _apply_jp_clins_profile(r)
        assert "meta" not in r or not r.get("meta", {}).get("profile")

    def test_preserves_existing_jp_core_profile(self):
        r = {
            "resourceType": "MedicationRequest",
            "meta": {"profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"
            ]},
        }
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"
            in r["meta"]["profile"]
        )
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_MedicationRequest_eCS"
            in r["meta"]["profile"]
        )
```

- [ ] **Step 2: Run test to verify it fails (ImportError)**

Run: `pytest tests/unit/test_jp_clins_profile_emit.py::TestApplyJpClinsProfile -v`
Expected: FAIL — cannot import `_JP_CLINS_PROFILES` / `_apply_jp_clins_profile`

- [ ] **Step 3: Add `_JP_CLINS_PROFILES` dict and `_apply_jp_clins_profile` helper to adapter**

In `clinosim/modules/output/fhir_r4_adapter.py`, directly after `_JP_CORE_PROFILES` dict and the `_apply_jp_core_profile` function, add:

```python
# JP-CLINS eCS profiles (Electronic Care Record Sharing Service).
# Applied additively on top of JP Core profiles for country=JP.
# URLs verified against jpfhir.jp/fhir/clins/ v2025.4 (see plan Task 1).
_JP_CLINS_PROFILES: dict[str, list[str]] = {
    "Condition": [
        "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_eCS",
    ],
    "AllergyIntolerance": [
        "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_AllergyIntolerance_eCS",
    ],
    "Observation": [
        "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Observation_LabResult_eCS",
    ],
    "DiagnosticReport": [
        "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_DiagnosticReport_LabResult_eCS",
    ],
    "MedicationRequest": [
        "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_MedicationRequest_eCS",
    ],
    "Procedure": [
        "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Procedure_eCS",
    ],
}

_JP_CLINS_CONDITION_INFECTION_PROFILE = (
    "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_Infection_eCS"
)

# ICD-10 chapter prefixes for infectious diseases (A00-B99).
_INFECTION_ICD_PREFIXES: tuple[str, ...] = ("A", "B")


def _apply_jp_clins_profile(resource: dict) -> None:
    """Attach JP-CLINS eCS profile URLs additively (idempotent).

    Called after `_apply_jp_core_profile`. Preserves existing meta.profile[]
    entries and skips URLs already present. Filters:

    - Observation: only when category=laboratory
    - DiagnosticReport: only when category=LAB
    - Condition: always attaches JP_Condition_eCS; additionally attaches
      JP_Condition_Infection_eCS when the primary code base (before '.')
      starts with an ICD-10 infection chapter prefix.
    """
    rt = resource.get("resourceType", "")
    profiles = _JP_CLINS_PROFILES.get(rt)
    if not profiles:
        return
    if rt == "Observation" and not _is_lab_observation(resource):
        return
    if rt == "DiagnosticReport" and not _is_lab_diagnostic_report(resource):
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    for url in profiles:
        if url not in profs:
            profs.append(url)
    if rt == "Condition" and _is_infection_condition(resource):
        if _JP_CLINS_CONDITION_INFECTION_PROFILE not in profs:
            profs.append(_JP_CLINS_CONDITION_INFECTION_PROFILE)


def _is_lab_observation(resource: dict) -> bool:
    for cat in resource.get("category", []):
        for coding in cat.get("coding", []):
            if coding.get("code") == "laboratory":
                return True
    return False


def _is_lab_diagnostic_report(resource: dict) -> bool:
    for cat in resource.get("category", []):
        for coding in cat.get("coding", []):
            if coding.get("code") == "LAB":
                return True
    return False


def _is_infection_condition(resource: dict) -> bool:
    code = resource.get("code", {})
    for coding in code.get("coding", []):
        c = coding.get("code", "")
        base = c.split(".", 1)[0].upper()
        if base and base[0] in _INFECTION_ICD_PREFIXES and len(base) >= 3:
            return True
    return False
```

- [ ] **Step 4: Run tests to verify base cases pass**

Run: `pytest tests/unit/test_jp_clins_profile_emit.py::TestApplyJpClinsProfile -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py tests/unit/test_jp_clins_profile_emit.py
git commit -m "feat(fhir): P2-13 PR1 add JP-CLINS profile URL layer helper

Adds _JP_CLINS_PROFILES dict + _apply_jp_clins_profile helper (idempotent,
additive) alongside existing _apply_jp_core_profile. Filter helpers for
lab Observation, lab DiagnosticReport, and infection Condition (ICD-10
A/B chapter). Not yet wired into _build_bundle — that lands in Task 3.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 3: Wire `_apply_jp_clins_profile` into `_build_bundle`

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py:_build_bundle` (1 行追加)
- Modify: `tests/unit/test_jp_clins_profile_emit.py`(bundle-level 検証追加)

**Interfaces:**
- Consumes: Task 2 の `_apply_jp_clins_profile`
- Produces: `_build_bundle` output に JP-CLINS profile 埋め込み(country=JP のみ)

- [ ] **Step 1: Write failing test — bundle-level integration**

Add to `tests/unit/test_jp_clins_profile_emit.py`:

```python
@pytest.mark.unit
class TestBundleIntegration:
    def test_jp_bundle_medication_request_has_both_profiles(self):
        from clinosim.modules.output.fhir_r4_adapter import _build_bundle
        record = _minimal_jp_record()
        bundle = _build_bundle(record, "JP")
        mrs = [e["resource"] for e in bundle["entry"]
               if e["resource"]["resourceType"] == "MedicationRequest"]
        assert mrs, "expected at least one MedicationRequest"
        for mr in mrs:
            profs = mr.get("meta", {}).get("profile", [])
            assert any("clins" in p and "MedicationRequest" in p for p in profs), profs
            assert any("core" in p and "MedicationRequest" in p for p in profs), profs

    def test_us_bundle_has_no_clins_profile(self):
        from clinosim.modules.output.fhir_r4_adapter import _build_bundle
        record = _minimal_us_record()
        bundle = _build_bundle(record, "US")
        for entry in bundle["entry"]:
            profs = entry["resource"].get("meta", {}).get("profile", [])
            assert not any("clins" in p for p in profs), \
                f"US bundle leaked clins profile: {profs}"


def _minimal_jp_record() -> dict:
    """Minimal CIF-shaped dict sufficient for bundle build."""
    return {
        "patient": {
            "patient_id": "POP-000001",
            "sex": "M",
            "date_of_birth": "1960-01-01",
            "name": {"family_name": "山田", "given_name": "太郎"},
        },
        "clinical_diagnosis": {
            "admission_diagnosis_code": "I21.4",
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": "I21.4",
        },
        "encounters": [{
            "encounter_id": "ENC-001",
            "encounter_type": "inpatient",
            "admission_datetime": "2026-01-15T09:00:00",
            "discharge_datetime": "2026-01-20T10:00:00",
        }],
        "orders": [{
            "order_type": "medication",
            "display_name": "アスピリン腸溶錠100mg",
            "medication_code": "1124402",
            "medication_system": "yj",
            "ordered_datetime": "2026-01-15T10:00:00",
            "start_datetime": "2026-01-15T10:00:00",
            "encounter_id": "ENC-001",
            "ordered_by": "PRAC-JP-001",
        }],
    }


def _minimal_us_record() -> dict:
    return {
        "patient": {
            "patient_id": "POP-000002",
            "sex": "F",
            "date_of_birth": "1970-01-01",
            "name": {"family_name": "Smith", "given_name": "Jane"},
        },
        "clinical_diagnosis": {
            "admission_diagnosis_code": "I21.4",
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": "I21.4",
        },
        "encounters": [{
            "encounter_id": "ENC-101",
            "encounter_type": "inpatient",
            "admission_datetime": "2026-01-15T09:00:00",
            "discharge_datetime": "2026-01-20T10:00:00",
        }],
        "orders": [{
            "order_type": "medication",
            "display_name": "aspirin 100 MG oral tablet",
            "medication_code": "1191",
            "medication_system": "rxnorm",
            "ordered_datetime": "2026-01-15T10:00:00",
            "start_datetime": "2026-01-15T10:00:00",
            "encounter_id": "ENC-101",
            "ordered_by": "PRAC-US-001",
        }],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_jp_clins_profile_emit.py::TestBundleIntegration -v`
Expected: FAIL — `assert any("clins" in p ...)` fails; no clins URL in bundle output

- [ ] **Step 3: Wire the call into `_build_bundle`**

In `clinosim/modules/output/fhir_r4_adapter.py:_build_bundle`, modify the resource loop from:

```python
            if ctx.country == "JP":
                _apply_jp_core_profile(resource)
```

to:

```python
            if ctx.country == "JP":
                _apply_jp_core_profile(resource)
                _apply_jp_clins_profile(resource)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_jp_clins_profile_emit.py -v`
Expected: all PASS (base cases + bundle integration)

- [ ] **Step 5: Full-adapter sanity check — ensure no other adapter test breaks**

Run: `pytest tests/unit/ -k "fhir" -q`
Expected: all PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py tests/unit/test_jp_clins_profile_emit.py
git commit -m "feat(fhir): P2-13 PR1 wire JP-CLINS profile emission into _build_bundle

country=JP bundles now carry both JP Core and JP-CLINS eCS profile URLs
on 6 information items (Condition/AllergyIntolerance/Observation-lab/
DiagnosticReport-lab/MedicationRequest/Procedure). US bundles untouched.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 4: Category filter tests — Observation vital signs must NOT get JP-CLINS profile

**Files:**
- Modify: `tests/unit/test_jp_clins_profile_emit.py`(vital-sign Observation の非 emit + DiagnosticReport 非 LAB の非 emit を明示的にカバー)

**Interfaces:**
- Consumes: Task 2, Task 3 の実装
- Produces: silent-no-op class の regression 検出 gate

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_jp_clins_profile_emit.py`:

```python
@pytest.mark.unit
class TestCategoryFilters:
    def test_vital_observation_no_clins_profile(self):
        r = {
            "resourceType": "Observation",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert "meta" not in r or not r.get("meta", {}).get("profile")

    def test_lab_observation_gets_clins_profile(self):
        r = {
            "resourceType": "Observation",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Observation_LabResult_eCS"
            in r["meta"]["profile"]
        )

    def test_diagnostic_report_lab_gets_clins_profile(self):
        r = {
            "resourceType": "DiagnosticReport",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "LAB",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_DiagnosticReport_LabResult_eCS"
            in r["meta"]["profile"]
        )

    def test_diagnostic_report_non_lab_no_clins_profile(self):
        r = {
            "resourceType": "DiagnosticReport",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "RAD",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert "meta" not in r or not r.get("meta", {}).get("profile")
```

- [ ] **Step 2: Run test to verify pass**

Run: `pytest tests/unit/test_jp_clins_profile_emit.py::TestCategoryFilters -v`
Expected: 4 PASS(Task 2 実装が既に filter を含む)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_jp_clins_profile_emit.py
git commit -m "test(fhir): P2-13 PR1 pin JP-CLINS category filter behavior

Locks in that only laboratory Observations and LAB DiagnosticReports
get JP-CLINS eCS profile emission; vital-sign Observation and RAD
report do not. Guards silent-no-op regression class where a filter
change would accidentally emit JP-CLINS on vitals or omit it on labs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 5: Condition infection classification (ICD-10 A/B chapter)

**Files:**
- Modify: `tests/unit/test_jp_clins_profile_emit.py`(感染症判別分岐テスト)

**Interfaces:**
- Consumes: Task 2 の `_is_infection_condition` and `_JP_CLINS_CONDITION_INFECTION_PROFILE`
- Produces: 感染症 Condition の 2 profile emit の regression guard

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_jp_clins_profile_emit.py`:

```python
@pytest.mark.unit
class TestConditionInfectionClassification:
    def test_sepsis_a41_gets_both_condition_and_infection(self):
        r = {
            "resourceType": "Condition",
            "code": {"coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": "A41.9",
                "display": "Sepsis, unspecified organism",
            }]},
        }
        _apply_jp_clins_profile(r)
        profs = r["meta"]["profile"]
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_eCS" in profs
        )
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_Infection_eCS"
            in profs
        )

    def test_pneumonia_j18_no_infection_profile(self):
        r = {
            "resourceType": "Condition",
            "code": {"coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": "J18.9",
                "display": "Pneumonia, unspecified organism",
            }]},
        }
        _apply_jp_clins_profile(r)
        profs = r["meta"]["profile"]
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_eCS" in profs
        )
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_Infection_eCS"
            not in profs
        )

    def test_b99_generic_infection_gets_infection_profile(self):
        r = {
            "resourceType": "Condition",
            "code": {"coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10",
                "code": "B99.9",
                "display": "Unspecified infectious disease",
            }]},
        }
        _apply_jp_clins_profile(r)
        profs = r["meta"]["profile"]
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_Infection_eCS"
            in profs
        )

    def test_i21_non_infection_no_infection_profile(self):
        r = {
            "resourceType": "Condition",
            "code": {"coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": "I21.4",
                "display": "Non-ST elevation (NSTEMI) myocardial infarction",
            }]},
        }
        _apply_jp_clins_profile(r)
        profs = r["meta"]["profile"]
        assert (
            "http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Condition_Infection_eCS"
            not in profs
        )
```

- [ ] **Step 2: Run test to verify pass**

Run: `pytest tests/unit/test_jp_clins_profile_emit.py::TestConditionInfectionClassification -v`
Expected: 4 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_jp_clins_profile_emit.py
git commit -m "test(fhir): P2-13 PR1 pin Condition infection classification

ICD-10 A00-B99 chapter Conditions receive JP_Condition_Infection_eCS in
addition to JP_Condition_eCS. Non-infection codes (I21, J18, etc) do not.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 6: Completeness invariants gate for JP-CLINS profile emission (in-process, canonical profile)

**Files:**
- Modify: `tests/unit/test_completeness_invariants.py`(JP-CLINS section 追加)

**Interfaces:**
- Consumes: Task 3 の bundle-level emission、`run_forced` + `convert_cif_to_fhir` in-process pipeline、既存 canonical patient profile fixture library(AD-66、`tests/fixtures/patient_profiles/*.yaml`)
- Produces: cohort 単位で「該当 resource が emit されている時、JP-CLINS profile URL が meta.profile[] に必ず含まれる」invariant guard

**Design note (session 47 improvement)**: unit test は subprocess ではなく、in-process の `run_forced`(engine)+ `write_cif` + `convert_cif_to_fhir` を直接呼ぶ。既存の canonical patient profile fixture(AD-66)を再利用することで、`test_fhir_coverage.py` と同型の focused pattern に統一(subagent-driven-development skill の pre-flight review + user 明示 = OSS-quality 改善)。

- [ ] **Step 1: Locate the completeness invariants file structure and identify insertion point**

Run: `grep -n "^class\|^def\|@pytest.mark" tests/unit/test_completeness_invariants.py | head -30`

Read: 既存 test class 群を確認、末尾に新 test class を追加する insertion point を決める。

- [ ] **Step 2: Write failing test — JP-CLINS emission gate (in-process)**

Add a new test class to `tests/unit/test_completeness_invariants.py`(末尾に追加):

```python
@pytest.mark.unit
class TestJpClinsProfileEmissionInvariants:
    """P2-13 PR1: JP-CLINS eCS profile URL emission gate.

    For a country=JP cohort, every emitted resource of a JP-CLINS-registered
    resource type MUST carry the JP-CLINS eCS profile URL in meta.profile[].
    Filters apply:
      - Observation: only laboratory category
      - DiagnosticReport: only LAB category
      - Condition: JP_Condition_eCS always; JP_Condition_Infection_eCS when
        primary code is in ICD-10 A/B chapter

    Uses the canonical patient profile fixture library (AD-66) via in-process
    run_forced + convert_cif_to_fhir. No subprocess.
    """

    def test_jp_bacterial_pneumonia_cohort_has_clins_profiles(
        self, jp_bacterial_pneumonia_resources
    ):
        from clinosim.modules.output.fhir_r4_adapter import (
            _JP_CLINS_PROFILES, _is_lab_diagnostic_report, _is_lab_observation,
        )

        # At least one Condition + Observation.lab + DiagnosticReport.lab +
        # MedicationRequest + Procedure should appear for a bacterial pneumonia
        # inpatient cohort. AllergyIntolerance is sparse (pool may be empty at
        # small profile counts; profile check is vacuously true if pool is empty).
        expected_dense = {"Condition", "Observation", "DiagnosticReport",
                          "MedicationRequest", "Procedure"}
        seen_dense: set[str] = set()

        for r in jp_bacterial_pneumonia_resources:
            rt = r["resourceType"]
            if rt not in _JP_CLINS_PROFILES:
                continue
            if rt == "Observation" and not _is_lab_observation(r):
                continue
            if rt == "DiagnosticReport" and not _is_lab_diagnostic_report(r):
                continue
            profs = r.get("meta", {}).get("profile", [])
            expected = _JP_CLINS_PROFILES[rt][0]
            assert expected in profs, (
                f"{rt}/{r.get('id')} missing {expected}, got {profs}"
            )
            if rt in expected_dense:
                seen_dense.add(rt)

        missing = expected_dense - seen_dense
        assert not missing, (
            f"expected dense JP-CLINS resource types missing from cohort: {missing}"
        )
```

Add a session-scoped fixture near the top of the same file (or in a shared conftest if one exists at `tests/unit/conftest.py`):

```python
@pytest.fixture(scope="session")
def jp_bacterial_pneumonia_resources(tmp_path_factory):
    """AD-66 canonical patient profile → in-process CIF → FHIR → resource list.

    Uses the JP bacterial pneumonia canonical fixture (5 patients, deterministic
    seed). Runs run_forced + write_cif + convert_cif_to_fhir in-process; no
    subprocess. Session-scoped so a single simulation run serves all tests
    in this class.
    """
    import json
    from pathlib import Path

    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import SimulatorConfig, load_patient_profile

    profile_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "patient_profiles"
        / "jp_inpatient_bacterial_pneumonia.yaml"
    )
    profile = load_patient_profile(str(profile_path))
    scenario = profile.to_forced_scenario()
    config = SimulatorConfig(
        random_seed=profile.random_seed,
        country=profile.country,
        hospital_scale=profile.hospital_scale,
        catchment_population=profile.count,
    )
    dataset = run_forced(scenario, config)

    outroot = tmp_path_factory.mktemp("jp-clins-invariant")
    cif_dir = str(outroot / "cif")
    fhir_dir = str(outroot / "fhir_r4")
    write_cif(dataset, cif_dir)
    convert_cif_to_fhir(cif_dir, fhir_dir, country=profile.country)

    resources: list[dict] = []
    for ndjson_path in sorted(Path(fhir_dir).glob("*.ndjson")):
        with open(ndjson_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                resources.append(json.loads(line))
    return resources
```

- [ ] **Step 3: Run test to verify pass**

Run: `pytest tests/unit/test_completeness_invariants.py::TestJpClinsProfileEmissionInvariants -v`
Expected: PASS(5 dense JP-CLINS resource types found and carry expected profile URL)

If the fixture profile does not produce all 5 dense types (e.g., no lab DiagnosticReport in a 5-patient run), adjust the profile choice or expected-dense set — but do NOT silently loosen the assertion.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_completeness_invariants.py
git commit -m "test(fhir): P2-13 PR1 add JP-CLINS profile emission invariant gate

Cohort-level invariant: every JP-CLINS-registered resource emitted in a
country=JP cohort MUST carry the JP-CLINS eCS profile URL. Guards the
silent-no-op class (a filter regression that omits Observation.laboratory
or Condition would go unnoticed by unit-level assertions).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 7: Integration test — p=100 JP end-to-end

**Files:**
- Create: `tests/integration/test_jp_clins_pr1_end_to_end.py`

**Interfaces:**
- Consumes: Task 3 完成 pipeline、`clinosim generate` CLI(既存 `tests/integration/_sr_helpers.py:run_generate` ヘルパー再利用)
- Produces: production-scale profile emission rate 検証、reference integrity 検証

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_jp_clins_pr1_end_to_end.py`:

```python
"""Integration test — P2-13 PR1: JP-CLINS profile URL emission at cohort scale.

Runs a small country=JP cohort (p=100 seed=42, snapshot end=2026-06-30),
verifies:
- 6 information items resource types carry JP-CLINS eCS profile URLs
- Filters honored (lab-only for Observation/DiagnosticReport)
- No profile URLs leak into country=US cohort
- AllergyIntolerance may be sparse or absent at p=100 (single-digit %
  prevalence in the general population); when the pool is empty, the
  profile check is vacuously satisfied. All other five resource types
  are expected to have non-empty pools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration._sr_helpers import run_generate


_JP_CLINS_PROFILE_ROOT = "http://jpfhir.jp/fhir/clins/StructureDefinition/"
_SNAPSHOT_END = "2026-06-30"


def _load_resources(outdir: Path) -> dict[str, list[dict]]:
    resources_by_type: dict[str, list[dict]] = {}
    for ndjson_path in sorted(outdir.rglob("*.ndjson")):
        with open(ndjson_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                rt = r.get("resourceType", "")
                if not rt:
                    continue
                resources_by_type.setdefault(rt, []).append(r)
    return resources_by_type


@pytest.mark.integration
def test_jp_p100_carries_clins_profiles_on_six_info(tmp_path):
    outdir = tmp_path / "jp"
    run_generate("JP", 100, 42, outdir, end=_SNAPSHOT_END)
    resources_by_type = _load_resources(outdir)

    from clinosim.modules.output.fhir_r4_adapter import (
        _JP_CLINS_PROFILES, _is_lab_observation, _is_lab_diagnostic_report,
    )

    # Dense resource types — expected to have at least one instance at p=100.
    dense_types = {"Condition", "Observation", "DiagnosticReport",
                   "MedicationRequest", "Procedure"}
    # AllergyIntolerance is sparse (single-digit % prevalence in the general
    # population); the profile check is vacuous if the pool is empty.
    for rt in _JP_CLINS_PROFILES:
        pool = resources_by_type.get(rt, [])
        if rt == "Observation":
            pool = [r for r in pool if _is_lab_observation(r)]
        elif rt == "DiagnosticReport":
            pool = [r for r in pool if _is_lab_diagnostic_report(r)]
        if rt in dense_types:
            assert pool, (
                f"expected dense JP-CLINS type {rt} non-empty at p=100 JP"
            )
        for r in pool:
            profs = r.get("meta", {}).get("profile", [])
            expected = _JP_CLINS_PROFILES[rt][0]
            assert expected in profs, (
                f"{rt}/{r.get('id')} missing {expected}"
            )


@pytest.mark.integration
def test_us_p50_has_no_clins_profile(tmp_path):
    outdir = tmp_path / "us"
    run_generate("US", 50, 42, outdir, end=_SNAPSHOT_END)
    for ndjson_path in sorted(outdir.rglob("*.ndjson")):
        with open(ndjson_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                profs = r.get("meta", {}).get("profile", [])
                assert not any(p.startswith(_JP_CLINS_PROFILE_ROOT) for p in profs), (
                    f"US cohort leaked JP-CLINS profile: {r['resourceType']}/{r.get('id')} → {profs}"
                )
```

- [ ] **Step 2: Run the integration test locally**

Run: `pytest tests/integration/test_jp_clins_pr1_end_to_end.py -v -m integration`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_jp_clins_pr1_end_to_end.py
git commit -m "test(integration): P2-13 PR1 verify JP-CLINS emission at p=100

Full simulate → NDJSON → resource-type coverage for country=JP p=100
seed=42. Confirms every 6-info resource carries JP-CLINS eCS profile
and country=US remains clean.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 8: Reproduce.sh baseline refresh (intentional byte-diff)

**Files:**
- Run: `bash scripts/reproduce.sh` and update baseline hashes if the script tracks any (or verify the script's current invariant: US + JP × 2runs internal byte-identical)

**Interfaces:**
- Consumes: Task 3 完成 pipeline
- Produces: reproducibility gate に JP-CLINS profile URL 追加後の baseline

- [ ] **Step 1: Read `scripts/reproduce.sh` to understand the baseline model**

Run: `cat scripts/reproduce.sh`
Expected: 現在 script は "US + JP それぞれ 2 回 run して sha256 が run 間で一致するか" を verify する形式(baseline は script 内保存でなく self-check)。

If the script self-checks run-to-run identity (no committed baseline), then no baseline file update is needed — the script's assertion should still pass because both runs (with the same seed) produce identical output including the new JP-CLINS URLs.

If the script does check against committed golden hashes, update them (or extend the script to accept the new hashes).

- [ ] **Step 2: Run reproduce.sh**

Run: `bash scripts/reproduce.sh`
Expected: PASS (US byte-identical run-to-run, JP byte-identical run-to-run — the JP output now includes JP-CLINS profile URLs, but both JP runs produce the same URLs, so identity holds)

If it fails, diagnose whether the failure is (a) determinism regression (real bug — investigate `_apply_jp_clins_profile` for any RNG or dict-ordering issue) or (b) baseline mismatch (update the baseline commit).

- [ ] **Step 3: Commit if baseline file(s) changed; otherwise skip**

If baseline files were regenerated:

```bash
git add <baseline-file(s)>
git commit -m "chore(reproducibility): P2-13 PR1 refresh JP baseline with JP-CLINS profiles

Intentional byte-diff: JP FHIR NDJSON now embeds JP-CLINS eCS profile
URLs on 6 information item resources. Both runs identical → reproduce.sh
determinism gate holds.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

Otherwise skip commit.

---

### Task 9: Docs update + TODO tick + audit registry entry

**Files:**
- Modify: `docs/jp-clins.md`(新規 file、PR3 で完成する予定だが PR1 段階の内容を write)or `README.md`(6 情報 profile support を明記)
- Modify: `TODO.md`(P2-13 PR1 段階の進捗記載)
- Modify: `docs/audit-cycles/by-design-registry.md`(未該当 = 記載省略、PR3 で健診 opt-in entry を追加予定)

**Interfaces:** —

- [ ] **Step 1: Create `docs/jp-clins.md` skeleton with the PR1 scope described**

Create `docs/jp-clins.md`:

```markdown
# JP-CLINS Profile Support

clinosim emits FHIR R4 resources with **JP-CLINS (電子カルテ情報共有サービス) profile URLs** for country=JP cohorts. This document covers the 6 information items covered in PR1; 3-document Composition support (退院時サマリー / 診療情報提供書 / opt-in 健康診断結果報告書) lands in PR2 and PR3.

## Scope

Acute-care hospital EHR/EMR data generation, `country=JP`.

### 6 Information Items (PR1)

For every country=JP cohort, the following resource types carry the JP-CLINS eCS profile URL in `meta.profile[]` alongside the existing JP Core profile:

| Information | Resource | JP-CLINS profile URL |
|---|---|---|
| 傷病名 | Condition | `.../JP_Condition_eCS` |
| 感染症 | Condition (ICD-10 A/B chapter) | `.../JP_Condition_eCS` + `.../JP_Condition_Infection_eCS` |
| アレルギー | AllergyIntolerance | `.../JP_AllergyIntolerance_eCS` |
| 検査 | Observation (category=laboratory) | `.../JP_Observation_LabResult_eCS` |
| 検査 | DiagnosticReport (category=LAB) | `.../JP_DiagnosticReport_LabResult_eCS` |
| 処方 | MedicationRequest | `.../JP_MedicationRequest_eCS` |
| 処置 | Procedure | `.../JP_Procedure_eCS` |

URL root: `http://jpfhir.jp/fhir/clins/StructureDefinition/`

**Filters:**
- Observation: only when `category.coding[].code == "laboratory"` — vital signs are excluded.
- DiagnosticReport: only when `category.coding[].code == "LAB"` — radiology and other categories are excluded.
- Condition (infection): the additional `JP_Condition_Infection_eCS` URL applies when the primary code base (before `.`) starts with `A` or `B` (ICD-10 chapter I).

**Out of scope for PR1** (see spec §1.3 in `docs/superpowers/specs/2026-07-12-p2-13-jp-clins-design.md`):
- 3 documents Composition (退院時サマリー / 診療情報提供書 / 健康診断結果報告書) — PR2 + PR3
- 健診 encounter generation — PR3 opt-in
- 機関間連携 workflow simulation — non-goal
```

- [ ] **Step 2: Update `TODO.md` — add a PR1 checkbox under P2-13**

Locate `TODO.md` P2-13 entry and add:

```markdown
- **P2-13** JP-CLINS (3 documents / 6 information items) FHIR profile — v0.3 flagship.
  - [x] PR1: 6 information items JP-CLINS eCS profile URL layer (session 47)
  - [ ] PR2: 2 documents Composition (退院時サマリー + 診療情報提供書)
  - [ ] PR3: 健診 opt-in + jpfhir-validator bridge + docs
```

- [ ] **Step 3: Commit docs**

```bash
git add docs/jp-clins.md TODO.md
git commit -m "docs(p2-13): PR1 add JP-CLINS profile support docs

Introduces docs/jp-clins.md documenting the 6 information item profile
emission (Condition, AllergyIntolerance, Observation.laboratory,
DiagnosticReport.LAB, MedicationRequest, Procedure) with filter rules
and out-of-scope items. TODO.md P2-13 entry tracks 3-PR chain progress.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 10: DQR + final push

**Files:** — (verification only)

**Interfaces:** —

- [ ] **Step 1: Run the full unit gate**

Run: `pytest tests/unit -q --no-header`
Expected: baseline pass count(前 session 末 2487)+ 新規テスト分 PASS、regression 0

- [ ] **Step 2: Run reproduce.sh one more time as final gate**

Run: `bash scripts/reproduce.sh`
Expected: PASS

- [ ] **Step 3: 3-axis DQR against feedback_pr_merge_dqr_required**

Manually verify:
- **構造**:6 情報 resource type 全てで JP-CLINS profile URL 存在、JP Core と併存、idempotent
- **臨床整合**:感染症 chapter 判別が clinical intuition と一致(A41 sepsis = infection ✓, I21 MI = not ✓)、Observation.laboratory 判別が vitals をリークしない
- **JP 言語**:profile URL は英字 canonical、他の resource field は既存の JP display / lookup を維持(URL 追加は言語中立)

- [ ] **Step 4: Push branch**

```bash
git push origin master
```

- [ ] **Step 5: Announce PR1 land + note PR2 plan authoring is next**

Notify user with a brief summary: PR1 tasks 1-10 完了、commit N commits pushed、next = PR2 plan(2 文書 Composition)authoring。

---

## Self-Review Checklist

**1. Spec coverage:** PR1 scope(spec §3.1)全項目カバー:
- `_JP_CLINS_PROFILES` map ✓ (Task 2)
- `_apply_jp_clins_profile` idempotent ✓ (Task 2)
- Observation category=laboratory filter ✓ (Task 2 + Task 4)
- Condition infection classification (ICD-10 A/B chapter) ✓ (Task 2 + Task 5)
- Structural conformance test ✓ (Task 2-5)
- Completeness invariants gate ✓ (Task 6)
- p=100 JP cohort integration test ✓ (Task 7)
- Byte-diff reproducibility with new baseline ✓ (Task 8)
- Docs skeleton ✓ (Task 9)

**2. Placeholder scan:** 全 step にコード block or 具体的 command あり、"TBD" / "TODO" 未使用。

**3. Type consistency:** Task 全体で以下の identifier が一貫:
- `_JP_CLINS_PROFILES: dict[str, list[str]]`
- `_JP_CLINS_CONDITION_INFECTION_PROFILE: str`
- `_apply_jp_clins_profile(resource: dict) -> None`
- `_is_lab_observation(resource: dict) -> bool`
- `_is_lab_diagnostic_report(resource: dict) -> bool`
- `_is_infection_condition(resource: dict) -> bool`
- `_INFECTION_ICD_PREFIXES: tuple[str, ...]` = `("A", "B")`
