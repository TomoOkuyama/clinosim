# 共通ヘルパー カタログ — 「X にはどのヘルパーを使うか」を引く唯一の場所

**対象読者:** clinosim のコードを書く人・レビューする人すべて。
**位置づけ:** [`implementation-rules.ja.md`](implementation-rules.ja.md) は規則 (「正準ヘルパーを再利用し、再実装しない」) を定め、このカタログはその規則が指すヘルパーを一覧にする。挙動は各節に記した binding spec が定義し、このページは入口の場所だけを示す。

使い方:

1. 小さな処理 (ハッシュ抽選、国判定、dict か属性かの読み取り、FHIR coding、日付整形) を書く前に、このページで該当する関心事を探す。
2. ヘルパーがあれば、示されたパスから import する。本体を自モジュールに写すことはレビューで差し戻す。
3. ヘルパーが無く、2 つ目のモジュールが同じ処理を必要とするなら、所有モジュール (モジュール横断の小道具なら `clinosim/modules/_shared.py`) に置いて両方から import し、同じ PR でこの表に行を足す。

パスはリポジトリ直下からの相対パス。*(モジュール内部)* と付けたシンボルは `_` で始まるがパッケージ内の別ファイルから import されている。パッケージの外では使わない。

---

## 1. 決定性と乱数

Governing spec: [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md)。

| ヘルパー | 用途 |
|---|---|
| `clinosim/determinism.py` `default_rng(seed)` | 乱数生成器を作る唯一の方法 (プラットフォーム間でビット再現)。`numpy.random.default_rng` と `random` は禁止。 |
| `clinosim/determinism.py` `normal` / `beta` / `exponential` | 生成器からのビット再現な連続分布の値。 |
| `clinosim/determinism.py` `sha_quantile(salt, byte_offset, byte_count)` | salt から得るストリーム非消費の一様 [0, 1) 値。抽選を足しても他の抽選をずらしてはいけないとき (RNG 中立な変更) に使う。 |
| `clinosim/determinism.py` `sha_bernoulli(salt, p)` / `sha_normal(salt, mean, sd)` / `sha_weighted_choice(salt, choices, weights)` | `sha_quantile` 上に作ったストリーム非消費の 2 値・正規・重み付き選択。 |
| `clinosim/determinism.py` `sha_index(salt, n, byte_count)` | ストリーム非消費の `[0, n)` の添字。固定リストから 1 件を選ぶ (文言の変種、カタログの行)。 |
| `clinosim/seeding.py` `derive_sub_seed(master_seed, module_offset, key)` + `ENRICHER_SEED_OFFSETS` | enricher ごと・キーごとのサブシード。新しい offset を登録し、シードをその場でハッシュしない。 |
| `clinosim/seeding.py` `derive_phase_rng(master_seed, phase_salt, key)` | シミュレーションのフェーズとキーごとに独立した生成器。 |
| `clinosim/seeding.py` `text_seed`, `panel_specimen_seed`, `individual_lab_seed`, `chronic_medication_seed`, `discharge_prescription_seed`, `ambulatory_visit_length_seed`, `issue939_procedure_seed`, `chronic_augment_sex_seed`, `chronic_isolated_seed`, `longitudinal_event_seed`, `perinatal_delivery_seed`, `chemotherapy_regimen_seed`, `daily_output_seed`, `radiation_therapy_seed`, `avpu_day_seed`, `newborn_seed`, `pregnancy_outcome_seed`, `newborn_conditions_seed`, `enumeration_case_seed`, `identity_person_seed` | 実体ごとの名前付きシード。呼び出し側でシードを導出せず、ここに名前付き関数を足す。 |
| `clinosim/seeding.py` `rendezvous_pick(key, ids, hashes)` / `id_hashes(ids)` | プール (職員・病室) から 1 人を一様かつ安定に選ぶ。プールが増えても選択が動かない。 |
| `clinosim/seeding.py` `morse_fall_history_unit(patient_id, encounter_id)` | Morse 転倒歴項目が使う、入院ごとに安定な単位値。 |
| `clinosim/modules/_shared.py` `normalize_probabilities(p, fallback="raise")` | YAML 由来の確率ベクトルを `rng.choice(p=...)` に渡す前に必ず通す。 |
| `clinosim/modules/_shared.py` `random_day_of_month(rng, year, month)` | 月内の一様な日付 (閏年対応)。 |
| `clinosim/modules/_shared.py` `select_with_exclusive_classes(drug_specs, exclusive_classes, rng)` | 排他クラスごとに最大 1 剤を選ぶ薬剤選択。 |
| `clinosim/modules/order/placed_order_mar.py` `stable_nurse(roster, key, ward=, department=)` | 投与記録の実施看護師を安定ハッシュで選ぶ (乱数を消費しない)。 |

## 2. 参照データ・設定・年齢帯

Governing spec: [`configuration-and-reference-data-spec.ja.md`](configuration-and-reference-data-spec.ja.md)。

| ヘルパー | 用途 |
|---|---|
| `clinosim/datafiles.py` `load_data_yaml(path)` | 唯一の YAML 読み込み。`metadata` ヘッダを除いた内容を返す。 |
| `clinosim/datafiles.py` `load_validated_yaml(path, model)` | YAML を読み Pydantic モデルで検証する。モジュール参照データの標準。 |
| `clinosim/datafiles.py` `data_metadata(path)` | データ YAML の `metadata` ヘッダ (出典・版・ライセンス)。 |
| `clinosim/modules/document/reference_data_loaders.py` `load_document_data_yaml(filename)` | document の小さな登録表 2 つ(`chronic_soap_templates.yaml` と `hedging_phrases.yaml`)を、モデルで検証してキャッシュ付きで読む (他のファイル名は `KeyError`。他の document の YAML は同じモジュールに専用のローダーがある)。 |
| `clinosim/reference_data.py` `load_reference_yaml(path)` | コピーを返すキャッシュ付き読み込み。データを組み替える呼び出し側向け。 |
| `clinosim/age_bands.py` `parse_age_band` / `parse_closed_age_band` / `age_band_covers` | `"18-49"`、`"85+"` などの年齢帯キーの解析と判定。 |
| `clinosim/age_bands.py` `find_age_band(keys, age)` / `lookup_age_band(table, age, default)` | 年齢から年齢帯キーまたは値を引く。`if age < 18` のような境界のハードコードは禁止。 |
| `clinosim/age_bands.py` `find_age_band_or_last(keys, age)` | `age` を含む年齢帯、無ければ最後の帯 (最後の帯が受け皿の表向け)。 |
| `clinosim/codes/valuesets.py` `has_condition(person, group)` / `concept_group(name)` / `group_names()` / `patient_condition_names()` | 手書きの ICD 接頭辞リストではなく、名前付きの疾患グループ (value set) を使う。 |
| `clinosim/codes/valuesets.py` `has_icd_prefix(items, prefixes)` / `code_by_chronic_prefix(mapping, person)` / `iter_chronic_codes(items)` | どの形の慢性疾患項目でも ICD 接頭辞で照合する。 |
| `clinosim/codes/valuesets.py` `normalize_icd(code)` / `icd_base(code)` | ICD の正準表記と、ドット前のカテゴリ部分。 |

## 3. 国と言語の判定

Governing spec: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) §5。

| ヘルパー | 用途 |
|---|---|
| `clinosim/countries/__init__.py` `is_jp(country)` / `is_us(country)` | 国固有の規則 (保険・プロファイル・コード体系)。国文字列を手で比較しない。表示言語の選択には使わない。 |
| `clinosim/countries/__init__.py` `lang_for(country)` / `normalize_lang(lang)` | 国の出力言語と、言語引数の唯一の正規化。 |
| `clinosim/countries/__init__.py` `country_code(country)` | どの表記 (`"jp"`、旧来の locale キー `"japan"` など) からも `"JP"` / `"US"` を返す。大文字コードを取るヘルパー向け。`is_jp` も同じ表記を受け付ける。 |
| `clinosim/countries/__init__.py` `country_slot(country, scheme=...)` | 国別 YAML ブロックのセクションキー。 |
| `clinosim/countries/__init__.py` `lang_name(lang, in_lang=)` / `output_language_instruction(lang)` / `has_authored_narrative(lang)` | 言語名、LLM への「この言語で書け」指示、その言語に記述済みの narrative があるか。 |
| `clinosim/country_profile.py` `country_profile(country).uses(fhir_profile)` | 国の FHIR 出力が FHIR profile (`jp_core`、`jp_clins`、`jp_echeckup`、`us_core`) を適用するか。builder は country を受け取り、profile 構造を出力言語から決めない (Issue #3216)。 |

## 4. コードと表示名

Governing spec: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md)。

| ヘルパー | 用途 |
|---|---|
| `clinosim/codes` `display(system, code, lang)` | コードの表示名。未登録なら `None` を返すので `display(...) or <明示的な fallback>` と書く。`lookup(...)` は旧 API で新規コードでは禁止。 |
| `clinosim/codes` `code_exists(system, code)` / `code_system(key)` / `system_keys()` / `data_table(name)` | レジストリの存在確認と生のコード表へのアクセス。 |
| `clinosim/codes` `system_key_for(kind, country)` / `get_system_uri(key)` / `system_key_for_uri(uri)` | 国がデータ種別に使うコード体系と、その正準 URI。URI のハードコードは禁止。 |
| `clinosim/codes` `is_english_only_system(key_or_uri)` | 英語表示のみを公開する体系 (LOINC、SNOMED) か。該当する coding は英語の display を保ち、自国語のラベルは `.text` に入れる。 |
| `clinosim/codes` `jlac10_display` / `jp_clins_lab_system` | JLAC10 の表示名と JP-CLINS の検査コード体系。 |
| `clinosim/codes/drugs.py` `identify_drug(text)` / `find_drug(ref)` / `get_drug(id)` / `resolve_drug(id)` / `drug_key(ref)` | id・名称・別名・オーダー文字列からカタログの薬剤を特定する。 |
| `clinosim/codes/drugs.py` `same_drug(a, b)` / `has_drug(meds, drug)` / `medication_matches(med, drugs, classes)` / `drug_classes(ref)` | 薬剤の比較と、薬剤・薬効分類での投薬リスト判定。文字列一致では判定しない。 |
| `clinosim/codes/drugs.py` `drug_display(ref, lang)` / `protocol_drug_name(spec)` | 出力用とプロトコル項目用の薬剤名。 |
| `clinosim/codes/drugs.py` `drug_system_key(code, country)` / `drug_system_uri(code, country)` | 出力する薬剤コードの体系 (米国は RxNorm、日本は YJ)。 |
| `clinosim/codes/drugs.py` `jp_drug_code(ref, route)` / `jp_drug_code_for_name(name, route)` / `rxnorm_scd_code(drug, route, dose, unit)` / `rxnorm_scd_codes(id)` | 製品レベルのコード (YJ、RxNorm SCD)。 |
| `clinosim/codes/drugs.py` `route_class(route)` | 投与経路文字列の経路クラス (経口・注射・吸入 …)。 |
| `clinosim/codes/bcp47.py` `bcp47_display(tag, profile=)` | BCP 47 言語タグの表示名。 |
| `clinosim/codes/hl7_encounter.py` `AdmitSource` / `DischargeDisposition` / `ActPriority` | HL7 の encounter 列挙。文字列リテラルではなく列挙メンバーを使う。 |

## 5. ラベルと自由記述のローカライズ

Governing spec: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) §3–§5。

| ヘルパー | 用途 |
|---|---|
| `clinosim/locale/localized.py` `localized(entry, lang, fallback=)` / `localized_field(record, base, lang)` / `label(catalog, section, key, lang)` | 言語マップの `lang` の値、無ければ英語、それも無ければ明示的な fallback。 |
| `clinosim/locale/localized.py` `language_slot(entry, lang)` | 言語マップのちょうど 1 言語だけ (fallback なし。検査と dual-slot 出力用)。 |
| `clinosim/locale/table.py` `localized_table(name)` / `LocalizedTable` | 内部 slug をキーとする名前付きの表示表・翻訳表。 |
| `clinosim/locale/i18n.py` `t(key, lang, **params)` | キーで引く対象言語のフレーズ (パラメータ埋め込み付き)。 |
| `clinosim/locale/text.py` `resolve_text(value, language, country)` | YAML のテキスト項目 (文字列または言語マップ) を適切な言語で返す。 |
| `clinosim/locale/loaders/narrative.py` `vocab_display(...)` / `load_narrative_display_dict(...)` | narrative 語彙の表示名。 |
| `clinosim/locale/loaders/medical_display.py` `load_med_terms_ja()` | 日本語の医学用語辞書。 |
| `clinosim/locale/free_text.py` `localize_drug_name` / `localize_procedure_name` / `localize_allergen_name` / `localize_free_text` | コード化されていない名称やオーダー文字列の翻訳。 |
| `clinosim/modules/output/fhir_r4/lib/localization.py` `localize_fixed_label(en_label, country)` | FHIR の固定ラベルを国の言語で。 |

## 6. CIF オブジェクトの読み書き

Governing spec: [`implementation-rules.ja.md`](implementation-rules.ja.md) §4。

| ヘルパー | 用途 |
|---|---|
| `clinosim/modules/_shared.py` `get_attr_or_key(obj, name, default)` | dict でも dataclass でもフィールドを読む。新たな `isinstance(x, dict)` 分岐やローカルの `_get` を作らない。 |
| `clinosim/modules/_shared.py` `set_attr_or_key(obj, name, value)` / `get_or_create_container(obj, name, factory)` | どちらの形でもフィールドを書く、または入れ子の list/dict を取得・作成する。 |
| `clinosim/timeutil.py` `parse_iso_datetime(value, lenient=False)` | `datetime`・`date`・ISO 8601 文字列 (末尾 `Z`、オフセット、日付のみ) のいずれかで届く CIF タイムスタンプの読み取り。欠落・解析不能なら `None` を返し、タイムゾーンは変更しない。`lenient=True` は前後の空白除去と先頭日付へのフォールバックも行う。ローカルな `_parse_dt` を書かないこと。 |
| `clinosim/modules/_shared.py` `strip_protocol_prefix(name)` | 薬剤オーダー文字列からプロトコル・分類の接頭辞を外す。 |
| `clinosim/modules/_shared.py` `sanitize_id_token(token, max_len)` | 自由記述を id に使える文字列にする。 |
| `clinosim/modules/_shared.py` `practitioner_name(staff_id, roster_map)` | 職員の名簿上の氏名。 |

## 7. 臨床ドメインのヘルパー

Governing specs: [`medication-lifecycle-spec.ja.md`](medication-lifecycle-spec.ja.md)、[`lab-orders-and-results-spec.ja.md`](lab-orders-and-results-spec.ja.md)、[`encounter-lifecycle-and-export-spec.ja.md`](encounter-lifecycle-and-export-spec.ja.md)。

| ヘルパー | 用途 |
|---|---|
| `clinosim/modules/disease/severity.py` `sample_severity` / `sample_severity_category` / `category_from_score` | 重症度の抽選と、スコア ↔ カテゴリの境界 (`SEVERITY_SCORE_RANGES`)。 |
| `clinosim/modules/physiology/engine.py` `scenario_flags_from_protocol` + `medication_flags_from_context` | 検査値導出に `**flags` として渡すフラグ。 |
| `clinosim/modules/observation/engine.py` `canonical_lab_name(name)` / `get_lab_unit(name)` | 検査の正準名と標準単位。 |
| `clinosim/modules/observation/engine.py` `medications_in_effect(home_medications, medication_orders, admission_date, current_day)` | 入院中のある日に検査値へ作用している薬剤。 |
| `clinosim/modules/physiology/statin_response.py` `statin_intensity(med)` / `statin_ldl_reduction(patient_id, medications)` / `ldl_reduction(patient_id, medications)` / `statin_treated_ldl(untreated_ldl, reduction)` | 薬剤と用量から決まるスタチンの強度、患者のスタチンが未治療 LDL から除く患者ごとの割合、その後に非スタチン追加薬 (エゼチミブ) を掛けた割合、その低下後の LDL。脂質低下薬で下がる LDL (検査値導出、健診) はすべてこれを通す。 |
| `clinosim/modules/physiology/engine.py` `lipid_panel(sex, has_diabetes, has_dyslipidemia, ldl_reduction)` / `patient_lipid_panel(patient)` | 脂質状態の TC / HDL / TG / LDL 真値、および患者の疾患と常用薬から得るその値。入院・外来の検査値と健診の両方が読み、患者ごとの未治療 LDL は一つになる。 |
| `clinosim/modules/order/panel_grouping.py` `classify_lab_specs(...)` | 検査オーダーをパネルと単項目に分ける。 |
| `clinosim/modules/order/engine.py` `place_imaging_orders(...)` | 画像検査オーダー。 |
| `clinosim/modules/order/absolute_dose.py` `is_continuous_infusion(frequency, name="")` | オーダーが持続投与(用量が速度)かを、頻度と名前から判定する。 |
| `clinosim/modules/order/absolute_dose.py` `is_one_time_infusion(name)` | 頻度のないオーダーが 1 回の時間指定投与(「Alteplase 100mg IV over 2h」)かを判定する。`enrich_medication_order` はこれを毎日投与でなく単回投与にする (Issue #3043)。 |
| `clinosim/modules/drug_safety/engine.py` `allergy_entries(allergies)` | 患者のアレルギー記録から有効なアレルゲンコードを取り出す (非活動・否定・「アレルギーなし」は除外)。`check_candidate_against_allergies` の入力。 |
| `clinosim/modules/drug_safety/engine.py` `check_candidate_against_allergies(candidate, allergen_codes)` | 候補薬を患者のアレルゲンコードと照合した、許可されない判定。処方経路はアレルギー照合を自作せず、これ (または `allergy_skip_verdict`) を呼ぶ。 |
| `clinosim/modules/drug_safety/engine.py` `allergy_skip_verdict(candidate, allergies)` | 患者のアレルギー記録で候補薬を除外する最も重い判定。投与可能なら None。 |
| `clinosim/modules/drug_safety/engine.py` `conflict_display(verdict)` | 判定が何と競合したかの (英語, 日本語) 表示。`SafetySkipEntry` 用で、記録されたアレルギーまたは有効薬を返す。 |
| `clinosim/simulator/medication_pipeline.py` `allergy_blocked(patient, drug_name, ...)` | 代替薬を出せない処方 (継続処方・固定バンドル項目) で、アレルギーにより除外なら True (スキップを記録)。 |
| `clinosim/simulator/medication_pipeline.py` `log_allergy_skip(patient, drug_name, verdict, ...)` | アレルギーで除外した処方項目を、代替薬があればそれも添えて `patient.safety_skip_log` に記録する。 |
| `clinosim/modules/order/pediatric_dose.py` `pediatric_order_name(name, age_months, weight_kg)` | 成人固定用量のオーダーを小児の体重から再計算する。最小月齢未満なら None。 |
| `clinosim/simulator/encounter_setup.py` `extend_visit_to_procedures(encounter, procedures)` | 受診が最後の処置の終了まで続くよう延長する。 |
| `clinosim/simulator/encounter_setup.py` `fit_procedures_in_stay(procedures, start, end)` | 各処置を在院期間内に収める (`end` が None なら在院中)。 |
| `clinosim/modules/observation/pediatric_ranges.py` `age_in_completed_months(birth, when)` | 小児の満月齢 (日付不明なら None)。 |
| `clinosim/modules/observation/pediatric_ranges.py` `pediatric_vital_range(vital, age_months)` / `pediatric_vital_range_text` / `age_independent_vital_range_text` | 月齢に応じた小児バイタル基準範囲と `referenceRange.text`。None は成人範囲を使う。 |
| `clinosim/modules/observation/pediatric_ranges.py` `pediatric_lab_range(lab_name, age_years, sex)` / `pediatric_lab_center` / `pediatric_lab_band` / `pediatric_lab_range_text` | 小児の検査基準範囲 (中点・年齢帯・表示文を含む)。None は成人範囲を使う。 |
| `clinosim/modules/staff/engine.py` `scoped_nurses(roster, ward=, department=)` | 病棟の看護師、無ければ診療科、それも無ければ全看護師。 |
| `clinosim/modules/diagnosis/nonspecific_codes.py` `is_visit_reason_zcode(code)` | Z コードが診断ではなく受診理由か。 |
| `clinosim/modules/document/engine.py` `_compute_los_days` *(モジュール内部、narrative pass も使用)* | 在院日数 (入院中の代替値を含む)。 |

## 8. FHIR の組み立て (Layer 4)

Governing guide: [`fhir-data-generation-logic.ja.md`](fhir-data-generation-logic.ja.md) (表示の規則は code-mapping spec が優先)。

| ヘルパー | 用途 |
|---|---|
| `clinosim/modules/output/fhir_r4/lib/context.py` `BundleContext` | 全ビルダー共通の入力 (record、国、名簿、病院設定)。 |
| `clinosim/modules/output/fhir_r4/lib/common.py` `system_coding(system_key, code, lang)` / `dual_slot_concept(system_key, code, lang, text=)` | すべての Coding と CodeableConcept。英語のみの体系の dual-slot 規則を内蔵。 |
| `clinosim/modules/output/fhir_r4/lib/common.py` `display_entry(text)` | `{"display": text}` または `{}`。Coding に空の display を入れない。 |
| `clinosim/modules/output/fhir_r4/lib/common.py` `build_diagnosis_codeable_concept`, `severity_coding`, `survey_category`, `make_participant`, `build_reference_range`, `build_address`, `build_telecom`, `build_presented_form`, `map_encounter_status`, `entry` | Condition・Observation・Encounter・Patient・DiagnosticReport の定型部品。 |
| `clinosim/modules/output/fhir_r4/lib/dosage.py` `build_dosage_instruction`, `build_route_concept`, `canonicalize_route`, `resolve_timing_repeat`, `frequency_in_text`, `is_rate_unit`, `augment_iv_dosage_with_rate`, `map_mar_status` | 用法・経路・タイミング・投与ステータス。 |
| `clinosim/modules/output/fhir_r4/lib/reference_data.py` `iter_route_values(data)` / `validate_yaml_route_value(...)` | プロトコル YAML の投与経路値をすべてたどり検証する。 |
| `clinosim/modules/output/fhir_r4/lib/fhir_time.py` `to_fhir_datetime` / `to_fhir_instant` / `to_fhir_date` / `to_fhir_deceased_datetime` / `tz_suffix_for_country` / `derive_meta_last_updated` | すべての FHIR の date・dateTime・instant (国のタイムゾーン付き)。 |
| `clinosim/modules/output/fhir_r4/lib/ids.py` `derive_opaque_id` / `structural_key_system` / `wrap_as_identifier` | リソース id と、構造キーを往復できる identifier。 |
| `clinosim/modules/output/fhir_r4/lib/ecs_extensions.py` `attach_ecs_institutional_extensions` / `build_ecs_institution_extension` / `build_ecs_department_extension` | JP eCS の医療機関・診療科 extension。 |
| `clinosim/modules/output/fhir_r4/demographics/patient.py` `patient_ref` / `clinosim/modules/output/fhir_r4/encounters/encounter.py` `encounter_ref` / `clinosim/modules/output/fhir_r4/conditions/primary_ref.py` `primary_condition_ref` | 患者・encounter・主病名への参照。`"Patient/" + id` を手で組まない。 |
| `clinosim/modules/output/fhir_r4/labs/coding_package.py` `load_lab_coding_package(...)` | 国ごとの検査コード (LOINC / JLAC10)。 |

## 9. Narrative の文言 (Stage 2 テンプレート)

Governing spec: [`narrative-and-document-generation-spec.ja.md`](narrative-and-document-generation-spec.ja.md)。

| ヘルパー | 用途 |
|---|---|
| `clinosim/modules/document/narrative/_vitals_line.py` `format_vitals_line` | 全文書が使う唯一のバイタル行。 |
| `clinosim/modules/document/narrative/_narrative_interpretation_thresholds.py` `bmi_band` / `bp_band` | BMI と血圧の文言の区分。 |
| `clinosim/modules/document/narrative/_safety_skips.py` `safety_skip_line` | 保留・スキップされた投与 (安全イベント) の文。 |
| `clinosim/modules/document/narrative/_template_helpers.py` `allergen_display` | 文書中のアレルゲン名。 |
| `clinosim/modules/document/narrative/_hedging.py` `hedged_phrase` | 決定的に選ぶ留保付きの臨床表現。 |
| `clinosim/modules/document/narrative/_chronic_soap.py` `resolve_chronic_soap` | 外来記録の慢性疾患 SOAP 文。 |
| `clinosim/modules/document/narrative/_replacement_localization.py` `localize_token` | replacement strategy のセクション内のトークンのローカライズ。 |

English counterpart: [`shared-helpers-catalog.md`](shared-helpers-catalog.md).
