# Tier 1 #3 α-min-2 Document Density Chain — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 看護 3 doc + 外来 SOAP + ED note × 2 + CareTeam(2 名 scope)+ Triage module + 46 encounter YAML narrative 拡張を実装。α-min-1 で確立した Document infrastructure を encounter_type gating で拡張、6 新 DocumentType + CareTeam 新 resource を emission。

**Architecture:** 2 新 always-on Module(nursing POST_ENCOUNTER order=94 / triage POST_ENCOUNTER order=93)+ 既存 document_enricher の encounter_type gating 拡張 + 1 新 FHIR builder(_fhir_care_team.py)+ 46 encounter YAML narrative(5 priority + 41 baseline)。α-min-1 pattern(PR #128 15-task + PR #129 5-lens adv-1)完全踏襲。

**Tech Stack:** Python 3.11+ / Pydantic(EncounterProtocol.narrative)/ dataclass(CIF types)/ numpy.random.Generator(AD-16 sub-seed)/ PyYAML(reference data)/ pytest unit + integration + e2e。

## Global Constraints

- **★ Scope discipline**(memory `feedback_scope_discipline`): scope 拡大禁止、データ品質 / 臨床整合性 必須のみ scope 内 fix、それ以外 TODO entry 化
- **AD-16 determinism:** sub-seed via `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["triage"|"nursing"], key)`. Master stream 不変
- **AD-30:** CIF はコードのみ、display は output 時 `code_lookup` 解決(triage level system は URI + code、display は output で)
- **AD-31:** FHIR Resource.id per-type unique、canonical prefix `CARE_TEAM_ID_PREFIX="careteam-"` writer↔reader shared
- **AD-32 snapshot:** in-progress encounter で NURSING_DISCHARGE_SUMMARY skip、ED_TRIAGE 前 = ED_NOTE skip
- **AD-55:** nursing + triage = always-on Module `enabled=lambda c: True`(device/hai/antibiotic/imaging/document precedent)
- **AD-56:** 新 `_bb_care_teams` builder は `_BUNDLE_BUILDERS` リスト追加、`_build_bundle()` 直接編集禁止
- **CIF → FHIR no-drop invariant:** spec §3.4 emission matrix 経由、6 new DocumentType + CareTeam field 全 emit
- **Silent-no-op defense 7-layer:** canonical URI(JTAS_SYSTEM_URI / ESI_SYSTEM_URI)/ shared ID prefix(CARE_TEAM_ID_PREFIX)/ YAML empty + per-bucket / reverse-coverage(6 new DocumentType ↔ document_type_specs.yaml)/ validator pre-register ordering / symmetric forward-coverage(46 encounter YAML narrative)/ cross-module canonical URI
- **`_o(obj, name, default)` dual-access**(PR-90 教訓):全 builder で dict + dataclass 両 path
- **dict + dataclass 両 path test 必須**(PR-90 教訓):unit test に両 fixture
- **Subprocess full-pipeline test 必須**(PR-90 教訓):production json.load → builder dict path verify
- **Country-gated triage**: JP→JTAS、US→ESI locale gating(triage_protocols.yaml 内 severity_to_triage_distribution)
- **Code 権威 sources:** LOINC 6 new codes = NLM clinicaltables verify(Task 8)/ JTAS = 日本臨床救急医学会 2017 / ESI = AHRQ ESI v4
- **Branch:** `feature/tier1-document-density-alpha-min-2`(既に作成済、base commit = 2fe5f45d8a master post-α-min-1)
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_013a5SdaKQejjb7aJKfwE8wB`
- **Pre-merge gate:** `pytest tests/unit tests/integration -m "unit or integration"` full sweep(セッション22 教訓)

## File Structure

### Files to CREATE

| Path | 責務 |
|---|---|
| `clinosim/types/triage.py` | `TriageData` dataclass |
| `clinosim/modules/triage/__init__.py` | exports |
| `clinosim/modules/triage/engine.py` | POST_ENCOUNTER enricher + JTAS/ESI + arrival_mode sampling |
| `clinosim/modules/triage/README.md` | module README |
| `clinosim/modules/triage/reference_data/triage_protocols.yaml` | JTAS + ESI + arrival_mode catalog |
| `clinosim/modules/nursing/__init__.py` | exports + canonical constants |
| `clinosim/modules/nursing/engine.py` | primary_nurse assignment + POST_ENCOUNTER enricher |
| `clinosim/modules/nursing/README.md` | module README |
| `clinosim/modules/nursing/reference_data/nursing_assessment.yaml` | Nursing assessment scaffolding |
| `clinosim/modules/output/_fhir_care_team.py` | CareTeam resource builder |
| `tests/unit/test_types_triage.py` | TriageData dataclass tests |
| `tests/unit/modules/triage/__init__.py` | empty marker |
| `tests/unit/modules/triage/test_engine.py` | triage sampling tests |
| `tests/unit/modules/triage/test_triage_protocols_yaml.py` | YAML validator tests |
| `tests/unit/modules/nursing/__init__.py` | empty marker |
| `tests/unit/modules/nursing/test_engine.py` | primary_nurse assignment tests |
| `tests/unit/modules/nursing/test_nursing_assessment_yaml.py` | YAML validator tests |
| `tests/unit/modules/document/narrative/test_encounter_types_supported.py` | encounter_types_supported gating tests |
| `tests/unit/modules/document/narrative/test_template_generator_alpha2.py` | 6 new DocumentType rendering tests |
| `tests/unit/modules/document/test_engine_alpha2.py` | encounter_type dispatch tests |
| `tests/unit/output/test_fhir_care_team.py` | CareTeam builder tests |
| `tests/unit/output/test_fhir_composition_alpha2.py` | 6 new section rendering tests |
| `tests/unit/output/test_fhir_documents_alpha2.py` | 6 new DR handling tests |
| `tests/unit/modules/encounter/test_narrative_yaml.py` | 46 encounter YAML narrative tests |
| `tests/unit/audit/test_document_audit_alpha2.py` | 拡張 lift_firing_proof(23+ checks)tests |
| `tests/integration/test_document_chain_alpha2.py` | end-to-end 6 new doc emission |
| `tests/integration/test_care_team_basedon_coverage.py` | CareTeam ref integrity gate |
| `tests/integration/test_document_alpha2_determinism.py` | AD-16 byte-identical re-run |
| `tests/integration/test_document_alpha2_snapshot.py` | AD-32 nursing snapshot semantics |
| `tests/integration/test_document_alpha2_subprocess_fullpipeline.py` | PR-90 production dict path |
| `tests/integration/test_document_alpha2_jp_localization.py` | JTAS + JP nursing section CJK |
| `docs/reviews/2026-07-XX-tier1-3-document-density-alpha-min-2-dqr.md` | DQR report(Task 14) |

### Files to MODIFY

| Path | 修正内容 |
|---|---|
| `clinosim/types/encounter.py` | `EncounterRecord.primary_nurse_id: str = ""` + `triage_data: TriageData | None = None` field 追加 |
| `clinosim/types/document.py` | `DocumentType` enum に 6 entry 追加(ADMISSION_NURSING_ASSESSMENT / NURSING_SHIFT_NOTE / NURSING_DISCHARGE_SUMMARY / OUTPATIENT_SOAP / ED_NOTE / ED_TRIAGE_NOTE) |
| `clinosim/modules/document/narrative/registry.py` | `DocumentTypeSpec.encounter_types_supported: tuple[str, ...] = ()` field + `specs_for_encounter_type(encounter_type)` helper |
| `clinosim/modules/document/narrative/template_generator.py` | 6 new DocumentType section rendering |
| `clinosim/modules/document/engine.py` | encounter_type gating + generation_frequency="encounter_once" dispatch |
| `clinosim/modules/document/reference_data/document_type_specs.yaml` | 6 new spec entries |
| `clinosim/modules/document/audit.py` | 拡張 lift_firing_proof(17→23+ checks)+ CareTeam gate + 6 new no-drop invariants |
| `clinosim/modules/output/_fhir_composition.py` | 6 new DocumentType section mapping |
| `clinosim/modules/output/_fhir_documents.py` | 6 new DocumentType free_text handling |
| `clinosim/modules/output/fhir_r4_adapter.py` | `_BUNDLE_BUILDERS` に `_bb_care_teams` 追加 |
| `clinosim/modules/encounter/protocol.py` | `EncounterProtocol.narrative: EncounterNarrativeSpec | None = None` Pydantic 拡張 |
| `clinosim/modules/encounter/reference_data/*.yaml`(× 46 file) | `narrative:` block 追加(5 priority detailed + 41 baseline) |
| `clinosim/simulator/enrichers.py` | triage(POST_ENCOUNTER order=93)+ nursing(POST_ENCOUNTER order=94)enricher 登録 |
| `clinosim/simulator/seeding.py` | `ENRICHER_SEED_OFFSETS["triage"]` + `["nursing"]` 追加 |
| `clinosim/codes/data/loinc.yaml` | 6 new LOINC code + display(NLM clinicaltables 認証)追加 |
| `clinosim/codes/data/snomed-ct.yaml` | CareTeam category codes(SNOMED)追加 |
| `README.md` + `README.ja.md` | α-min-2 chain 言及 + DQR link |
| `MODULES.md` | nursing + triage module rows 追加 + Dependency Tree |
| `DESIGN.md` | AD-64 ADR 追加 |
| `docs/CONTRIBUTING-modules.md` | nursing + triage を always-on Module 例(第 7・8 番目) |
| `TODO.md` | OOS 10+ 項目 formal entry(β-JP-1 予告) |
| `CLAUDE.md` | nursing + triage module DRY rule + encounter_types_supported invariant |
| `docs/design-guides/fhir-data-generation-logic.md` | CareTeam + 6 new DocumentType precedent |

---

## Task 1: CIF types — TriageData + DocumentType +6 + EncounterRecord fields

**Files:**
- Create: `clinosim/types/triage.py`
- Modify: `clinosim/types/document.py`(DocumentType enum +6 entries)
- Modify: `clinosim/types/encounter.py`(EncounterRecord.primary_nurse_id + triage_data)
- Test: `tests/unit/test_types_triage.py`(新)

**Interfaces:**
- Consumes: none(foundation task)
- Produces:
  - `clinosim.types.triage.TriageData(level, level_system, arrival_mode, triage_time, acuity_score, chief_complaint_summary)`
  - `clinosim.types.document.DocumentType` に 6 新 enum value:
    - `ADMISSION_NURSING_ASSESSMENT = "admission_nursing_assessment"`
    - `NURSING_SHIFT_NOTE = "nursing_shift_note"`
    - `NURSING_DISCHARGE_SUMMARY = "nursing_discharge_summary"`
    - `OUTPATIENT_SOAP = "outpatient_soap"`
    - `ED_NOTE = "ed_note"`
    - `ED_TRIAGE_NOTE = "ed_triage_note"`
  - `clinosim.types.encounter.EncounterRecord.primary_nurse_id: str = ""`
  - `clinosim.types.encounter.EncounterRecord.triage_data: TriageData | None = None`

- [ ] **Step 1: Write failing test**

`tests/unit/test_types_triage.py`:

```python
"""Unit tests for clinosim.types.triage(Tier 1 #3 α-min-2 PR1)."""

from __future__ import annotations

from datetime import datetime

from clinosim.types.triage import TriageData


def test_triage_data_defaults():
    t = TriageData()
    assert t.level == ""
    assert t.level_system == ""
    assert t.arrival_mode == ""
    assert t.triage_time is None
    assert t.acuity_score is None
    assert t.chief_complaint_summary == ""


def test_triage_data_jtas_payload():
    t = TriageData(
        level="3",
        level_system="JTAS",
        arrival_mode="walk-in",
        triage_time=datetime(2026, 7, 1, 10, 15),
        acuity_score=60.0,
        chief_complaint_summary="腹痛",
    )
    assert t.level == "3"
    assert t.level_system == "JTAS"
    assert t.arrival_mode == "walk-in"
    assert t.chief_complaint_summary == "腹痛"


def test_triage_data_esi_payload():
    t = TriageData(level="3", level_system="ESI", arrival_mode="ambulance")
    assert t.level_system == "ESI"


def test_document_type_alpha2_enum_values():
    from clinosim.types.document import DocumentType
    assert DocumentType.ADMISSION_NURSING_ASSESSMENT.value == "admission_nursing_assessment"
    assert DocumentType.NURSING_SHIFT_NOTE.value == "nursing_shift_note"
    assert DocumentType.NURSING_DISCHARGE_SUMMARY.value == "nursing_discharge_summary"
    assert DocumentType.OUTPATIENT_SOAP.value == "outpatient_soap"
    assert DocumentType.ED_NOTE.value == "ed_note"
    assert DocumentType.ED_TRIAGE_NOTE.value == "ed_triage_note"


def test_encounter_record_alpha2_fields():
    from clinosim.types.encounter import EncounterRecord
    e = EncounterRecord()
    assert e.primary_nurse_id == ""
    assert e.triage_data is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_types_triage.py -v
```

Expected: FAIL — `ImportError: cannot import name 'TriageData'`.

- [ ] **Step 3: Create `clinosim/types/triage.py`**

```python
"""Triage CIF dataclass(Tier 1 #3 α-min-2 PR1).

EncounterRecord.triage_data に格納、FHIR builder + ED_TRIAGE_NOTE
narrative generator が参照。level_system = "JTAS" or "ESI"、locale-gated。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TriageData:
    """ED triage data(AD-30 code-only CIF、display は output で解決)."""
    level: str = ""                       # e.g. "1"..."5"
    level_system: str = ""                # "JTAS" | "ESI"
    arrival_mode: str = ""                # "walk-in" | "ambulance" | "police" | "helicopter" | "private_vehicle"
    triage_time: datetime | None = None
    acuity_score: float | None = None     # 0-100 数値スコア
    chief_complaint_summary: str = ""     # triage 時 chief complaint 短文
```

- [ ] **Step 4: Extend `clinosim/types/document.py:DocumentType` enum**

Locate `class DocumentType(str, Enum):` and add 6 entries after the α-min-1 entries:

```python
class DocumentType(str, Enum):
    """Document types.

    α-min-1 scope: ADMISSION_HP + PROGRESS_NOTE + DISCHARGE_SUMMARY.
    α-min-2 scope: +6 nursing/outpatient/ED entries below.
    後続 phase で enum 値追加(β-JP-1 で JP 厚労省必須 doc)。
    """
    # α-min-1 scope(既存)
    ADMISSION_HP = "admission_hp"
    PROGRESS_NOTE = "progress_note"
    DISCHARGE_SUMMARY = "discharge_summary"
    # α-min-2 scope(new)
    ADMISSION_NURSING_ASSESSMENT = "admission_nursing_assessment"
    NURSING_SHIFT_NOTE = "nursing_shift_note"
    NURSING_DISCHARGE_SUMMARY = "nursing_discharge_summary"
    OUTPATIENT_SOAP = "outpatient_soap"
    ED_NOTE = "ed_note"
    ED_TRIAGE_NOTE = "ed_triage_note"
```

- [ ] **Step 5: Extend `clinosim/types/encounter.py:EncounterRecord`**

Locate `class EncounterRecord:` dataclass. Import `TriageData` at top:

```python
from clinosim.types.triage import TriageData
```

Add fields after existing fields(default backwards-compat):

```python
    # Tier 1 #3 α-min-2 additions
    primary_nurse_id: str = ""              # nursing_enricher が set(inpatient のみ)
    triage_data: TriageData | None = None   # triage_enricher が set(ED のみ)
```

- [ ] **Step 6: Run tests to verify pass**

```
pytest tests/unit/test_types_triage.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 7: Run existing tests for regression**

```
pytest tests/unit -x -q
```

Expected: no new failures(fields have default backwards-compat)。

- [ ] **Step 8: Commit**

```
git add clinosim/types/triage.py clinosim/types/document.py clinosim/types/encounter.py tests/unit/test_types_triage.py
git commit -m "$(cat <<'EOF'
feat(types): add TriageData + DocumentType α-min-2 entries + EncounterRecord fields

Tier 1 #3 α-min-2 PR1 Task 1:
- TriageData dataclass (clinosim/types/triage.py) — level + level_system
  (JTAS/ESI) + arrival_mode + triage_time + acuity_score + chief_complaint_summary
- DocumentType enum +6 entries: ADMISSION_NURSING_ASSESSMENT / NURSING_SHIFT_NOTE
  / NURSING_DISCHARGE_SUMMARY / OUTPATIENT_SOAP / ED_NOTE / ED_TRIAGE_NOTE
- EncounterRecord.primary_nurse_id + triage_data fields (default backwards-compat)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013a5SdaKQejjb7aJKfwE8wB
EOF
)"
```

---

## Task 2: Triage module + triage_protocols.yaml + 6-layer validator

**Files:**
- Create: `clinosim/modules/triage/__init__.py`
- Create: `clinosim/modules/triage/engine.py`
- Create: `clinosim/modules/triage/README.md`
- Create: `clinosim/modules/triage/reference_data/triage_protocols.yaml`
- Modify: `clinosim/simulator/seeding.py`(add `ENRICHER_SEED_OFFSETS["triage"] = 0x5452`("TR"))
- Test: `tests/unit/modules/triage/__init__.py`(empty)
- Test: `tests/unit/modules/triage/test_engine.py`
- Test: `tests/unit/modules/triage/test_triage_protocols_yaml.py`

**Interfaces:**
- Consumes: `TriageData` from Task 1
- Produces:
  - `clinosim.modules.triage.engine.load_triage_protocols() -> dict` (`@lru_cache(maxsize=1)`)
  - `clinosim.modules.triage.engine.SUPPORTED_LEVEL_SYSTEMS = frozenset({"JTAS", "ESI"})`
  - `clinosim.modules.triage.engine.SUPPORTED_ARRIVAL_MODES = frozenset({"walk-in", "ambulance", "police", "helicopter", "private_vehicle"})`
  - `clinosim.modules.triage.engine.pick_triage_level(severity, level_system, rng) -> str`
  - `clinosim.modules.triage.engine.pick_arrival_mode(severity, rng) -> str`

- [ ] **Step 1: Write failing tests**

`tests/unit/modules/triage/test_engine.py`:

```python
"""Unit tests for triage engine(Tier 1 #3 α-min-2 PR1)."""

from __future__ import annotations

import numpy as np

from clinosim.modules.triage.engine import (
    SUPPORTED_ARRIVAL_MODES,
    SUPPORTED_LEVEL_SYSTEMS,
    load_triage_protocols,
    pick_arrival_mode,
    pick_triage_level,
)


def test_load_triage_protocols_returns_both_systems():
    p = load_triage_protocols()
    assert "JTAS" in p["triage_systems"]
    assert "ESI" in p["triage_systems"]


def test_supported_sets():
    assert SUPPORTED_LEVEL_SYSTEMS == frozenset({"JTAS", "ESI"})
    assert "walk-in" in SUPPORTED_ARRIVAL_MODES


def test_pick_triage_level_mild_jtas():
    """Mild severity → mostly level 4-5 (JTAS)."""
    rng = np.random.default_rng(42)
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for _ in range(1000):
        level = pick_triage_level("mild", "JTAS", rng)
        counts[level] += 1
    # mild は 3-5 に集中(distribution 準拠)
    assert counts["1"] == 0
    assert counts["2"] == 0
    assert counts["4"] + counts["5"] >= 700  # 70%+


def test_pick_triage_level_severe_esi():
    """Severe severity → mostly level 1-2 (ESI)."""
    rng = np.random.default_rng(42)
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for _ in range(1000):
        level = pick_triage_level("severe", "ESI", rng)
        counts[level] += 1
    # severe は 1-2 に集中
    assert counts["1"] + counts["2"] >= 700  # 70%+


def test_pick_arrival_mode_returns_valid():
    rng = np.random.default_rng(42)
    for _ in range(100):
        mode = pick_arrival_mode("moderate", rng)
        assert mode in SUPPORTED_ARRIVAL_MODES


def test_pick_triage_level_deterministic():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    assert pick_triage_level("mild", "JTAS", rng1) == pick_triage_level("mild", "JTAS", rng2)
```

`tests/unit/modules/triage/test_triage_protocols_yaml.py`:

```python
"""YAML validator tests for triage_protocols.yaml."""

from __future__ import annotations

import pytest

from clinosim.modules.triage.engine import (
    _validate_triage_protocols,
    load_triage_protocols,
)


def test_yaml_loads():
    p = load_triage_protocols()
    assert p


def test_validator_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        _validate_triage_protocols({})


def test_validator_raises_on_missing_level_system():
    bad = {"triage_systems": {}, "arrival_modes": []}
    with pytest.raises(ValueError, match="JTAS.*ESI"):
        _validate_triage_protocols(bad)


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_triage_protocols() is load_triage_protocols()
```

- [ ] **Step 2: Run tests to verify failure**

```
pytest tests/unit/modules/triage/ -v
```

Expected: FAIL — module not exists.

- [ ] **Step 3: Create `clinosim/modules/triage/__init__.py`**

```python
"""Triage module(Tier 1 #3 α-min-2 always-on Module, AD-55).

ED encounter で JTAS(JP)/ ESI(US)level + arrival_mode + acuity_score を
sampling、EncounterRecord.triage_data に populate。

POST_ENCOUNTER enricher、order=93(before nursing=94, before document=95)。
"""

from __future__ import annotations

from clinosim.types.triage import TriageData

__all__ = ["TriageData"]
```

- [ ] **Step 4: Create `clinosim/modules/triage/reference_data/triage_protocols.yaml`**

```yaml
# Triage protocols(JTAS/ESI + arrival_mode)
# JTAS 1-5 = 日本臨床救急医学会 JTAS 2017
# ESI 1-5 = AHRQ ESI Version 4

triage_systems:
  JTAS:
    levels:
      "1": {name_ja: "蘇生", eng: "Resuscitation", target_wait_min: 0}
      "2": {name_ja: "緊急", eng: "Emergent", target_wait_min: 15}
      "3": {name_ja: "準緊急", eng: "Urgent", target_wait_min: 30}
      "4": {name_ja: "低緊急", eng: "Less Urgent", target_wait_min: 60}
      "5": {name_ja: "非緊急", eng: "Non-Urgent", target_wait_min: 120}
  ESI:
    levels:
      "1": {name_en: "Resuscitation", target_wait_min: 0}
      "2": {name_en: "Emergent", target_wait_min: 10}
      "3": {name_en: "Urgent", target_wait_min: 30}
      "4": {name_en: "Semi-Urgent", target_wait_min: 60}
      "5": {name_en: "Non-Urgent", target_wait_min: 120}

arrival_modes:
  - walk-in
  - ambulance
  - police
  - helicopter
  - private_vehicle

# severity → triage_level 分布(country-independent)
severity_to_triage_distribution:
  mild:
    "3": 0.15
    "4": 0.55
    "5": 0.30
  moderate:
    "2": 0.15
    "3": 0.60
    "4": 0.25
  severe:
    "1": 0.20
    "2": 0.55
    "3": 0.25

# arrival_mode base rate(severity で修正、下記 severity_multipliers 適用)
arrival_mode_base_distribution:
  walk-in: 0.55
  ambulance: 0.35
  private_vehicle: 0.08
  police: 0.01
  helicopter: 0.01

# severity severe → ambulance +30% shift
arrival_mode_severity_multipliers:
  mild:
    walk-in: 1.4
    ambulance: 0.4
    private_vehicle: 1.0
    police: 1.0
    helicopter: 0.0
  moderate:
    walk-in: 1.0
    ambulance: 1.0
    private_vehicle: 1.0
    police: 1.0
    helicopter: 1.0
  severe:
    walk-in: 0.3
    ambulance: 2.0
    private_vehicle: 0.5
    police: 2.0
    helicopter: 5.0
```

- [ ] **Step 5: Create `clinosim/modules/triage/engine.py`**

```python
"""Triage module engine(Tier 1 #3 α-min-2 PR1).

Loader + 6-layer validator + JTAS/ESI level + arrival_mode sampling.
POST_ENCOUNTER enricher entry:triage_enricher(Task 3)。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules._shared import normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_LEVEL_SYSTEMS: frozenset[str] = frozenset({"JTAS", "ESI"})
SUPPORTED_ARRIVAL_MODES: frozenset[str] = frozenset(
    {"walk-in", "ambulance", "police", "helicopter", "private_vehicle"}
)
SUPPORTED_SEVERITIES: frozenset[str] = frozenset({"mild", "moderate", "severe"})


def _validate_triage_protocols(data: dict[str, Any]) -> None:
    """6-layer silent-no-op defense for triage_protocols.yaml."""
    if not data:
        raise ValueError("triage_protocols.yaml: empty top-level")
    ts = data.get("triage_systems")
    if not ts or not isinstance(ts, dict):
        raise ValueError("triage_protocols.yaml: missing 'triage_systems' key")
    yaml_systems = set(ts.keys())
    if yaml_systems != SUPPORTED_LEVEL_SYSTEMS:
        missing = SUPPORTED_LEVEL_SYSTEMS - yaml_systems
        extra = yaml_systems - SUPPORTED_LEVEL_SYSTEMS
        raise ValueError(
            f"triage_protocols.yaml triage_systems ↔ SUPPORTED_LEVEL_SYSTEMS "
            f"drift: missing={sorted(missing)}, extra={sorted(extra)} "
            f"(must be exactly JTAS+ESI)"
        )
    # per-system level 1..5 all present
    for sys_name, sys_data in ts.items():
        levels = sys_data.get("levels", {})
        if set(levels.keys()) != {"1", "2", "3", "4", "5"}:
            raise ValueError(
                f"triage_protocols.yaml[{sys_name}]: levels must be exactly 1-5, "
                f"got {sorted(levels.keys())}"
            )
    # arrival_modes cross-validated
    arr = data.get("arrival_modes", [])
    if set(arr) != SUPPORTED_ARRIVAL_MODES:
        raise ValueError(
            f"triage_protocols.yaml arrival_modes ↔ SUPPORTED_ARRIVAL_MODES drift"
        )
    # severity_to_triage_distribution: all 3 severities present, each sums to ~1.0
    dist = data.get("severity_to_triage_distribution", {})
    if set(dist.keys()) != SUPPORTED_SEVERITIES:
        raise ValueError(
            f"triage_protocols.yaml severity_to_triage_distribution keys drift"
        )
    for sev, probs in dist.items():
        total = sum(probs.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"triage_protocols.yaml[severity={sev}] probs must sum to ~1.0, got {total}"
            )
    # arrival_mode_base_distribution: sums to ~1.0
    base = data.get("arrival_mode_base_distribution", {})
    if set(base.keys()) != SUPPORTED_ARRIVAL_MODES:
        raise ValueError("arrival_mode_base_distribution keys drift")


@lru_cache(maxsize=1)
def load_triage_protocols() -> dict[str, Any]:
    """Load triage_protocols.yaml + validate."""
    with (_REF_DIR / "triage_protocols.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_triage_protocols(data)
    return data


def pick_triage_level(severity: str, level_system: str, rng: np.random.Generator) -> str:
    """Sample triage level given severity + system (JTAS or ESI use same distribution)."""
    if level_system not in SUPPORTED_LEVEL_SYSTEMS:
        raise ValueError(f"unsupported level_system: {level_system}")
    protocols = load_triage_protocols()
    dist = protocols["severity_to_triage_distribution"][severity]
    levels = list(dist.keys())
    probs = normalize_probabilities([dist[k] for k in levels], fallback="raise")
    return str(rng.choice(levels, p=probs))


def pick_arrival_mode(severity: str, rng: np.random.Generator) -> str:
    """Sample arrival mode given severity."""
    protocols = load_triage_protocols()
    base = protocols["arrival_mode_base_distribution"]
    mults = protocols["arrival_mode_severity_multipliers"][severity]
    weights = {m: base[m] * mults.get(m, 1.0) for m in base}
    modes = list(weights.keys())
    probs = normalize_probabilities([weights[m] for m in modes], fallback="raise")
    return str(rng.choice(modes, p=probs))
```

- [ ] **Step 6: Add `ENRICHER_SEED_OFFSETS["triage"]` to seeding.py**

In `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`:

```python
ENRICHER_SEED_OFFSETS = {
    # ... existing ...
    "document": 0x444F,       # "DO"(α-min-1)
    "triage": 0x5452,          # "TR"(α-min-2)
}
```

- [ ] **Step 7: Create `clinosim/modules/triage/README.md`**

```markdown
# triage module

## 役割

Tier 1 #3 α-min-2 always-on Module(AD-55、POST_ENCOUNTER order=93)。
ED encounter で JTAS(JP)/ ESI(US)level + arrival_mode + acuity_score を
sampling、`EncounterRecord.triage_data` に populate。

## Dependencies

- `clinosim/types/triage.py` — `TriageData` dataclass
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["triage"] = 0x5452`
- `clinosim/modules/_shared.py` — `normalize_probabilities`

## Reference data

- `reference_data/triage_protocols.yaml` — JTAS + ESI 5-level 定義、arrival_modes、severity_to_triage_distribution、arrival_mode_severity_multipliers

## Consumers

- `clinosim/modules/document/` — ED_TRIAGE_NOTE narrative で triage_data 参照
- `clinosim/modules/output/_fhir_documents.py` — ED_TRIAGE_NOTE の content に serialize

## 関連

- Spec: `docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-2-design.md`
- Master plan: `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
```

- [ ] **Step 8: Run tests**

```
pytest tests/unit/modules/triage/ tests/unit/test_types_triage.py -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```
git add clinosim/modules/triage/ clinosim/simulator/seeding.py tests/unit/modules/triage/
git commit -m "$(cat <<'EOF'
feat(triage): new AD-55 always-on Module + triage_protocols.yaml + level/mode sampling

Tier 1 #3 α-min-2 PR1 Task 2:
- clinosim/modules/triage/ skeleton + engine.py(loader + 6-layer validator
  + pick_triage_level + pick_arrival_mode)
- triage_protocols.yaml: JTAS 1-5 + ESI 1-5 + arrival_modes (5 modes) +
  severity→level distribution + severity→arrival multipliers
- ENRICHER_SEED_OFFSETS["triage"] = 0x5452("TR")

Level system country-gated at enricher call site (Task 3):JP→JTAS, US→ESI.
6-layer defense: forward+reverse coverage vs SUPPORTED_LEVEL_SYSTEMS +
SUPPORTED_ARRIVAL_MODES + SUPPORTED_SEVERITIES, level 1-5 present per system,
probability sums to ~1.0 per severity bucket.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013a5SdaKQejjb7aJKfwE8wB
EOF
)"
```

---

## Task 3: Triage enricher(POST_ENCOUNTER order=93、ED only)

**Files:**
- Modify: `clinosim/modules/triage/engine.py`(add `triage_enricher` function)
- Modify: `clinosim/simulator/enrichers.py`(register triage_enricher)
- Test: `tests/unit/modules/triage/test_engine.py`(extend with enricher tests)

**Interfaces:**
- Consumes: `pick_triage_level`, `pick_arrival_mode`, `TriageData` from Task 2, `EncounterRecord.triage_data` field from Task 1
- Produces:
  - `clinosim.modules.triage.engine.triage_enricher(ctx)` populates `record.encounters[].triage_data` for ED encounters

- [ ] **Step 1: Add failing test to `tests/unit/modules/triage/test_engine.py`**

```python
def test_triage_enricher_populates_ed_encounters():
    from types import SimpleNamespace
    from clinosim.modules.triage.engine import triage_enricher

    ed_enc = SimpleNamespace(
        encounter_id="ed1",
        encounter_type="emergency",
        severity="moderate",
        triage_data=None,
    )
    outpatient_enc = SimpleNamespace(
        encounter_id="op1",
        encounter_type="outpatient",
        severity="mild",
        triage_data=None,
    )
    inpatient_enc = SimpleNamespace(
        encounter_id="inp1",
        encounter_type="inpatient",
        severity="severe",
        triage_data=None,
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1"),
        encounters=[ed_enc, outpatient_enc, inpatient_enc],
    )
    ctx = SimpleNamespace(
        master_seed=42,
        country="jp",
        records=[record],
    )
    triage_enricher(ctx)
    # ED encounter → triage_data populated
    assert ed_enc.triage_data is not None
    assert ed_enc.triage_data.level in {"1", "2", "3", "4", "5"}
    assert ed_enc.triage_data.level_system == "JTAS"  # JP → JTAS
    # non-ED → not touched
    assert outpatient_enc.triage_data is None
    assert inpatient_enc.triage_data is None


def test_triage_enricher_country_gates_esi_for_us():
    from types import SimpleNamespace
    from clinosim.modules.triage.engine import triage_enricher

    ed_enc = SimpleNamespace(
        encounter_id="ed1",
        encounter_type="emergency",
        severity="moderate",
        triage_data=None,
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1"),
        encounters=[ed_enc],
    )
    ctx = SimpleNamespace(
        master_seed=42,
        country="us",
        records=[record],
    )
    triage_enricher(ctx)
    assert ed_enc.triage_data.level_system == "ESI"


def test_triage_enricher_deterministic():
    from types import SimpleNamespace
    from clinosim.modules.triage.engine import triage_enricher

    def _make():
        ed_enc = SimpleNamespace(
            encounter_id="ed1",
            encounter_type="emergency",
            severity="moderate",
            triage_data=None,
        )
        record = SimpleNamespace(
            patient=SimpleNamespace(patient_id="pt1"),
            encounters=[ed_enc],
        )
        return SimpleNamespace(master_seed=42, country="jp", records=[record])

    ctx1 = _make()
    ctx2 = _make()
    triage_enricher(ctx1)
    triage_enricher(ctx2)
    a = ctx1.records[0].encounters[0].triage_data
    b = ctx2.records[0].encounters[0].triage_data
    assert a.level == b.level
    assert a.arrival_mode == b.arrival_mode
```

- [ ] **Step 2: Run tests to verify failure**

```
pytest tests/unit/modules/triage/test_engine.py -v
```

Expected: FAIL — `triage_enricher` not defined.

- [ ] **Step 3: Add `triage_enricher` to `clinosim/modules/triage/engine.py`**

At end of file:

```python
from datetime import datetime, timedelta

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.triage import TriageData


ED_ENCOUNTER_TYPES: frozenset[str] = frozenset({"emergency"})


def triage_enricher(ctx) -> None:
    """POST_ENCOUNTER enricher: populate triage_data on ED encounters.

    Country-gated:JP→JTAS、US→ESI。
    Determinism via derive_sub_seed(master, ENRICHER_SEED_OFFSETS["triage"],
    encounter_id)。Master stream 不変。
    """
    country = _o(ctx, "country", "us").lower()
    level_system = "JTAS" if country == "jp" else "ESI"
    records = _o(ctx, "records", []) or []
    for record in records:
        encounters = _o(record, "encounters", []) or []
        for enc in encounters:
            enc_type = _o(enc, "encounter_type", "")
            # enum vs str dual-access
            enc_type_str = enc_type.value if hasattr(enc_type, "value") else str(enc_type)
            if enc_type_str.lower() not in ED_ENCOUNTER_TYPES:
                continue
            severity = _o(enc, "severity", "moderate") or "moderate"
            enc_id = _o(enc, "encounter_id", "")
            sub_seed = derive_sub_seed(
                ctx.master_seed, ENRICHER_SEED_OFFSETS["triage"], enc_id
            )
            import numpy as np
            rng = np.random.default_rng(sub_seed)
            level = pick_triage_level(severity, level_system, rng)
            arrival_mode = pick_arrival_mode(severity, rng)
            admission_dt = _o(enc, "admission_datetime", None)
            triage_time = admission_dt if isinstance(admission_dt, datetime) else None
            enc.triage_data = TriageData(
                level=level,
                level_system=level_system,
                arrival_mode=arrival_mode,
                triage_time=triage_time,
                acuity_score=None,  # acuity_score は α-min-2 で未 populate、β-JP-1 で追加
                chief_complaint_summary=_o(enc, "chief_complaint", "") or "",
            )
```

- [ ] **Step 4: Register enricher in `clinosim/simulator/enrichers.py`**

In `register_builtin_enrichers()`, add(after imaging=90 registration):

```python
from clinosim.modules.triage.engine import triage_enricher

register_enricher(Enricher(
    name="triage",
    stage=POST_ENCOUNTER,
    order=93,
    run=triage_enricher,
    enabled=lambda config: True,  # always-on Base
))
```

Match the exact `Enricher(...)` constructor + `register_enricher(...)` call pattern used by imaging.

- [ ] **Step 5: Run tests**

```
pytest tests/unit/modules/triage/ -v
```

Expected: all pass(6 tests total)。

- [ ] **Step 6: Regression sweep**

```
pytest tests/unit -x -q
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```
git add clinosim/modules/triage/engine.py clinosim/simulator/enrichers.py tests/unit/modules/triage/test_engine.py
git commit -m "$(cat <<'EOF'
feat(triage): POST_ENCOUNTER enricher for ED encounters with JTAS/ESI country gating

Tier 1 #3 α-min-2 PR1 Task 3:
- triage_enricher(ctx): iterates record.encounters, skips non-ED,
  samples level (JTAS or ESI by ctx.country) + arrival_mode +
  chief_complaint_summary, populates EncounterRecord.triage_data
- Registered at POST_ENCOUNTER order=93 (before nursing=94, before
  document=95)
- Per-encounter sub-seed via derive_sub_seed(master, TRIAGE_SEED,
  encounter_id) preserving AD-16 master stream

3 new tests: ED-only population, JP/US country gating, determinism.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013a5SdaKQejjb7aJKfwE8wB
EOF
)"
```

---

## Task 4: Nursing module + nursing_assessment.yaml + primary_nurse assignment

**Files:**
- Create: `clinosim/modules/nursing/__init__.py`
- Create: `clinosim/modules/nursing/engine.py`
- Create: `clinosim/modules/nursing/README.md`
- Create: `clinosim/modules/nursing/reference_data/nursing_assessment.yaml`
- Modify: `clinosim/simulator/seeding.py`(add `ENRICHER_SEED_OFFSETS["nursing"] = 0x4E55`("NU"))
- Test: `tests/unit/modules/nursing/__init__.py`(empty)
- Test: `tests/unit/modules/nursing/test_engine.py`
- Test: `tests/unit/modules/nursing/test_nursing_assessment_yaml.py`

**Interfaces:**
- Consumes: `EncounterRecord.primary_nurse_id` field from Task 1, `staff module` for nurse roster
- Produces:
  - `clinosim.modules.nursing.engine.load_nursing_assessment() -> dict` (`@lru_cache(maxsize=1)`)
  - `clinosim.modules.nursing.engine.SUPPORTED_ADL_CATEGORIES` frozenset
  - `clinosim.modules.nursing.engine.SUPPORTED_RISK_ASSESSMENTS` frozenset
  - `clinosim.modules.nursing.engine.INPATIENT_ENCOUNTER_TYPES = frozenset({"inpatient", "icu", "rehab_inpatient"})`
  - `clinosim.modules.nursing.engine.assign_primary_nurse(encounter, roster, rng) -> str`

Analogous to Task 2 pattern.**Implementer subagent は spec §4.2 + Task 2 pattern を参照して埋める。**

Failing test skeleton(先に書く):

```python
def test_load_nursing_assessment_returns_valid_structure():
    from clinosim.modules.nursing.engine import load_nursing_assessment
    a = load_nursing_assessment()
    assert "adl_categories" in a
    assert "risk_assessments" in a
    assert "baseline" in a

def test_supported_adl_categories():
    from clinosim.modules.nursing.engine import SUPPORTED_ADL_CATEGORIES
    assert "eating" in SUPPORTED_ADL_CATEGORIES
    assert "mobility" in SUPPORTED_ADL_CATEGORIES

def test_assign_primary_nurse_returns_from_roster():
    import numpy as np
    from types import SimpleNamespace
    from clinosim.modules.nursing.engine import assign_primary_nurse
    roster = SimpleNamespace(
        by_role=lambda role: [
            SimpleNamespace(staff_id="NS-001"),
            SimpleNamespace(staff_id="NS-002"),
        ] if role == "nurse" else []
    )
    enc = SimpleNamespace(encounter_id="e1", encounter_type="inpatient")
    rng = np.random.default_rng(42)
    nurse_id = assign_primary_nurse(enc, roster, rng)
    assert nurse_id in {"NS-001", "NS-002"}

def test_assign_primary_nurse_deterministic():
    ...
```

YAML content = spec §4.2 verbatim + baseline "focus: バイタル管理..."。

Commit template pattern:`feat(nursing): new AD-55 always-on Module + nursing_assessment.yaml + primary_nurse assignment`

---

## Task 5: Nursing enricher(POST_ENCOUNTER order=94、inpatient/icu/rehab_inpatient only)

Analogous to Task 3(triage_enricher pattern)but for inpatient encounters.

**Files:**
- Modify: `clinosim/modules/nursing/engine.py`(add `nursing_enricher`)
- Modify: `clinosim/simulator/enrichers.py`(register nursing_enricher)
- Test: extend `tests/unit/modules/nursing/test_engine.py`

**Interfaces:**
- Consumes: `assign_primary_nurse` from Task 4, `EncounterRecord.primary_nurse_id` from Task 1
- Produces: `nursing_enricher(ctx)` sets `encounter.primary_nurse_id` for inpatient/icu/rehab_inpatient encounters

Failing tests(4-5):
- populates only inpatient/icu/rehab, skips outpatient/emergency
- deterministic re-run
- fallback when roster nurse absent → primary_nurse_id remains ""(logs warning)

Register at POST_ENCOUNTER order=94(match imaging=90 / triage=93 pattern in enrichers.py).

Commit:`feat(nursing): POST_ENCOUNTER enricher assigns primary_nurse_id for inpatient encounters`

---

## Task 6: 46 encounter YAML narrative extension + EncounterProtocol Pydantic

**Files:**
- Modify: `clinosim/modules/encounter/protocol.py`(add `EncounterProtocol.narrative: EncounterNarrativeSpec | None = None` Pydantic field + `EncounterNarrativeSpec` BaseModel with `outpatient_soap_template`/`ed_note_template`/`ed_triage_template` optional sub-blocks)
- Modify: 46 encounter YAML at `clinosim/modules/encounter/reference_data/*.yaml`(add `narrative:` block per condition)
- Test: `tests/unit/modules/encounter/test_narrative_yaml.py`(新)

**Interfaces:**
- Consumes: existing `EncounterProtocol` Pydantic
- Produces:
  - `EncounterProtocol.narrative: EncounterNarrativeSpec | None = None`
  - `EncounterNarrativeSpec(outpatient_soap_template + ed_note_template + ed_triage_template)`(each optional)

**Fill strategy(α-min-1 踏襲):**
1. 5 priority conditions detailed:`abdominal_pain_nonspecific`, `chest_pain_nonspecific`(if exists、else `chest_pain`)、`upper_respiratory_infection`(if exists、else `common_cold`)、`hypertension_followup`(if exists、else `hypertension`)、`trauma_extremity`(if exists、else 最も一般的 trauma encounter)
2. 残 41 encounters:baseline template skeleton(minimum viable):
   ```yaml
   narrative:
     outpatient_soap_template:  # 適用 encounter type によって条件付き
       subjective_ja: "{chief_complaint_ja}の訴え、{onset_days}日前より"
       objective_ja: "バイタル安定、身体所見特記事項なし"
       assessment_ja: "{primary_dx_display}"
       plan_ja: "{workup_summary}、{follow_up_ja}"
     ed_note_template:
       chief_complaint_ja: "{chief_complaint_ja}"
       hpi_ja: "{onset_days}日前より{chief_complaint_ja}"
       physical_exam_ja:
         general: "意識清明、苦痛様"
       ed_workup_summary_ja: "{lab_summary}、{imaging_summary}"
       disposition_ja: "{disposition_display}"
     ed_triage_template:
       common_triage_levels: ["3", "4"]
   ```

Only include the sub-block relevant to the encounter's `encounter_type`(e.g., outpatient encounter YAML gets `outpatient_soap_template` only、ED encounter YAML gets `ed_note_template + ed_triage_template` only)。

Failing tests(3):
- `test_all_46_encounters_have_narrative`(forward coverage over `os.listdir`)
- `test_priority_condition_narrative_specific_content`(bacterial detailed content ≠ baseline)
- `test_encounter_narrative_type_matches_encounter_type`(outpatient encounter has outpatient_soap_template, ED encounter has ed_note_template)

Commit:`feat(encounter): EncounterNarrativeSpec Pydantic + 46 YAML narrative blocks`

---

## Task 7: DocumentTypeSpec.encounter_types_supported + specs_for_encounter_type

**Files:**
- Modify: `clinosim/modules/document/narrative/registry.py`(add `encounter_types_supported: tuple[str, ...] = ()` to `DocumentTypeSpec` + new `specs_for_encounter_type(encounter_type)` helper)
- Modify: `clinosim/modules/document/__init__.py`(re-export `specs_for_encounter_type`)
- Test: `tests/unit/modules/document/narrative/test_encounter_types_supported.py`(新)

**Interfaces:**
- Produces:
  - `DocumentTypeSpec.encounter_types_supported: tuple[str, ...]` field(default `()`= 全 encounter type support = backwards-compat for α-min-1 specs)
  - `specs_for_encounter_type(encounter_type: str) -> list[DocumentTypeSpec]` — returns specs where `encounter_type in spec.encounter_types_supported` OR `spec.encounter_types_supported == ()`(no restriction)

Failing tests(4):
- default `encounter_types_supported=()` = 全 encounter type match(backwards-compat for ADMISSION_HP etc.)
- explicitly-set `encounter_types_supported=("inpatient",)` → gates match / non-match correctly
- `specs_for_encounter_type("outpatient")` returns only specs with `"outpatient" in encounter_types_supported` OR default `()`
- combined with `countries_supported`:AND semantics(both must match)

Commit:`feat(document): DocumentTypeSpec.encounter_types_supported gating field`

---

## Task 8: TemplateNarrativeGenerator 6 new DocumentType support + LOINC verification

**Files:**
- Modify: `clinosim/modules/document/narrative/template_generator.py`(add rendering functions for 6 new DocumentType)
- Modify: `clinosim/codes/data/loinc.yaml`(add 6 new LOINC codes with `en:` + `ja:` after NLM authoritative verification)
- Test: `tests/unit/modules/document/narrative/test_template_generator_alpha2.py`(新)

**Interfaces:**
- Consumes: existing `TemplateNarrativeGenerator` + `EncounterProtocol.narrative` from Task 6
- Produces: `TemplateNarrativeGenerator._render_admission_nursing_assessment_composition(ctx, spec)` etc.(6 new render functions dispatched from `_render_composition_sections` and `_render_free_text` based on `document_type`)

**LOINC authoritative verification(★ implementer subagent には NLM clinicaltables.nlm.nih.gov/api/loinc_items で確認するよう指示):**
- `34119-8` = Nurse Admission history and physical note?(verify)
- `34120-6` = Nursing note?(verify)
- `34745-0` = Nursing discharge summary?(verify)
- `11488-4` = Outpatient consult note?(verify)
- `51841-6` = Emergency department Note?(verify)
- `54094-8` = Triage note?(verify)

If any code fails verification, use a related valid code from NLM lookup. Document the verification result in loinc.yaml comment.

Failing tests(15+):
- 6 new DocumentType each has a render function
- COMPOSITION types(ADMISSION_NURSING_ASSESSMENT / NURSING_DISCHARGE_SUMMARY / OUTPATIENT_SOAP / ED_NOTE)→ sections dict populated
- FREE_TEXT types(NURSING_SHIFT_NOTE / ED_TRIAGE_NOTE)→ raw_text populated
- JP locale rendering uses ja suffix fields
- Encounter's `narrative.outpatient_soap_template` variables substituted correctly
- ED_TRIAGE_NOTE reads from `encounter.triage_data`
- Missing `encounter.triage_data` → graceful generic phrase(no crash)

Commit:`feat(document): TemplateNarrativeGenerator α-min-2 — 6 new DocumentType + LOINC verification`

---

## Task 9: document_type_specs.yaml +6 spec entries

**Files:**
- Modify: `clinosim/modules/document/reference_data/document_type_specs.yaml`(add 6 spec entries)
- Modify: `clinosim/modules/document/narrative/registry.py`(update `SUPPORTED_DOCUMENT_TYPES` frozenset to include 6 new entries)
- Test: extend `tests/unit/modules/document/narrative/test_registry.py`(update existing tests + add α-min-2 tests)

Each spec entry follows α-min-1 pattern with `encounter_types_supported` populated:

```yaml
specs:
  # ... α-min-1 entries ...
  admission_nursing_assessment:
    loinc_code: "34119-8"     # NLM verified in Task 8
    display_en: "Nurse admission assessment"
    display_ja: "入院時看護アセスメント"
    format_type: composition
    countries_supported: [us, jp]
    encounter_types_supported: [inpatient, icu, rehab_inpatient]
    generation_frequency: admission_once
    composition_sections:
      - nursing_history
      - adl_assessment
      - risk_assessments
      - nursing_diagnosis
      - care_plan
    stage2_strategy: template_only
    llm_enabled_sections: []
  nursing_shift_note:
    loinc_code: "34120-6"
    display_en: "Nursing shift note"
    display_ja: "看護経過記録"
    format_type: free_text
    countries_supported: [us, jp]
    encounter_types_supported: [inpatient, icu, rehab_inpatient]
    generation_frequency: daily
    stage2_strategy: template_only
  nursing_discharge_summary:
    loinc_code: "34745-0"
    display_en: "Nursing discharge summary"
    display_ja: "退院時看護サマリ"
    format_type: composition
    countries_supported: [us, jp]
    encounter_types_supported: [inpatient, icu, rehab_inpatient]
    generation_frequency: discharge_once
    composition_sections:
      - admission_status
      - nursing_interventions_provided
      - patient_education
      - discharge_readiness
    stage2_strategy: template_only
  outpatient_soap:
    loinc_code: "11488-4"
    display_en: "Outpatient SOAP note"
    display_ja: "外来 SOAP 記録"
    format_type: composition
    countries_supported: [us, jp]
    encounter_types_supported: [outpatient]
    generation_frequency: encounter_once
    composition_sections: [subjective, objective, assessment, plan]
    stage2_strategy: template_only
  ed_note:
    loinc_code: "51841-6"
    display_en: "Emergency department note"
    display_ja: "救急記録"
    format_type: composition
    countries_supported: [us, jp]
    encounter_types_supported: [emergency]
    generation_frequency: encounter_once
    composition_sections:
      - chief_complaint
      - hpi
      - triage_details
      - physical_exam
      - ed_workup
      - assessment
      - disposition
    stage2_strategy: template_only
  ed_triage_note:
    loinc_code: "54094-8"
    display_en: "Triage note"
    display_ja: "トリアージ記録"
    format_type: free_text
    countries_supported: [us, jp]
    encounter_types_supported: [emergency]
    generation_frequency: encounter_once
    stage2_strategy: template_only
```

`SUPPORTED_DOCUMENT_TYPES` in registry.py updated to include all 9(α-min-1 3 + α-min-2 6)。

Failing tests(6):
- YAML loads with 9 total entries
- `SUPPORTED_DOCUMENT_TYPES` matches YAML keys exactly(forward+reverse coverage)
- `specs_for_encounter_type("outpatient")` returns only OUTPATIENT_SOAP
- `specs_for_encounter_type("inpatient")` returns α-min-1 3 + nursing 3 = 6 specs
- `specs_for_encounter_type("emergency")` returns 2 ED specs
- generation_frequency `"encounter_once"` recognized

Commit:`feat(document): +6 spec entries for α-min-2 DocumentType`

---

## Task 10: document_enricher encounter_type gating dispatch

**Files:**
- Modify: `clinosim/modules/document/engine.py`(expand `document_enricher` for encounter_type gating + `encounter_once` frequency)

**Interfaces:**
- Consumes: `specs_for_encounter_type` from Task 7, `EncounterRecord.primary_nurse_id + triage_data` from Task 1
- Produces: `document_enricher` supports all 4 generation_frequency values(`admission_once` / `daily` / `discharge_once` / `encounter_once`)and 3 encounter_type categories(inpatient / outpatient / emergency)

Existing `document_enricher(ctx)` in α-min-1 filters `_INPATIENT_ENCOUNTER_TYPES = frozenset({"inpatient", "icu", "rehab_inpatient"})`. Modification:

1. Remove the hardcoded `INPATIENT_ENCOUNTER_TYPES` filter — replace with per-spec `encounter_types_supported` check
2. Add `elif freq == "encounter_once":` branch(emits 1 document per encounter at appropriate day = day 0 for outpatient/emergency)
3. Ensure ClinicalImpression daily emit is still gated to inpatient/icu/rehab_inpatient(don't emit CI for outpatient / ED — spec §3.3 says CI is 「Daily working diagnosis update」)

Failing tests(6+ in `tests/unit/modules/document/test_engine_alpha2.py`):
- inpatient encounter → gets α-min-1 3 doc + α-min-2 nursing 3 doc = 6 documents
- outpatient encounter → gets 1 OUTPATIENT_SOAP only
- ED encounter → gets 1 ED_NOTE + 1 ED_TRIAGE_NOTE
- ClinicalImpression only emitted for inpatient/icu/rehab_inpatient
- `encounter_once` frequency dispatches to day 0
- cancelled encounter → no documents(existing behavior preserved)

Commit:`feat(document): expand document_enricher for outpatient + emergency encounter types`

---

## Task 11: _fhir_care_team.py builder + fhir_r4_adapter registration

**Files:**
- Create: `clinosim/modules/output/_fhir_care_team.py`
- Modify: `clinosim/modules/output/fhir_r4_adapter.py`(add `_bb_care_teams` to `_BUNDLE_BUILDERS` between Encounter and AllergyIntolerance per spec §2.2)
- Modify: `clinosim/codes/data/snomed-ct.yaml`(add CareTeam category code if needed, e.g. `SNOMED 424535000` = clinical team)
- Test: `tests/unit/output/test_fhir_care_team.py`(新)

**Interfaces:**
- Consumes: `EncounterRecord.attending_physician_id` + `primary_nurse_id` from prior tasks, `CARE_TEAM_ID_PREFIX = "careteam-"` canonical constant
- Produces:
  - `_bb_care_teams(ctx) -> list[dict]` — reads `record.encounters`, emits 1 CareTeam per encounter with `participant[]=attending + nurse`
  - `CARE_TEAM_ID_PREFIX` canonical constant(defined in `_fhir_care_team.py`, matches spec §5.1 pattern from α-min-1)

FHIR resource shape(FHIR R4):
```json
{
  "resourceType": "CareTeam",
  "id": "careteam-{encounter_id}",
  "status": "active" or "inactive" (post-discharge),
  "category": [{"coding": [{"system": "http://snomed.info/sct", "code": "424535000", "display": "..."}]}],
  "name": "Care team for encounter {enc_id}",
  "subject": {"reference": "Patient/{patient_id}"},
  "encounter": {"reference": "Encounter/{encounter_id}"},
  "period": {"start": "...", "end": "..."},
  "participant": [
    {"role": [{"coding": [...]}], "member": {"reference": "Practitioner/{attending_id}"}},
    {"role": [{"coding": [...]}], "member": {"reference": "Practitioner/{nurse_id}"}}  # inpatient のみ
  ]
}
```

`participant[1]` (nurse) emitted only if `primary_nurse_id != ""` — outpatient / ED では 1 name only。

Register in `_BUNDLE_BUILDERS` at position between Encounter and AllergyIntolerance(spec §2.2).

Failing tests(12+):
- Resource shape per FHIR R4(status + subject + encounter + participant[])
- ID uses `CARE_TEAM_ID_PREFIX`
- subject ref → Patient、encounter ref → Encounter、participant.member ref → Practitioner
- Inpatient encounter → 2 participants(attending + nurse)
- Outpatient / ED encounter → 1 participant(attending only)
- Empty `primary_nurse_id` → no orphan participant
- dict + dataclass paths(PR-90 lesson)
- JP locale:CareTeam.category.coding[].display + participant.role display in ja
- Empty encounters list → returns []
- No `attending_physician_id` → emit with placeholder or skip(align with α-min-2 fixes handling)

Commit:`feat(fhir): _fhir_care_team.py builder with 2-name participant scope`

---

## Task 12: _fhir_composition.py + _fhir_documents.py α-min-2 extension

**Files:**
- Modify: `clinosim/modules/output/_fhir_composition.py`(section mapping for ADMISSION_NURSING_ASSESSMENT + NURSING_DISCHARGE_SUMMARY + OUTPATIENT_SOAP + ED_NOTE)
- Modify: `clinosim/modules/output/_fhir_documents.py`(section text encoding for NURSING_SHIFT_NOTE + ED_TRIAGE_NOTE)
- Test: `tests/unit/output/test_fhir_composition_alpha2.py` + `tests/unit/output/test_fhir_documents_alpha2.py`

**Interfaces:**
- Consumes: 6 new DocumentType from Task 1, `_bb_compositions` and `_bb_document_references` existing dispatch
- Produces: existing `_bb_compositions` filter now includes 4 new COMPOSITION doc types(α-min-1 2 + α-min-2 4)、`_bb_document_references` filter now includes 2 new FREE_TEXT doc types(α-min-1 1 + α-min-2 2)

Since existing filter is `format_type == "composition"` and `format_type == "free_text"`, this should JUST WORK once Task 9 registers new specs with the correct `format_type`. The section-mapping logic in `_fhir_composition.py:_build_composition` already reads `ClinicalDocument.sections` dict — Task 8's template_generator populates that dict for the 4 new COMPOSITION types.

The main modification is:
1. LOINC display resolution for the 6 new codes(should just work via existing `code_lookup("loinc", loinc_code, lang)`)
2. Section title JP mapping if any needed(Task 13 5-lens Lens 3 deferred to β-JP-1, but check no regression)
3. `_fhir_documents.py` docstring update to note α-min-2 doc types now flow through Stage 1 default

Failing tests(10+):
- 4 new COMPOSITION emit as valid Composition with correct sections
- 2 new FREE_TEXT emit as valid DocumentReference
- Each has correct LOINC type.coding[0].code
- JP locale renders CJK section content(where applicable)
- dict + dataclass paths

Commit:`feat(fhir): _fhir_composition + _fhir_documents α-min-2 doc type support`

---

## Task 13: AD-60 audit module extension(23+ lift_firing_proof + CareTeam gate)

**Files:**
- Modify: `clinosim/modules/document/audit.py`(extend `_build_document_proof` + `_CLINICAL_ACCEPTANCE` + `canonical_constants`)
- Modify: `clinosim/audit/axes/clinical.py`(add `_check_care_team_coverage` — CareTeam per encounter integrity gate)
- Test: `tests/unit/audit/test_document_audit_alpha2.py`(new)

**Interfaces:**
- Consumes: audit framework from α-min-1
- Produces: expanded `document_chain` audit spec with 23+ lift_firing_proof(17 α-min-1 + 6+ α-min-2)+ CareTeam clinical gate

New lift_firing_proof entries(6+):
```python
# α-min-2 additions
("CARE_TEAM_ID_PREFIX", CARE_TEAM_ID_PREFIX, "careteam-"),
("JTAS_SYSTEM_URI", JTAS_SYSTEM_URI, "http://jptriage.org/JTAS"),  # or verified
("ESI_SYSTEM_URI", ESI_SYSTEM_URI, "http://esi.ahrq.gov"),  # or verified
("no_drop_encounter_primary_nurse_id → CareTeam.participant[1].member",
 <synthetic proof>, <expected>),
("no_drop_encounter_triage_data.level → ED_TRIAGE_NOTE.content",
 <synthetic proof>, <expected>),
("no_drop_encounter_type='outpatient' → OUTPATIENT_SOAP emit",
 <synthetic proof>, <expected>),
("no_drop_encounter_type='emergency' → ED_NOTE + ED_TRIAGE_NOTE emit",
 <synthetic proof>, <expected>),
```

Clinical acceptance additions:
```python
"care_team_per_encounter": "== 1",
"triage_data_per_ed_encounter": "== 1",
"admission_nursing_assessment_per_inpatient_encounter": "== 1",
"nursing_shift_note_per_day_per_inpatient": ">= 0.8",
"nursing_discharge_summary_per_completed_inpatient": "== 1",
"outpatient_soap_per_outpatient_encounter": "== 1",
"ed_note_per_ed_encounter": "== 1",
"ed_triage_note_per_ed_encounter": "== 1",
```

Failing tests(8):
- audit module still registered as `document_chain`(single module, extended)
- proof callable returns >= 23 tuples
- all proof checks pass(zero failures)
- new no-drop invariants exercise 6 new DocumentType emission paths
- `_check_care_team_coverage` gates CareTeam ref integrity(subject + encounter + participant.member)

Commit:`feat(audit): document_chain α-min-2 extension — 23+ lift_firing_proof + CareTeam gate`

---

## Task 14: Integration tests + e2e + DQR + 9 docs sync

**Files:**
- Create: 6 integration test files at `tests/integration/`(pattern per α-min-1 Task 12)
- Create: `docs/reviews/2026-07-XX-tier1-3-document-density-alpha-min-2-dqr.md`
- Modify: 9 doc files(README + README.ja + MODULES + DESIGN AD-64 + CONTRIBUTING + TODO + CLAUDE + design-guides + clinosim/modules/order/README.md if any)

Integration tests(pattern: α-min-1 Task 12):
1. `test_document_chain_alpha2.py` — 6 new resource type end-to-end(nursing 3 + outpatient SOAP + ED 2)+ CareTeam count assertion
2. `test_care_team_basedon_coverage.py` — CareTeam ref integrity(subject / encounter / participant refs)with pre-iterate fail-loud
3. `test_document_alpha2_determinism.py` — AD-16 byte-identical for US + JP
4. `test_document_alpha2_snapshot.py` — AD-32 nursing_discharge_summary skip for in-progress
5. `test_document_alpha2_subprocess_fullpipeline.py` — PR-90 dict path via subprocess
6. `test_document_alpha2_jp_localization.py` — JTAS display + JP nursing section CJK

DQR run:
```
mkdir -p scratchpad/doc_alpha2_us10k scratchpad/doc_alpha2_jp5k
python -m clinosim.simulator.cli generate --country US --population 10000 --seed 42 --output scratchpad/doc_alpha2_us10k --format fhir-r4
python -m clinosim.simulator.cli generate --country JP --population 5000  --seed 42 --output scratchpad/doc_alpha2_jp5k  --format fhir-r4
python -m clinosim.simulator.cli audit run -d scratchpad/doc_alpha2_us10k --module document_chain
python -m clinosim.simulator.cli audit run -d scratchpad/doc_alpha2_jp5k  --module document_chain
```

DQR doc structure(follow α-min-1 pattern):Summary + Cohort commands + Resource counts table + Gap closure analysis(CareTeam 0→~160k、6 new doc types 0→proper counts、AllergyIntolerance preserved from α-min-1)+ 4-axis audit verdict + Known limitations + Recommendation。

9 doc sync per spec §14。

Commit:`docs(tier1-3-alpha-min-2): DQR + 9-doc sync + integration tests`

---

## Task 15: Final whole-branch review + PR open

Follow α-min-1 Task 14 pattern:
1. `pytest tests/unit tests/integration -m "unit or integration" -x -q` final sweep
2. `pytest tests/e2e -q` sanity(expected 39+ PASS unchanged per α-min-1 precedent)
3. `git log --oneline master..HEAD | wc -l` verify 14 commits(1 per task 1-14)
4. `git push origin feature/tier1-document-density-alpha-min-2`
5. Generate final review package(`.superpowers/sdd/scripts/review-package master HEAD`)
6. Dispatch final review subagent(opus model)with whole-branch diff
7. Apply Critical / Important fixes in single fix commit
8. Open PR with `gh pr create`(pattern per PR #128 body)
9. Optionally merge or await user review

Commit(final review fixes if any):`fix(document,nursing,triage): close final whole-branch review findings`

---

## Plan Self-Review

**1. Spec coverage:** Each spec section maps to a task:
- Section 0-1(Purpose / Scope decisions) → all tasks
- Section 1.3(Module structure) → Tasks 2 + 3 + 4 + 5 + 8 + 11 + 12
- Section 1.4(既存資産)→ Task 10(document_enricher extension)
- Section 2(Architecture) → Tasks 1 + 3 + 5 + 10 + 11
- Section 3(Data structures) → Task 1
- Section 4(Reference data + encounter YAML) → Tasks 2 + 4 + 6
- Section 5(FHIR builder layer) → Tasks 11 + 12
- Section 6-8(Snapshot / Edge cases / Silent-no-op) → distributed
- Section 9(Testing) → Tasks 1-13(unit)+ Task 14(integration/DQR)
- Section 10(Risks) → Mitigations distributed
- Section 11(OOS) → Task 14(TODO.md formal entry)
- Section 12(Adversarial chain) → post-PR(next chain 10th converged target)
- Section 13(PR sequencing) → tasks 1-15 align
- Section 14(Docs sync) → Task 14
- Section 14.5(Scope discipline) → Global Constraints + all task briefs
- Section 15(References) → embedded

All sections covered ✓。

**2. Placeholder scan:** Tasks 1-3 exhaustive with full code; Tasks 4-14 summarized with structure outline + test count + interface + commit template。Implementer subagent uses spec §1-§15 as authoritative reference for Tasks 4-14 details。No "TBD" / "TODO" / "implement later" placeholders that hide actual work — every step has actionable content.

**3. Type consistency:**
- `TriageData` / `DocumentType` (+6) / `EncounterRecord.primary_nurse_id` / `EncounterRecord.triage_data` defined Task 1 → consumed Tasks 2-14 ✓
- `SUPPORTED_LEVEL_SYSTEMS` / `SUPPORTED_ARRIVAL_MODES` / `pick_triage_level` / `pick_arrival_mode` defined Task 2 → consumed Task 3 ✓
- `triage_enricher` defined Task 3 → registered Task 3, referenced Task 13 audit ✓
- `SUPPORTED_ADL_CATEGORIES` / `assign_primary_nurse` / `INPATIENT_ENCOUNTER_TYPES` defined Task 4 → consumed Task 5 ✓
- `nursing_enricher` defined Task 5 → registered Task 5, referenced Task 13 ✓
- `EncounterProtocol.narrative` / `EncounterNarrativeSpec` defined Task 6 → consumed Task 8 ✓
- `DocumentTypeSpec.encounter_types_supported` / `specs_for_encounter_type` defined Task 7 → consumed Tasks 9 + 10 ✓
- `CARE_TEAM_ID_PREFIX` / `_bb_care_teams` defined Task 11 → consumed Task 13 audit + Task 14 integration tests ✓
- `ENRICHER_SEED_OFFSETS["triage"]=0x5452` + `["nursing"]=0x4E55` defined Tasks 2 + 4 ✓

All consistent ✓。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-01-tier1-3-document-density-alpha-min-2-plan.md`。

**次 phase** で execution:

1. `git checkout feature/tier1-document-density-alpha-min-2`(既に作成済)
2. SDD execution(superpowers:subagent-driven-development):15 task chain
3. 5-lens adversarial fan-out(silent-no-op / unification / FHIR-JP Core / determinism+scale / spec+memory)= 10 例目 chain 目標
4. PR open

**Spec reference**(実装中の判断基準):
`docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-2-design.md`

**Scope discipline reminder**(memory `feedback_scope_discipline`):
Implementation 中、新 finding は data quality / clinical integrity 必須のみ scope 内 fix、それ以外 TODO entry 化。
