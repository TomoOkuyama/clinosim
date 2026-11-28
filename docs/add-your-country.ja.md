# clinosim に国を追加する

*P2-14 (2026-07-13)、2026-11-28 に
[国プロファイル仕様](design-guides/country-profile-spec.ja.md) に基づき書き直し。
本ガイドは、clinosim が新規国向けの locale 適合合成 EHR/EMR データを生成
できるように国を追加する手順を示します。*

## Overview

`clinosim/locale/<cc>/country.yaml` が存在すると、その国が clinosim に存在
します (`<cc>` は小文字の ISO 3166-1 alpha-2 コード)。このファイルが国
プロファイルです。`clinosim.country_profile.supported_countries()` は
`country.yaml` を持つ locale ディレクトリを列挙し、`--country` の値、
`SimulatorConfig.country`、`country_profile(...)` の呼び出しはすべてこの
一覧に照らして検査されます。登録手順は別になく、国 → ディレクトリの
対応表もありません (`clinosim/locale/_io.py::_country_dir` がコードから
ディレクトリを導出します)。

国の追加は主にデータ作業です:

1. `clinosim/locale/<cc>/country.yaml` (プロファイル) と、そのディレクトリ
   の残りの locale YAML 一式
2. `clinosim/config/` のヘルスケアシステム設定
3. 国をキーとする共有ファイル・モジュール reference data への新規国の
   エントリ (下記一覧。欠けると失敗するものがある)
4. コードが必要なのは、既存のどの国にも無いアルゴリズム (名前付き実装)
   または clinosim がまだ知らない FHIR プロファイルが要る場合のみ。どちらも
   core ファイルの編集になる (後述)
5. 標準 CLI を country フラグ経由でテスト

Locale データは厳密に **文化 / 規制 / 言語** のみ。国際臨床コード
(ICD-10 / LOINC / RxNorm / SNOMED) は `clinosim/codes/` に残り、
国別作業を必要としません。

## 前提条件

- **権威ある統計ソース** — 人口、血液型分布、慢性疾患 prevalence、
  検査 reference range 用。人口統計データの捏造は禁止 — 政府 / 医学
  会公表を引用。
- **現地臨床コードシステム** の知識 (`icd-10` vs `icd-10-cm` vs
  国別コーディングスキームのいずれを適用するか)。
- **任意**: 下流プロファイル emit 用の国別 FHIR IG (JP Core /
  US Core / DE Basisprofil 等)。

## Quick start

```bash
# 1. US フォルダを作業用 scaffold としてコピー (完結していて実行可能。
#    clinosim/locale/_template/ はスキーマコメントのみで実行不可)
cp -R clinosim/locale/us clinosim/locale/xx

# 2. clinosim/locale/xx/country.yaml を編集: `code: XX`、ヘルスケア
#    システム、言語、タイムゾーン、コードシステム、FHIR プロファイル、
#    features を設定
# 3. 各 YAML を locale 適合値に置換 (下記参照)
# 4. locale/xx/ の外にあるエントリを追加 (「locale/<cc>/ の外のエントリ」参照)
```

そして:

```bash
clinosim simulate --country XX --population 100 --seed 42 --format fhir-r4 \
    --output ./out
```

## 国プロファイル: `country.yaml`

`clinosim/locale/<cc>/country.yaml` は `clinosim/locale/_root/country.yaml`
と異なる値だけを持ち、両者は deep-merge されます (map は key 単位で
merge、list と scalar は置換)。`clinosim/locale/_template/country.yaml`
または `us` / `jp` のファイルから始めます。各 key は
[`design-guides/country-profile-spec.ja.md`](design-guides/country-profile-spec.ja.md)
§3.2 に仕様があります:

| Key | 設定内容 |
|---|---|
| `code` | 大文字の ISO コード。ディレクトリ名と一致させる (`locale/qq/country.yaml` が `US` を宣言すると `ValueError`) |
| `healthcare_system` | `clinosim/config/` のヘルスケアシステム設定の stem (`us` → `us.yaml`、`japan` → `japan.yaml`)。**root に既定値なし**: `clinosim/config/<stem>.yaml` を作成する (`HealthcareSystemConfig` として検証、`clinosim/types/config.py`) |
| `language`, `timezone` | 出力言語 (ISO 639-1) と FHIR タイムスタンプの UTC オフセット |
| `code_systems` | `lab`、`diagnosis`、`drug`、`procedure`、`microbiology` の 5 種を過不足なく。各値は `clinosim.codes` の key であること |
| `fhir_profiles` | `us_core`、`jp_core`、`jp_clins`、`jp_echeckup` から選んだ list (`clinosim/country_profile.py` の `FHIR_PROFILES`)。`[]` は base FHIR |
| `features` | root で宣言済みのスイッチ (`health_checkup`、`care_level`、`maternal_tdap`)。国が単独で新しい feature 名を追加することはできない |
| `formats` | 氏名順、日付 / 時刻 / 日時フォーマット、医師名の接頭辞 |
| `implementations` | アルゴリズム種別ごとの名前付き実装 (`egfr_equation`、`triage_scale`、`identity_provider`、`lab_coding`、`drug_system`、`drug_order_code`、`copay_rule` など) |

プロファイルが誤っている場合に起きること (いずれも実測):

- `country.yaml` が無い: `country_profile(...)` が
  `KeyError: no country profile for 'XX'; supported: [...]` を送出し、
  `simulate --country XX` はこのエラーで停止する
- `code` がディレクトリと異なる: `ValueError`
- `healthcare_system` が無い: ヘルスケア設定のロード時に
  `KeyError: country XX names no healthcare_system`。指定したファイルが
  無い場合は `FileNotFoundError: Healthcare config not found`
- 未知のコードシステム・FHIR プロファイル・feature・実装種別: ロード時の
  検証エラー
- 誰も登録していない実装名:
  `ValueError: country XX: unregistered implementations {...}`

### 実装 (implementations)

新しい国は既定で root の実装 (米国のもの: eGFR は `ckd_epi_2021`、triage は
`esi`、identity provider は `us`、lab coding は `loinc`、copay は
`category_rate` など) を継承します。別の登録済み実装を選ぶには
`implementations:` に名前を書きます。登録済みの名前は、
`IMPLEMENTATION_MODULES` (`clinosim/country_profile.py`) に載っているモ
ジュール内の `@register_implementation(kind, name)` デコレータです。
`clinosim/locale/jp/country.yaml` に全種別の例があります。

まだ無いアルゴリズムが必要な場合は、名前付き実装として書き (国専用のものは
`clinosim/countries/<cc>/`)、`@register_implementation(kind, name)` を付け、
**そのモジュールを `IMPLEMENTATION_MODULES` に追加**します。discovery は
無く、載っていないモジュールは import されないため、プロファイルは
"unregistered implementations" で失敗します。これは core ファイル
`clinosim/country_profile.py` の編集です。

## 必須 YAML ファイル

`clinosim/locale/xx/` に以下を作成します。スキーマコメントと skeleton 値は
`_template/` scaffold (`clinosim/locale/_template/`) 参照。
`_template/demographics.yaml` は us/jp と同じスキーマ。

| File | 目的 | 権威ソースヒント |
| --- | --- | --- |
| `country.yaml` | 国プロファイル (上記)。これがあることで国が存在する | — |
| `names.yaml` | 姓 + 名 と頻度重み | 国家統計局 / 戸籍 |
| `addresses.yaml` | 地域 (都道府県 / 県 / 州) + 郵便コード + 電話パターン | 国営郵便サービス |
| `demographics.yaml` | 年齢分布、血液型、慢性疾患 prevalence (下記スキーマ注記参照)、疾患 incidence、生活習慣、入院に至らない ED 受診率 (`ed_visit_not_admitted.rate_per_1000_person_years`) | 政府センサス / 疾患サーベイランス / 国の救急利用統計 |
| `formatting.yaml` | 日付 / 時刻 / 数値フォーマット | 現地慣習 |
| `code_mapping_diagnosis.yaml` | 内部疾患 id → 国別診断コード | 現地コーディングスキーム |
| `code_mapping_lab.yaml` | 内部検査名 → 国別検査コード | 現地検査コードシステム (JLAC10 / LOINC / 国別) |
| `code_mapping_drug.yaml` | 内部薬剤名 → 国別薬剤コード | 処方コード (YJ / RxNorm / 国別) |
| `code_mapping_procedure.yaml` | 内部手技名 → 国別手技コード | 現地手技スキーム (K コード / CPT / 国別) |
| `reference_range_lab.yaml` | 性別 / 年齢別検査 reference range | 現地臨床学会標準 |
| `care_practice.yaml` | 入院診療の慣行: 退院基準、手術までの時間、リハビリ時間 | 国の診療実態調査 / 診療ガイドライン |
| `population_genetics.yaml` | Rh 陽性割合、ABO 対立遺伝子頻度、薬物代謝表現型 | 集団遺伝学の文献 |

`care_practice.yaml` と `population_genetics.yaml` は `us/` と `jp/` にあり
ますが `_template/` にはありません。`us/` からコピーして値を置換します。

### 失敗するものとフォールバックするもの

`us/` のコピーを `XX` として登録し、ファイルを 1 つずつ削除して
`clinosim simulate --country XX --population 5 --seed 42 --format fhir-r4`
を実行して観測した結果:

| 欠けているもの | 結果 |
|---|---|
| `addresses.yaml` | 実行が停止する (`KeyError: 'phone'`) |
| `care_practice.yaml`、`population_genetics.yaml` | 実行が停止する (`FileNotFoundError: locale/xx/<file> is missing or empty`、`clinosim/locale/loaders/country_parameters.py`) |
| `names.yaml`、`formatting.yaml`、`demographics.yaml` | 実行は止まらない: ローダーが `clinosim/locale/shared/fallback_defaults.yaml` の中立な組み込みデフォルトにフォールバックするため、データは locale を代表しない |
| `code_mapping_*.yaml`、`reference_range_lab.yaml`、下記の任意ファイル | 実行は止まらない: ローダーは空の表を返し、対応する値は出力に無いかコード化されない。出力を確認すること (5 人の実行ではすべてのコードパスを通らない) |

存在するが形式が誤っているファイルはロード時に検証され、エラーになります。

## `locale/<cc>/` の外のエントリ

国をキーとするデータの一部は、国フォルダの外のファイルにあります。新規国
では、そこにも自国の key を追加します。上記のコホートコマンドを `locale/xx/`
のファイルだけで実行して観測した結果:

| ファイル | 追加するエントリ | 欠けた場合 |
|---|---|---|
| `clinosim/locale/shared/naming_rules.yaml` | トップレベルの `xx:` ブロック (氏名順、ミドルネーム・姓の規則) | 実行が停止する: `KeyError: 'xx'` (`load_naming_rules`) |
| `clinosim/modules/population/reference_data/anthropometric_reference.yaml` | `pediatric_growth` 配下の `XX:` ブロック (年齢・性別ごとの身長 / 体重 / 頭囲) | import 時の `ValidationError`: "pediatric_growth countries must be the supported countries" |
| `clinosim/modules/encounter/reference_data/minor_burn.yaml`、`minor_laceration.yaml` | `diagnosis_variants` の各 `codes:` mapping に `xx:` key (対応する全ての国にコードが必要) | `ValueError: Invalid encounter condition YAML` |
| `clinosim/locale/shared/actuarial_life_table.yaml` | `annual_mortality_qx` と `community_death_share` の両方に `xx:` エントリ | US ブロックにフォールバック (`clinosim/modules/population/mortality.py::_locale_key`) |
| `clinosim/locale/shared/country_language.yaml` | `xx: <language>` | 言語は `en` にフォールバック |
| 疾患 YAML (`clinosim/modules/disease/reference_data/*.yaml`) | `target_los` は `japan` / `us` を key とする | 自国ブロックの無い国は `us` ブロックを使う (`clinosim/modules/disease/localization.py::target_los_config`) |
| `clinosim/modules/drug_safety/` の hyperkalemia `treatment` と `clinosim/modules/order/label_dose.py` の `limits` | 任意。大文字の国コード key | 対応国コードでない key はロード時に拒否される。これらは部分集合で、全ての国に必須ではない |

最初の 3 行は他モジュールが所有するファイルの編集です。これらを 1 か所に
列挙したものは無いので、上記コマンドを実行し、エラーが指す箇所を、完走する
まで直してください。

### `demographics.yaml::chronic_prevalence` スキーマの 2 形式

エントリごとに 2 つの形式を受け付けます:

- **Flat form** (単性別または性別非依存): `sex: F |M |""` +
  `"<lo>-<hi>": <target_marginal>` 年齢帯 pair。共有の population
  master RNG からサンプリング。

  ```yaml
  chronic_prevalence:
    N40:                  # BPH、男性のみ
      sex: M
      "60-99": 0.20
    E11:                  # T2DM、性別非依存
      "40-99": 0.10
  ```

- **`by_sex` form** (性別で非対称な帯域。男性乳がんが C50 全体の
  ~1 % で女性 BC より遅い年齢 peak を持つケース等)。最初の性別 key が
  primary となり (flat form と同一の master RNG からサンプリング)、
  残りの性別 key はすべて `augment_sex_bands` に入り
  `(patient_id, code)` 毎の sub-RNG からサンプリングされる (opposite-sex
  活性化が master stream を cascade しないため)。

  ```yaml
  chronic_prevalence:
    C50:                  # 乳がん — F primary + M ~0.02 %
      by_sex:
        F:
          "40-59": 0.015
          "60-99": 0.030
        M:
          "60-99": 0.0002
  ```

full な挙動 + downstream の sex-conditional 請求コード mapping:
[`reference/oncology-obstetric-service-lines.ja.md`](reference/oncology-obstetric-service-lines.ja.md) §3。

### `demographics.yaml::ed_visit_not_admitted`

入院に至らない ED 受診の率 (1,000 人年あたり)。forward month loop が
これから各月の ED 受診数を引く (`clinosim/simulator/phases/_ed_slot.py`)。
key が無いと率 0 扱いとなり、ED のみの受診は生成されない。

```yaml
ed_visit_not_admitted:
  rate_per_1000_person_years: 380   # US の値。JP は 150
```

### 死亡 (`locale/shared/actuarial_life_table.yaml`)

院外死亡 (シミュレートされた入院以外での死亡) は
`clinosim/modules/population/mortality.py` が人ごと・年ごとに前向きに
引く: 生命表 `qx` (年齢帯 × 性別) × その人の慢性疾患による相対 SMR ×
`community_death_share`。`annual_mortality_qx` と `community_death_share`
はどちらも共有 yaml 内で locale (`us`、`jp`) を key とする。
自国の locale には両 key に `xx` エントリを追加する。エントリの無い
locale は US のブロックを使う。

## 任意 YAML ファイル (opt-in モジュール)

対応国が特定 opt-in モジュールをサポートする場合のみ追加します。ファイルが
無くても実行は止まりません (上記の表参照):

| File | 追加タイミング | モジュール |
| --- | --- | --- |
| `identity.yaml` | 国民識別子 / 保険番号をモデル化する場合 | `identity` |
| `code_mapping_microbiology.yaml` | 国別 microbiology コーディング | `microbiology` |
| `code_mapping_microbiology_susceptibility.yaml` | 国別感受性報告 | `microbiology` |
| `care_level_rates.yaml` | 長期ケアレベル (JP 要介護度相当) | `care_level` — JP 固有概念、通常スキップ |
| `code_status_rates.yaml` | 蘇生ステータス分布 | `code_status` |
| `family_history_prevalence.yaml` | 一親等家族疾患 prevalence | `family_history` |
| `immunization_schedule.yaml` | 現地予防接種スケジュール | `immunization` |
| `ambulatory_visit_length.yaml` | 外来受診種別ごとの受診時間分布 | 外来 simulator (無ければ 15/25/45 分の一律三角分布にフォールバック) |

## FHIR プロファイル

国別 FHIR プロファイルを適用するかは国プロファイルで宣言します: `country.yaml`
の `fhir_profiles:` に列挙します。出力ビルダーは国ではなくプロファイルで分岐
します: `_finalize_resource`
(`clinosim/modules/output/fhir_r4/builder.py`) が
`profile.uses("jp_core")`、`profile.uses("jp_clins")`、
`profile.uses("us_core")` を呼び、`_apply_jp_core_profile`、
`_apply_jp_clins_profile`、`_apply_us_core_profile` を適用します (helper は
`clinosim/modules/output/fhir_r4/post_process/profile.py`、URL レジストリは
`clinosim/codes/data/fhir-profiles-{jp-core,us-core,jp-clins}.yaml`)。
`fhir_profiles: []` の国は base FHIR となり、第三の国に他国のプロファイルが
付くことはありません。

したがって US Core または JP プロファイルを使う国は `fhir_profiles` を設定
するだけで済みます。clinosim が知らないプロファイル (DE Basisprofil、AU Core
など) は core ファイルの編集が必要です: `clinosim/country_profile.py` の
`FHIR_PROFILES` に名前を追加し、既存と同形状のレジストリ YAML を追加し、
`_apply_<name>_profile` helper を追加し、`_finalize_resource` に
`if profile.uses("<name>"):` の gate を追加します。仕様 (§5) どおり、この
分岐はプロファイルが要求する構造を emit するかどうかだけを決め、その中の値は
YAML から取ります。

## 国の feature (opt-in モジュール)

国固有のモジュールは、国の判定ではなくプロファイルの `features:` で切り替わります:

- `identity` — 常に有効 (JP は `--no-jp-insurance` に従う)。locale に
  `identity.yaml` が無ければ `assign_identities` は no-op
- `care_level` — `features.care_level` (現状 JP のみ); スキップ
- `health_checkup` — `features.health_checkup` (JP-eCheckup); 同等物を設計
  する場合以外はスキップ
- `maternal_tdap` — `features.maternal_tdap` (US は on)

## テストチェックリスト

国フォルダ作成後:

- [ ] `python -c "from clinosim.country_profile import country_profile; print(country_profile('XX'))"`
      がエラーなくプロファイルをロードする
- [ ] `clinosim simulate --country XX --population 10 --seed 42 --format cif`
      がエラーなく走行し、空でない CIF 出力を作成
- [ ] `clinosim simulate --country XX --population 10 --format fhir-r4`
      が有効な FHIR R4 リソースを emit
- [ ] 同 seed の 2 実行がバイト同一出力を生成 (決定性チェック —
      clinosim のコア不変条件、AD-16):
      ```bash
      clinosim simulate --country XX --seed 42 -o /tmp/xx-run1
      clinosim simulate --country XX --seed 42 -o /tmp/xx-run2
      diff -r /tmp/xx-run1 /tmp/xx-run2  # manifest transactionTime のみが差分
      ```
- [ ] 氏名 / 住所 / 日付が期待される現地慣習でレンダリング
- [ ] 検査 reference range が権威ソースと一致
- [ ] YAML から emit されるが `clinosim/codes/data/` に不在の
      新規コード追加が
      `pytest tests/unit/test_diagnosis_code_coverage.py` を fail
      させる (期待通り)。適切な `codes/data/*.yaml` に登録
      (`AGENTS.md` の「Diagnosis code coverage」節参照)。
- [ ] `pytest tests/unit tests/modules tests/simulator` (CI が走らせる
      ディレクトリ) が通る。診断ルールのコード検査
      (`clinosim/simulator/diagnosis_rules.py`) のようなロード時検査は
      `supported_countries()` を走査するため、新規国もそこで検証される

## よくある落とし穴

- **人口統計データを絶対に捏造しない**。全人口統計は公開の権威
  ソース (センサス / 厚生省 / 医学会) に追跡可能でなければならない。
  捏造データは下流で silent-no-op クラスのバグの原因。
- **locale 固有コードを異なる国のバンドルに絶対に emit しない**。
  回帰テスト `test_us_p50_has_no_japanese_language_leakage` が US
  出力を JP leakage から守る; 新規国にも対称ガードを書く。
- **`code_mapping_*.yaml` 内でコードシステムを混在させない**。各
  ファイルは内部名を単一の外部システムにマップ。ファイル単位で分割。
- **LLM で臨床用語を翻訳しない**。国の公式用語 master を参照。
  clinosim の AD-27 ルールは LLM 駆動臨床翻訳を禁止。
- **分布が現実的かを判断する前に population ≥ 100 でテスト**。
  小規模コホートは long-tail サンプリング問題を隠す。
- **`jp/country.yaml` や `us/country.yaml` をそのまま使わない**: コピーした
  `code` は検証で失敗し、コピーしたプロファイル・feature・実装はその国の
  ものであって自国のものではない。

## 次に読むもの

- 国プロファイル仕様: [`docs/design-guides/country-profile-spec.md`](design-guides/country-profile-spec.ja.md)
- プロジェクト全体概念: [`docs/design-guides/project-concept-and-design.md`](design-guides/project-concept-and-design.ja.md)
- Locale モジュールリファレンス: [`clinosim/locale/README.ja.md`](../clinosim/locale/README.ja.md)
- 診断コードカバレッジルール: [`AGENTS.md`](../AGENTS.md) §"Diagnosis code coverage"
- 再現性不変条件: [`docs/development/reproducibility.md`](development/reproducibility.ja.md)

## Scaffold テンプレート

`clinosim/locale/_template/` はスキーマコメント付きプレースホルダ
YAML セットを含みます。**これらのプレースホルダは非機能** —
`clinosim simulate --country _template` を実行すると、`_template` は国では
なく (ディレクトリ名がアンダースコアで始まるため `country_profile` が拒否する)、
値も TODO マーカーでありデータではないため失敗します。テンプレートは実国別
パックを authoring する際の必須スキーマ形状を示す目的のみで存在します。
