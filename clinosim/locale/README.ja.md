# `clinosim.locale` — locale 固有設定バンドル

## 目的

シミュレータの他部分が消費する国別データバンドルを同梱します: 氏名
プール、住所形式、人口動態分布、フォーマット規則、国別コードマッピ
ング表 (診断 / 薬剤 / 検査 / 手技)、reference range、予防接種スケジ
ュール、identity 慣習。

同梱 locale は 2 つ:

- **US** (`us/`) — 英語氏名、US 住所形式、RxNorm / LOINC / ICD-10-CM
  コードマッピング、US 固有 reference range と人口動態。
- **JP** (`jp/`) — 日本語氏名 + カナ、JP 住所形式 (都道府県 / 市区
  町村 / 番地)、YJ / JLAC10 / HOT / ICD-10-JP コードマッピング、
  日本 identity 慣習 (マイナンバー)、microbiology / susceptibility
  マッピング。

国際コードレジストリ (ICD / LOINC / RxNorm …) 自体は
[`clinosim.codes`](../codes/README.ja.md) に移行済で、ここには存在
しません。

## スコープ

- **In scope**: 氏名プール、住所テンプレート、人口動態分布、国別
  コードマッピング表 (薬剤 / 検査 / 手技 / 診断 / microbiology)、
  reference range、予防接種スケジュール、フォーマット規則、
  疾患 / 観察 / 薬剤 module が消費する identity 形式 YAML。
- **Out of scope**: 国際コードレジストリ本体 (`clinosim/codes/`)、
  locale データを消費するモジュール (`clinosim/modules/*/`)、トップ
  レベル国別設定 YAML (`clinosim/config/{us,japan}.yaml`)。

## 公開 API

`clinosim/locale/__init__.py` は **意図的に空** — 呼び出し側は
loader ヘルパーを直接 import します:

```python
from clinosim.locale.loader import (
    load_names,                     # (country) -> dict[str, Any]
    load_addresses,                 # (country) -> dict[str, Any]
    load_demographics,              # (country) -> dict[str, Any]
    load_formatting,                # (country) -> dict[str, Any]
    load_reference_ranges,          # (country) -> dict[str, Any]
    load_identity_config,           # (country) -> dict[str, Any]
    load_naming_rules,              # (country) -> dict[str, Any]
    load_terminology,               # (domain, country) -> dict[str, str] (legacy、下記参照)
    load_code_mapping,              # (domain, country) -> dict[str, str]
    load_chronic_medications,       # () -> dict[str, Any] (shared)
    load_chronic_followup,          # () -> dict[str, Any] (shared)
    load_med_terms,                 # () -> 多言語カタログ (shared med_terms.yaml)
    load_med_terms_ja,              # () -> dict[str, dict[str, str]] (deprecated alias)
    load_narrative_display_dict,             # () -> dict[str, str] (shared)
    load_department_display,        # () -> dict[str, dict[str, str]] (shared)
)
from clinosim.locale.text import (
    resolve_text,                   # (value, language, country) -> str
)
```

上記はよく使う部分集合: `clinosim.locale.loader` は 46 個の `load_*`
関数を再 export しており、実装は `clinosim/locale/loaders/`
(`clinical.py` / `demographics.py` / `fhir_identity.py` /
`medical_display.py` / `narrative.py`) にある。

`load_terminology` は legacy: `<country>/terminology_<domain>.yaml` を
読むが、該当ファイルはもう同梱されていないので `{}` を返す。表示名は
`clinosim/codes/` に移った。`load_med_terms_ja` は `load_med_terms` の
`ja` のみ view (deprecated)。`load_code_mapping("drug", country)` は
`<country>/code_mapping_drug.yaml` と薬剤 identity カタログ
`clinosim/codes/data/drugs.yaml` を union する (キー衝突時は yaml 優先)。

## 決定性

該当なし — 本パッケージはデータローダー層です。全ローダーは
`@lru_cache` で装飾済 (キャッシュキー: country 文字列で有界) なので、
繰り返し呼び出しは同一 `dict` インスタンスを返します。YAML 解析は
`yaml.safe_load` によりバイト入力 → dict 出力が決定的。

## 依存

- `pyyaml` — YAML ロード用。
- 標準ライブラリ `pathlib` / `functools` / `typing`。
- **import 時に他の `clinosim.*` パッケージへの依存なし**。2 つの
  ローダーが関数内で遅延 import する: `clinosim.codes.drugs` (薬剤
  カタログ union) と `clinosim.modules.output.fhir_r4.lib.reference_data`
  (`chronic_medications.yaml` の route 語彙検証)。consumer 側が返却
  dict を自身の型に渡します。

## 定数と設定

- **`_LOCALE_DIR`** = `Path(__file__).parent` (`_io.py` 内) — import
  時の locale バンドルルート。
- **`_COUNTRY_DIR_MAP`** = `{"JP": "jp", "US": "us"}` — 国 ISO
  コード → ディレクトリ名マッピング。未マップコードは
  `country.lower()` にフォールスルー。
- **P2-14 セーフガード** — `_country_dir` は解決後のディレクトリ名
  が `_` で始まるものを全て拒否します。これにより `_template/`
  (新規 locale scaffold) が実 country として使用不可能になります —
  `country="_template"` は `ValueError` を投げます。新規国追加時に
  先頭アンダースコアは使用禁止。
- **`@lru_cache`** — 全ローダーを memoize。キャッシュキーは
  (country, [domain]) タプルなので run 中キャッシュサイズは有界。
- **`resolve_text`** 慣習: 文字列値はそのまま返却、`{lang: string}`
  dict は要求言語を返却し英語にフォールバック。これはモジュールが
  ファイル重複なしで YAML レコードを両 locale で人間可読に保つ
  メカニズムです。

## ディレクトリ構成

```
clinosim/locale/
  __init__.py                     (意図的に空 — .loader / .text から
                                   直接 import)
  loader.py                       再 export facade (公開 load_* 関数 46)
  _io.py                          共有 YAML プリミティブ (_LOCALE_DIR /
                                   _COUNTRY_DIR_MAP / _country_dir /
                                   _load_yaml / fallback 既定値)
  loaders/                        トピック別 @lru_cache YAML ローダー:
                                   clinical / demographics / fhir_identity
                                   / medical_display / narrative
  text.py                         resolve_text (多言語テキスト解決
                                   ヘルパー)
  i18n.py                         共有 phrase カタログに対する
                                   t(key, lang, **params) 翻訳器
  us/                             US 固有バンドル (15 YAML):
                                   addresses / ambulatory_visit_length /
                                   ckd_under60_prevalence /
                                   code_mapping_{diagnosis,drug,lab,procedure}
                                   / code_status_rates / demographics /
                                   family_history_prevalence / formatting
                                   / identity / immunization_schedule /
                                   names / reference_range_lab
  jp/                             JP 固有バンドル (20 YAML — US 集合から
                                   ckd_under60_prevalence を除き、
                                   care_level_rates /
                                   code_mapping_microbiology /
                                   code_mapping_microbiology_susceptibility
                                   / external_organizations /
                                   patient_instructions_ja /
                                   practitioner_qualifications を追加)
  shared/                         locale 間共有データ (37 YAML)。例:
                                   actuarial_life_table / chemo_regimens
                                   (化学療法 regimen ライブラリ) /
                                   chronic_followup / chronic_medications
                                   / chronic_onset_min_age /
                                   condition_mortality_smr /
                                   country_language / department_display
                                   / encounter_disposition_defaults /
                                   fallback_defaults /
                                   icd10_sex_restrictions /
                                   iv_infusion_defaults / med_terms /
                                   naming_rules / narrative_* (10 ファイル)
                                   / perinatal / specialty_routing
  shared/longitudinal/            縦断属性カタログ (64 YAML。同ディレク
                                   トリの README 参照)
  _template/                      新規 locale scaffolding — README +
                                   必要 YAML の stub。先頭アンダー
                                   スコアガードにより country として
                                   解決不可。
```

## Extending — 新規 locale 追加

1. `clinosim/locale/<cc>/` (2 文字 ISO 国コード、小文字。**先頭
   アンダースコア禁止**) を作成。`_template/` を scaffold としてコピー。
2. `us/` または `jp/` の形状に従いバンドルを埋める:
   - `names.yaml` — first / family / phonetic 氏名プール。
   - `addresses.yaml` — 郵便形式テンプレートと市区 / region プール。
   - `demographics.yaml` — 年齢 / 性別 / 民族分布。
   - `code_mapping_{diagnosis,drug,lab,procedure}.yaml` — 臨床キー
     → 国別コード解決。
   - `formatting.yaml` — 電話 / 日付 / 通貨フォーマット。
   - `reference_range_lab.yaml` — 国の典型的検査基準範囲。
   - `immunization_schedule.yaml` — 国の予防接種スケジュール。
   - 必要に応じて他の `code_mapping_*.yaml` (JP は `microbiology` と
     `microbiology_susceptibility` を追加)。
3. ISO コードが小文字ディレクトリ名に直接マップされない場合は
   `_COUNTRY_DIR_MAP` (`clinosim/locale/_io.py`) に国を登録。
4. トップレベル `clinosim/config/<country>.yaml` を追加して国別
   医療制度デフォルト (`lab_frequency_multiplier` /
   `discharge_criteria` / `target_los_multiplier` / コードシステム名)
   を宣言し、`clinosim/modules/healthcare_system/loader.py` の国
   マップに登録。
5. `SimulatorConfig.country` で切り替えるモジュールの国別 dispatch
   を拡張。
6. 新規国をカバーする統合テストを追加。

[`docs/add-your-country.md`](../../docs/add-your-country.ja.md) も参照。

## テスト

```bash
pytest tests/unit -k locale -q
pytest tests/integration -k locale -q
```

`clinosim.locale` を参照するテストファイルは約 80。ローダーバリデー
ション、`_template` ガード、`resolve_text` フォールバックチェーン、
国別 YAML 形状アサーションを網羅。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.ja.md) 参照。

英語版: [`README.md`](README.md)。
