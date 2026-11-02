# コードマッピング・名称解決・多言語対応 仕様

位置づけ: **規範 (normative)**。コード・コード体系・多言語名称を追加、対応付け、解決、表示する変更は、すべてこの文書に従う。従えない場合は、同じ PR でこの文書を理由とともに改訂する。

英語版: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md)。

## 1. 原則

1. **1 つの事実は 1 つのソースに置く。** コード、コード体系 URI、表示名、対応表は、それぞれ 1 つのデータファイルにだけ置く。Python はそれを読むだけで、書き写さない。
2. **権威ソースごとにアクセサ 1 つ、語彙ごとに解決関数 1 つ。** 権威ソースのデータは権威ごとに専用のファイルに置き、専用のモジュールが読む (§2.2)。LOINC 表示、薬の日本語名、診療科名など、名前解決の種類ごとに関数を 1 つ用意する。FHIR、narrative、LLM プロンプト、CSV、eval、audit、benchmarks は、すべてその関数を呼び、再実装しない。
3. **CIF はコード、名称は出力時。** CIF にはコードと内部 id だけを保存する (AD-30)。表示名は FHIR / narrative / CSV の出力時に解決する。
4. **捏造しない。** コードは権威ソースで照合してから登録する (§8)。照合済みのコードがないものは、推測で埋めず未コードのままにする。表示名は、そのコード自身のものだけを出す。
5. **英語が基底言語。** 翻訳対象のエントリはすべて英語を持つ。他の言語は任意で、無ければ英語にフォールバックする (§6)。
6. **言語の追加はデータの変更だけで済む。** コードは言語を `"ja"` などのリテラルと比較しない。§5 の関数で文字列を選ぶので、新しい言語はデータへのキー追加と `country_language.yaml` の 1 行で足りる。
7. **すべてのルールにガードを置く。** この文書のルールはテストで強制する (§10)。ガードの無いルールは §11 に未対応として載せる。

## 2. 層と権威ソースの分離

### 2.1 層

| 層 | パッケージ | 持つもの | import してよい範囲 |
|---|---|---|---|
| 権威コード体系 | `clinosim/codes/` | 登録コード、URI、表示名、value set、薬・処置・職種カタログ、UCUM、JIS X 0401、名前付き SNOMED 概念 | `clinosim.countries` のみ (`clinosim.locale` / `clinosim.modules` 禁止) |
| 国別・表示データ | `clinosim/locale/` | 国別コード対応、コードを持たない語彙の表示表、翻訳表、フレーズカタログ | `clinosim.codes`、`clinosim.countries` |
| 言語の選択 | `clinosim/countries.py` | 国→言語、言語タグの正規化 (§5.1) | clinosim 内は import しない |
| データファイル | `clinosim/datafiles.py` | データ YAML の唯一の読み込み (`load_data_yaml`、`data_metadata`) と kind の一覧 (§3.1) | clinosim 内は import しない |
| 利用側 | `clinosim/modules/` / `simulator/` / `eval/` / `audit/` / `benchmarks/` | 判定ロジック、出力処理 | 上の層。§4 の関数経由に限る |

### 2.2 1 権威 = 1 組のファイル

**権威**とは、コード体系を定める機関 (NLM、WHO、MHLW、Regenstrief、SNOMED International、HL7、AMA、JSLM、MEDIS など) をいう。権威ごとの資料は、他の権威の資料と混ぜない。

1. **データ。** コード体系ごとに、システムキーを名前にしたレジストリファイルを 1 つ置く (§3.3)。その体系への内部キー対応表や crosswalk は、体系名を付けた別ファイルにする (`loinc-maps.yaml`、`snomed-maps.yaml`)。
2. **アクセサ。** すべてのコード体系は基底クラス `CodeSystem` (§2.3) のインスタンスとする。フックや独自の参照 (対応付け、階層、製品の選択、正規 URI の規則など) が要る権威は、`clinosim/codes/<authority>.py` にサブクラスを 1 つ持ち、そのモジュールは自分の権威のファイルだけを読む。基底クラスだけで足りる権威 (HL7 terminology、CVX、DICOM、OMB、clinosim 独自の体系) は、レジストリファイルから作る素のインスタンスで、モジュールを持たない。
3. **スナップショット。** 権威から照合済みで取り出したデータは `clinosim/codes/authoritative/` に、権威とリリースごとに 1 ファイルで置き (`loinc_2_82_tx.json`、`rxnorm_rxnav_snapshot.json` など)、テストでレジストリと突き合わせる。
4. **カタログは権威をつなぐだけで、権威を持たない。** カタログ (薬、処置、職種) は内部 id、名称、複数の権威のコードを持つ。各コードはその権威のアクセサで解決し、権威の参照規則を再実装しない。

現在の配置:

| 権威 | レジストリファイル | アクセサ | スナップショット |
|---|---|---|---|
| ICD-10-CM (NLM / CMS) | `icd-10-cm.yaml` | `codes/icd10.py` | — |
| ICD-10 (WHO、MHLW 日本語名) | `icd-10.yaml` (alias `icd-10-mhlw`) | `codes/icd10.py` | `icd10_who_tx.json`、`icd10_mhlw_2013_ja.json` |
| MEDIS 病名管理番号 | `medis-disease-keyno.yaml` | `codes/medis.py` | — |
| LOINC | `loinc.yaml`、`loinc-maps.yaml` | `codes/loinc.py` | `loinc_2_82_tx.json` |
| SNOMED CT | `snomed-ct.yaml`、`snomed-maps.yaml`、`procedure-phrase-to-snomed.yaml`、`procedure-snomed-metadata.yaml` | `codes/snomed.py`、`codes/snomed_concepts.py` | — |
| RxNorm | `rxnorm.yaml` | `codes/drugs.py` 経由 | `rxnorm_rxnav_snapshot.json` |
| YJ / HOT (MHLW、MEDIS) | `yj.yaml`、`hot7.yaml` | `codes/yj.py` (形式、YJ マスタ)。薬ごとの製品は `codes/drugs.py` のカタログ | `yj_mhlw_snapshot.json`、`JP_MedicationCodeYJ_CS_full.json`、`yj_tx_fragment.json` |
| JLAC10 / JP-CLINS 検査 | `jlac10.yaml`、`jp-clins-lab-uncoded.yaml` | `codes/jlac10.py` | JP-CLINS パッケージ |
| CPT / K コード | `cpt.yaml`、`k-codes.yaml` | `codes/procedures.py` | `shinryo_koui_ssk_20261013_ja.json` |
| UCUM | `ucum-aliases.yaml` | `codes/ucum.py` | — |
| JIS X 0401 | `jis-x-0401-prefectures.yaml` | `codes/prefectures.py` | — |
| HL7 terminology | `hl7-*.yaml` | 汎用関数、`codes/hl7_encounter.py` (型付きの名前。レジストリと照合) | — |
| JP Core / JP-CLINS / JP eCheckup / MHLW 文書コード | `jpfhir-*.yaml`、`jp-*.yaml`、`mhlw-*.yaml`、`fhir-profiles-*.yaml` | 汎用関数 | — |
| clinosim 独自の体系 | `clinosim-*.yaml` | 汎用関数 | — |

### 2.3 基底クラス

すべてのソースに共通する処理は、基底クラスに 1 度だけ実装し、ソースごとに再実装も上書きもしない。

**`CodeSystem` (codes 層)。** システムキーごとに 1 インスタンスで、そのレジストリファイル (§3.3) から作る。

- **基底クラスが持ち、上書き不可のもの。** `display(code, lang)`、`code_exists(code, *, exact)`、`uri`、言語の正規化 (§5.1)、解決の順序 (§4.4)、フォールバックの順序 (§6)、見つからないときの扱い (`None` を返し、コードは返さない)。サブクラスはこれらを上書きしない。テストで確認する。
- **サブクラスが実装してよいフック。** `parents(code)`: そのコードを一般化したコードを、詳細なものから順に返す (既定は無し。ICD-10 と ICD-10-CM は小数点以下を除いたコード)。参照の兄弟体系はデータとして宣言し (§3.3)、コードには書かない。
- **権威固有の参照。** サブクラスは権威固有の参照をメソッドとして足す。例: 薬と経路区分に対応する YJ 製品、内部キーの LOINC コード、処置の語句に対応する SNOMED コード。
- **レジストリ。** すべてのシステムキーはちょうど 1 つのインスタンスに対応し、テストで全体系を走査できる (スナップショット、URI、`en` の網羅)。

**`LocalizedTable` (locale 層)。** 表示表・翻訳表 (§3.7、§3.8) ごとに 1 インスタンス。

- **基底クラスが持ち、上書き不可のもの。** 読み込みと kind の検証、§6 のフォールバック順序に従う `get(key, lang, *, fallback)`、`en` の規則。
- **宣言するプロパティ。** 未知の slug を人間可読化するか (§6.4) は表のプロパティとし、slug の網羅をテストしている表に限って許す。

**入口。** 利用側はこれまでどおり §4 のモジュール関数 (`codes.display`、`loinc_display`、`vocab_display` など) を呼ぶ。これらの関数がインスタンスに委譲する。利用側はインスタンスを作ったり継承したりしない。カタログ (§3.5) は `CodeSystem` のサブクラスにしない。カタログは内部 id を持ち、コードは `CodeSystem` のインスタンスで解決する。

## 3. YAML の書き方

### 3.1 共通ルール

`clinosim/codes/data/`、`clinosim/locale/`、`clinosim/modules/*/reference_data/` の下のデータ YAML すべてに適用する。

1. **ヘッダ。** ファイルは `metadata` ブロックで始める。`kind` (§3.2 のいずれか)、`name`、`source` (権威ソース、独自データなら `clinosim`) を持ち、コード体系なら `uri`、権威と照合した内容なら `verified` (日付またはリリース) も持つ。ブロックの上にファイルを説明するコメントを置いてよい。
2. **キーは識別子。** キーは内部識別子 (snake_case の slug、カタログ id、正規の検査名、または権威が書くとおりのコード) にする。表示文字列はキーにしない。唯一の例外は翻訳表 (§3.2) で、キーは翻訳元の英語の文字列になる。
3. **コードは文字列。** コードの値は必ず引用符で囲む (`"2A010"`、`"0410"`)。先頭のゼロや数値に見えるコードを壊さないため。
4. **翻訳対象の文字列は言語マップ。** `{en: ..., ja: ...}` で、英語を先に書く。`en` は必須 (翻訳表はキーが英語なので除く)。言語キーは小文字の BCP-47 タグで、通常は ISO 639-1 のコード (`en`、`ja`)。フィールド名に言語を入れない (`title_ja`、`display_en` は不可)。2 つ目の言語はマップのキーを 1 つ足す。
5. **書式。** インデントは空白 2 つ、タブ・アンカー・エイリアスは使わない。1 行に収まるエントリは flow 形式 (`office: {en: Office worker, ja: 事務職}`)、入れ子のあるエントリは block 形式にする。
6. **並び順。** 意味のある順序でない限り、キー順に並べる。順序に意味があるときは `metadata` に書く (例: `drugs.yaml` の YJ 経路区分の順序、§3.5)。
7. **編集。** 手で編集するか、テキストをその場で書き換えるスクリプトを使う。読み込んで書き戻す (load → dump) のは禁止。コメントがすべて消えるため。生成したファイルは、どのスクリプトと元データで作ったかをヘッダに書く。
8. **読み込みと検証。** データファイルはすべて `clinosim.datafiles.load_data_yaml` で読む。この関数は `metadata` ヘッダを除いた中身を返す (ヘッダはセクションではない)。ヘッダは `data_metadata` で取る。各ファイルの `kind` と置き場所はテストで確認し、ローダは未知のフィールドを無視せずエラーにする。

### 3.2 種類と置き場所

| `kind` | 中身 | 置き場所と名前 |
|---|---|---|
| `code-system` | 1 つの体系のコードと表示名 | `codes/data/<system-key>.yaml` (§3.3) |
| `map` | 内部キー → 1 つの体系のコード | `codes/data/<system-key>-maps.yaml` |
| `crosswalk` | コードや語句 → 別の体系のコード | `codes/data/<from>-to-<to>.yaml` または `<from>-<subject>-crosswalk.yaml` |
| `catalog` | コードと名称を持つ内部識別子 | `codes/data/` (§3.5) |
| `value-set` | コードの名前付きグループ | `codes/data/valuesets.yaml` (§3.6) |
| `country-mapping` | 内部名 → その国が出力するコード | `locale/<cc>/code_mapping_<domain>.yaml` (§3.4) |
| `display-table` | 内部 slug → 表示名 (コードを持たない語彙) | `locale/shared/<vocabulary>.yaml` (§3.7) |
| `translation-table` | 英語の元文字列 → 他の言語 (生成器が英語の自由文字列で書くもの) | `locale/shared/` |
| `phrase-catalog` | 文テンプレート | `locale/shared/narrative_phrases.yaml` (§3.8) |
| `protocol` | 疾患・encounter のプロトコル (§3.9) | `modules/disease/reference_data/`、`modules/encounter/reference_data/` |
| `reference` | 閾値、キーワード一覧、コードでも表示でもない内容 | 規則を持つモジュールの `<module>/reference_data/`。locale 層がローダー (`load_chronic_followup` など) で多くのモジュールに提供するものは `locale/shared/` |

`codes/data` に置くのは `code-system`、`map`、`crosswalk`、`catalog`、`value-set` だけとする。

### 3.3 コード体系レジストリ

```yaml
metadata:
  kind: code-system
  name: HL7 FHIR Discharge Disposition
  uri: http://terminology.hl7.org/CodeSystem/discharge-disposition   # 正規 URI (仕様の fixedUri)
  source: "HL7 Terminology (THO)"                                    # 照合した権威ソース
codes:
  home: {en: "Home", ja: "自宅退院"}
  exp:  {en: "Expired", ja: "死亡退院"}
```

- ファイル名が**システムキー**で、すべての解決関数がこのキーを使う (`loinc`, `snomed-ct`, `icd-10-cm`, `hl7-discharge-disposition` …)。
- `codes.<code>.en` は**必須**で、権威ソースの表示名 (LOINC の Long Common Name、SNOMED の preferred term など) と一致させる。他の言語は任意のキーとする。
- コードデータを持たず URI だけ使う体系は、`_BUILTIN_URIS` (`codes/loader.py`) にキーで登録する。複数のキーでデータを共有する仕組みが 2 つある。
  - **データ alias** (`_SYSTEM_DATA_ALIASES`): 同じデータを別の URI で使う。例: `icd-10-mhlw` → `icd-10`。
  - **参照の兄弟体系** (`_SYSTEM_LOOKUP_SIBLINGS`): 表示名の参照を別の体系にフォールバックさせる。例: `yj` → `hot7`、ICD-10-CM のコードが同じ WHO コードの MHLW 日本語名を使う。
- 生成器がコードでなく slug で指す体系 (OMB の人種・民族) は、同じファイルに `slug_to_code` ブロックを置き、`slug_to_code` で読む。

### 3.4 国別コード対応

```yaml
# locale/jp/code_mapping_lab.yaml
WBC: "2A010"
CRP: "5C070"
```

- **内部名**を、その国が出力するコードに対応付ける。ドメインは `lab` / `drug` / `diagnosis` / `procedure`。
- 値のコード体系は `codes.system_key_for(kind, country)` で決まる。例: `lab`/`US` は `loinc`、`lab`/`JP` は `jlac10`。
- 値はすべて、その体系のレジストリファイルに登録されている。

### 3.5 カタログ

| カタログ | ファイル | エントリの形 |
|---|---|---|
| 薬 | `codes/data/drugs.yaml` | `<drug_id>: {names: {en, ja}, codes: {rxnorm, yj: {<route_class>: <YJ12>}}, classes: [...], aliases: [...]}` |
| 処置 | `codes/data/clinosim-procedure-catalog.yaml` | `bedside: [{type, cpt, k_code, name: {en, ja}, anesthesia}]` |
| 職種 | `codes/data/clinosim-clinician-role.yaml` | `<role>: {title: {en, ja}, staff_prefix, suffix: {en, ja}, practitioner_role, qualification: {code, display: {en, ja}}}` |
| 診療科 | `locale/shared/department_display.yaml` | `<dept>: {en, ja, specialty_snomed}` |

カタログ id (`drug_id`、処置の `type`、職種、診療科) が安定した内部識別子で、コードや名称はそこから引く。逆向きには引かない。

**JP の薬剤コード。** YJ コードは 1 つの製品を指し、剤形と規格もそれで決まる。そのため `codes.yj` は経路区分 (`oral` / `injection` / `inhalation` / `rectal` / `topical` / `intravesical`。`drugs.yaml` 冒頭の `route_classes` 表) を 12 桁の YJ コードに対応付ける。

- **順序**: よく使う経路を先に書く。経路のない参照では、先頭の `codes["yj"]` を使う。
- **選び方**: シミュレータの標準用量に合う製品を選び、先発品を優先する。
- **照合**: すべて MHLW YJ マスタ (スナップショット `codes/authoritative/yj_mhlw_snapshot.json`) と `JP_MedicationCodeYJ_CS_full.json` に載っている。
- **製品がない場合**: その経路に収載製品のない薬はコードを持たず、eCS の `nocoded` slice で出力する。
- **使わないもの**: YJ の 7 桁接頭辞はコードとして使わない。`hot7.yaml` にはコードを登録しない。

### 3.6 Value set

```yaml
groups:
  diabetes: {space: internal, match: prefix, members: [E11, E10, E13]}
```

- `space` は `internal` (CIF の慢性疾患に保存された形のコード) か `emitted` (国別対応を通した後のコード)。
- `match` は `prefix` か `exact`。
- internal のグループは、疾患 YAML から参照できる名前付き患者状態にもなる。
- 判定ロジックがコードの該当を調べるときは value set を使う。条件にコードのリテラルを書かない。

### 3.7 表示表

```yaml
occupation:
  office: {en: Office worker, ja: 事務職}
```

- 内部 slug をキーにし、slug ごとに言語マップを 1 つ持つ。
- 語彙ごとに表は 1 つ。例:
  - `vocabulary.yaml`: 職業、喫煙、飲酒、来院方法
  - `narrative_imaging.yaml`: 画像検査
  - `lab_display.yaml`: 検査項目とパネル。小文字化した検査トークンをキーにする。言語マップは臨床での略称で、任意の `formal` マップに正式な項目名を持つ。
  - `department_display.yaml`
- FHIR、narrative、LLM プロンプトは同じ表を読む。同じ語彙の 2 つ目の表は作らない。コードを持つ語彙は、表示表ではなくそのコード体系から名称を取る (§5.3)。

### 3.8 翻訳表とフレーズカタログ

- **翻訳表。** 生成器が英語の自由文字列で書く名称 (オーダ文字列、薬剤用語) は、翻訳表で英語の文字列を他の言語に対応付ける: `"dvt prophylaxis": {ja: DVT予防}`。§4.3 の自由文字列用の解決関数からのみ読む。コードの表示名は訳さない (それはコード体系自身の `ja`)。データファイルが元になっている文字列も持たない (その文字列は元の場所で言語マップを持つ)。
- **フレーズカタログ。** ドット区切りの id (`prescription.next_visit`) をキーにした文テンプレートで、`{placeholder}` の引数を取る。`t(key, lang, **kwargs)` で読む。

### 3.9 疾患・encounter プロトコル

疾患 YAML は、自分が持つコードを `icd_codes` (primary / variants / `by_chronic_prefix`)、`implied_chronic_codes`、`sequela_code` で参照する。薬は `drug_id` で、患者状態は value set 名で参照する。表示する文字列 (主訴、注記) はプロトコル自身の中で言語マップとして持つ。encounter condition の YAML も同じ規則に従う。

## 4. 解決関数

利用側は、名称をこれらの関数でのみ解決する。

### 4.1 コード体系 (`clinosim.codes`)

| 関数 | 返すもの | 見つからないとき |
|---|---|---|
| `display(system, code, lang)` | `lang` の表示名、なければ英語 (§4.4) | `None` |
| `code_exists(system, code, *, exact=False)` | 登録の有無 | `False`。未知の system は例外 |
| `get_system_uri(system)` / `system_key_for_uri(uri)` | URI ↔ キー | `urn:clinosim:<key>` / `None` |
| `data_table(name)` | 専用アクセサのない表の `codes/data/<name>.yaml` (コピー) | `FileNotFoundError` |
| `system_key_for(kind, country)` | ドメインと国に対応するシステムキー | 未知の kind は例外 |
| `is_english_only_system(key_or_uri)` | 表示名が英語のみの体系か (§5.3) | — |
| `slug_to_code(system)` | 体系の `slug_to_code` ブロック | `{}` |
| `code_system(system)` / `system_keys()` | 体系の `CodeSystem` インスタンス (§2.3) / 全体系を走査するテスト用の全システムキー | `None` / — |
| `jp_clins_lab_system(kind)` / `jlac10_display(code, lang)` | JP 検査 CodeSystem URI / JLAC10 表示名 | 例外 / `None` |
| `codes.loinc`: `loinc_display`, `loinc_coding` | LOINC 表示名 / Coding | `None` / display なし coding |
| `codes.loinc`: `loinc_for(kind, key)`, `loinc_map(kind)` | 内部キーの LOINC コード (`codes/data/loinc-maps.yaml`: anthropometric、blood_group、care_level、report、section、apgar、newborn_screen) | 未知の kind / key は `KeyError` |
| `modules.document.narrative.registry.document_loinc(doc_type)` | 文書種別の LOINC コード。`document_type_specs.yaml` に 1 度だけ定義する | 未知の種別は例外 |
| `codes.valuesets`: `concept_group`, `has_condition`, `patient_condition_names`, `code_by_chronic_prefix` | value set の該当判定 | 未知のグループは `KeyError` |
| `codes.drugs`: `resolve_drug`, `get_drug`, `find_drug`, `drug_key(ref)`, `same_drug(a, b)` | 薬の同定。同一性キー (カタログ id、なければ正規化した名前) と、2 つの参照が同じ薬か (部分一致は使わない) | 例外 / `None` / `""` / `False` |
| `codes.yj`: `jp_drug_system_key(code)`, `is_verified_yj(code)` | JP の薬剤コードの形式 (YJ、HOT7 / HOT9 / HOT13) に対応するレジストリキー / YJ コードが国の YJ マスタにあるか | `hot9` / `False` |
| `codes.drugs`: `route_class(route)`, `jp_drug_code(drug, route)`, `jp_drug_code_table(route)` | オーダ経路の経路区分 / 薬と経路に対応する JP の YJ 製品 | `""` / `None` / エントリなし |
| `codes.drugs`: `drug_display(ref, lang)` | 薬の id・名前・別名 (なければ先頭語の最長一致) のカタログ名を `lang` で、なければ英語で返す | `None` |
| `codes.drugs`: `identify_drug(text)`, `drug_classes(ref)` | 自由文字列の薬剤名が指すカタログの薬 (id / 名前 / 別名の完全一致、先頭語、含まれる最長の名前・別名の順。ASCII は単語境界で照合) / 薬の分類 (ドット区切りの上位分類を含む) | `None` / `()` |
| `codes.drugs`: `drug_ref(name_or_id)`, `has_drug(meds, drug_id_or_class)`, `medication_matches(med, drugs, classes)` | 名前・別名・自由文字列が指すカタログの `drug_id` / 投薬記録にその薬またはその分類の薬があるか (`drug_id`、なければ名前で判定) | `""` / `False` |
| `codes.icd10`: `icd10_system(country)`, `icd10_display(code, country, lang)`, `condition_short_name(code, lang)`, `condition_label(code, country, lang)`, `medis_disease_keyno(icd)` | 国の ICD-10 体系 / 正式表示名 (JP の日本語は MHLW 2013 の名称をそのまま) / 臨床略称 (カテゴリ単位) / 文章と `Condition.code.text` に使う名称 (略称、なければ正式表示名) / MEDIS 病名管理番号 | キー / `None` / `None` / `None` / `None` |
| `codes.procedures`: `procedure_code`, `procedure_type_display`, `procedure_code_display` | 処置コードと処置名 | `""` / 人間可読化した type / `None` |
| `codes.ucum`: `ucum_code`, `ucum_quantity`, `ucum_prose` | UCUM コード / FHIR Quantity / 文章中の単位表記 (`mm[Hg]` → `mmHg`、`{INR}` → `""`) | 単位をそのまま返す |
| `codes.prefectures.prefecture_code(name)` | JIS X 0401 コード | `""` |
| `codes.snomed_concepts` | ロジックで使う名前付き SNOMED 概念 | — |
| `codes.snomed`: `snomed_display(code, lang)`, `snomed_for(kind, key)`, `snomed_map(kind)`, `snomed_for_phrase(text)` | SNOMED 表示名 / 内部キー → コード (`route`、`severity`、`abo`、`rh`、`cchd_site`、`encounter_type`、`oxygen_device`、`stage`、`procedure_category`、`order_category`、`specimen_type`、`newborn_screen`。`codes/data/snomed-maps.yaml`) / 処置・オーダの自由文字列 → コード (`codes/data/procedure-phrase-to-snomed.yaml` で最初に合う語句) | `None` / `None` / `KeyError` / `None` |

`lookup(system, code, lang)` は、見つからないときに `""` を返す `display(...)` で、コード自身は返さない。新しいコードでは `display(...) or <明示的な代替>` を使う。

### 4.2 国別対応・表示表 (`clinosim.locale.loader`)

| 関数 | 返すもの |
|---|---|
| `load_code_mapping(domain, country)` | その国の内部名 → コード |
| `lab_code(lab_name, country)` / `lab_codes(lab_name)` | `(system_key, code)` / 全ロケールのコード |
| `vocab_display(vocab, slug, lang, *, fallback)` | 語彙の表示名 (`vocabulary.yaml`) |
| `narrative_label(section, key, lang, fallback)` | narrative のラベル |
| `imaging_exam_display(exam_id, lang)` | 画像検査名 |
| `lab_display(name, lang, *, style, fallback)` | 検査項目・パネル名。narrative、LLM テキスト、`DiagnosticReport.conclusion` には `style="prose"`、標準コードのない項目の FHIR `code.text` には `style="formal"`。コードのある `Observation.code.coding.display` は権威の表示名のまま |
| `department_display(dept, lang)` / `department_specialty_snomed(dept)` | 診療科名 / 専門科コード |
| `role_display(role, lang, *, facet)` | 職種の名称・接尾辞・資格 |
| `chronic_followup_vitals(code)` / `chronic_followup_interval_months(codes)` | フォローアップ予定のデータ |
| `t(key, lang, **kwargs)` (`clinosim.locale.i18n`) | フレーズ。未知のキーは `""` (キーそのものは返さない) |
| `locale.localized`: `localized(entry, lang, *, fallback)`, `localized_field(record, base, lang, *, fallback)`, `label(catalog, section, key, lang, *, fallback)` | 言語マップ、`<base>_<lang>` フィールド、語彙カタログから値を選ぶ唯一の処理 (§6)。`t`、`resolve_localized_display`、`resolve_text` はこれに委譲する |
| `locale.table`: `LocalizedTable.get(key, lang, *, fallback)`, `localized_tables()` | すべての表示表・翻訳表を読む基底クラス (§2.3)。`vocab_display`、`imaging_exam_display`、`prompt_label`、`narrative_label` はこれに委譲する。`localized_tables()` はテスト用に全表を列挙する |

### 4.3 自由文字列の名称 (`clinosim.locale.free_text`)

生成器に英語の自由文字列として届き、コードもカタログ id も持たない名称に使う。名称の種類ごとに、専用の表を読む解決関数を 1 つ持つ。

| 関数 | 表 | 返すもの |
|---|---|---|
| `localize_drug_name(name, lang)` | 薬カタログの名前と別名、剤形の変種 (`load_drug_display_dict`) | `lang` の名称。`lang` のエントリが無ければ入力のまま |
| `localize_procedure_name(name, lang)` | 処置の語句と画像検査 (`load_procedure_display_dict`)。完全一致を先に試し、複合したオーダ文字列には自由文字列の翻訳を使う | 同上 |
| `localize_allergen_name(name, lang)` | アレルゲン・物質名 (`load_allergen_display_dict`) | 同上 |
| `localize_free_text(text, lang)` | すべての表 (`load_narrative_display_dict`) と用量・経路・頻度の用語 (`med_terms.yaml`) | 同上 |

コードやカタログ id を持っている呼び出し側は §4.1 を使う。これらの関数はコードの表示名を訳さない。

### 4.4 `display` がコードを解決する順序

基底クラス `CodeSystem` (§2.3) が、すべての体系をこの順序で解決する。

1. 体系内の完全一致。
2. 体系の `parents` フックが返すコード (`E11.9` → `E11`)。コードを一般化したもので、そのコードについても正しい。
3. 体系の参照兄弟体系 (§3.3) で 1〜2 を繰り返す。
4. それでも無ければ `None`。より詳細な子コードの表示名を、粗いコードに使うことはしない。生成器が引くカテゴリは、カテゴリ自体を登録する。

エントリの言語は §6 で選ぶ。要求言語、参照兄弟体系にある同じコードの要求言語、英語、`None` の順。

### 4.5 出力の補助関数

| 関数 | 用途 |
|---|---|
| `modules.output.fhir_r4.lib.common.dual_slot_concept(system_key, code, lang, *, text, fallback_display)` | コード付き CodeableConcept すべて (§5.3) |
| `modules.output.fhir_r4.lib.common.system_coding(system_key, code, lang, *, fallback_display)` | `text` を持たない Coding 型の要素 (`Encounter.class` など、§5.3) |
| `modules._shared.practitioner_name(staff_id, roster_map)` | 医療者の表示名。見つからなければ `""` |
| `simulator.event_refs.event_ref_kind(value)` | `disease_id` / ground truth の値の名前空間 |

国の出力言語は `countries.lang_for(country)`、CIF の `<base>_<lang>` フィールドは `localized_field` で読む。

## 5. 多言語対応

### 5.1 出力言語

- **国から決める。** 出力言語は国から決まる: `clinosim.countries.lang_for(country)`。元データは `locale/shared/country_language.yaml`。大文字小文字は区別せず、対応のない国は英語になる。
- **国の規則は言語の規則ではない。** `countries.is_jp` / `is_us` を調べるのは、国ごとの規則 (診療報酬コード、プロファイル、JP 専用の section) に限る。表示言語を選ぶために国を調べたり、言語をリテラルと比較したりしない。
- **言語タグ。** `lang` を受け取る関数は、すべて同じ方法 (`countries.normalize_lang`) で正規化する。小文字にする。国コードはその言語にする (`"JP"` → `ja`)。地域付きのタグは主タグに落とす (`ja-JP` → `ja`)。空なら `en`。`codes` 層と `locale` 層は、この 1 つの正規化を共有する (§11)。

### 5.2 データの形

- **YAML の翻訳対象の文字列**は言語マップにする (§3.1 の 4)。`x_ja if is_jp(...) else x_en` のような書き方はしない。
- **CIF のフィールド** (YAML ではなく Pydantic のレコードのフィールド) で言語ごとの文字列を持つものは、英語を `<base>`、他の言語を `<base>_<lang>` にし、`localized_field` で読む (`<base>_en` も受け付ける)。
- **新しい言語**は、データに `<lang>` キーを足すだけで追加できる。コードの変更は要らない。

### 5.3 英語のみのコード体系 (dual slot)

`is_english_only_system` は LOINC、SNOMED CT、HL7 terminology、`http://hl7.org/fhir/`、DICOM、UCUM を対象にする。これらの体系では次のとおりにする。

- **JP 出力**: `coding.display` は英語の正規表示名にし、日本語のラベルは `CodeableConcept.text` に入れる。coding の中に日本語の display を入れると検証エラーになる。
- **それ以外の体系**: JP Core、JP-CLINS、MEDIS、YJ、clinosim 独自の体系は、出力言語の表示名をそのまま使う。
- **作る場所**: 出力する箇所で `dual_slot_concept` を使って作る。後処理の walker で後から埋めることはしない。
- **Coding 型の要素**: 型が `Coding` の要素 (`Encounter.class`、`classHistory.class`) には `text` がない。`system_coding` で作り、どのロケールでも英語の表示名を入れる。
- **HL7 の語彙**: 生成器が出力する HL7 CodeSystem には、それぞれコードをキーにしたレジストリファイルがある (`hl7-v3-actcode`、`hl7-v3-actpriority`、`hl7-observation-category`、`hl7-condition-category`、`hl7-v3-participationtype`、`hl7-diagnosis-role`、`hl7-organization-type`、`hl7-observation-interpretation` …)。日本語ラベルはコードで引き、英語の表示名では引かない。
- **コードを持つ語彙のラベル**: コード付き概念の `text` ラベルは、その概念のコードの横にある言語マップから取る。生成器がコードに対応付けた内部の英語トークン (`PO` などのオーダ経路、`BID` などの頻度) を持つ場合は、そのトークンの翻訳表 (`locale/shared/fhir_text_translations.yaml`) から取り、英語ではトークンをそのまま使う。言語ごとの別表は使わない。

## 6. フォールバック規則

§4 のすべての解決関数に、両方の層で共通に適用する。

1. **順序**: 要求された言語 → 英語 → 呼び出し側が**明示的に**渡した代替値。
2. **代替値にしてはいけないもの**: 英語以外の別の言語 (英語出力に日本語など)、引いたキー、生のコード、生の id、生の slug。
3. **コードや id が見つからない**ときは、解決関数は `None` / `""` を返す。何を表示するかは呼び出し側が決めて明示的に渡すか、要素ごと省く (「捏造より沈黙」)。
4. **slug の人間可読化**: slug の `_` を空白に置き換える処理は、内部 slug の表示表の最後のフォールバックに限って使える。例: `imaging_exam_display`、`procedure_type_display`、`department_display`、`lab_display` は未知の slug を人間可読化する。使えるのは、生成器が出力する slug がすべて表にあることを unit test で確認している場合だけ。`.title()` で語頭を大文字にした slug は使わない。
5. **英語のエントリが欠けている**のはデータのバグで、テストで検出する。英語以外のエントリが欠けている場合は英語にフォールバックする (規則 1)。
6. **表にない自由文字列**は英語のまま残す。自由文字列用の解決関数 (§4.3) は入力をそのまま返す。

## 7. 拡張の手順

### 7.1 新しいコード体系・権威

1. コードを照合する (§8)。
2. `codes/data/<system-key>.yaml` を足す (§3.3)。ファイルに URI が無ければ `_BUILTIN_URIS` にキーを足す。
3. フックや独自の参照が要る権威なら、`codes/<authority>.py` に `CodeSystem` のサブクラスを足し (§2.3)、§2.2 と §4.1 に載せる。要らなければレジストリファイルだけで素のインスタンスになる。
4. 権威がスナップショットを公開していれば、スナップショットとそのテストを足す。
5. 表示名が英語のみの体系なら `is_english_only_system` に足す。

### 7.2 新しい言語

1. その言語を使う国を `locale/shared/country_language.yaml` に対応付ける。
2. 表示したい言語マップに `<lang>` キーを足す。対象はコード体系レジストリ、カタログ、表示表、翻訳表、フレーズカタログ。
3. 網羅テスト (§10) を流す。新しいキーの無いエントリは英語にフォールバックする。コードの変更は無い。

### 7.3 新しい国

1. 言語を対応付ける (§7.2)。
2. コード体系が異なるドメインごとに `locale/<cc>/code_mapping_<domain>.yaml` を足し、`system_key_for` にその国の行を足す。
3. 国の規則 (プロファイル、診療報酬コード) は国で判定し、言語では判定しない (§5.1)。

### 7.4 新しい語彙

1. コードを持つ語彙はコード体系として扱い (§7.1)、ラベルもそのレジストリファイルに置く。
2. コードを持たない語彙は、表示表 `locale/shared/<vocabulary>.yaml` を 1 つ (§3.7、すべての slug に `en`) 足して `LocalizedTable` (§2.3) として読み、入口の関数を 1 つ §4.2 に載せる。

## 8. コードの追加・変更手順

1. 登録の前に**権威ソースで照合する**。

   | 体系 | 照合先 |
   |---|---|
   | ICD-10-CM | NLM / CMS |
   | ICD-10 | WHO browser |
   | LOINC | loinc.org または tx.fhir.org `$lookup` |
   | SNOMED CT | tx.fhir.org `$lookup` / SNOMED browser |
   | RxNorm | RxNav |
   | YJ / HOT | MHLW / MEDIS マスタ |
   | JLAC10 | JSLM マスタ |
   | CPT | AMA CPT |
   | K コード | MHLW 診療報酬点数表 |
   | HL7 | THO |
   | JP Core / JP-CLINS の URI | パッケージの fixedUri |

2. `codes/data/<system>.yaml` に**登録する**。`en` は権威ソースの表示名と一致させる。
3. その体系にスナップショットがある場合は、`codes/authoritative/` の**スナップショットを更新する**。
4. そのコードを使う**対応表やカタログのエントリを足す** (§3.4〜3.6)。
5. **網羅テストを流す**: 診断の網羅テスト、権威スナップショットのテスト、システム URI の網羅テスト。

## 9. 禁止パターン

- `clinosim/codes/` の外にコード体系 URI の文字列リテラルを書く。`get_system_uri` を使う。例外は URI の系統を表す接頭辞リストだけ。
- `clinosim/codes/` の外で `codes/data/*.yaml` を直接読む、または `clinosim.codes.loader._load_system` を import する。ソースごとのアクセサか `data_table` を使う。
- ある権威の参照規則を、その権威のアクセサの外で実装する (§2.2)。
- Python の比較式にコードのリテラルを書く、またはコードや表示名を Python の dict・list・enum に持つ (CPT、LOINC、SNOMED、ICD、YJ、HL7 …)。value set、カタログ、レジストリファイル、名前付き概念を使う。唯一の例外は、登録済みのコードに型付きの名前を付けるだけで、全メンバーを読み込み時にレジストリファイルと照合する enum (`codes/hl7_encounter.py`)。
- 同じ語彙やコード対応の 2 つ目の表を作る。語彙自身の表の横に置く言語別の表も含む。
- 薬・検査・病態を自由文字列の部分一致で同定する。カタログ id、正規の検査名、value set を使う。自由文字列から薬を同定してよいのは `identify_drug` だけ。
- 表示を選ぶために言語をリテラルと比較する (`lang == "ja"`、`lang != "ja"`)、または `is_jp` で選ぶ。§4.2 を使う。
- YAML のフィールド名に言語を入れる (`title_ja`)、翻訳表以外で表示文字列を YAML のキーにする、コードの値を引用符で囲まない。
- 出力に届く slug に `.title()` や素の `replace("_", " ")` を使う (規則 6.4 の場合を除く)。
- コードの表示名を、コード体系自身の `ja` 表示ではなく自由文字列用の解決関数 (§4.3) で訳す。
- 新しいコードで `lookup(...)` を使う。代替値が見える `display(...) or <明示的な代替>` を使う。

## 10. 強制の仕組み

| ルール | テスト |
|---|---|
| ここに書いた関数とファイルが実在し、逸脱は Issue を指す | `tests/unit/test_code_mapping_spec_2342.py` |
| URI とコードデータは `clinosim.codes` 経由のみ | `tests/unit/codes/test_codes_lint_guard_2266.py`、`tests/unit/test_system_uri_coverage.py`、`tests/unit/test_hl7_uri_registry_2349.py`、`tests/unit/test_registry_uris_2265.py` |
| 正規 URI がプロファイルの fixedUri と一致 | `tests/unit/test_registry_uri_pin.py` |
| レジストリの表示名が権威と一致 | `tests/unit/codes/test_display_matches_authoritative.py` |
| 出力するコードが登録済み | `tests/unit/codes/test_emitted_diagnosis_registered_2429.py`、`tests/unit/codes/test_procedure_codes_registered_2340.py` |
| 見つからないときにコードをそのまま返さない | `tests/unit/codes/test_no_code_echo_2416.py` |
| 英語のみの体系の dual slot | `tests/unit/test_dual_slot_2276.py` |
| 選択 API とフォールバック順序が 1 つ | `tests/unit/locale/test_localized_api_2395.py` |
| 言語を直接選ばない | `tests/unit/locale/test_no_direct_language_selection_2397.py` |
| 言語をリテラルと比較しない (ラチェット: 残っている箇所は是正する Issue に紐づけて固定) | `tests/unit/locale/test_no_language_literal_comparison_2455.py` |
| 残っている言語接尾辞付きの YAML フィールド (§11) は `<base>_ja` と `<base>_en` を対で持つ | `tests/unit/locale/test_localized_field_shape_2398.py` |
| 日本語以外の出力に日本語を出さない、Python に日本語リテラルを書かない | `tests/unit/test_no_japanese_fallback_2273.py`、`tests/unit/test_no_japanese_literals_2277.py`、`tests/unit/test_narrative_literals_2400.py`、`tests/unit/test_module_literals_2406.py`、`tests/unit/test_simulator_literals_2405.py`、`tests/unit/output/test_fhir_lib_literals_2402.py`、`tests/unit/output/test_fhir_lab_condition_literals_2403.py`、`tests/unit/output/test_fhir_emitter_literals_2404.py` |
| 第三国を米国扱いしない | `tests/unit/test_third_country_fallbacks_2203.py` |
| `CodeSystem` / `LocalizedTable` の処理を上書きしない。表示表のすべてのエントリが英語を持つ | `tests/unit/codes/test_code_system_base_2470.py`、`tests/unit/locale/test_localized_table_2471.py` |
| すべてのデータ YAML が置き場所に合った `metadata.kind` を持ち、`clinosim.datafiles` で読まれる (設定ファイルは除く) | `tests/unit/test_data_yaml_conventions_2465.py` |

## 11. 既知の逸脱

以下はまだこの仕様に沿っていない。それぞれ記載の Issue で解消する。全体は [#2452](https://github.com/TomoOkuyama/clinosim/issues/2452) で追う。

| 逸脱 | Issue |
|---|---|
| narrative のレンダラが、日本語だけの処理 (主訴バリエーション、CC/PE 整合、daily trajectory、JP のコード選択) を言語リテラルで切り替えている (12 ファイル 18 箇所) | #2483 |
| プロトコルとテンプレートの YAML が、言語マップではなく言語接尾辞付きのキー (`title_ja`、`findings_en` など、70 ファイル約 1,300 キー) を使っている (§3.1 の 4) | #2475 |
