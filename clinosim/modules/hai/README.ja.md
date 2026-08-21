# `clinosim.modules.hai` — HAI 発症サンプリング + culture + lab lift

## 概要

CDC NHSN の per-line-day risk rate に基づき、encounter ごとに医療関連
感染 (HAI) 事象 — CLABSI / CAUTI / VAP — をサンプリングし、
`record.extensions["hai"]` に書き込み、既存 FHIR builder が自動 emit
できるよう companion `MicrobiologyResult` を生成し、新 infection を
反映すべく既存 WBC + CRP 観測値を closed-form 順方向 delta で持ち上げる
(Phase 3a) モジュール。

[`clinosim.modules.device`](../device/README.md) (POST_ENCOUNTER
order=70、line-days 生成)、
[`clinosim.modules.antibiotic`](../antibiotic/README.md)
(POST_ENCOUNTER order=85、empirical regimen)、observation
microbiology emitter と組み合わさり、本モジュールは 4 モジュール
HAI cascade の中核。

## Scope

- **In scope**: `sample_hai_onset` — `extensions["device"]` line-days
  上で HAI type ごとに CDC NHSN per-line-day risk サンプリング;
  `_sample_organism` — `hai_organisms.yaml` からの organism 選択;
  `_add_days` date helper; `apply_hai_lab_lift` — Phase 3a の
  closed-form WBC + CRP 順方向 delta。`_hai_lift_delta` は
  `derive_lab_values` の CRP + WBC 式を鏡像化 (state snapshot は
  `state_history[day_index + 1]` から取り、`round_to_precision` +
  `determine_flag` を再適用); 6 load 時 YAML validator
  (`_validate_hai_organisms` / `_validate_hai_rates` /
  `_validate_hai_codes` / `_validate_hai_specimens` +
  antibiogram loader 内 `_validate_hai_antibiogram` +
  `_validate_hai_lab_lift`); `HAI_TYPES` canonical 定数。
- **In scope (audit)**: [`audit.py`](audit.py) — 最初の per-Module
  AD-60 audit plug-in。合成 CAUTI の `lift_firing_proof` を登録し
  runtime が生成する closed-form delta を再現 (PR-90 が欠いていた
  load-bearing 検証)、canonical-constants + structural-obs-codes
  check + clinical-acceptance cohort gate (CAUTI WBC delta ≥ 1500、
  CRP delta ≥ 25、CLABSI / VAP 各 ≥ 3000 / ≥ 50、小 cohort → WARN)
  も含む。
- **Out of scope**: device line-days 生成
  ([`device`](../device/README.md))、empirical / narrowing
  抗菌薬 regimen 構築
  ([`antibiotic`](../antibiotic/README.md))、culture の FHIR
  `Observation` / `DiagnosticReport` emission
  ([`output/fhir_r4/labs/`](../output/fhir_r4/) —
  `_fhir_microbiology.py`)、ServiceRequest emission
  ([`order`](../order/README.md))。

## Public API

```python
from clinosim.modules.hai import HAI_TYPES         # ("clabsi", "cauti", "vap")
from clinosim.modules.hai.engine import (
    sample_hai_onset,                              # (encounter, devices, rng) -> list[HAIEvent]
    load_hai_rates,                                # () -> dict (@lru_cache)
    load_hai_codes,                                # () -> dict (@lru_cache)
    load_hai_organisms,                            # () -> dict (@lru_cache)
    load_hai_specimens,                            # () -> dict (@lru_cache)
)
from clinosim.modules.hai.enricher import hai_enricher   # POST_ENCOUNTER entry
from clinosim.modules.hai.lab_lift import (
    apply_hai_lab_lift,                            # (record) -> None (observations を mutate)
    _hai_lift_delta,                               # closed-form WBC / CRP delta
)
```

## 決定論

- サブ seed オフセット `0x4841` (`"HA"`, PR-B) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["hai"]` に登録済み。
- 患者単位サブ RNG: `derive_sub_seed(master_seed, offset, patient_id)`
  — 患者主 RNG 未消費 (AD-16)。
- Lab lift は決定論的 (closed-form delta、rng draw 無し)。state
  snapshot 入力は pre-lift state history で完全決定するため、
  lift 適用 / 不適用は WBC / CRP 観測値そのもの以外は byte-clean。
- **Canonical `HAI_TYPES = ("clabsi", "cauti", "vap")`** — 小文字
  文字列を常に使うこと。旧 UPPERCASE YAML キー + lowercase enricher
  書き込みが本番で Phase 3a lift 全体を silent no-op にした
  (PR-90 教訓)。YAML integrity test + 本 canonical 単一情報源で
  この種の regression を防ぐ。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`,
  `get_or_create_container`, `normalize_probabilities`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.modules.antibiotic` — `ANTIBIOTIC_LOINC_LOOKUP`
  (enricher が culture 書込時に消費)。
- `clinosim.modules.observation.engine` — `round_to_precision`,
  `determine_flag` (lift 後に再適用)。
- `clinosim.audit.registry` (`audit.py` 経由) — AD-60 audit 登録。
- `clinosim.types.encounter` — `Device`, `HAIEvent`,
  `MicrobiologyResult`。
- `numpy`, `yaml`。

## 定数と設定

- **`HAI_TYPES`** — 全 submodule import 前に `__init__.py` で定義
  される canonical 小文字 tuple (enricher.py との循環 import 回避)。
- **6 YAML** ([`reference_data/`](reference_data/)) に per-validator
  6-layer sibling sweep (Issue #121-#122):
  - `hai_organisms.yaml` — HAI type 別 organism SNOMED カタログ。
  - `hai_rates.yaml` — per-line-day HAI risk rate (CDC NHSN 2018-2020)。
  - `hai_codes.yaml` — HAI type 別 condition コード (ICD-10 + SNOMED)。
  - `hai_specimens.yaml` — HAI type 別 specimen type。
  - `hai_antibiogram.yaml` — organism × antibiotic S/I/R rate
    (antibiotic モジュールが load。`HAI_TYPES` + `hai_organisms.yaml`
    + `ANTIBIOTIC_LOINC_LOOKUP` に対し 3-way validate)。
  - `hai_lab_lift.yaml` — `_hai_lift_delta` が使う HAI type 別
    WBC + CRP delta parameter。
- **7-layer system-level silent-no-op 防御** (PR3b-3 / PR3b-5 chain
  で確立): canonical URIs + ID prefix + validator ordering +
  reverse-coverage (forward + staleness) + writer / reader 共有
  `HAI_EVENT_ID_SYSTEM` — 7-layer + per-validator 6-layer pattern の
  詳細は [`AGENTS.md`](../../../AGENTS.md) HAI-cascade 節を参照。

## ディレクトリ構造

```
clinosim/modules/hai/
  __init__.py                    HAI_TYPES canonical 定数 + loader stub
  engine.py                      sample_hai_onset + loader + validator + _sample_organism
  enricher.py                    POST_ENCOUNTER hai_enricher
  lab_lift.py                    apply_hai_lab_lift + _hai_lift_delta (Phase 3a)
  audit.py                       AD-60 audit plug-in (最初の per-Module) — lift_firing_proof
  reference_data/
    hai_organisms.yaml           organism SNOMED カタログ
    hai_rates.yaml               per-line-day HAI risk rate
    hai_codes.yaml               HAI type 別 ICD + SNOMED code
    hai_specimens.yaml           HAI type 別 specimen type
    hai_antibiogram.yaml         organism × antibiotic S/I/R
    hai_lab_lift.yaml            WBC + CRP delta parameter
```

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
で登録:

- `name="hai"`, `stage=POST_ENCOUNTER`, `order=80`,
  `enabled=lambda c: True`。`device` (order=70) の後に走り
  `extensions["device"]` が用意された状態で発火。
- `audit.py` module は import 時に AD-60 audit framework に登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) | POST_ENCOUNTER order=80 登録。 |
| Audit registry | [`clinosim/modules/hai/audit.py`](audit.py) | AD-60 audit plug-in — lift_firing_proof + canonical / structural / clinical check。 |
| Antibiotic enricher | [`clinosim/modules/antibiotic/enricher.py`](../antibiotic/enricher.py) | empirical regimen 選択のため `extensions["hai"]` を read。 |
| Observation microbiology emitter | [`clinosim/modules/observation/microbiology.py`](../observation/microbiology.py) | HAI 由来 culture に `Observation.specimen.reference` と `HAI_EVENT_ID_SYSTEM` identifier を emit。 |
| FHIR microbiology / diagnostic-report / servicerequest / document chain | 下記 integration test 参照 | HAI cascade emission の end-to-end。 |

## テスト

```bash
pytest tests/unit -k "hai" -q
pytest tests/integration -k "hai" -q
clinosim audit run -d <cohort_dir> --module hai
```

個別ファイル:

- [`tests/unit/test_hai_yaml_validators.py`](../../../tests/unit/test_hai_yaml_validators.py)
  — 6-layer per-validator sibling sweep。
- [`tests/unit/test_hai_engine.py`](../../../tests/unit/test_hai_engine.py)
  — `sample_hai_onset` + organism サンプリング。
- [`tests/unit/test_hai_enricher.py`](../../../tests/unit/test_hai_enricher.py)
  — POST_ENCOUNTER enricher 決定論 + `extensions["device"]` 消費。
- [`tests/unit/test_derive_lab_values_hai.py`](../../../tests/unit/test_derive_lab_values_hai.py)
  — lab-lift closed-form と `derive_lab_values` の一致。
- [`tests/unit/test_forced_scenario_hai.py`](../../../tests/unit/test_forced_scenario_hai.py)
  — `ForcedScenario.force_hai_event` 決定論的注入。
- [`tests/unit/test_hai_codes_coverage.py`](../../../tests/unit/test_hai_codes_coverage.py)
  — ICD / SNOMED coverage。
- [`tests/integration/test_hai_susceptibility_chain.py`](../../../tests/integration/test_hai_susceptibility_chain.py)
  — PR3b-2 chain end-to-end。
- [`tests/integration/test_audit_hai_module.py`](../../../tests/integration/test_audit_hai_module.py)
  — AD-60 audit run integration。
- [`tests/integration/test_servicerequest_chain.py`](../../../tests/integration/test_servicerequest_chain.py),
  [`test_document_chain.py`](../../../tests/integration/test_document_chain.py)
  — cross-module emission。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
