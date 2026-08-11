# clinosim.codes — Clinical Code Systems Module

## 目的

clinosim における **臨床コード体系の単一情報源 (Single Source of Truth)** を提供する。

CIF (Clinosim Intermediate Format) はコードのみを保持し、 表示用テキスト (display) は出力時に本モジュール経由で取得する。 これにより:

- 1コード = 1エントリ + 多言語表示属性 (英語、日本語、他)
- FHIR / HL7 v2 / CDA / CSV など複数の出力形式が同じ用語ソースを参照
- 翻訳の不一致を構造的に防止
- 国際標準 (locale 非依存) と locale 固有データ (`clinosim/locale/`) の責務分離

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **英語は一次データ** | 全コードに `en` フィールド必須。日本語等は翻訳オプション |
| 2 | **権威ソースに準拠** | コード値・英語表記は公式機関 (CMS, NLM, AMA, WHO 等) の最新版に従う |
| 3 | **Locale 非依存** | コード体系は国際標準。`clinosim/locale/` には人名・住所等の文化依存データのみ |
| 4 | **Code is the truth** | CIF は コード + system のみ保持。display は派生 (出力時 lookup) |
| 5 | **Fallback chain** | 要求言語 → 英語 → コード自体 (常に何か返す) |

## ディレクトリ構造

```
clinosim/codes/
├── __init__.py            # public API (lookup, get_system_uri, get_display)
├── loader.py              # YAML ローダー + lookup 関数
├── README.md              # 本ドキュメント
└── data/
    ├── icd-10-cm.yaml     # ICD-10-CM (US 診断)
    ├── icd-10.yaml        # WHO ICD-10 (JP 診断)
    ├── loinc.yaml         # LOINC (検査・バイタル)
    ├── jlac10.yaml        # JLAC10 (JP 検査)
    ├── rxnorm.yaml        # RxNorm (US 医薬品)
    ├── yj.yaml            # YJ コード (JP 医薬品)
    ├── cpt.yaml           # CPT (US 手技)
    └── k-codes.yaml       # K コード (JP 診療報酬手技)
```

## サポートしているコード体系と権威ソース

| Key | 名称 | FHIR System URI | 権威ソース | 用途 |
|---|---|---|---|---|
| `icd-10-cm` | ICD-10-CM | `http://hl7.org/fhir/sid/icd-10-cm` | [CMS / NCHS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) | US 診断・問題リスト |
| `icd-10` | WHO ICD-10 | `http://hl7.org/fhir/sid/icd-10` | [WHO ICD-10](https://icd.who.int/browse10/) | WHO 国際版・JP 診断 |
| `loinc` | LOINC | `http://loinc.org` | [Regenstrief LOINC](https://loinc.org/) | 検査・バイタル・観察 |
| `jlac10` | JLAC10 | `urn:oid:1.2.392.200119.4.1005` | [日本臨床検査標準協議会 JCCLS](https://www.jccls.org/) | JP 臨床検査コード |
| `rxnorm` | RxNorm | `http://www.nlm.nih.gov/research/umls/rxnorm` | [NLM RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/) | US 医薬品 (一般名 / ブランド名) |
| `yj` | YJ コード | `urn:oid:1.2.392.100495.20.2.74` | [医薬品 YJ コード (薬価基準)](https://www.mhlw.go.jp/topics/2018/04/dl/yakkasanteibasis.pdf) | JP 医薬品 |
| `cpt` | CPT | `http://www.ama-assn.org/go/cpt` | [AMA CPT](https://www.ama-assn.org/practice-management/cpt) | US 診療手技 |
| `k-codes` | K コード | `urn:oid:1.2.392.200119.4.401` | [診療報酬点数表 (厚生労働省)](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000188411.html) | JP 診療報酬手技 |

加えて、loader にビルトイン定義された参照可能な system URI:

| Key | URI | 用途 |
|---|---|---|
| `snomed-ct` | `http://snomed.info/sct` | SNOMED CT 臨床所見 (将来拡張) |
| `ucum` | `http://unitsofmeasure.org` | 単位 |
| `hl7-v3-actcode` | `http://terminology.hl7.org/CodeSystem/v3-ActCode` | HL7 v3 行為コード |
| `hl7-v3-maritalstatus` | `http://terminology.hl7.org/CodeSystem/v3-MaritalStatus` | 婚姻状態 |

## YAML スキーマ

```yaml
metadata:
  name: "ICD-10-CM"                              # 人間可読名
  uri: "http://hl7.org/fhir/sid/icd-10-cm"       # FHIR canonical URI
  version: "2024"                                # 版・年度
  description: "International Classification..." # 説明

codes:
  N10:                                            # コード値 (string key)
    en: "Acute tubulo-interstitial nephritis"   # 英語表示 (必須)
    ja: "急性腎盂腎炎"                          # 日本語表示 (オプション)
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
  # ...
```

### スキーマ規則

- `metadata.uri` が無い場合、loader はキーから推測 (icd-10-cm → CMS URI 等)
- `codes` の各エントリは少なくとも `en` を持つこと
- 追加言語は ISO 639-1 二文字コード (`ja`, `de`, `fr`, `zh` 等)
- コード値は文字列。 ICD では `J18.9`, LOINC では `1988-5`, RxNorm では `309090` のように元の表記を維持

## API リファレンス

### `lookup(system: str, code: str, lang: str = "en") -> str`

コードに対応する display text を指定言語で取得する。

**Resolution order**:

1. 完全一致 (例: `J18.9`)
2. ベースコード (例: `J18.9` → `J18`)
3. サブコード前方一致 (例: `I63` → `I63.9`)
4. コード自体 (フォールバック)

**言語フォールバック**: 要求 lang → `en` → 最初に見つかった言語 → コード自体

```python
from clinosim.codes import lookup

lookup("icd-10-cm", "N10", "en")
# → "Acute tubulo-interstitial nephritis"

lookup("icd-10-cm", "N10", "ja")
# → "急性腎盂腎炎"

lookup("icd-10-cm", "I63", "en")  # base code
# → "Cerebral infarction, unspecified"  (sub-code から解決)

lookup("icd-10-cm", "X99.99", "ja")  # 存在しない
# → "X99.99"  (fallback to code itself)
```

### `get_display(system: str, code: str, country: str = "US") -> str`

国コードから言語を自動選択するヘルパー (`US` → `en`, `JP` → `ja`)。

```python
from clinosim.codes import get_display

get_display("icd-10-cm", "N10", "JP")
# → "急性腎盂腎炎"
```

### `get_system_uri(system: str) -> str`

短縮キーから FHIR canonical system URI を取得。

```python
from clinosim.codes import get_system_uri

get_system_uri("icd-10-cm")
# → "http://hl7.org/fhir/sid/icd-10-cm"

get_system_uri("loinc")
# → "http://loinc.org"
```

### `CodeSystem` (dataclass)

```python
@dataclass
class CodeSystem:
    key: str                              # 短縮キー (e.g., "icd-10-cm")
    name: str                             # 人間可読名
    uri: str                              # FHIR system URI
    version: str                          # 版
    codes: dict[str, dict[str, str]]      # code → {lang: display}
```

## 使用例: FHIR Observation 出力

```python
from clinosim.codes import get_system_uri, lookup

# CIF データ (codes only)
lab_result = {
    "code": "1988-5",       # LOINC: CRP
    "value": 38.2,
    "unit": "mg/L",
}

# FHIR Observation 構築
obs = {
    "resourceType": "Observation",
    "code": {
        "coding": [{
            "system": get_system_uri("loinc"),
            "code": lab_result["code"],
            "display": lookup("loinc", lab_result["code"], "en"),
        }],
        "text": lookup("loinc", lab_result["code"], "en"),
    },
    "valueQuantity": {
        "value": lab_result["value"],
        "unit": lab_result["unit"],
    },
}
```

JP locale なら同じデータから日本語表示を取得:

```python
display_ja = lookup("loinc", "1988-5", "ja")
# → "C反応性蛋白"
```

## CIF データモデルとの関係

CIF (`clinosim/types/`) は **コードと system キーのみ** を保持する:

```python
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str = ""              # 例: "N10"
    admission_diagnosis_system: str = "icd-10-cm"   # コード体系キー
    discharge_diagnosis_code: str = ""
    discharge_diagnosis_system: str = "icd-10-cm"
    # display text は保持しない (出力時 lookup)


@dataclass
class ChronicCondition:
    code: str = ""
    system: str = "icd-10-cm"
```

FHIR R4 アダプタ (`clinosim/modules/output/fhir_r4_adapter.py`) は出力時に:

```python
display = code_lookup(
    record["clinical_diagnosis"]["discharge_diagnosis_system"],
    record["clinical_diagnosis"]["discharge_diagnosis_code"],
    lang="en" if country == "US" else "ja",
)
```

## 拡張方法

### 新しいコードを追加する

該当する `data/<system>.yaml` を編集:

```yaml
codes:
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
  # 既存エントリ...
  J45.901:                              # 新規追加
    en: "Unspecified asthma with (acute) exacerbation"
    ja: "喘息急性増悪"
```

エントリのソート順は任意 (loader はキーで dict 検索)。 可読性のためアルファベット順を推奨。

### 新しいコード体系を追加する

1. `data/<new-system>.yaml` を作成 (上記スキーマに従う)
2. `loader.py` の `_BUILTIN_URIS` に短縮キー → URI を追加 (オプション)
3. ファイルを置くだけで自動的に loader が検出 (`@lru_cache(maxsize=32)`)

### 新しい言語を追加する

各 `codes` エントリに新しい言語キーを追加:

```yaml
codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"
    ja: "急性腎盂腎炎"
    de: "Akute tubulointerstitielle Nephritis"   # 新規追加
```

呼び出し側:

```python
lookup("icd-10-cm", "N10", "de")
# → "Akute tubulointerstitielle Nephritis"
```

ある言語が無いコードは英語にフォールバック:

```python
lookup("icd-10-cm", "Z99.2", "de")
# → "Dependence on renal dialysis"  (de 未定義 → en fallback)
```

## カバレッジ

|Code system | Codes | Languages | Coverage focus |
|---|---|---|---|
| icd-10-cm | 234 | en, ja | clinosim で生成される全疾患 + よく使う Z-codes / ED 症状 |
| icd-10 | 133 | en, ja | WHO ICD-10 ベースコード (JP 互換) |
| loinc | 65 | en, ja | バイタル + 主要血液生化学 + 凝固 + 心臓マーカー |
| jlac10 | 30 | en, ja | JP 検査標準コード (JCCLS 共用基準範囲対応) |
| rxnorm | 68 | en, ja | 抗菌薬・抗凝固・循環器・救急薬等 |
| yj | 39 | en, ja | JP 医薬品 (主要処方薬) |
| cpt | 31 | en, ja | 主要外科手技 + ベッドサイド処置 + 画像 |
| k-codes | 25 | en, ja | JP 診療報酬手技 (K コード) |
| snomed-ct | 31 | en, ja | 手技構造化フィールド (category, performer role, body site, outcome, complication) |

合計: **656 codes** (執筆時点)

## locale モジュールとの境界

| | `clinosim.codes` | `clinosim.locale` |
|---|---|---|
| **責務** | 国際標準コード体系 + 多言語表示 | 文化・国依存のデータ |
| **Locale-scoped?** | No (1ファイルに全言語) | Yes (`jp/`, `us/` 等) |
| **典型データ** | ICD/LOINC/RxNorm 等 | 人名、住所、電話フォーマット、基準範囲 |
| **CIF が直接持つ** | コード値 + system キー | 個々のフィールド (Address、PersonName 等) |

`locale/<country>/code_mapping_*.yaml` は引き続き存在し、 シミュレータ内部の test name (例: `"WBC"`) → 標準コード (`"6690-2"`) のマッピングを担う。 表示テキストの解決は本モジュールへ委譲。

## ライセンスと出典

各コード体系は元の権威ソースのライセンスに従う:

- **ICD-10-CM**: パブリックドメイン (CMS)
- **WHO ICD-10**: WHO の利用規約に従う
- **LOINC**: LOINC License (商用利用無料、再配布可)
- **RxNorm**: NLM Open Use (パブリックドメイン)
- **JLAC10**: JCCLS が公開
- **CPT**: AMA Copyright (clinosim では教育・研究目的の最小サブセットのみ収載)
- **YJ コード**: 厚生労働省 公開データ
- **K コード**: 厚生労働省 診療報酬点数表

clinosim の codes/data/ には各レジストリから clinosim の合成データ生成に必要なサブセットのみを抽出して収載している。 商用 EHR に組み込む場合は元の権威ソースから完全な最新版を取得することを推奨。

**サブセットは「出力されうるコード」を漏れなく覆うこと。** 診断コードについては
`tests/unit/test_diagnosis_code_coverage.py` が「全 disease/encounter の `icd_codes` と
診断マップのターゲットが code-data に exact 解決する」不変条件を回帰ガードする。新しい
外来/疾患シナリオを追加する際は、参照する ICD コードの収載も必須(CLAUDE.md「Diagnosis
code coverage」参照)。未収載だと FHIR Condition の display が近似 prefix fallback になる。

## 更新ポリシー

- ICD-10-CM: 毎年 10 月 1 日に CMS が新版発表 → clinosim も追従
- LOINC: 半年毎 (6月・12月) → 主要変更を反映
- RxNorm: 毎週月曜更新 → 安定版を年1回程度反映
- WHO ICD-10: 滅多に更新されない (現行版は 2019)
- 内部キー (短縮名) は安定。yaml 構造変更時はメジャーバージョン更新
