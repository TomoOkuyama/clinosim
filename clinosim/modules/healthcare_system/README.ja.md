# `clinosim.modules.healthcare_system` — 国別コンフィグ loader

## 概要

他モジュールが国別挙動を切り替えるための設定 bundle
(`HealthcareSystemConfig`) を単一 loader で提供する。切替対象は
検査発注頻度、退院判断基準、目標在院日数、および 4 つのコード体系
(診断 / 薬 / 検査 / 手技) 識別子。YAML 実体は
[`clinosim/config/`](../../config/) 配下にあり、本モジュールは load /
cache / country dispatch 契約のみを持つ。

## Scope

- **In scope**: `clinosim/config/{japan,us}.yaml` を Pydantic
  `HealthcareSystemConfig` に読み込み、国別 `@lru_cache`、
  country 文字列正規化 (`"JP"` → `japan.yaml`、`"US"` → `us.yaml`、
  それ以外 → `ValueError`)。
- **Out of scope**: 病院レベルのレイアウト / ベッド数 / 部門運用
  ([`clinosim/config/hospital_*.yaml`](../../config/) にあり
  [`clinosim.modules.facility`](../facility/README.md) が消費)、
  患者 demographics / 検査基準範囲 / drug code mapping
  (locale scope、[`clinosim/locale/<country>/`](../../locale/))、
  cross-facility 紹介 / スケジューリング (現状モデル化していない)、
  FHIR `Organization` emission
  ([`clinosim.modules.output`](../output/README.md))。

## Public API

本モジュールは `loader` サブモジュール経由で 1 関数のみを公開。
パッケージ `__init__.py` は空で、呼び出し側は loader を直接 import する:

```python
from clinosim.modules.healthcare_system.loader import load_healthcare_config

cfg = load_healthcare_config("JP")
# cfg.lab_frequency_multiplier  -> 1.3
# cfg.discharge_criteria        -> "lab_normalization"
# cfg.diagnosis_code_system     -> "ICD-10"
```

`load_healthcare_config` は `@lru_cache(maxsize=2)` 付きで run 中の
反復 lookup は無料。返却モデルは全 consumer が read-only 扱い —
共有 instance を mutate してはいけない。

## 決定論

該当なし — 本モジュールは乱数を引かない。load される config は
country 文字列 (と on-disk YAML) の純粋関数で、返却される Pydantic
モデルは共有 read-only。

## 依存

- `yaml` — YAML パーサ。
- `clinosim.types.config` — `HealthcareSystemConfig` (Pydantic
  BaseModel)。
- 他の `clinosim.modules.*` には依存しない — **leaf module** であり
  他モジュールが循環なく依存できる。

## 定数と設定

- [`clinosim/config/japan.yaml`](../../config/japan.yaml) と
  [`clinosim/config/us.yaml`](../../config/us.yaml) — 2 config file。
  フィールド (詳細は
  [`clinosim/types/config.py`](../../types/config.py) を参照):
  - `country`: `"JP"` / `"US"`。
  - `lab_frequency_multiplier` (float、default `1.0`) — 下流の
    lab ordering 頻度倍率。JP = `1.3`、US = `0.8`。
  - `discharge_criteria` (string、default `"lab_normalization"`)
    — `"lab_normalization"` (JP) / `"functional_recovery"` (US)。
  - `target_los_multiplier` (float、default `1.0`) — JP = `1.0`、
    US = `0.35` (短い LOS)。
  - `diagnosis_code_system` (default `"ICD-10"`) — `"ICD-10"` (JP)
    / `"ICD-10-CM"` (US)。
  - `drug_code_system` (default `"YJ"`) — `"YJ"` (JP) /
    `"RxNorm"` (US)。
  - `lab_code_system` (default `"JLAC10"`) — `"JLAC10"` (JP) /
    `"LOINC"` (US)。
  - `procedure_code_system` (default `"K-code"`) — `"K-code"` (JP)
    / `"CPT"` (US)。
- 国 dispatch 表 (`loader.py`):
  `{"JP": "japan.yaml", "US": "us.yaml"}`。国追加時は YAML を追加、
  dict を拡張、必要なら上記文字列を分岐する下流モジュールも拡張する。
- 将来 field (comorbidity multiplier / 保険制度 / DPC/DRG /
  screening) の拡張参考資料は本モジュールの [`SPEC.md`](SPEC.md)
  に記載。現在の runtime `HealthcareSystemConfig` は意図的に v0.1
  最小 subset に留めている。

## ディレクトリ構造

```
clinosim/modules/healthcare_system/
  __init__.py                     空
  loader.py                       load_healthcare_config のみ
  SPEC.md                         拡張 (v1+) 設計参考 (runtime data ではない)
```

**`engine.py` / `enricher.py` / `audit.py` / `reference_data/` は
存在しない** — runtime surface は `loader.py` 全体。

## Enricher 配線

該当なし — 本モジュールは国 config loader であり enricher ではない。
`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS`
にも seed 未登録。simulator boot 経路が run あたり 1 回
`load_healthcare_config` を直接呼び、返却の `HealthcareSystemConfig`
が `SimulatorConfig` 経由で全下流モジュールに伝播する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`L17` 付近) | `load_healthcare_config` を import、起動時に国別 1 回 cache。以降 `SimulatorConfig` 経由で全モジュールに `HealthcareSystemConfig` が届く。 |
| `HealthcareSystemConfig` field consumers | [`clinosim/types/config.py`](../../types/config.py) | 下流モジュールが共有モデルから `discharge_criteria` や `*_code_system` 文字列、各種 multiplier を読み取る。検索: `grep -rn "hc_config\." clinosim/`。 |

## テスト

現時点で専用 test は無い。simulator を起動する任意の test
(例: `pytest tests/integration -q`) で loader が間接的にカバーされる。
coverage gap は follow-up として、JP → `japan.yaml`、US → `us.yaml`、
未知コード → `ValueError` を assert する小さな unit test 追加が低コスト
勝ち筋。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
