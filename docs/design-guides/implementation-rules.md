# clinosim Implementation Rules — 実装モデル必読の不変則集

**Status:** Active(2026-07-03、session 32 で確立)
**Audience:** clinosim のコードを書く・直す全ての実装者/実装 AI(Opus 4.7 等)。
**位置づけ:** CLAUDE.md(全文)と `docs/CONTRIBUTING-modules.md`(詳細 HOW-TO)の**蒸留版**。
ここに書かれた規則は例外なく適用される。詳細・根拠・精密な手順は各リンク先が正。
迷ったら判断 4 軸:**データ品質 / 臨床整合性 / メンテ性(責任分解点)/ コンセプト適切性**。

---

## 0. Workflow 規律(コードを書く前に)

1. **Chain workflow(確立済、逸脱禁止)**: recon → design spec commit
   (`docs/superpowers/specs/`)→ TDD 実装(test first)→ 独立検証 → PR →
   compact adversarial review(5-lens、finding は実証必須)→ fix → 全 suite green → merge。
2. **Scope discipline(★★★)**: spec 確定後の scope 拡大禁止。scope 外の発見は
   「データ品質/臨床整合性に必須」の場合のみ対応、それ以外は **TODO.md に formal entry 化**
   (文脈・file:line・修正案つき)。
3. **着手前 status audit**: TODO/ドキュメントの記述を鵜呑みにせず、**実装前に実測で検証**
   (実例: α-min-3 の「CRITICAL 配線 gap」は 2 世代前に解決済みだった。cohort 出力を
   数えるだけで 1 PR 分の無駄を回避)。
4. **観測前に語らない**: ツール結果を見る前に「成功した」と書かない。検証は実行結果
   (test 出力・実 cohort の grep・sha256)で示す。
5. **Commit 規約**: `feat(<chain>): ...` / `fix(<chain> adv-1): ...` / `refactor: ...` /
   `docs: ...`。task 単位でコミット。push と PR 作成は検証 green 後。

## 1. コーディング標準

- Python 3.11+ / ruff / mypy strict / line length 100。
- **コード内コメント・docstring は英語**。ユーザー向け docs は各ファイルの既存言語に従う
  (CONTRIBUTING と design-guides は日本語+英語技術用語)。
- **型は `clinosim/types/` にのみ定義**(module コード内での dataclass/BaseModel 新設禁止。
  YAML config = Pydantic BaseModel(AD-18)、runtime = `@dataclass`)。
- **Public API = module `__init__.py` で export したものだけ**。
- コメントは「コードが示せない制約」だけを書く。変更の経緯説明・自明な説明は書かない。

## 2. アーキテクチャ不変則(データフロー)

| 不変則 | 内容 |
|---|---|
| AD-17 | **CIF がシミュレーションの唯一の出力**。format adapter(FHIR/CSV)は CIF だけを読む |
| AD-30 | **CIF は code のみ、display text 禁止**。表示解決は出力時に `clinosim.codes.lookup()` |
| AD-65 | **structural / narrative の 2 層 file 分離**。Stage 1 は `ClinicalDocument` stub のみ(narrative=None)、narrative は post-simulation の `NarrativePass` が `narratives/<version>/` に書く。inline 混在禁止 |
| AD-31 | FHIR は Bulk Data NDJSON(resource id は type 内 globally unique、reference は同 export 内で解決) |
| AD-32 | `--end` = snapshot date。それ以降の event 生成禁止、in-progress encounter semantics 遵守 |
| AD-55/56 | module は `CIFPatientRecord.extensions[<module>]` に書く(typed field 追加は Base のみ)。拡張は 3 registry(`register_bundle_builder` / `register_output_adapter` / `register_enricher`)経由 — dispatch 本体を編集しない |
| AD-11 | **LLM 呼出しは `llm_service` 経由のみ**。narrative 層からは `LLMService.complete_prompt()` が唯一の seam。provider SDK の直接 import 禁止 |

## 3. 決定性(AD-16 / AD-59)— 絶対規則

- `random.random()` 禁止。RNG は必ず sub-seed 由来の `numpy.random.Generator`
  (`simulator/seeding.py`: `derive_sub_seed` + `ENRICHER_SEED_OFFSETS` 登録、
  lab は `panel_specimen_seed` / `individual_lab_seed`)。
- **`datetime.now()` / `date.today()` を生成経路に書かない**(既存の残存は determinism
  chain の TODO — 増やすのは禁止)。narrative の時刻は `_deterministic_timestamp` 系。
- **`@lru_cache` 済み loader の戻り値は shared instance — mutate 絶対禁止**
  (`load_disease_protocol` / `load_encounter_condition` / `load_healthcare_config` /
  `load_hospital_operations` / ほか全 cached loader)。
- enricher の実行順序(stage + order)を変えない。新 enricher は
  `simulator/enrichers.py:register_builtin_enrichers` に登録。
- `NarrativePass` の walk 順序((doc_type, language)→ sorted patients)は
  prompt-cache 最適化のため**変更禁止**。

## 4. Canonical single-source helpers(再実装・inline 化 絶対禁止)

同じロジックが 2 箇所以上 = 違反。以下は必ず import して使う:

| 用途 | Helper(定義場所) |
|---|---|
| JP 判定 / 表示言語 | `is_jp(country)` / `is_us(country)` / `resolve_lang(country)`(`modules/_shared.py`)。`country == "JP"` 等の手書き比較禁止 |
| 国→コード体系選択 | `system_key_for(kind, country)`(`clinosim.codes`)。jlac10/loinc 等の inline 分岐禁止 |
| system URI | `get_system_uri(key)`(`clinosim.codes`)。URI 文字列 hardcode 禁止 |
| code→display | `code_lookup(system, code, lang)`。display 文字列 hardcode 禁止 |
| dict/dataclass 双対 read | `get_attr_or_key`(`_shared.py`)/ FHIR builder では `_o()`。`isinstance(x, dict)` 分岐の新設禁止。**cache key・比較・分岐などデータを読む全経路に適用**(C-1 教訓: `getattr` を dict に使い cohort 全体が同一 cache entry を共有した) |
| dict/dataclass 双対 write | `set_attr_or_key(obj, name, value)`(単一フィールド代入)/ `get_or_create_container(obj, name, factory)`(ネストしたコンテナを取得 or 生成して直接 mutate)。`isinstance(rec, dict): rec["x"]=v else: rec.x=v` 分岐の新設禁止(session 37 dual-access sweep) |
| 確率ベクトル | `normalize_probabilities(p, fallback="raise")`(`_shared.py`)を YAML 由来の全 `rng.choice(p=)` に |
| lab order 分類 | `classify_lab_specs`(`order/panel_grouping.py`) |
| scenario/medication flags | `scenario_flags_from_protocol` + `medication_flags_from_context` を **merge して `**flags` 渡し**。named-arg 追加禁止(J5 教訓) |
| **重症度サンプリング** | `sample_severity(protocol, person, rng)` / `sample_severity_category(...)` / `category_from_score(score)`(`disease/severity.py`、AD-67)。重症度は疾患 YAML `severity.distribution × modifiers` が canonical。locale `severity_beta`/`severity_minimum` は撤廃済 — 復活禁止。0.3/0.7 のカテゴリ↔score 境界を call-site に hardcode 禁止(`SEVERITY_SCORE_RANGES` が唯一定義) |
| imaging orders | `place_imaging_orders`(`order/engine.py`) |
| 薬剤 protocol prefix 除去 | `strip_protocol_prefix`(`_shared.py`。FHIR と narrative の共用) |
| LOS 計算 | `document/engine._compute_los_days`(in-progress proxy 込み) |
| locale 表示テーブル | `locale/loader.py` の cached loaders(`load_med_terms_ja` 等)。Layer 4 での raw YAML open 禁止 |

新しい共通処理が 2 module に必要になったら `_shared.py` か owner module に 1 箇所定義し
双方 import。**第三の消費者が現れても import、再定義しない。**

## 5. Loader / reference data 規約

- Path 定数正規形: `_HERE = Path(__file__).resolve().parent` / `_REF_DIR = _HERE /
  "reference_data"` / `_LOCALE = _HERE.parents[1] / "locale"`。fragile な
  `.parent.parent.parent` 禁止。他 module の reference_data への直接 path 禁止
  (owner module に accessor を作る。例: `observation.microbiology.antibiotic_loinc_lookup`)。
- `@lru_cache`: no-param → maxsize=1、`(country)` → 2。hand-rolled sentinel cache 禁止。
- **import/load 時 fail-loud validation(`_validate_*`)必須**: 外部 ID(SNOMED/LOINC/ICD/
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

- `codes/data/*.yaml` は **`en` 必須**、出典は authoritative(CMS/NLM/WHO/JCCLS/MHLW)。
  **コードの捏造絶対禁止** — 新 code は NLM API / WHO browser で検証してから登録。
- 診断コード追加時は「Diagnosis code coverage」手順(CLAUDE.md)に従い
  `pytest tests/unit/test_diagnosis_code_coverage.py` green を確認。
- **JP 出力は全 display/text/name が日本語、US 出力は日本語文字 0**(既知の例外 =
  `KNOWN_JA_ONLY_FALLBACK_SECTIONS`。勝手に拡げない)。緊急番号等の locale 依存表現に注意
  (実例: en テキストに「Call 119」が混入 → guard test あり)。
- Condition/Procedure 等は dual coding(local primary + interop)。数値 Observation は
  referenceRange + interpretation を両方 emit し出力時に再計算。

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

- markers: `pytest -m unit`(~15s)/ `integration`(~12min)/ `e2e`(~4min)/
  `regression`(opt-in、goldens byte-diff。template 6 + llm-mock 6)。
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

## 9. Silent-no-op 防御(PR-90 class)チェックリスト

新機能・修正が「実際に発火している」ことを構造的に証明する:

1. **canonical constants** を単一定義し writer/reader 双方が import(ID prefix、URI、
   `HAI_TYPES` 等)。
2. **import/load 時 cross-validation** で typo・欠落を fail-loud に。
3. audit `lift_firing_proof` に equality_checks(発火証明)を追加。
4. **"fired" counter / 観測可能性**: fallback や skip は counter + manifest/stderr で可視化
  (例: `generator_fallback_docs`、eligible>0 かつ fired=0 で WARN)。
5. **aspirational scaffold 禁止**: 登録したが未消費のコード(seed offset、config field、
   strategy 値)は **wire するか削除**。「後で使う」で ship しない。
6. 既知の named precedents(再発防止の合言葉):
   **J5**(flag が 1 venue でしか読まれない)/ **PR-90**(YAML キー大文字小文字不一致で
   lift 全体が無音 no-op)/ **C-1**(dict に getattr で cache key 退化)/
   **Call 119 / ICU drip**(golden に臨床誤りが焼き込み)/ **stale TODO**(実測せず着手)。

## 10. FHIR builder(Layer 4)の要点

詳細 = [`fhir-data-generation-logic.md`](fhir-data-generation-logic.md)。最低限:
CIF は read-only / display・URI・ID prefix は canonical source から / builder 登録は
registry 経由 / dict+dataclass 両 path のテスト必須 / reference integrity(dangling 禁止)。

---

## 読む順序(新規参加の実装 AI 向け)

1. 本書(不変則)
2. [`README.md`](README.md)(読了パス)→ `MODULES.md`(全体地図)
3. `docs/CONTRIBUTING-modules.md`(Layers 1-3 詳細 HOW-TO)
4. `fhir-data-generation-logic.md`(Layer 4、builder を書くとき)
5. `clinosim/modules/output/SPEC.md`(two-pass narrative、Stage 2 を触るとき)
6. 直近の chain 文脈: `.session-resume-prompt.md` + `TODO.md` 各 deferred section
