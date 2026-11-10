# 国プロファイル仕様 — 国ごとの違いの表し方

**Status:** Active (2026-11-10 に設計を採用。移行は Issue で追跡)。
**対象:** 国を追加する人、国ごとの挙動を変える人、国で分岐するコードに触れる人。
**位置付け:** [`implementation-rules.ja.md`](implementation-rules.ja.md#グランドデザイン-コードとデータの分離)
のグランドデザインを国について具体化する仕様。コード体系・表示文言・多言語化は
[`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md)、
YAML の読み込みと検証は
[`configuration-and-reference-data-spec.ja.md`](configuration-and-reference-data-spec.ja.md)
に従う。

## 1. 原則

国ごとの違いは**データ**であり、**国プロファイル**で選ぶ。コードは汎用のロジック
を持ち、ある国だけのアルゴリズムが要るときは、プロファイルが選ぶ名前付きの実装
として持つ。共通の流れは「日本か?」を問わず、プロファイルに値・機能・実装を問う。

| 国で何が違うか | 置き場所 | 例 |
|---|---|---|
| 値: コード・表示文言・閾値・率・年齢の区切り・単位・書式・一覧 | YAML (`clinosim/locale/<cc>/`、モジュールの `reference_data/`、`clinosim/codes/data/`) | 退院基準、手術までの時間、氏名の順序、電話の書式、保険者表 |
| 一部の国だけが使うアルゴリズム | コード (名前付きの実装) | JSN の eGFR 式、保険者番号の検証番号、JTAS と ESI のトリアージ |
| 国がどのアルゴリズム・プロファイル・機能・コード体系を使うか | 国プロファイル (YAML) | `implementations.egfr_equation: jsn`、`fhir_profiles: [jp_core, jp_clins]` |

国の追加はデータの変更 (プロファイルとその locale YAML) で済み、コードを足すのは
どの国もまだ持たないアルゴリズムが要るときだけである。

## 2. 依拠する定番手法

- **継承とフォールバックを持つロケールデータ** (Unicode CLDR、Babel): ルートが既定
  値を持ち、各ロケールは差分だけを持つ。無い値は親、最後はルートから解決する。
- **国ごとの既定値の上書き** (Synthea の国際版): 国のリソースと設定が既定値を書き
  換えずに差し替える。
- **書式をメタデータで持つ** (Google libaddressinput / libphonenumber): 書式を処理
  するコードは 1 つで、国ごとのテンプレートとパターンをデータに持つ。
- **国コードごとのパッケージ** (django-localflavor の `localflavor.jp`、Odoo の
  `l10n_jp`、Faker のロケール別プロバイダ): 国固有のアルゴリズムを国コード名の
  パッケージに置く。
- **名前付きの実装を明示的な設定で選ぶ** (ストラテジーのレジストリ): 実装を名前で
  登録し、設定が使う実装を名指しする。暗黙の自動検出はしない。

## 3. 国プロファイル

### 3.1 ファイル

- `clinosim/locale/_root/country.yaml` — すべての国が継承する既定値。
- `clinosim/locale/<cc>/country.yaml` — その国の差分だけ。ルートに深くマージする
  (マップはキーごとにマージ、リストとスカラーは置き換え)。
- 対応国は `country.yaml` を持つディレクトリ。`_root` と `_template` は国ではない。

### 3.2 内容

| キー | 意味 |
|---|---|
| `code` | ISO 3166-1 alpha-2 の国コード (`US`、`JP`)。 |
| `language`、`timezone` | 出力言語 (ISO 639-1) と、FHIR のタイムスタンプに使う UTC オフセットまたはゾーン。 |
| `code_systems` | 種類 (`lab`、`diagnosis`、`drug`、`procedure`、`microbiology`) ごとのコード体系キー。`clinosim.codes` が解決する。 |
| `fhir_profiles` | 出力に適用する FHIR プロファイル (`us_core`、`jp_core`、`jp_clins`、`jp_echeckup`)。 |
| `features` | 国ごとに有効・無効を切り替える機能 (`health_checkup`、`care_level`、`maternal_tdap` など)。 |
| `formats` | 氏名の順序 (`given_family` / `family_given`)、日付・時刻・日時の書式。住所テンプレート、電話のパターン、MRN・国の識別子の仕様は移行の手順 2 (§7) で加える。 |
| `implementations` | アルゴリズムの種類ごとに使う実装の名前 (`egfr_equation`、`triage_scale`、`copay_rule`、`insurer_number` など)。 |

モジュールの**国別パラメータ** (退院基準、手術までの時間など) は、そのモジュール
の `reference_data/` または `clinosim/locale/<cc>/<topic>.yaml` に国をキーとして
置き、モジュールのローダーで読む。プロファイルには重複して持たない。

### 3.3 API

すべて `clinosim/country_profile.py` にある。

- `country_profile(country) -> CountryProfile` — 検証済みでキャッシュされる
  Pydantic モデル (`extra="forbid"`、frozen)。国コードは大文字小文字を
  区別しない。旧来の表記 (`"japan"`) はローダー内のデータ表で変換し、
  `is_jp` / `is_us` は使わない。未知の国は `KeyError` にし、黙って US に
  戻さない。
- `profile.code`、`profile.language`、`profile.timezone` (`"Z"` または
  `+HH:MM` / `-HH:MM` の UTC オフセット)、`profile.formats`。
- `profile.uses(profile_name) -> bool`、`profile.feature(name) -> bool`、
  `profile.code_system(kind) -> str`、`profile.implementation(kind) -> str`。
  未知の名前 (既知の集合にない FHIR プロファイル、プロファイルが持たない
  feature や種類) はどれも `KeyError` にし、綴り間違いを「無効」として
  読まない。
- `implementation(kind, country)` — プロファイルが選んだ名前で登録された実装
  (§4)。
- `supported_countries()` — `country.yaml` を持つ locale ディレクトリの
  国コード (大文字。`_root` と `_template` を除く)。
- `load_profile_data(country)` — 検証前のマージ結果 (ルートに国のファイルを
  深くマージしたもの)。`deep_merge(base, override)` がマージ本体。
- `validate_implementations(profile)` — 登録するモジュール (§4) を import し、
  プロファイルが未登録の実装を名指ししていれば `ValueError` にする。
  `country_profile` は返す前にこれを呼ぶ。

読み込み時の検証: コード体系はすべて `clinosim.codes` のキーで、5 種類を
過不足なく持つ。FHIR プロファイル名は既知のもの。feature と実装の種類は
`_root/country.yaml` で宣言されていなければならない。
`locale/<cc>/country.yaml` の `code` は `<cc>` と一致しなければならない。

`is_jp` / `is_us` はプロファイルのローダーでは使わない。新しいコードは
プロファイルを呼ぶ。

## 4. 名前付きの実装

- アルゴリズムの種類は、それを呼ぶ汎用コードの隣でシグネチャを 1 回宣言する
  (`Protocol`)。
- 実装は `@register_implementation(kind, name)` で明示的に登録する。同じ種類と
  名前を 2 回登録すると `ValueError` になる。複数の国が使いうるアルゴリズムは
  汎用コードの隣に置く (例: `clinosim/modules/physiology/egfr.py` の eGFR 式)。
- ある国だけのアルゴリズムは国パッケージ `clinosim/countries/<cc>/` に置く
  (例: JP の保険者番号の検証番号)。最初の国パッケージを作るとき、モジュール
  `clinosim/countries.py` をパッケージ `clinosim/countries/__init__.py` に
  変え、今の API を再エクスポートして既存の
  `from clinosim.countries import ...` がそのまま動くようにする
  (django-localflavor と同じ形)。
- 登録は明示的に行う: 実装を登録するモジュールはすべて
  `clinosim/country_profile.py` の `IMPLEMENTATION_MODULES` に列挙し、
  プロファイルを検証する前に import する。エントリーポイントやパッケージ走査
  による自動検出はしない。登録されていない実装を名指しするプロファイルは
  読み込み時に失敗する。
- 実装の係数は定数の規則に従う: 式の係数はその `_<topic>_thresholds.py`
  または参照 YAML、国で異なる値は YAML。

## 5. 残してよい分岐

プロファイルによる分岐は、FHIR プロファイルや仕様が要求する構造を出すかどうかを
決めるときだけ許す (`if profile.uses("jp_core"):` で JP Core のスライスを足す)。
その構造の中の値は YAML から取る。値を選ぶ分岐は、表をコードで書いたものなので
YAML に移す (ポリシー §5.1)。

## 6. 守らせ方

- 減らすことだけを許すラチェット: ファイルごとに国・言語の分岐と比較中の数値
  リテラルを数え、記録した上限を超えたら失敗する (Issue #3137)。
- プロファイルのモデルは未知のキーを拒否し、参照するコード体系・プロファイル・
  機能・実装の名前をすべて検証する。

## 7. 移行

移行は 1 ステップ 1 PR で行い、各 PR は不具合の修正を伴わない限り出力をバイト
単位で変えない:

1. プロファイルのファイル、モデル、ローダー、API、ラチェット。
2. 言語、タイムゾーン、氏名・住所・電話の書式、識別子をプロファイルと locale
   YAML から読む。
3. Python に直書きされた国別パラメータを YAML に移す。
4. コード体系の選び方と対応国の一覧をプロファイルから読む。
5. 国の機能を `profile.feature(...)` から読む。
6. 国のアルゴリズムを登録し、プロファイルで選ぶ。
7. FHIR 出力に残る `is_jp` の分岐を `profile.uses(...)` による構造の判定に
   置き換える。リソースの種類ごとに 1 PR。

FHIR の組み立てをプロファイルごとのプラグインに分割することは、この移行に含めない。
ステップ 7 の後、プロファイル固有のコードがなお大きいリソースの種類があれば、その
時点で改めて判断する。
