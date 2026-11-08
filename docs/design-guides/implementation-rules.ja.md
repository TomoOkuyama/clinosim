# clinosim Implementation Rules — 実装者必読の不変則集

**Status:** Active
**Audience:** clinosim のコードを書く・直す全ての人とコーディングエージェント。
**位置づけ:** コーディング規則の入口。ここに書かれた規則は例外なく適用される。ドメインごとの詳細規則は binding spec (下表)、規則が指す共通ヘルパーは [`shared-helpers-catalog.ja.md`](shared-helpers-catalog.ja.md)、モジュール作成の HOW-TO は `docs/CONTRIBUTING-modules.ja.md` にある。
迷ったら判断 4 軸:**データ品質 / 臨床整合性 / メンテ性(責任分解点)/ コンセプト適切性**。

### 規則の所在

| 関心事 | 読む文書 |
| --- | --- |
| すべての変更に適用される規則 (本書) | `implementation-rules.ja.md` |
| X にどの共通ヘルパーを使うか | [`shared-helpers-catalog.ja.md`](shared-helpers-catalog.ja.md) |
| 文書の言語・コメント・定数の置き場所・dead code | [`documentation-and-code-quality-policy.ja.md`](documentation-and-code-quality-policy.ja.md) |
| コード体系・表示名・多言語化・fallback | [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) |
| 乱数・シード・時計 | [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) |
| 参照データ YAML・年齢帯・定数 | [`configuration-and-reference-data-spec.ja.md`](configuration-and-reference-data-spec.ja.md) |
| 薬剤オーダー・保留・投与・退院処方 | [`medication-lifecycle-spec.ja.md`](medication-lifecycle-spec.ja.md) |
| 検査値・オーダー・結果 | [`lab-orders-and-results-spec.ja.md`](lab-orders-and-results-spec.ja.md) |
| 文書計画と narrative の文言 | [`narrative-and-document-generation-spec.ja.md`](narrative-and-document-generation-spec.ja.md) |
| encounter の設定・スナップショット・FHIR 仕上げ | [`encounter-lifecycle-and-export-spec.ja.md`](encounter-lifecycle-and-export-spec.ja.md) |
| FHIR 完全性 (C1 / C2 / C3) | [`data-model-and-completeness-conventions.ja.md`](data-model-and-completeness-conventions.ja.md) |
| FHIR builder を書く | [`fhir-data-generation-logic.ja.md`](fhir-data-generation-logic.ja.md) |

---

## 0. Workflow 規律(コードを書く前に)

1. **Workflow**: 1 GitHub Issue = 1 PR → コードと binding spec を読む → TDD 実装(test first)→
   生成コホートでの検証 → PR → レビュー(finding は実証必須)→ fix → 全 suite green → merge。
   大きな設計は先に設計ノートを書く(`docs/history/specs-archive/`)。
2. **Scope discipline**: spec 確定後の scope 拡大禁止。scope 外の発見は
   「データ品質/臨床整合性に必須」の場合のみ対応、それ以外は
   **GitHub Issues board に formal entry 化** (`docs/roadmap.ja.md` 参照;
   旧 `TODO.md` は Issues 化に伴い廃止) — 文脈・file:line・修正案つきで。
3. **着手前 status audit**: TODO/ドキュメントの記述を鵜呑みにせず、**実装前に実測で検証**
   (先に生成コホートで挙動を数える — 報告された gap は既に直っていることが多い)。
4. **観測前に語らない**: ツール結果を見る前に「成功した」と書かない。検証は実行結果
   (test 出力・実 cohort の grep・sha256)で示す。
5. **Commit 規約**: `<type>(<module>): <要約>`、type は `feat` / `fix` / `refactor` / `docs` /
   `test` / `chore`。`git commit --signoff` で署名する (DCO)。push と PR 作成は検証 green 後。

## 1. コーディング標準

- Python 3.11+ / ruff (line length 120) / mypy (`mypy clinosim/` をローカルで通す。CI では
  informational) / vulture (未使用コード。フレームワークが読むメンバーは `.vulture-whitelist.py` へ)。
- **コード内コメント・docstring は英語**。例外は文書ポリシー §4 の日本の仕様に関するカテゴリのみ。
  ドキュメントは `*.md` が英語、日本語版は `*.ja.md`
  ([`documentation-and-code-quality-policy.ja.md`](documentation-and-code-quality-policy.ja.md) §1)。
- **モジュール間で共有する型と CIF の型は `clinosim/types/` にのみ定義**(YAML config = Pydantic
  BaseModel(AD-18)、runtime = `@dataclass`)。モジュールの外に出ない private な型 (自モジュールの
  参照 YAML を検証する Pydantic モデル (`_models.py` か loader の隣) と内部用の補助型) はモジュール内に
  置いてよい。2 つ目のモジュールが必要とした時点で `clinosim/types/` に移す。
- **Public API = module `__init__.py` で export したものだけ**。
- コメントは「コードが示せない制約」だけを書く。変更の経緯説明・自明な説明は書かない。

## 2. アーキテクチャ不変則(データフロー)

| 不変則 | 内容 |
| --- | --- |
| AD-17 | **CIF がシミュレーションの唯一の出力**。format adapter(FHIR/CSV)は CIF だけを読む |
| AD-30 | **CIF は code のみ、display text 禁止**。表示解決は出力時に `clinosim.codes.display(...)` と明示的な fallback |
| AD-65 | **structural / narrative の 2 層 file 分離**。Stage 1 は `ClinicalDocument` stub のみ(narrative=None)、narrative は post-simulation の `NarrativePass` が `narratives/<version>/` に書く。inline 混在禁止 |
| AD-31 | FHIR は Bulk Data NDJSON(resource id は type 内 globally unique、reference は同 export 内で解決) |
| AD-32 | `--end` = snapshot date。それ以降の event 生成禁止、in-progress encounter semantics 遵守 |
| AD-55/56 | module は `CIFPatientRecord.extensions[<module>]` に書く(typed field 追加は Base のみ)。拡張は 3 registry(`register_bundle_builder` / `register_output_adapter` / `register_enricher`)経由 — dispatch 本体を編集しない |
| AD-11 | **LLM 呼出しは `llm_service` 経由のみ**。narrative 層からは `LLMService.complete_prompt()` が唯一の seam。provider SDK の直接 import 禁止 |

## 3. 決定性(AD-16 / AD-59)— 絶対規則

**規範仕様:** [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) が生成器の生成元・シード導出・乱数をずらさない変更・時計の規則とそのガードを定める。以下は要約。

- `random` と `numpy.random.default_rng` 禁止。生成器は必ず `clinosim.determinism.default_rng(seed)` で作り、
  seed は `clinosim/seeding.py` で導出する(`derive_sub_seed(master_seed, module_offset, key)` +
  `ENRICHER_SEED_OFFSETS` (16-bit hex-ASCII) 登録、または `panel_specimen_seed` / `individual_lab_seed`
  などの実体ごとの名前付き関数)。call site でシードをハッシュしない。
- 他の抽選をずらしてはいけない抽選 (RNG 中立な変更) は `clinosim.determinism` のストリーム非消費の
  `sha_quantile` / `sha_bernoulli` / `sha_normal` / `sha_weighted_choice` を使い、`hashlib.sha256` の式を
  inline で書かない。
- **`datetime.now()` / `date.today()` を生成経路に書かない**。時計を読んでよいファイルは
  `tests/unit/test_determinism_spec_guards.py` に固定されており、増やすのは禁止。narrative の時刻は
  `_deterministic_timestamp` 系。
- **`@lru_cache` 済み loader の戻り値は shared instance — mutate 絶対禁止**
  (`load_disease_protocol` / `load_encounter_condition` / `load_healthcare_config` /
  `load_hospital_operations` / ほか全 cached loader)。
- enricher の実行順序(stage + order)を変えない。新 enricher は
  `simulator/enrichers.py:register_builtin_enrichers` に登録。
- `NarrativePass` の walk 順序((doc_type, language)→ sorted patients)は
  prompt-cache 最適化のため**変更禁止**。

## 4. Canonical single-source helpers(再実装・inline 化 絶対禁止)

同じロジックが 2 箇所以上 = 違反。共通ヘルパーはパスと governing spec 付きで
[`shared-helpers-catalog.ja.md`](shared-helpers-catalog.ja.md) に一覧がある。小さな処理を書く前に必ず引く。
特に誤りやすい規則:

| 関心事 | 規則 |
| --- | --- |
| 国判定 | `is_jp(country)` / `is_us(country)`(`clinosim/countries.py`)は国ごとの規則にだけ使う。`country == "JP"` 等の手書き比較禁止。表示言語は `lang_for(country)` で決め、`is_jp` では決めない |
| 国→コード体系 | `system_key_for(kind, country)` / `drug_system_key(code, country)`(`clinosim.codes`)。jlac10/loinc や yj/rxnorm の inline 分岐禁止 |
| system URI | `get_system_uri(key)`(`clinosim.codes`)。コード体系 URI の hardcode 禁止。複数ファイルで使う profile / identifier URI はモジュールレベル定数 1 つにする |
| code→display | `display(system, code, lang) or <明示的な fallback>`(`clinosim.codes`)、FHIR の coding は `dual_slot_concept` / `system_coding`。`lookup(...)` は旧 API で新規コードでは使わない。display 文字列の hardcode 禁止 |
| dict/dataclass 双対 read | `get_attr_or_key`(`modules/_shared.py`)。`isinstance(x, dict)` 分岐やローカル `_get` の新設禁止。**cache key・比較・分岐などデータを読む全経路に適用**(dict に `getattr` を使い cohort 全体が同一 cache entry を共有した前例) |
| dict/dataclass 双対 write | `set_attr_or_key(obj, name, value)` / `get_or_create_container(obj, name, factory)` |
| ハッシュ抽選とシード | `clinosim.determinism.sha_*` と `clinosim/seeding.py` の名前付き関数。call site で `hashlib.sha256` + `int.from_bytes` を書かない(§3) |
| 年齢帯 | 年齢帯キーの YAML 表を `clinosim.age_bands` で引く。`if age < 18` 等の境界 hardcode 禁止 |
| 確率ベクトル | YAML 由来の全 `rng.choice(p=)` に `normalize_probabilities(p, fallback="raise")` |
| scenario/medication flags | `scenario_flags_from_protocol` + `medication_flags_from_context` を **merge して `**flags` 渡し**。named-arg 追加禁止(1 か所でしか読まれない flag は他の経路で無効になる) |
| 重症度 | `sample_severity` / `sample_severity_category` / `category_from_score`(`disease/severity.py`、AD-67)。疾患 YAML `severity.distribution × modifiers` が唯一の源。0.3/0.7 境界の hardcode 禁止(`SEVERITY_SCORE_RANGES` が唯一定義) |
| JP Core / JP-CLINS profile URI | spec の `StructureDefinition-*.json` の `fixedUri` を引用し、**推測しない**。モジュールレベル定数として定義し unit test で pin する(`tests/unit/output/test_fhir_jp_core_p14_slices.py` が手本)。推測 URI は validator に slice を無視させる。JP-eCheckup / SS-MIX2 の URI も同じ |
| locale 表示テーブル | `locale/loaders/` の cached loaders(`locale/loader.py` が re-export)。Layer 4 での raw YAML open 禁止 |

新しい共通処理が 2 module に必要になったら `_shared.py` か owner module に 1 箇所定義し
双方 import し、カタログに追加する。**第三の消費者が現れても import、再定義しない。**

## 5. Loader / reference data 規約

- Path 定数正規形: `_HERE = Path(__file__).resolve().parent` / `_REF_DIR = _HERE /
  "reference_data"` / `_LOCALE = _HERE.parents[1] / "locale"`。fragile な
  `.parent.parent.parent` 禁止。他 module の reference_data への直接 path 禁止
  (owner module に accessor を作る。例: `observation.microbiology.antibiotic_loinc_lookup`)。
- `@lru_cache`: no-param → maxsize=1、`(country)` → 2。hand-rolled sentinel cache 禁止。
- **import/load 時 fail-loud validation 必須**: モジュール参照 YAML はすべて
  `load_validated_yaml(path, Model)` で読む(または load 時に Pydantic モデルで検証する)。外部 ID(SNOMED/LOINC/ICD/
  drug key)・確率重み・enum 値(`generation_frequency` / `stage2_strategy` 等)を参照する
  YAML は、canonical 集合との照合で未知キー・矛盾を **load 時に raise**。
  `dict.get()` の silent fall-through 禁止。
- aggregate loader(glob して全件 load)は **owner module に置く**(simulator 側から
  他 module の dir を glob しない)。
- **YAML-loaded Pydantic model は `extra="forbid"`**(AD-69)。`DiseaseProtocol` /
  `PatientProfile` は導入済。新しい top-level YAML キーは **model field を足してから**追加
  (足さないと load で raise = author-time silent-drop 防御)。`DiseaseProtocol` の raw-dict
  消費経路(`order/engine.py`)は forbid の保護外なので、そちらで読むキーも model に宣言する。
- **FHIR completeness 3 不変則**(AD-67/68/69、`data-model-and-completeness-conventions.md`):
  ①**C1** 読まれない YAML キーを ship しない(forbid + 消費配線)②**C2** 生成した要素は必ず
  下流消費者を持つ — 特に **graded-stage 疾患(`_generate_stage`)は必ず `STAGE_SEVERITY` に
  entry を持つ**(I10-class no-op の再発防止、`test_completeness_invariants.py` が強制)
  ③**C3** 急性疾患は `course_archetypes` + `complications` を author(fallback は感染チューニング
  で外傷/循環器に不整合)。regression ガード = `tests/unit/test_completeness_invariants.py`。

## 6. codes / locale / 多言語

**規範仕様:** [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) が YAML の書き方・解決関数・多言語対応・フォールバック規則を定める。コードに関わる変更はすべてこれに従う。以下は要約。

- `codes/data/*.yaml` は **`en` 必須**、出典は authoritative(CMS/NLM/WHO/JCCLS/MHLW)。
  **コードの捏造絶対禁止** — 新 code は NLM API / WHO browser で検証してから登録。
- 診断コード追加時は「Diagnosis code coverage」手順(AGENTS.md)に従い
  `pytest tests/unit/test_diagnosis_code_coverage.py` green を確認。
- **JP 出力は全 display/text/name が日本語、US 出力は日本語文字 0**(既知の例外 =
  `KNOWN_JA_ONLY_FALLBACK_SECTIONS`。勝手に拡げない)。緊急番号等の locale 依存表現に注意
  (実例: en テキストに「Call 119」が混入 → guard test あり)。
- Condition/Procedure 等は dual coding(local primary + interop)。数値 Observation は
  referenceRange + interpretation を両方 emit し出力時に再計算。

## 6.5 共通ロジック所在マップ(4 横断ロジック)

誰でも「◯◯のロジックはどこで、どの入口で書くか」を即引くための一覧。各ロジックは
**単一の canonical 入口**を持ち、call-site で再実装しない(§4 の原則の適用)。

| 横断ロジック | canonical 入口(owner) | 規約 / データ源 |
| --- | --- | --- |
| **データ参照**(YAML/参照データの load) | 各 module の `load_X()`(`@lru_cache` + `_HERE/_REF_DIR/_LOCALE` path 定数 + `load_validated_yaml` による load 時の Pydantic モデル検証)。他 module の reference_data は owner の accessor 経由(§5) | Layer 1 = `modules/*/reference_data/`・`locale/`・`config/`。cached loader の戻り値は shared read-only(mutate 禁止) |
| **データ生成**(乱数・生理・重症度) | 乱数 = `derive_sub_seed` + `ENRICHER_SEED_OFFSETS` か `seeding.py` の名前付き関数で seed した `determinism.default_rng`(lab は `panel_specimen_seed`/`individual_lab_seed`)、ストリーム非消費の抽選 = `determinism.sha_*`。重症度 = `disease.severity.sample_severity`。course = `clinical_course.select_archetype`。生理 = `physiology.engine`(initialize_state / derive_lab_values) | 全乱数 seed 由来で決定的(AD-16)。臨床値は疾患/検査 YAML 駆動、Python にハードコードしない。`rng.choice(p=)` は `normalize_probabilities(p, fallback="raise")` 経由 |
| **コードマッピング**(内部名→標準コード→表示) | 内部名→標準コード = `locale/<country>/code_mapping_*.yaml`。国→コード体系 = `system_key_for(kind, country)`。code→display = `display(system, code, lang) or <fallback>`。system URI = `get_system_uri(key)` | `codes/data/*.yaml`(EN 必須、国際標準、locale 非依存)。display 文字列・URI・コードの hardcode/捏造禁止。CIF は code のみ(AD-30) |
| **多言語対応**(i18n) | 国判定 = `is_jp`/`is_us`、表示言語 = `countries.lang_for(country)`。表示解決は [コードマッピングと多言語化の仕様](code-mapping-and-localization-spec.ja.md) に従う: コードは `display(...)`、FHIR の coding は `dual_slot_concept` / `system_coding`、語彙は `vocab_display` | 変換は language-neutral(AD-44):enrichment は英語構造化データを産み、LLM が翻訳。**JP 出力は全 display 日本語 / US 出力は日本語 0**(audit の jp_language 軸が強制) |

これらが「統一されているか」の判定は `data-model-and-completeness-conventions.md`(重症度)+ 本書 §4
(canonical helpers)+ audit の silent_no_op 軸。実装の end-to-end 像は
`data-generation-walkthrough.md`。

## 7. Narrative 層(Stage 2)規約

- Generator 契約 = `NarrativeGenerator` Protocol(`types/document.py`)。
  `NarrativePass` へは **constructor 注入**(hardcode 禁止)。
- LLM 経路: `LLMNarrativeGenerator` → `apply_replacement_strategy` →
  `LLMService.complete_prompt()`。fallback は generator の責務(complete_prompt は raise)。
- **prompt は `llm_service/prompts/{en,ja}/*.yaml` のみ**(AD-40)。Python 内での
  prompt 文字列組立て禁止。
- `DocumentTypeSpec` は YAML(`document_type_specs.yaml`)+ registry validation
  (frequency / stage2_strategy / llm_enabled_sections ⊆ composition_sections)。
- **partial version guard**: `--patient-filter` 実行は current を default で更新しない・
  既存 version への上書きは `--merge-into-version` opt-in。`regenerate-goldens` に
  filter を渡すことは永久に禁止。
- 実 LLM 出力の gate は `check-narratives`(semantic check 5 軸)。byte-diff は
  template / mock にのみ適用。

## 8. Golden / テスト / 検証 gate

- テストスイート: `pytest tests/unit`(`-m unit` ではない — marker の無い unit ファイルがある)/
  `pytest -m integration` / `-m e2e` / `pytest tests/regression -m regression`(opt-in、全 canonical
  profile の narrative golden byte-diff、template + llm-mock)。
- **AD-66 Rule 1**: profile YAML か生成ロジックを変えたら `regenerate-goldens` +
  **YAML と golden を同一 commit**。
- **AD-66 Rule 2 + 臨床内容レビュー**: golden diff は「期待した種類の変化か」の categorize
  だけでなく**中身の臨床妥当性まで読む**(実例: 死亡退院患者に ICU 昇圧剤 drip が
  退院処方として golden に焼き込まれていた)。
- **byte-diff の使い分け**: refactor PR = byte-identical 必須(FHIR NDJSON + narratives の
  sha256 比較。CIF structural は既知 wall-clock 2 フィールドのみ許容)。new-feature PR =
  byte-diff intentionally broken、gate は audit + goldens + 実出力検証。
- **実出力 grep を verification に含める**: wiring/context 変更は下流 renderer の実出力を
  実 cohort で grep(破綻文・placeholder 残骸・locale 混入の検出)。test green だけでは不十分。
- `clinosim audit run -d <cohort>`(AD-60 4 軸)= 新機能 PR の一次 gate。

## 9. Silent-no-op 防御チェックリスト

新機能・修正が「実際に発火している」ことを構造的に証明する:

1. **canonical constants** を単一定義し writer/reader 双方が import(ID prefix、URI、
   `HAI_TYPES` 等)。
2. **import/load 時 cross-validation** で typo・欠落を fail-loud に。
3. audit `lift_firing_proof` に equality_checks(発火証明)を追加。
4. **"fired" counter / 観測可能性**: fallback や skip は counter + manifest/stderr で可視化
  (例: `generator_fallback_docs`、eligible>0 かつ fired=0 で WARN)。
5. **aspirational scaffold 禁止**: 登録したが未消費のコード(seed offset、config field、
   strategy 値)は **wire するか削除**。「後で使う」で ship しない。
6. 覚えておく前例: 1 か所でしか読まれない flag / YAML キーの大文字小文字不一致で機能全体が
   無音で無効化 / dict に `getattr` して cache key が 1 つに退化 / golden に臨床誤りが焼き込み
   (英語文中の「Call 119」、退院処方に ICU の drip)/ 古い TODO を実測せず着手。

## 10. FHIR builder(Layer 4)の要点

詳細 = [`fhir-data-generation-logic.md`](fhir-data-generation-logic.ja.md)。最低限:
CIF は read-only / display・URI・ID prefix は canonical source から / builder 登録は
registry 経由 / dict+dataclass 両 path のテスト必須 / reference integrity(dangling 禁止)。

---

## 読む順序(新規参加の実装者向け)

1. 本書(規則)と [`shared-helpers-catalog.ja.md`](shared-helpers-catalog.ja.md)(ヘルパーの所在)
2. [`README.ja.md`](README.ja.md)(読了パス)→ `MODULES.md`(全体地図)
3. 変更するドメインの binding spec(冒頭の表)
4. `docs/CONTRIBUTING-modules.ja.md`(モジュール HOW-TO)
5. FHIR builder を書くときは `fhir-data-generation-logic.ja.md`、Stage 2 narrative を触るときは `clinosim/modules/output/SPEC.md`
6. 未着手の作業は GitHub Issues board(`docs/roadmap.ja.md` 参照)

English counterpart: [`implementation-rules.md`](implementation-rules.md).
