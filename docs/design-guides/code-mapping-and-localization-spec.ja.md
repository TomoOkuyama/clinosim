# コードマッピング・名称解決・多言語対応 仕様

位置づけ: **規範 (normative)**。コード・コード体系・多言語名称を追加、対応付け、解決、表示する変更は、すべてこの文書に従う。従えない場合は、同じ PR でこの文書を理由とともに改訂する。

英語版: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md)。

## 1. 原則

1. **1 つの事実は 1 つのソースに置く。** コード、コード体系 URI、表示名、対応表は、それぞれ 1 つのデータファイルにだけ置く。Python はそれを読むだけで、書き写さない。
2. **権威ソース・語彙ごとに解決関数は 1 つ。** LOINC 表示、薬の日本語名、診療科名など、名前解決の種類ごとに関数を 1 つ用意する。FHIR、narrative、LLM プロンプト、CSV、eval、audit、benchmarks は、すべてその関数を呼び、再実装しない。
3. **CIF はコード、名称は出力時。** CIF にはコードと内部 id だけを保存する (AD-30)。表示名は FHIR / narrative / CSV の出力時に解決する。
4. **捏造しない。** コードは権威ソースで照合してから登録する (§7)。照合済みのコードがないものは、推測で埋めず未コードのままにする。
5. **言語の追加はデータの変更だけで済む。** コード側で特定の言語に分岐するのは、§5 の関数を経由する場合に限る。

## 2. 層

| 層 | パッケージ | 持つもの | import してよい範囲 |
|---|---|---|---|
| 権威コード体系 | `clinosim/codes/` | 登録コード、URI、表示名、value set、薬・処置・職種カタログ、UCUM、JIS X 0401、名前付き SNOMED 概念 | 上位層は import しない (`clinosim.locale` / `clinosim.modules` 禁止) |
| 国別・表示データ | `clinosim/locale/` | 国別コード対応、コードを持たない語彙の表示表、フレーズカタログ、国→言語 | `clinosim.codes` |
| 利用側 | `clinosim/modules/` / `simulator/` / `eval/` / `audit/` / `benchmarks/` | 判定ロジック、出力処理 | 上の 2 層。§4 の関数経由に限る |

## 3. YAML の書き方

### 3.1 コード体系レジストリ — `clinosim/codes/data/<system-key>.yaml`

```yaml
metadata:
  name: HL7 FHIR Discharge Disposition
  uri: http://terminology.hl7.org/CodeSystem/discharge-disposition   # 正規 URI (仕様の fixedUri)
  source: "HL7 Terminology (THO)"                                    # 照合した権威ソース
codes:
  home: {en: "Home", ja: "自宅退院"}
  exp:  {en: "Expired", ja: "死亡退院"}
```

- ファイル名が**システムキー**で、すべての解決関数がこのキーを使う (`loinc`, `snomed-ct`, `icd-10-cm`, `hl7-discharge-disposition` …)。
- `codes.<code>.en` は**必須**で、権威ソースの表示名 (LOINC の Long Common Name、SNOMED の preferred term など) と一致させる。他の言語は ISO-639-1 のキー (`ja` …) で任意に持つ。
- コードデータを持たず URI だけ使う体系は、`_BUILTIN_URIS` (`codes/loader.py`) にキーで登録する。複数のキーでデータを共有する仕組みが 2 つある。
  - **データ alias** (`_SYSTEM_DATA_ALIASES`): 同じデータを別の URI で使う。例: `icd-10-mhlw` → `icd-10`。
  - **表示 sibling** (`_SYSTEM_LOOKUP_SIBLINGS`): 表示だけ別の体系にフォールバックする。例: `yj` → `hot7`。
- 権威ソースのスナップショットは `clinosim/codes/authoritative/` に置く (§7)。

### 3.2 国別コード対応 — `clinosim/locale/<cc>/code_mapping_<domain>.yaml`

```yaml
# locale/jp/code_mapping_lab.yaml
WBC: "2A010"
CRP: "5C070"
```

- ドメイン `lab` / `drug` / `diagnosis` / `procedure` ごとに、**内部名**をその国で出力するコードに対応付ける。
- 値のコード体系は `codes.system_key_for(kind, country)` で決まる。例: `lab`/`US` は `loinc`、`lab`/`JP` は `jlac10`。
- 値はすべて、そのコード体系のレジストリに登録されていること。

### 3.3 カタログ — コードと名称を持つ同一性

| カタログ | ファイル | エントリ形式 |
|---|---|---|
| 薬 | `codes/data/drugs.yaml` | `<drug_id>: {names: {en, ja}, codes: {rxnorm, yj: {<route_class>: <YJ12>}}, classes: [...], aliases: [...]}` |
| 処置 | `codes/data/clinosim-procedure-catalog.yaml` | `bedside: [{type, cpt, k_code, name: {en, ja}, anesthesia}]` |
| 職種 | `codes/data/clinosim-clinician-role.yaml` | `<role>: {title: {en, ja}, staff_prefix, suffix_en, suffix_ja, practitioner_role, qualification: {code, display, display_en}}` |
| 診療科 | `locale/shared/department_display.yaml` | `<dept>: {en, ja, specialty_snomed}` |

カタログの id (`drug_id`、処置の `type`、職種、診療科) が安定した内部識別子になる。コードや名称はこの id から引き、逆向きには引かない。

**JP の薬コード。** YJ コードは 1 つの製品 (剤形と規格) を指す。そのため `codes.yj` は投与経路の区分 (`oral` / `injection` / `inhalation` / `rectal` / `topical` / `intravesical`。`drugs.yaml` 冒頭の `route_classes` 表) から 12 桁の YJ コードへの対応表にする。

- **順序。** よく使う経路を先に書く。経路が無い参照には先頭のコードが `codes["yj"]` として返る。
- **選び方。** シミュレータの通常用量に合う規格の製品を選び、先発品を優先する。
- **検証。** どのコードも MHLW の YJ マスタ (スナップショット: `codes/authoritative/yj_mhlw_snapshot.json`) と `JP_MedicationCodeYJ_CS_full.json` の両方に載っている。
- **製品が無い経路。** その経路に収載製品が無い薬はコードを持たず、eCS の `nocoded` slice で出力する。
- **使わないもの。** 7 桁の YJ prefix をコードとして使わない。`hot7.yaml` にはコードを登録しない。

### 3.4 Value set — `clinosim/codes/data/valuesets.yaml`

```yaml
groups:
  diabetes: {space: internal, match: prefix, members: [E11, E10, E13]}
```

- `space` は `internal` (CIF の慢性疾患に保存されたコード) か `emitted` (国別対応を通した後のコード)。
- `match` は `prefix` か `exact`。
- internal のグループは、疾患 YAML から参照できる「名前付き患者条件」も兼ねる。
- 判定ロジックでのコード所属判定は value set だけで行い、条件式にコードのリテラルを書かない。

### 3.5 コードを持たない語彙の表示表 — `clinosim/locale/shared/<vocabulary>.yaml`

```yaml
occupation:
  office: {en: Office worker, ja: 事務職}
```

- 内部 slug をキーにし、slug と言語ごとに 1 エントリ。
- 語彙ごとに表は 1 つ。例:
  - `vocabulary.yaml` — 職業、喫煙、飲酒、来院手段
  - `narrative_imaging.yaml` — 画像検査
  - `department_display.yaml`
- FHIR、narrative、LLM プロンプトは同じ表を読む。同じ語彙の写しを作ってはいけない。

### 3.6 フレーズカタログ — `clinosim/locale/shared/narrative_phrases.yaml`

ドット区切りのキー (`prescription.next_visit`) で文テンプレートを持ち、`{placeholder}` で引数を受ける。読み出しは `t(key, lang, **kwargs)`。

### 3.7 疾患・encounter プロトコル

疾患 YAML は、自分が持つコードを自身のフィールドで表す: `icd_codes` (primary / variants / `by_chronic_prefix`)、`implied_chronic_codes`、`sequela_code`。薬は `drug_id` で、患者条件は value set 名で参照する。encounter condition の YAML も同じ規則に従う。

## 4. 解決関数

利用側はこれらの関数でしか名前を解決しない。いくつかは未 merge の PR で追加される。まだ存在しない関数は §9 に挙げる。

### 4.1 コード体系 (`clinosim.codes`)

| 関数 | 返すもの | ヒットしない場合 |
|---|---|---|
| `display(system, code, lang)` | `lang` の表示名、なければ英語 | `None` |
| `code_exists(system, code, *, exact=False)` | 登録の有無 | `False`。未知の体系なら例外 |
| `get_system_uri(system)` / `system_key_for_uri(uri)` | URI とキーの相互変換 | `urn:clinosim:<key>` / `None` |
| `system_key_for(kind, country)` | ドメインと国に対応するシステムキー | 未知の kind なら例外 |
| `is_english_only_system(key_or_uri)` | 表示が英語のみの体系か (§5.3) | — |
| `jp_clins_lab_system(kind)` / `jlac10_display(code, lang)` | JP 検査コード体系の URI / JLAC10 表示 | 例外 / `None` |
| `codes.loinc`: `loinc_display` / `loinc_coding` | LOINC 表示 / Coding | `None` / display なしの coding |
| `codes.valuesets`: `concept_group` / `has_condition` / `patient_condition_names` / `code_by_chronic_prefix` | value set への所属 | 未知のグループなら `KeyError` |
| `codes.drugs`: `resolve_drug` / `get_drug` / `find_drug` / `names_drug` / `drug_name_needles` | 薬の同一性と名称照合 | 例外 / `None` / `False` |
| `codes.drugs`: `route_class(route)` / `jp_drug_code(drug, route)` / `jp_drug_code_table(route)` | 投与経路の区分、薬と経路に対応する JP の YJ 製品コード | `""` / `None` / 該当なし |
| `codes.procedures`: `procedure_code` / `procedure_type_display` / `procedure_code_display` | 処置のコードと名称 | `""` / 人間可読化した type / `None` |
| `codes.ucum`: `ucum_code` / `ucum_quantity` | UCUM コード / FHIR Quantity | 単位をそのまま通す |
| `codes.prefectures.prefecture_code(name)` | JIS X 0401 コード | `""` |
| `codes.snomed_concepts` | 判定ロジックで使う名前付き SNOMED 概念 | — |

`lookup(system, code, lang)` は旧 API で、ヒットしないとコード自体を返す。新しいコードでは `display(...) or <明示フォールバック>` を使う。

### 4.2 国別対応と表示表 (`clinosim.locale.loader`)

| 関数 | 返すもの |
|---|---|
| `load_code_mapping(domain, country)` | その国の内部名 → コード |
| `lab_code(lab_name, country)` / `lab_codes(lab_name)` | `(system_key, code)` / 全ロケールのコード |
| `vocab_display(vocab, slug, lang, *, fallback)` | 語彙の表示名 (`vocabulary.yaml`) |
| `narrative_label(section, key, lang, fallback)` | narrative のラベル |
| `imaging_exam_display(exam_id, lang)` | 画像検査名 |
| `department_display(dept, lang)` / `department_specialty_snomed(dept)` | 診療科名 / 専門科コード |
| `role_display(role, lang, *, facet)` | 職種の名称・接尾辞・資格 |
| `chronic_followup_vitals(code)` / `chronic_followup_interval_months(codes)` | 慢性疾患フォローアップの予定データ |
| `t(key, lang, **kwargs)` (`clinosim.locale.i18n`) | フレーズ |

### 4.3 出力用ヘルパ

| 関数 | 用途 |
|---|---|
| `modules.output.fhir_r4.lib.common.dual_slot_concept(system_key, code, lang, *, text, fallback_display)` | コード付きの CodeableConcept はすべてこれで組み立てる (§5.3) |
| `modules.output.fhir_r4.lib.common.system_coding(system_key, code, lang, *, fallback_display)` | `text` を持たない Coding 型の要素 (`Encounter.class` など) (§5.3) |
| `modules._shared.practitioner_name(staff_id, roster_map)` | 医療者名。ヒットしなければ `""` |
| `modules._shared.pick_localized_field(record, base, lang)` | CIF の `<base>_<lang>` フィールド |
| `simulator.event_refs.event_ref_kind(value)` | `disease_id` / ground truth の値の名前空間 |

## 5. 多言語対応

### 5.1 出力言語

出力言語は国から決まる: `clinosim.countries.lang_for(country)` (`locale/shared/country_language.yaml`)。大文字小文字は区別せず、対応のない国は英語。`countries.is_jp` / `is_us` は、国ごとのルール (保険点数コード、プロファイル) にだけ使い、表示言語の選択には使わない。

### 5.2 データの形

- **翻訳する文字列**は `{<lang>: text}` エントリで持つ。`x_ja if is_jp(...) else x_en` のインライン分岐は禁止。
- **CIF で言語ごとの文字列**を持つフィールドは、英語を `<base>`、他の言語を `<base>_<lang>` に置き、`pick_localized_field` で読む。
- **言語の追加**はデータに `<lang>` キーを足すだけで済み、コードの変更は要らない。

### 5.3 英語のみのコード体系 (dual slot)

`is_english_only_system` の対象は LOINC、SNOMED CT、HL7 terminology、`http://hl7.org/fhir/`、DICOM、UCUM。これらの体系では次のとおり。

- **JP 出力。** `coding.display` は英語の正規表示、日本語ラベルは `CodeableConcept.text` に置く。coding に日本語 display を入れると検証エラーになる。
- **それ以外の体系。** JP Core / JP-CLINS / MEDIS / YJ / clinosim 独自の体系は、出力言語の表示をそのまま持つ。
- **組み立てる場所。** 出力箇所で `dual_slot_concept` を使って組み立てる。後処理の walker で補完しない。
- **Coding 型の要素。** 型が `Coding` の要素 (`Encounter.class`、`classHistory.class`) には `text` が無い。`system_coding` で組み立て、どの locale でも英語の display を持つ。
- **HL7 の語彙。** 出力する HL7 CodeSystem ごとに、コードをキーにした registry ファイルを置く (`hl7-v3-actcode`、`hl7-v3-actpriority`、`hl7-observation-category`、`hl7-condition-category`、`hl7-v3-participationtype`、`hl7-diagnosis-role`、`hl7-organization-type`、`hl7-observation-interpretation` など)。日本語ラベルはコードで引き、英語の表示名では引かない。

## 6. フォールバック規則

1. **順序。** 要求言語 → 英語 → 呼び出し側が**明示した**フォールバック。
2. **フォールバックにしてはいけないもの。** 他の言語 (英語出力に日本語など)、検索キー、生コード、生 id、生 slug。
3. **コードや id がない場合**、解決関数は `None` / `""` を返す。何を表示するかは呼び出し側が決めて明示的に渡すか、要素ごと省く (「捏造より沈黙」)。
4. **slug の人間可読化** (アンダースコア → 空白) を許すのは、内部 slug の表示表の最後のフォールバックだけ。例: `imaging_exam_display` / `procedure_type_display` / `department_display` は未知の slug を人間可読化する。これを許す条件は、生成側が出す slug がすべて表にあることを unit test で保証していること。`.title()` による slug は常に禁止。
5. **英語エントリの欠落**はデータのバグで、テストで検出する。英語以外の欠落は英語にフォールバックする (規則 1)。

## 7. コードの追加・変更手順

1. **登録前に権威ソースで照合する。**

   | 体系 | 権威ソース |
   |---|---|
   | ICD-10-CM | NLM / CMS |
   | ICD-10 | WHO browser |
   | LOINC | loinc.org か tx.fhir.org `$lookup` |
   | SNOMED CT | tx.fhir.org `$lookup` / SNOMED browser |
   | RxNorm | RxNav |
   | YJ / HOT | MHLW / MEDIS マスタ |
   | JLAC10 | JSLM マスタ |
   | CPT | AMA CPT |
   | K コード | MHLW 診療報酬点数表 |
   | HL7 | THO |
   | JP Core / JP-CLINS の URI | パッケージの fixedUri |

2. **`codes/data/<system>.yaml` に登録する。** `en` は権威ソースの表示名と一致させる。
3. **スナップショットを更新する。** その体系に `codes/authoritative/` のスナップショット (`rxnorm_rxnav_snapshot.json` / `loinc_2_82_tx.json`) があれば更新する。
4. **対応表・カタログにエントリを足す** (§3.2–3.4)。
5. **カバレッジテストを実行する。** 診断コードカバレッジ、権威スナップショット、system URI カバレッジ。

## 8. 禁止パターン

- `clinosim/codes/` の外にコード体系 URI の文字列リテラルを書く。`get_system_uri` を使う。例外は URI ファミリーの prefix リストだけ。
- Python の比較式にコードのリテラルを書く、または Python の dict でコードや表示名を持つ (CPT / LOINC / SNOMED / ICD / YJ …)。value set、カタログ、名前付き概念を使う。
- 同じ語彙やコード対応の表を 2 つ持つ。
- 自由文の部分文字列一致で薬・検査・疾患を同定する。カタログ id、canonical lab name、value set を使う。名称照合で許されるのは `names_drug` だけ。
- 出力に出る slug に `.title()` や素の `replace("_", " ")` をかける (規則 6.4 の場合を除く)。
- コードの表示名を自由文翻訳器 (`localize_drug_name` など) で訳す。コード体系自身の `ja` 表示を使う。
- `lookup(...) or ...` と書く。`lookup` はヒットしなくてもコードを返すので、フォールバック側は使われない。

## 9. 既知の未準拠箇所

次の箇所はまだ仕様に準拠していない。それぞれ記載の Issue で解消する。

| 未準拠箇所 | Issue |
|---|---|
| **フォールバック。** `display` / `lookup`、`resolve_text`、`t` は最後の手段として、最初に見つかった言語・コード・`str(value)`・キーを返す。§6.1–6.2 に反する場合があり、取得 API も 1 本化されていない。 | #2275 |
| ICD の検索・短縮名・crosswalk が 1 つの accessor にまとまっていない (短縮名の表が 2 つ、CM と WHO で日本語表示が食い違う)。 | #2257 |
| SNOMED のコードと表示名を出力側の dict がまだ持っている (route / severity)。SNOMED のリテラル 74 件が未登録。 | #2258 |
| 文書 LOINC の定義が 8 箇所にある。意味の合わない section コードがある。出力側に LOINC 定数が残っている。 | #2344 |
| 疾患 YAML にインラインの `code_yj` が残り、JP の CIF `order_code` がカタログではなくそこから写されている。 | #2351 |
| 生成側が出しているのに未登録の CPT / K コード。 | #2340 |
| `clinosim/codes/` の外に HL7 `terminology.hl7.org` の URI 直書きがあり、coding を組み立てる helper が 3 つ重複している (`_coding_with_display` / `_value` / `_build_hosp_concept`)。 | #2349 |
| 手組みの dual-slot が残っている。後処理で text を補う walker も残っている。 | #2337 |
| 検査項目の表示名が 5 つの表に分かれている。 | #2267 |
| 薬名がカタログではなく自由文翻訳を通っている。 | #2271 |
| Python に言語ごとのリテラルが残っている。 | #2277 |
| レコードが `drug_id` を持っていない。 | #2297 |
| 薬の分類と別名がカタログの外にある。 | #2298 |
| 一部の境界で canonical でない検査名を使っている。 | #2299 |
| 健診の結果が `lab_name` に LOINC コードを入れている。 | #2300 |
| eval の妥当性範囲、パネル定義が 2 つ。 | #2332 |
| §8 を強制する lint guard がない。 | #2266 |
