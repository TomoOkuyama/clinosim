# drugs.escalation の手技 entry に explicit type signal を導入する design

- Issue: #460
- Date: 2026-08-07 (session 82)
- Status: Approved for planning

## 背景

`clinosim/modules/disease/reference_data/*.yaml` の `drugs.escalation` block に、
**投薬ではない手技 entry が 6 件混在**している。これらは `Order(OrderType.MEDICATION)`
として生成され、FHIR では MedicationRequest + MedicationAdministration として emit
される可能性がある。

該当 6 entries(Issue #460 実測):

| file | country key | drug | drug code field | dose 文字列 |
|---|---|---|---|---|
| `acute_kidney_injury.yaml` | japan | Hemodialysis | `code_yj: "procedure"` | `3-4h session, 3x/week or continuous (CRRT)` |
| `acute_kidney_injury.yaml` | us | Hemodialysis | `code_rxnorm: "procedure"` | `3-4h session or CRRT` |
| `deep_vein_thrombosis.yaml` | japan | Catheter-directed thrombolysis | `code_yj: "N/A"` | `Urokinase 60,000-240,000 IU via catheter` |
| `deep_vein_thrombosis.yaml` | us | Catheter-directed thrombolysis | `code_rxnorm: "N/A"` | `Alteplase 0.5-1mg/h via catheter x12-24h` |
| `vertebral_compression_fracture.yaml` | japan | Vertebroplasty | `code_yj: "N/A"` | `Percutaneous vertebroplasty under fluoroscopy` |
| `vertebral_compression_fracture.yaml` | us | Kyphoplasty | `code_rxnorm: "N/A"` | `Balloon kyphoplasty under fluoroscopy` |

**YAML 作者は 6 entries 全てで drug code field に `"procedure"` / `"N/A"` を書き、
「これは薬剤ではない」と明示している**が、この signal は現在の実装で読まれていない。

## 現状の実装

session 74 以降 (commit `8c0e258816`) `simulator/inpatient.py:1230` は
`classify_encounter_treatment(_esc_display)` (text-substring keyword match) を経由。

現時点での実測 routing:
- ✅ Hemodialysis (AKI japan/us) — "hemodialysis" keyword hit → `OrderType.PROCEDURE`
- ✅ Vertebroplasty (VCF japan) — "vertebroplasty" keyword hit → `OrderType.PROCEDURE`
- ❌ Kyphoplasty (VCF us) — keyword 未収録 → `OrderType.MEDICATION`
- ❌ Catheter-directed thrombolysis (DVT japan/us) — keyword 未収録 → `OrderType.MEDICATION`

**latent defect の scope は 6 → 3。** ただし root cause は残る:
1. text-substring 照合が fragile(YAML author の spelling で結果が変わる)
2. YAML author が `code_*: "procedure"|"N/A"` と明示している signal を機械が読んでいない

## 選択肢と決定

| 選択肢 | データ品質 | 臨床整合性 | モジュール責任 |
|---|---|---|---|
| narrow: keyword 追加のみ | 3/6 → 6/6、次の spelling drift で再発 | 特定 3 件のみ | text-substring 単一 source、脆さ残 |
| **medium (採用)**: author signal 規範化 | 現 3/6 + 将来の全 escalation 手技を systematic に routing | author 明示意図が output に反映、不要な `route:IV` fallback 自動消滅 | classifier が「明示 signal > keyword > default」階層で責任分解 clear |
| large: スキーマ分離 | 最 clean | 完全な Procedure model 注入可能 | 43 疾患 YAML touch、migration cost 大 |

medium は narrow の superset(3 件も自然に片付く)+ large への道を閉じない
(explicit type signal は large の subset)。Issue 論点 4 の `EXTRACORPOREAL` 追加も
不要 — Procedure に route field は無いため。

## Architecture

現状 escalation Order 生成の分岐は 1 段 (text-substring classifier)。これを
**3 段 precedence** に変更する。分岐は `classify_escalation_treatment(esc_drug: dict)`
に集約(既存の `classify_encounter_treatment` は encounter YAML 由来の平文だけ扱うので触らない — 責任分解)。

```
esc_drug (dict from YAML)
  │
  ├─ (1) explicit type signal   ← YAML author が明示した意図を最優先
  │    esc_drug["type"] == "procedure"  →  OrderType.PROCEDURE
  │    esc_drug["type"] == "medication" →  OrderType.MEDICATION
  │
  ├─ (2) keyword fallback       ← 未 migration YAML の後方互換
  │    display_name を classify_encounter_treatment に投げる
  │    (session 74 の既存挙動を保つ、canonical set は既存の PROCEDURE_KEYWORDS)
  │
  └─ (3) default                 ← 上記いずれも合致しなければ
       OrderType.MEDICATION
```

**責任分解の粒度**:
- `classify_escalation_treatment` は escalation dict → OrderType の判定のみ
- 既存 `classify_encounter_treatment` は encounter YAML の平文 → OrderType のみ(責任不変)
- import-time validation は disease YAML の Pydantic model 側 (`DiseaseProtocol` の
  `drugs.escalation` schema) で `type` field validation を行い、legacy marker
  (`code_*: "procedure"|"N/A"`) を raise
- classifier 呼び出し点は `inpatient.py:1230` の 1 箇所のみ(既存)

**scope 外(明記)**:
- ED / outpatient encounter YAML の `treatment[]` — 別 classifier、別 Issue
- Order → Procedure の FHIR 変換ロジック(既に `fhir_r4_adapter.py:857+` に存在、活用のみ)
- Procedure structural fields (body_site / start_end / outcome) の充実 —
  「Order 発の light-weight Procedure」の現状を維持。ProcedureRecord への昇格は
  out-of-scope(large 側の議論)

## Components

| # | file | 変更 | 責任 |
|---|---|---|---|
| C1 | `clinosim/modules/order/treatment_classifier.py` | 新 fn `classify_escalation_treatment(esc_drug: dict) -> OrderType` を追加 | escalation dict の 3 段判定 |
| C2 | `clinosim/simulator/inpatient.py:1230` | 呼び出しを `classify_encounter_treatment(_esc_display)` → `classify_escalation_treatment(esc_drug)` に置換 | 呼び出し点 1 箇所のみ変更 |
| C3 | `clinosim/modules/disease/protocol.py` (Pydantic `DiseaseProtocol`) | `drugs.escalation[]` item schema に optional `type: Literal["medication","procedure"] \| None = None` を追加 + import-time validator で legacy marker (`code_*: "procedure"\|"N/A"`) を raise + `type=procedure && route` を raise | schema-level author signal 化 |
| C4 | `clinosim/modules/disease/reference_data/*.yaml` (3 files: `acute_kidney_injury.yaml` / `deep_vein_thrombosis.yaml` / `vertebral_compression_fracture.yaml`) | 6 entries に `type: "procedure"` 追加、legacy marker (`code_yj: "procedure"` / `code_rxnorm: "N/A"`) 削除、Procedure に不要な `route` field 削除 | YAML author signal 化 |
| C5 | `tests/unit/order/test_escalation_classifier.py`(新規) | 3 段 precedence の unit test | 判定 logic 単独 test |
| C6 | `tests/unit/disease/test_escalation_schema.py`(新規) | legacy marker が import-time で reject されることを test | silent regression 防御 |

## Data flow(6 entries fix 後)

```
disease YAML                          import-time                       simulation
─────────────                         ───────────                       ──────────

drugs.escalation:                                                       inpatient.py:1230
  japan:                              DiseaseProtocol                      │
    - drug: "Hemodialysis"    ──►     (validation)             ──►         │
      type: "procedure"               ├─ type OK                            ▼
      dose: "3-4h session..."         ├─ code_yj optional         classify_escalation_treatment(esc_drug)
      indication: "..."               └─ no legacy marker                    │
                                                                             ▼
                                                                     OrderType.PROCEDURE (via (1) explicit)
                                                                             │
                                                                             ▼
                                                                     Order(order_type=PROCEDURE, ...)
                                                                     ※ route field を持たない = 誤 IV 消滅
                                                                             │
                                                                             ▼
                                                              _fhir_procedures.py:857
                                                              FHIR Procedure resource
                                                              (light-weight, category=277132007)
```

**Kyphoplasty / Catheter-directed thrombolysis** も同じ flow で `type: "procedure"` に
より Procedure に routing。text classifier に依存しないので spelling drift immune。

**未 migration YAML(将来他 disease に新 escalation entry を書いたとき)**:
- `type` 未指定 → 段 (2) keyword fallback で従来挙動維持(silent regression 無し)
- 段 (2) は既存 `classify_encounter_treatment` を再利用(重複コードを作らない)

**AD-16 (determinism)**:
- 新 fn は pure function(RNG 消費なし)
- YAML の `type: "procedure"` 追加は Order 生成の code path を変えるだけ、seed には影響しない
- **byte-diff は変わる予定** — Order の `order_type` field が変わることで downstream
  FHIR emission が MR → Procedure に切り替わり、NDJSON レイアウトが変わる。これは
  意図した変更(new-feature PR、byte-diff invariant は保持しない、audit run が primary gate)

## Error handling + Validation

### Import-time validation (Pydantic `DiseaseProtocol`)

**Layer 1: `type` field 検査**(新規)

`drugs.escalation[*]` の item schema に optional
`type: Literal["medication", "procedure"] | None = None` を追加。値が入っていれば
literal 制約で誤値 (`"proc"` / `"procedure "` 等) は Pydantic が自動 reject → `ValidationError`。

**Layer 2: legacy marker 検出**(新規、model-level validator)

```python
@model_validator(mode="after")
def _reject_legacy_procedure_markers(self) -> "DiseaseProtocol":
    for country_key, entries in (self.drugs or {}).get("escalation", {}).items():
        for entry in entries if isinstance(entries, list) else [entries]:
            code_yj = entry.get("code_yj", "") if isinstance(entry, dict) else ""
            code_rxnorm = entry.get("code_rxnorm", "") if isinstance(entry, dict) else ""
            if code_yj in ("procedure", "N/A") or code_rxnorm in ("procedure", "N/A"):
                raise ValueError(
                    f"drugs.escalation entry for {country_key} carries a legacy "
                    f"non-code marker (code_yj={code_yj!r}, code_rxnorm={code_rxnorm!r}). "
                    f"Migrate to `type: \"procedure\"` and remove the marker "
                    f"(disease {self.disease_id}, drug {entry.get('drug', '')})."
                )
    return self
```

fail-loud、silent-no-op 防御 4 層 pattern と整合(canonical constants + upstream
`_validate_*` + backward `fallback="raise"`)。

**Layer 3: type と `route` の一貫性**(新規、同 model validator 内)

`type: "procedure"` の entry に `route` が付いていたら reject:

```python
if entry.get("type") == "procedure" and entry.get("route"):
    raise ValueError(
        f"drugs.escalation entry with type='procedure' must not carry a `route` "
        f"field (Procedure resource has no route). Remove `route` from entry "
        f"(disease {self.disease_id}, drug {entry.get('drug', '')})."
    )
```

これにより将来 author が「Procedure なのに route を書く」誤りを import-time で検出。

### Runtime error handling

- `classify_escalation_treatment(esc_drug)` は defensive:
  - `esc_drug` が dict でない → 上位 loop が `isinstance(esc_drug, dict)` guard 済み
    (inpatient.py:1220)、classifier 側でも同 guard を入れて double-defense
  - `type` field が Pydantic 通過後の値 → literal のみ、`None`/`"medication"`/`"procedure"` の 3 値
  - unknown `type` は Pydantic で reject 済 → classifier 到達時は必ず 3 値のいずれか

### 段 (2) keyword fallback は残す

将来 escalation に新 disease で `type` 未指定の手技が追加された場合の safety net。
既存 3 件 (hemodialysis / vertebroplasty / crrt) の挙動維持で silent regression を起こさない。
**Layer 2 の legacy marker 検出は `code_*: "procedure"|"N/A"` の 2 値のみ厳格化** —
この 2 値は「YAML author が明示的に非薬剤と signal した」印であり、他の code
(空文字 / 実 code)は無関係。

## Testing strategy

### C5: `tests/unit/order/test_escalation_classifier.py`(新規)

Unit test は判定 logic を classifier 単独で pin する(YAML loader / simulator を通さない = 早い):

```python
def test_explicit_type_procedure_wins_over_medication_default():
    esc = {"drug": "Mystery drug", "type": "procedure"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE

def test_explicit_type_medication_wins_over_keyword_hit():
    esc = {"drug": "Hemodialysis-adjacent drug", "type": "medication"}
    assert classify_escalation_treatment(esc) == OrderType.MEDICATION

def test_keyword_fallback_when_type_absent():
    esc = {"drug": "Hemodialysis", "dose": "3-4h"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE

def test_default_medication_when_no_type_no_keyword():
    esc = {"drug": "Vancomycin 1g", "dose": "q12h"}
    assert classify_escalation_treatment(esc) == OrderType.MEDICATION

def test_kyphoplasty_via_explicit_type():
    esc = {"drug": "Kyphoplasty", "type": "procedure"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE

def test_catheter_directed_thrombolysis_via_explicit_type():
    esc = {"drug": "Catheter-directed thrombolysis", "type": "procedure"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE

def test_non_dict_input_returns_medication_default():
    assert classify_escalation_treatment("bare string") == OrderType.MEDICATION
```

### C6: `tests/unit/disease/test_escalation_schema.py`(新規)

Import-time validation の pin(silent regression 防御):

```python
def test_legacy_procedure_marker_rejected_import_time():
    yaml_str = """..."""
    with pytest.raises(ValidationError, match="legacy non-code marker"):
        DiseaseProtocol.model_validate(yaml.safe_load(yaml_str))

def test_legacy_na_marker_rejected_import_time(): ...
def test_procedure_type_with_route_rejected(): ...
def test_unknown_type_value_rejected_by_literal(): ...

def test_all_shipped_disease_yamls_load_after_migration():
    for p in Path("clinosim/modules/disease/reference_data").glob("*.yaml"):
        DiseaseProtocol.model_validate(yaml.safe_load(p.read_text()))
```

### Integration test

大 test ではなく、cohort-level firing を 1 patient / small seed で pin:

```python
# tests/integration/simulator/test_escalation_procedure_emission.py(新規、~30 行)
def test_aki_escalation_emits_procedure_not_medication_request():
    # AKI cohort で inflammation escalation を強制発火する ForcedScenario
    # 検証:
    # - Order(order_type=PROCEDURE) が cif.orders に存在
    # - Procedure.ndjson に "Hemodialysis" を text に持つ resource が存在
    # - MedicationRequest.ndjson に "Hemodialysis" を含む resource が **ない**
```

### 実測 gate(verify-before-completion skill 準拠)

PR 前に production-scale cohort で以下を確認、PR 本文に結果を貼る:

```bash
PYTHONPATH=. clinosim generate --country JP --population 3000 --seed 42 \
  --start 2025-01-01 --end 2026-01-01 --output /tmp/i460-jp

# 実測 gate:
#   grep -c "Hemodialysis\|Vertebroplasty\|Kyphoplasty\|Catheter-directed" \
#     /tmp/i460-jp/fhir/MedicationRequest.ndjson  = 0
#   grep -c "Hemodialysis\|Vertebroplasty\|Kyphoplasty\|Catheter-directed" \
#     /tmp/i460-jp/fhir/Procedure.ndjson         > 0
```

同時に master 対比 diff --stat:
```
期待:
  MedicationRequest.ndjson: line count 減少
  Procedure.ndjson:         line count 増加(同数分)
  他 NDJSON:                byte-identical
```

**tail 禁止 rule 遵守**: pytest -m integration は `2>&1 | tee LOGFILE` + Monitor で監視、
`| tail -N` は使わない(session 81 §4.1)。

### CI gate

- `pytest -m unit` — 全 pass(所要 <30s)
- `pytest -m integration` — 全 pass
- Lint / mypy strict — clean

## Migration steps(PR 内順序)

1 PR で完結、1 論点 (scope discipline)。以下の順で 1 commit ずつ:

| # | commit | 影響 | 検証 |
|---|---|---|---|
| M1 | classifier 新設 (C1) + unit test (C5) | 新 fn 追加のみ、既存 caller 影響なし | `pytest tests/unit/order/test_escalation_classifier.py` |
| M2 | inpatient.py:1230 呼び出し置換 (C2) | 既存挙動維持(YAML 未 migration = 段 (2) fallback) | `pytest -m unit -k escalation` + `pytest -m integration -k inpatient` |
| M3 | Pydantic schema + literal validator (C3 Layer 1) + schema test (C6) の一部 | 段階 A: `type` field 受入 + literal 制約のみ。legacy marker validator は未 wire | `pytest tests/unit/disease/test_escalation_schema.py::test_unknown_type_value_rejected_by_literal` + `test_all_shipped_disease_yamls_load_after_migration` |
| M4 | 3 YAML migration (C4) | 6 entries に `type: "procedure"` 追加、legacy marker + `route` 削除 | 実測 gate(下記) |
| M5 | legacy marker validator を raise 化 (C3 Layer 2/3) + 対応 test 追加 | 43 YAML 全 load PASS(migration 済み) | `pytest tests/unit/disease/test_escalation_schema.py` 全 pass |
| M6 | 実測 gate (production cohort) | JP p=3000 で MR に該当 drug 0、Procedure に該当 drug > 0 | grep + diff --stat |

**M3-M5 の 3 段分割理由**: M3 で validator を最初から raise にすると M3 commit
単体で 43 YAML 全て load 失敗 → CI 赤 → M4 が「validator 無効化 → migration →
validator 再有効化」の醜い順になる。段階分けで各 commit の CI green を保つ + revert しやすい。

## 未解決論点(design 決定を明示、本 PR scope 外)

| # | 論点 | 判断 | 理由 |
|---|---|---|---|
| U1 | Procedure structural fields (body_site / start_end / outcome / anesthesia) の充実 | 本 PR は scope 外、Issue #460 の large 案として backlog 継承 | 現行 `_fhir_procedures.py:857+` の light-weight Procedure で臨床整合性は最低限確保。structural 充実は ProcedureRecord への promotion が必要で design 変更が大 |
| U2 | `route: extracorporeal` 等の canonical route 追加 | 本 PR で `_ROUTE_SNOMED` に追加しない | Procedure に route field は無い。medication で extracorporeal を使う場面は存在しないため canonical set への追加自体不要 |
| U3 | ED / outpatient encounter YAML の `treatment[]` 同種 defect | 別 Issue で扱う | 責任分解 clear、`classify_encounter_treatment` (encounter YAML 用) と `classify_escalation_treatment` (disease YAML escalation 用) は責任が分かれる |
| U4 | dose の semantics(procedure に "3-4h session, 3x/week" を書くのは奇妙、Procedure.performedPeriod など別 field 候補) | 本 PR は Order.display_name にそのまま吸収(現状維持) | dose→Procedure schedule mapping は design が非自明、次段の U1 と同時対応が clean |
| U5 | `discharge_oral` の非経口薬混在 | Issue #460 が明示的に scope 外宣言 | 別 Issue |

## PR scope 宣言

**scope IN**:
- classifier 新設 + 3 段 precedence 化
- Pydantic schema 拡張 (`type` field + legacy marker reject + `type=procedure && route` reject)
- 3 YAML (AKI / DVT / VCF) の 6 entries migration
- unit + integration test

**scope OUT**(明示):
- Procedure structural fields 充実 (U1)
- ED / outpatient 用 classifier (U3)
- `_ROUTE_SNOMED` 拡張 (U2)
- dose → Procedure schedule mapping (U4)

## 成果基準

- 43 disease YAML 全 load PASS
- `pytest -m unit` + `pytest -m integration` clean
- JP p=3000 cohort で MedicationRequest.ndjson に該当 4 drug 名 0 件、
  Procedure.ndjson に該当 4 drug 名 > 0 件
- byte-diff は変わる予定(該当 drug の resource type 移動のみ)、他 NDJSON は identical

## Refs

- Issue #460 (this)
- Refs #437 #455 #458 (Issue 内)
- session 74 commit `8c0e258816` — classifier 導入
- CLAUDE.md silent-no-op 防御 4 層 pattern
