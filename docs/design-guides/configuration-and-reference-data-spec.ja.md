# 設定と参照データ — 仕様

位置づけ: **規範**。参照データ YAML・設定表・年齢区分の表・定数を追加する、または読む変更は、すべて本書に従う。従えない変更は、同じ PR で理由とともに本書を改訂する。

英語版: [`configuration-and-reference-data-spec.md`](configuration-and-reference-data-spec.md)。

関連仕様(本書では繰り返さずリンクする):
- YAML の書き方と読み方(`load_data_yaml`、`metadata.kind`、ファイルの置き場所)、コード表、値集合: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) §3.1 / §3.6。
- 定数の置き場所(YAML か Python か): [`documentation-and-code-quality-policy.ja.md`](documentation-and-code-quality-policy.ja.md) §5 / §5.1。
- ローダーの約束事(パス定数、`@lru_cache`、所有モジュールのアクセサ): [`implementation-rules.ja.md`](implementation-rules.ja.md) §5。

## 1. 原則

1. **読み手は一つ、形の検査も一つ。** 参照データは所有モジュールのローダーを通して読み、形はキーを初めて引き損ねた時ではなく読み込み時に検査する。モジュールの参照 YAML(`clinosim/modules/<module>/reference_data/*.yaml`)は `extra="forbid"` の Pydantic モデルがこれを行い、形が崩れたキーや未知のキーは読み込み時に大きく失敗する。それ以外のデータ YAML はまだモデルで検証していない(§5)。
2. **一つの事実に一つの表。** 複数の段階が使う値(フォローアップ間隔、名前付きの病態、年齢区分の率)は一つの表に置き、各段階は一つのアクセサでその表を読む。
3. **キー形式の解釈は一つ。** 共通のキー形式(年齢区分、コード群)は一つの補助関数が解釈し、すべての表が同じ書き方・読み方をする。
4. **規則には必ずガードがある。** 各規則はそれを強制するテストを示す。テストの無い規則は §5 に挙げる。

## 2. 読み込みと検証

| 規則 | 正準コード | ガード |
|---|---|---|
| データ YAML はすべて一つの読み手で解析し、`metadata.kind` を宣言する。 | `clinosim/datafiles.py::load_data_yaml`, `data_metadata` | `tests/unit/test_data_yaml_conventions_2465.py` |
| モジュールの参照 YAML は、読み込み時に Pydantic モデルで検証する。欠けた必須キーや型の誤りは import 時に失敗する。ガードは `modules/<module>/reference_data/*.yaml` のファイルを一つずつ確かめる。ファイルを名指すコードは、`load_validated_yaml` かモデル(`Model.model_validate` / `Model(**data)`)を通して読み込まなければならず、例外のファイルは無い。モデルは未知のキーも拒否する(`ConfigDict(extra="forbid")`)。開いたマップは型付きの `dict[str, X]` フィールドにし、`extra="allow"` は使わない。YAML が名指すコードは `clinosim.codes` で存在を確かめる。新しいキーは先にモデルへ足す(AD-69)。 | モジュールごとのモデル(allergy, antibiotic, care_level, clinical_course, code_status, device, diagnosis, disease, document, drug_safety, encounter, family_history, hai, imaging, llm_service, monitoring, newborn, nursing, observation, order, patient, pediatric, physiology, population, procedure, prophylaxis, sdoh, triage) | `tests/unit/test_configuration_spec_guards.py::test_module_reference_yaml_has_a_model`、`::test_not_yet_modeled_stays_empty`、`::test_module_models_forbid_unknown_keys`(縮小のみのラチェット)、`::test_no_extra_allow_models`、各モジュールのモデルのテスト |
| キャッシュ付きローダーの戻り値は共有物で、読み取り専用。 | `@lru_cache` ローダー | `implementation-rules.ja.md` §3(レビュー) |

## 3. 共有の表

| 規則 | 正準コード | ガード |
|---|---|---|
| 年齢区分の表のキーは `"lo-hi"`(両端を含む)と `"lo+"`(上限なし)。解析と参照は共通の補助関数だけで行う。年齢を含む最初の区分を採り、どの区分にも入らない年齢の結果は呼び出し側が決める。 | `clinosim/age_bands.py`(`parse_age_band`, `parse_closed_age_band`, `age_band_covers`, `find_age_band`, `lookup_age_band`) | `tests/unit/test_age_bands_2516.py`, `tests/unit/test_configuration_spec_guards.py::test_no_ad_hoc_age_band_parsing` |
| 慢性疾患のフォローアップのバイタルと受診間隔は一つの表から得る。シミュレータ、人口カレンダー、外来記録がそれを読む。 | `locale/shared/chronic_followup.yaml`(`clinosim.locale.loader` 経由) | `tests/unit/test_followup_from_yaml_2287.py` |
| 判断ロジックで名指す病態(重症度の修飾因子、合併症の危険因子、検査のフラグ: "diabetes", "dyslipidemia" …)は値集合で解決し、呼び出し側に ICD の接頭辞を書かない。 | `clinosim/codes/valuesets.py`(`has_condition`, `concept_group`)、`codes/data/valuesets.yaml` | `tests/unit/test_named_conditions_2285.py`, `tests/unit/test_valuesets_2280.py`, `tests/unit/test_diabetes_group_2281.py` |
| YAML 由来の確率ベクトルは `normalize_probabilities(p, fallback="raise")` で正規化する。 | `clinosim/modules/_shared.py` | [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) §2 |

## 4. 定数

| 規則 | 正準コード | ガード |
|---|---|---|
| 領域の識別子(疾患・薬剤・検査・年齢区分・国)をキーとする表は YAML に置く。式の係数や臨床の閾値は、`_<topic>_thresholds.py` / `_defaults.py` の名前付き・説明付きの定数とし、出典を付ける。コードに名前の無い臨床リテラルを書かない。 | 方針 | [`documentation-and-code-quality-policy.ja.md`](documentation-and-code-quality-policy.ja.md) §5.1(レビュー) |

## 5. 未対応

| 未対応 | 場所 |
|---|---|
| 定数の置き場所の方針には自動のガードが無い。 | レビュー |
| `clinosim/modules/*/reference_data/` の外にあるデータ YAML は Pydantic モデルで検証しておらず、§2 のガードも見ていない: `clinosim/simulator/reference_data/*.yaml`(モデルがあるのは `statin_monitoring.yaml` だけ)、`clinosim/locale/**`(一部のファイルは `clinosim/locale/loader.py` の手書きの検査を持つ)、`clinosim/codes/data/*.yaml`。これらのファイルの未知のキーは読み込み時に拒否されない。 | `tests/unit/test_configuration_spec_guards.py` は `modules/*/reference_data/` だけを走査する |
| キャッシュ付きローダーの戻り値を書き換えない(§2)。 | レビュー |
