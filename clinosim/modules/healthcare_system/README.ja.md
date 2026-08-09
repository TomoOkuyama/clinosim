# clinosim.modules.healthcare_system — 国別医療制度コンフィグ

## 目的

clinosim の **国別パラメータの単一情報源**。 シミュレータ全体が参照する国固有の設定 (臨床プラクティスのクセ、 使用するコード体系、 在院日数の傾向、 検査頻度等) を YAML から読み込み、 型付き `HealthcareSystemConfig` として提供する。

各モジュールは本モジュール経由で `country` に応じた振る舞いを切り替える:

- disease / encounter: `target_los_multiplier` で在院日数を日本↔米国で調整
- order / observation: `lab_frequency_multiplier` で採血頻度を調整
- output (FHIR/CSV): `diagnosis_code_system`, `drug_code_system`, `lab_code_system`, `procedure_code_system` に従ったコード体系選択
- physiology / clinical_course: `discharge_criteria` で退院判定ロジック切替 (lab 正常化 vs 機能回復)

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Leaf module** | 他の clinosim モジュールに依存しない (types 除く) |
| 2 | **Pydantic 型安全** | YAML load 時に `HealthcareSystemConfig` で検証 |
| 3 | **国コードは ISO 準拠** | `"JP"` / `"US"` (将来 `"KR"`, `"DE"` 等拡張可) |
| 4 | **Defaults 付き** | 新しいフィールド追加時、 既存 YAML を壊さない |
| 5 | **コード体系の参照先** | `diagnosis_code_system` 等は文字列で `clinosim.codes` の短縮キーに対応 |

## API リファレンス

### `load_healthcare_config(country: str) -> HealthcareSystemConfig`

国コードから対応する YAML を読み込み、 Pydantic model にパースして返す。

```python
from clinosim.modules.healthcare_system.loader import load_healthcare_config

config_jp = load_healthcare_config("JP")
print(config_jp.target_los_multiplier)   # 1.0  (長めの在院)
print(config_jp.lab_frequency_multiplier) # 1.3 (採血多め)
print(config_jp.diagnosis_code_system)    # "ICD-10"

config_us = load_healthcare_config("US")
print(config_us.target_los_multiplier)   # 0.35 (短い在院)
print(config_us.discharge_criteria)      # "functional_recovery"
print(config_us.diagnosis_code_system)   # "ICD-10-CM"
```

**エラー**:

- サポート外の country コード: `ValueError("Unsupported country: XX. Supported: ['JP', 'US']")`
- YAML ファイル欠落: `FileNotFoundError`
- YAML スキーマ違反: Pydantic `ValidationError`

**国 → ファイル対応表**:

```python
country_map = {"JP": "japan.yaml", "US": "us.yaml"}
```

ファイルは `clinosim/config/` 以下に配置。

## データ構造

### `HealthcareSystemConfig` (clinosim.types.config)

```python
class HealthcareSystemConfig(BaseModel):
    """Country-specific configuration. Loaded from clinosim/config/{country}.yaml."""

    country: str  # "JP" | "US"

    # Clinical practice
    lab_frequency_multiplier: float = 1.0   # 採血頻度倍率 (基準 US=1.0)
    discharge_criteria: str = "lab_normalization"
                                            # "lab_normalization" | "functional_recovery"
    target_los_multiplier: float = 1.0      # 目標在院日数倍率

    # Coding systems (clinosim.codes の短縮キーと対応)
    diagnosis_code_system: str = "ICD-10"   # "ICD-10" | "ICD-10-CM"
    drug_code_system: str = "YJ"            # "YJ" | "RxNorm"
    lab_code_system: str = "JLAC10"         # "JLAC10" | "LOINC"
    procedure_code_system: str = "K-code"   # "K-code" | "CPT"
```

## 国別設定ファイル

### `clinosim/config/japan.yaml`

```yaml
country: "JP"

# Clinical practice
lab_frequency_multiplier: 1.3      # 日本は採血頻度が多め
discharge_criteria: "lab_normalization"  # 検査値正常化まで入院継続
target_los_multiplier: 1.0         # 基準 (例: 肺炎 14 日)

# Coding systems
diagnosis_code_system: "ICD-10"    # 日本は WHO ICD-10 ベース
drug_code_system: "YJ"             # 薬価基準 YJ コード
lab_code_system: "JLAC10"          # JCCLS 臨床検査標準
procedure_code_system: "K-code"    # 診療報酬点数表 K コード
```

### `clinosim/config/us.yaml`

```yaml
country: "US"

# Clinical practice
lab_frequency_multiplier: 0.8      # 米国は採血頻度が少なめ
discharge_criteria: "functional_recovery"  # 機能回復が判断基準 (lab より早い)
target_los_multiplier: 0.35        # 短い在院 (例: 肺炎 4-5 日)

# Coding systems
diagnosis_code_system: "ICD-10-CM" # 米国 CM バリアント
drug_code_system: "RxNorm"         # NLM RxNorm
lab_code_system: "LOINC"           # LOINC
procedure_code_system: "CPT"       # AMA CPT
```

## 使用例: シミュレーション開始時の初期化

```python
from clinosim.modules.healthcare_system.loader import load_healthcare_config

# At simulation startup
country = "JP"
hc_config = load_healthcare_config(country)

# Encounter module uses target_los_multiplier
target_los = base_los * hc_config.target_los_multiplier

# Order module uses lab_frequency_multiplier
lab_order_count = base_count * hc_config.lab_frequency_multiplier

# Discharge logic branches on discharge_criteria
if hc_config.discharge_criteria == "lab_normalization":
    ready = (crp < 10.0 and wbc < 10_000)
elif hc_config.discharge_criteria == "functional_recovery":
    ready = (can_ambulate and oral_intake_ok and afebrile_24h)

# Output module selects coding systems
from clinosim.codes import get_system_uri
diagnosis_uri = get_system_uri(
    "icd-10-cm" if hc_config.diagnosis_code_system == "ICD-10-CM" else "icd-10"
)
```

## 新しい国を追加する

1. `clinosim/config/<country>.yaml` を作成 (上記スキーマに従う):
   ```yaml
   country: "KR"
   lab_frequency_multiplier: 1.2
   discharge_criteria: "lab_normalization"
   target_los_multiplier: 0.9
   diagnosis_code_system: "KCD-8"   # 韓国標準疾病分類
   drug_code_system: "EDI"          # 韓国保険薬価コード
   lab_code_system: "EDI-LAB"
   procedure_code_system: "EDI-PROC"
   ```
2. `loader.py` の `country_map` に `"KR": "korea.yaml"` を追加
3. 必要なら `clinosim.codes` に新コード体系の YAML データを追加
4. 関連モジュール (population, locale) でも対応国を拡張

## 依存関係

- `clinosim.types.config` — `HealthcareSystemConfig` (Pydantic model)
- `pyyaml` — YAML パース
- **他の clinosim モジュールへの依存なし** — leaf module

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/engine.py` | 起動時 1 回 `load_healthcare_system_config()` をロード | infrastructure (起動時のみ) |
| `encounter`, `order`, `observation`, `output` モジュール (cross-ref) | シミュレーション全体で参照 (lab freq / dept names 等) | medium |

## テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_healthcare_system.py -v
```

カバー範囲: JP/US 両方の YAML ロード、 未サポート国の例外、 デフォルト値の適用。

## 今後の拡張

現在の `HealthcareSystemConfig` は v0.1 の最小限。 将来的には以下のフィールド追加が計画されている (TODO.md 参照):

- 健康保険制度 (single-payer / multi-payer / uninsured ratio)
- 診療報酬体系 (DPC / DRG / Fee-for-service)
- スクリーニングプログラム (対象年齢・頻度)
- 処方慣行 (ジェネリック比率、 後発品優先度)
- 看護体制 (1:7 / 1:10 / 1:4 等の日本固有の病棟区分)
- 紹介制度 (primary care ゲートキーパー vs 自由受診)

## healthcare_system vs locale の境界

| データ | 管理場所 | 理由 |
|---|---|---|
| 年齢分布、疾患 incidence、occupation | `locale/<country>/demographics.yaml` | 人口動態データ |
| 姓名、住所パターン | `locale/<country>/names.yaml`, `addresses.yaml` | 文化データ |
| 検査基準範囲 (JCCLS等) | `locale/<country>/reference_range_lab.yaml` | 臨床検査基準 |
| 薬品コード (RxNorm/YJ) | `locale/<country>/code_mapping_drug.yaml` | コードマッピング |
| 常用薬 (慢性疾患別) | `locale/shared/chronic_medications.yaml` | 国共通 + `drug_ja` |
| JP 薬品名辞書 | `locale/shared/drug_names_ja.yaml` | FHIR 出力用翻訳 |
| ICD/LOINC/SNOMED コード | `codes/data/*.yaml` | 国際コード体系（locale ではない） |
| 病院構成 (ベッド数、科) | `config/hospital_*.yaml` | 施設設定 |
| 医療制度 (保険、処方慣行) | `healthcare_system/*.yaml` | 制度レベル設定 |

**原則**: 「人や文化に紐づくデータ」→ locale、「制度や政策に紐づくデータ」→ healthcare_system、「国際標準コード」→ codes

## 修正ガイド

### 新しい国を追加する

1. `clinosim/locale/<country>/` ディレクトリ作成:
   - `demographics.yaml` — 年齢分布、疾患 incidence、occupation_distribution
   - `names.yaml` — 姓名 (weighted sampling)
   - `addresses.yaml` — 住所パターン
   - `reference_range_lab.yaml` — 検査基準範囲
   - `code_mapping_lab.yaml`, `code_mapping_drug.yaml`
2. `clinosim/locale/loader.py` の `_COUNTRY_DIR_MAP` に追加
3. `clinosim/config/hospital_operations.yaml` の `recommended_population` に国追加
4. `codes/data/*.yaml` に必要な ICD/LOINC/drug コードの多言語エントリ追加
5. `llm_service/prompts/<lang>/` にナラティブプロンプト追加
6. コード変更: population engine, patient activator は原則コード変更不要（YAML駆動）
