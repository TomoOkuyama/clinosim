# `clinosim.codes` — 臨床コードシステム

## 目的

clinosim における **臨床コードシステムの単一情報源** を提供します。

CIF (Clinosim Intermediate Format) はコードのみを保持し、表示テキス
トは出力時に本モジュールで解決します。これにより:

- 1 コード = 1 エントリ + 多言語表示属性 (英語 / 日本語 / …)
- FHIR / HL7 v2 / CDA / CSV 出力形式が同一の terminology 源を参照
- 翻訳ドリフトを構造的に防止
- 国際標準 (locale 非依存) と culture 依存データ (`clinosim/locale/`)
  の分離を担保

## スコープ

- **In scope**: clinosim が出力する全臨床コードシステムの統一 lookup、
  多言語表示解決、canonical FHIR system-URI マッピング
  (`_BUILTIN_URIS` に約 55 URI 登録)、curated コードデータ YAML、
  Encounter リソース向け HL7 v2/v3 語彙 StrEnum、再現性のために
  キャプチャした authoritative-source JSON 断片 (`authoritative/`)。
- **Out of scope**: locale-scoped データ (氏名 / 住所 / フォーマット
  規則 — `clinosim/locale/`)、疾患 / 観察 / 薬剤コンテンツ
  (`clinosim/modules/*/`)、CIF データスキーマ自体 (`clinosim/types/`)。

## 公開 API

```python
from clinosim.codes import (
    lookup,             # (system, code, lang="en") -> str
    get_display,        # (system, code, country="US") -> str
    get_system_uri,     # (system) -> str
    system_key_for,     # (kind, country) -> str  (例: ("diagnosis","JP")→"icd-10-mhlw")
    CodeSystem,         # dataclass: key / name / uri / version / codes
)
```

パッケージレベル未再エクスポートだが `clinosim.codes.loader` から
import 可能なローダー層ヘルパー:

```python
from clinosim.codes.loader import is_japanese_only_display_system
```

Encounter リソース向け HL7 語彙 StrEnum (Issue #562) —
`clinosim.codes.hl7_encounter` から import:

```python
from clinosim.codes.hl7_encounter import (
    AdmitSource,          # http://terminology.hl7.org/CodeSystem/admit-source
    DischargeDisposition, # http://terminology.hl7.org/CodeSystem/discharge-disposition
    ActPriority,          # http://terminology.hl7.org/CodeSystem/v3-ActPriority
)
```

`StrEnum` は `str` を継承するので、
`encounter.admit_source = AdmitSource.EMD` はリファクタ前の `str`
型と wire 互換 (`== "emd"` 比較も継続動作)。周産期の新生児 Patient
チェーン向けに `AdmitSource.BORN` (= `"born"`) を追加済 — 新生児の
Encounter が本値と `admit_source_encounter_id` (母親の分娩 Encounter を
指す) を保持し、FHIR 側では `Encounter.partOf` に emit されます。

## 決定性

該当なし — 本パッケージは純粋な lookup。`_load_system` は
`@lru_cache` 装飾済で、あるシステムキーは呼び出し毎に同一
`CodeSystem` インスタンスに解決。同一の YAML on-disk が与えられれば、
同じ `(system, code, lang)` 3 つ組は常に同じ文字列に解決します。

## 依存

- `pyyaml` — YAML ロード用。
- 標準ライブラリ `pathlib` / `functools` / `dataclasses` / `enum`。
- **他の `clinosim.*` パッケージへの依存なし。**

## 定数と設定

- **`_DATA_DIR`** = `Path(__file__).parent / "data"` — per-system
  YAML ファイル配置場所。
- **`_BUILTIN_URIS`** — clinosim が出力する全コードシステムの
  short-key → canonical URI マッピング (約 55: ICD variants / LOINC /
  SNOMED CT / RxNorm / JLAC10 / YJ / HOT7/9/13 / K-codes / JP-Core
  NamingSystem / HL7 v2/v3/FHIR terminology CodeSystem / JP-CLINS eCS
  Nocoded / gap-fill 用の clinosim-owned CodeSystem — URI ごとの
  根拠は `loader.py` のブロックレベルコメント参照)。
- **`_SYSTEM_DATA_ALIASES`** — Issue #350 メカニズム。同一コードデータ
  を共有するが distinct な canonical URI を必要とする 2 キー用
  (具体例: `icd-10-mhlw` は `icd-10` コードデータへ alias + JP
  MHLW-2013 registry URI)。
- **言語フォールバックチェーン** — 要求 lang → `en` → 最初に利用
  可能な言語 → コード自身。
- **コード lookup フォールバックチェーン** — 完全一致 → 基底コード
  (末尾サブコード除去) → サブコードプレフィックススキャン → コード
  自身。

## ディレクトリ構成

```
clinosim/codes/
  __init__.py                     公開 API (5 export)
  loader.py                       CodeSystem dataclass、lookup /
                                  get_display / get_system_uri /
                                  system_key_for、_BUILTIN_URIS、
                                  _SYSTEM_DATA_ALIASES
  hl7_encounter.py                AdmitSource / DischargeDisposition /
                                  ActPriority StrEnum
  data/                           curated コード YAML 32 件 (全リストは
                                  下の「対応コードシステム」参照)
  authoritative/                  再現性のためにキャプチャした
                                  authoritative-source JSON 断片
                                  (icd10_who_tx.json、loinc_2_82_tx.json、
                                  yj_tx_fragment.json、
                                  yj_tx_valid_codes.json + README)
```

## テスト

```bash
pytest tests/unit -k codes -q
```

`clinosim.codes` を参照するテストファイルは約 45。フォールバック
チェーン、システム URI 解決、`system_key_for` 国別 dispatch、
JP-only-display 検出、システム別データ形状不変条件を網羅。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。

---

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **英語がプライマリデータ** | 各コードは `en` フィールド必須。他言語は翻訳オプション。 |
| 2 | **権威ある情報源との整合** | コード値と英語表示は公式団体 (CMS / NLM / AMA / WHO / MHLW / MEDIS / JCCLS …) の最新リリースに追従。 |
| 3 | **locale 非依存** | コードシステムは国際標準。`clinosim/locale/` には culture 依存データのみ (氏名 / 住所 …)。 |
| 4 | **コードが真実** | CIF は `code` + `system` のみ保持。表示は導出 (出力時に検索)。 |
| 5 | **フォールバックチェーン** | 要求言語 → 英語 → コード自身 (必ず何かを返す)。 |
| 6 | **alias、duplicate しない** | 同一コードデータを共有し distinct canonical URI が必要な 2 システムは `_SYSTEM_DATA_ALIASES` で処理し YAML を duplicate しない。 |

## 対応コードシステム

### コア臨床レジストリ (curated data 付き)

| キー | 名称 | FHIR system URI | コード数 | 情報源 |
|---|---|---|---|---|
| `icd-10-cm` | ICD-10-CM | `http://hl7.org/fhir/sid/icd-10-cm` | 357 | CMS / NCHS |
| `icd-10` | WHO ICD-10 | `http://hl7.org/fhir/sid/icd-10` | 320 | WHO ICD-10 |
| `icd-10-mhlw` | JP MHLW ICD-10 (2013 registry) | `http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full` | (icd-10 に alias) | MHLW / JP-Core |
| `loinc` | LOINC | `http://loinc.org` | 153 | Regenstrief LOINC |
| `snomed-ct` | SNOMED CT | `http://snomed.info/sct` | 147 | IHTSDO |
| `jlac10` | JLAC10 | `urn:oid:1.2.392.200119.4.1005` | 45 | JCCLS |
| `rxnorm` | RxNorm | `http://www.nlm.nih.gov/research/umls/rxnorm` | 82 | NLM RxNorm |
| `yj` | YJ code | `http://capstandard.jp/iyaku.info/CodeSystem/YJ-code` | 59 | JP Core / capstandard |
| `hot7` | HOT7 (JP MEDIS) | `http://medis.or.jp/CodeSystem/master-HOT7` | 106 | MEDIS |
| `cpt` | CPT | `http://www.ama-assn.org/go/cpt` | 31 | AMA CPT |
| `k-codes` | K codes | `urn:oid:1.2.392.200119.4.401` | 25 | MHLW 診療報酬 |
| `cvx` | CVX (ワクチンコード) | `http://hl7.org/fhir/sid/cvx` | 10 | CDC |

### HL7 terminology CodeSystem (データ付き)

| キー | コード数 |
|---|---|
| `hl7-condition-clinical` / `hl7-condition-ver-status` | 6 + 6 |
| `hl7-admit-source` / `hl7-discharge-disposition` | 3 + 2 |
| `hl7-allergyintolerance-clinical` / `hl7-allergyintolerance-verification` | 3 + 4 |
| `hl7-observation-interpretation` | 3 |
| `hl7-practitioner-role` / `hl7-subscriber-relationship` | 6 + 7 |
| `hl7-v3-actreason` / `hl7-v3-administrativegender` / `hl7-v3-maritalstatus` | 4 + 3 + 6 |
| `hl7-endpoint-connection-type` / `hl7-endpoint-payload-type` | 1 + 1 |

### JP 固有 gap-fill および構造 CodeSystem

| キー | コード数 |
|---|---|
| `jp-care-level` | 8 |
| `jpfhir-doc-section` | 42 |
| `jpfhir-doc-typecodes` | 5 |
| `jpfhir-eCheckup-section` | 7 |
| `condition-short-name` | 42 |
| `clinosim-nursing-scores` | 1 |
| `bcp-47-language` | 2 |

### URI のみ登録 (YAML データなし)

`_BUILTIN_URIS` には、clinosim が参照するが文字列表示は不要な
システムの URI も登録されています — HOT9、HOT13、medication-nocoded、
UCUM、HL7 v2 / v3 / terminology 追加系 (v2-0092、v2-0131、v2-0203、
v2-0360、service-type、referencerange-meaning、organization-type、
condition-category、location-physical-type、RoleCode、
ParticipationType、ActCode、ObservationCategory、
DiagnosticServiceSection)、US Core documentreference-category。
解決は `get_system_uri()`、`lookup()` はコード自身にフォールバック。

## YAML スキーマ

```yaml
metadata:
  name: "ICD-10-CM"                              # 人間可読名
  uri: "http://hl7.org/fhir/sid/icd-10-cm"       # FHIR canonical URI
  version: "2024"                                # 版 / 年
  description: "International Classification..." # 説明

codes:
  N10:                                            # コード値 (文字列キー)
    en: "Acute tubulo-interstitial nephritis"   # 英語表示 (必須)
    ja: "急性腎盂腎炎"                          # 日本語表示 (オプション)
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
```

### スキーマ規則

- `metadata.uri` 欠如時はローダーが `_BUILTIN_URIS[key]` にフォール
  バック。
- `codes` 配下の各エントリは最低 `en` を含める必要あり (JP-only
  display system — `is_japanese_only_display_system` — の場合は
  `ja`)。
- 追加言語は ISO 639-1 の 2 文字コード (`ja` / `de` / `fr` / `zh` …)。
- コード値は文字列で情報源のフォーマットを維持: ICD は `J18.9`、
  LOINC は `1988-5`、RxNorm は `309090`。

## 例: FHIR Observation 出力

```python
from clinosim.codes import get_system_uri, lookup

lab_result = {"code": "1988-5", "value": 38.2, "unit": "mg/L"}

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
    "valueQuantity": {"value": lab_result["value"], "unit": lab_result["unit"]},
}
```

## Extending

### コード追加

該当 `data/<system>.yaml` を編集 (ローダーは dict key で検索するので
順序は自由。可読性のためアルファベット順推奨):

```yaml
codes:
  J45.901:
    en: "Unspecified asthma with (acute) exacerbation"
    ja: "喘息急性増悪"
```

### 新規コードシステム追加

1. `data/<new-system>.yaml` を作成 (上記スキーマ)。
2. 任意で short key → URI マッピングを `loader.py::_BUILTIN_URIS`
   に登録。
3. ファイルを配置するだけでローダーが自動検出
   (`@lru_cache(maxsize=32)`)。

### 新規言語追加

各エントリに新言語キーを追加:

```yaml
codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"
    ja: "急性腎盂腎炎"
    de: "Akute tubulointerstitielle Nephritis"
```

要求言語を持たないコードは「定数と設定」記載の lookup フォール
バックチェーン経由で英語にフォールバック。

## `locale` モジュールとの境界

| | `clinosim.codes` | `clinosim.locale` |
|---|---|---|
| **責務** | 国際コードシステム + 多言語表示 | culture / 国依存データ |
| **locale scoped?** | いいえ (全言語 1 ファイル) | はい (`jp/` / `us/` …) |
| **典型データ** | ICD / LOINC / RxNorm / SNOMED CT / HL7 語彙 … | 氏名、住所、電話フォーマット、reference range |
| **CIF が保持** | コード値 + system key | 具体的フィールド (Address / PersonName …) |

`locale/<country>/code_mapping_*.yaml` も引き続き存在します — シミュ
レータ内部のテスト名 (例: `"WBC"`) を標準コード (例: `"6690-2"`) に
マップ。表示テキスト解決は `clinosim.codes` に委譲。

## ライセンスと出典

各コードシステムは自身の上流ライセンスに従います:

- **ICD-10-CM**: パブリックドメイン (CMS)。
- **WHO ICD-10**: WHO 使用条件。
- **LOINC**: LOINC License (商用利用無料、再配布可)。
- **RxNorm**: NLM Open Use (パブリックドメイン)。
- **SNOMED CT**: SNOMED International 条件。clinosim は生成データ
  に出現する小規模 curated subset のみを同梱。
- **JLAC10**: JCCLS 発行。
- **CPT**: AMA copyright — clinosim は教育・研究用の最小 subset のみ
  同梱。
- **YJ code**: MHLW open data。
- **K codes**: MHLW 診療報酬体系。
- **HL7 terminology (v2 / v3 / condition-clinical / …)**: HL7 IPR
  policy — HL7 terminology CodeSystem は CC BY-SA 4.0。
- **JP Core / JP-CLINS eCS**: MHLW / JAMI 公開資料。

`codes/data/` は clinosim の合成データ生成を駆動するのに必要な subset
のみを抽出。商用 EHR 統合には、上流当局から最新版フルセットを取得
してください。

**subset は「出力に現れうるコード」を網羅する必要があります。**
診断コードについては
`tests/unit/test_diagnosis_code_coverage.py` が「全疾患 / エンカウン
ターの `icd_codes` エントリと診断マップの全ターゲットがコードデータ
に対して完全一致で解決すること」の不変条件を守ります。新規外来 /
疾患シナリオ追加時は、参照される ICD コードをここに追加することが
必須 (AGENTS.md「Diagnosis code coverage」参照)。さもなくば FHIR
Condition display が近似 prefix マッチにフォールバック。

`authoritative/` は tx.fhir.org と MHLW registry から特定時点で取得
した raw JSON 断片 — curated subset のバイト完全な出典であり、
回帰テストの diff 対象。

## 更新ポリシー

- **ICD-10-CM**: CMS が毎年 10 月 1 日に新版リリース → clinosim
  追従。
- **LOINC**: 半年ごと (6 月 / 12 月) → 大幅変更を取り込み。
- **SNOMED CT**: 国際リリース月次 → 年 1 回安定版を追従。
- **RxNorm**: 週次更新 (毎週月曜) → 年 1 回安定版を追従。
- **WHO ICD-10**: 更新まれ (現行 2019)。
- **JP Core / JP-CLINS eCS**: `.github/jp-validator-pins.env` の
  JP Core `1.1.7` と、
  `.github/workflows/jp-clins-lab-compliance-gate.yml` が assert する
  JP-CLINS package version (現在 `1.13.0`) に追従。v1.12.0 → v1.13.0
  差分は additive terminology のみ (hepatitis serology + labo split の
  9 新規 ValueSet)、clinosim が emit する StructureDefinition canonical
  URL に変更なし。
- 内部 short key は安定。YAML 構造変更は major version bump。
