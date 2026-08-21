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
    load_terminology,               # (domain, country) -> dict[str, str] (legacy)
    load_code_mapping,              # (domain, country) -> dict[str, str]
    load_chronic_medications,       # () -> dict[str, Any] (shared)
    load_chronic_followup,          # () -> dict[str, Any] (shared)
    load_med_terms_ja,              # () -> dict[str, dict[str, str]] (shared)
    load_drug_names_ja,             # () -> dict[str, str] (shared)
    load_department_display,        # () -> dict[str, dict[str, str]] (shared)
)
from clinosim.locale.text import (
    resolve_text,                   # (value, language, country) -> str
)
```

`load_terminology` および旧 `load_formatting` は後方互換維持のため
保持。新規コードは所有モジュール経由で YAML を読み込む方が望ましい
(例: 薬剤キー → RxNorm / YJ 解決は
`clinosim/locale/{us,jp}/code_mapping_drug.yaml` 経由で
`clinosim.modules.antibiotic` が処理)。

## 決定性

該当なし — 本パッケージはデータローダー層です。全ローダーは
`@lru_cache` で装飾済 (キャッシュキー: country 文字列で有界) なので、
繰り返し呼び出しは同一 `dict` インスタンスを返します。YAML 解析は
`yaml.safe_load` によりバイト入力 → dict 出力が決定的。

## 依存

- `pyyaml` — YAML ロード用。
- 標準ライブラリ `pathlib` / `functools` / `typing`。
- **import 時に他の `clinosim.*` パッケージへの依存なし** — ローダー
  は純粋な YAML リーダー。consumer 側が返却 dict を自身の型に渡し
  ます。

## 定数と設定

- **`_LOCALE_DIR`** = `Path(__file__).parent` — import 時の locale
  バンドルルート。
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
  loader.py                       @lru_cache YAML ローダー (公開関数 14)
  text.py                         resolve_text (多言語テキスト解決
                                   ヘルパー)
  us/                             US 固有バンドル (12 YAML):
                                   addresses / code_mapping_{diagnosis,
                                   drug,lab,procedure} / code_status_rates
                                   / demographics / family_history_
                                   prevalence / formatting /
                                   immunization_schedule / names /
                                   reference_range_lab
  jp/                             JP 固有バンドル (15 YAML — US 集合
                                   + care_level_rates / identity /
                                   code_mapping_microbiology /
                                   code_mapping_microbiology_susceptibility)
  shared/                         locale 間共有データ (6 YAML):
                                   chronic_followup / chronic_medications
                                   / department_display / drug_names_ja
                                   / med_terms_ja / naming_rules
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
   `_COUNTRY_DIR_MAP` に国を登録。
4. トップレベル `clinosim/config/<country>.yaml` を追加して国別
   デフォルト (encounter mix、疾患 prevalence 重み、insurance
   パターン) を宣言。
5. `SimulatorConfig.country` で切り替えるモジュールの国別 dispatch
   を拡張。
6. 新規国をカバーする統合テストを追加。

[`docs/add-your-country.md`](../../docs/add-your-country.md) も参照。

## テスト

```bash
pytest tests/unit -k locale -q
pytest tests/integration -k locale -q
```

`clinosim.locale` を参照するテストファイルは 13。ローダーバリデー
ション、`_template` ガード、`resolve_text` フォールバックチェーン、
国別 YAML 形状アサーションを網羅。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
