# アーキテクチャ整合性レビュー — clinosim

## 1. 概要

全体として clinosim のアーキテクチャは健全である。AD-16 (determinism)、AD-17 (CIF-only output)、AD-18 (Pydantic/dataclass 分離) は概ね正しく守られており、stdlib `random` の使用はゼロ (DET-8)、`types/` から `modules/` への逆依存もゼロ (TYP-10)、英語ファースト原則も全 10 code system で完全に enforce されている (CODES-1)。問題は「コンセプト違反」ではなく「コンセプトの適用漏れ」が大半である — 既定のルールは正しいが、機械的に徹底されていない箇所が点在する。

最も価値あるリファクタ 3 点 (value/effort 比で):

1. **DET-4 (`_prev_diet` function-object global state)** — AD-16 を実際に破る唯一の confirmed `high` 違反。process 内で stale state を共有し、`run_forced` の決定的 patient ID (`FORCED-0001` 等) と組み合わさって test 間汚染を起こす。修正は local 変数化のみで small。
2. **FA-4 (ghost field `*_diagnosis_name`)** — `csv_adapter.py:94,96` と `narrative_generator.py:94` が CIF に存在しないフィールドを読み、常に空文字を返している。AD-30 違反かつ実害 (CSV の診断名列が常に空) のある `high`。`code_lookup()` 呼び出しへの置換で解決。
3. **共通 sub-seed helper の抽出 (DET-2/EXT-4)** — `_sub_seed` の同一実装が 3 モジュールにコピペされ、OFFSET 衝突を防ぐ test も無い。AD-16 の中核ロジックが分散しているのは determinism 保証の観点で risk。共有 helper + OFFSET 一意性 test で解決。

---

## 2. モジュール/プラグインの一貫性評価

### `clinosim/types/` 組織と公開 API 境界

統一されている点:
- AD-18 の Pydantic/dataclass 分離は `types/` 内で 0 違反 (TYP-9): `config.py` のみ `BaseModel`、他は全て `@dataclass`。
- レイヤー分離が clean — `types/*.py` に `from clinosim.modules` / `from clinosim.simulator` はゼロ、内部 import も acyclic (TYP-10)。

ズレている点:
- **shared runtime type が module 内に定義** — `PersonRecord`/`LifeEvent`/`HospitalizationSummary` (`population/engine.py:34,81,18`)、`StaffMember`/`StaffRoster` (`staff/engine.py:17,31`)、`ProcedureRecord`/`RehabSession` (`procedure/engine.py:17,426`)、`HospitalState` (`facility/hospital_state.py:17`)。いずれも cross-module で typed import されているのに `types/` 配下に無い (MOD-2,3,4,6 / TYP-2)。CLAUDE.md「All types defined in `clinosim/types/`」に対する違反。
- **CIF の untyped `list` フィールド** — `output.py:52-55` の `intake_output_records`/`adl_assessments`/`nursing_risk_assessments`/`immunizations` は要素型が既に `encounter.py:177-232` にあるのに import されず bare `list` (TYP-3)。一方 `procedures`/`rehab_sessions` は要素型が `modules/` 側にあるため、先に型を移動しないと型付けできない (逆依存になる)。
- **star import による名前漏洩** — `types/__init__.py` の 7 star import で `Any`/`BaseModel`/`dataclass`/`datetime` が `clinosim.types` 名前空間に漏れる (TYP-6)。`__all__` を持つのは `identity.py`/`microbiology.py` のみ。
- **dead code** — `DiagnosticAccuracyConfig` (`clinical.py:94`) は全コードベースで未参照 (TYP-7)。

### `clinosim/modules/` 構造と依存規約

統一されている点:
- `observation/engine.py` は cross-module import ゼロ、全 context を引数で受ける「pure function engine」の規範例 (MOD-13 / OBS-1)。

ズレている点:
- **`__init__.py` が 18 中 17 が 0 バイト** — `identity/__init__.py` (378 バイト, `__all__` あり) のみが公式 API surface を持つ。残りは `.engine` から直接 import される (MOD-1 / TYP-1)。CLAUDE.md「Public API surface: only what's exported in module `__init__.py`」が事実上死文化。
- **private 関数の cross-module import** — `patient/activator.py:13` が `population/engine.py:589` の `_sample_given_name` (underscore = private) を import (MOD-7 / TYP-5)。encapsulation 違反。関数の実体は locale name data の sampler であり、本来 `locale/` に属する。
- **依存宣言 heading の不統一** — `identity/README.md` のみ英語 `## Dependencies`、他 17 は `## 依存関係` (MOD-12)。内容は存在するが CI で parse できない。
- `disease/protocol.py:15` の `DiseaseProtocol(BaseModel)` は cross-module 利用される config 型だが、loader と YAML directory に密結合しているため borderline (MOD-5 / TYP-2 partly)。移動より `disease/__init__.py` 経由の export が現実的。

### Extension Point Registries (AD-55..58)

ズレている点 (3 registry が三者三様):
- **builtins ロード方式が 3 パターン** — bundle builder は静的 list literal (`fhir_r4_adapter.py:1119`)、output adapter は lazy `_ensure_builtins()` (`adapter.py:46`)、enricher は明示呼び出し `register_builtin_enrichers()` (`enrichers.py:64`, `engine.py:103`) (EXT-2)。
- **冪等性戦略が三者三様** — adapter は dict overwrite (last-wins, `adapter.py:43`)、enricher は name skip (first-wins, `enrichers.py:49`)、builder は identity-check (`if builder not in`, `fhir_r4_adapter.py:1140`) (EXT-3)。builder の identity-check が最も脆い: 同一意図の別 callable が二重登録され得る。
- **builder に metadata 型が無い** — `Enricher` dataclass (`enrichers.py:35-40`) は name/stage/order/enabled を持つが `_BUNDLE_BUILDERS` は plain callable list (EXT-1)。
- **`module_enabled()` が production で未使用** — `types/config.py:128-130` で定義されるが call site ゼロ。enricher の enabled lambda は直接属性チェック (`enrichers.py:79,93,106`) を使い、AD-56 が広告する gating が未配線 (EXT-5)。
- **`register_bundle_builder()` が公開 surface から未 export** — `fhir_r4_adapter.py:1138` 定義のみ。`register_output_adapter`/`register_enricher` との非対称 (EXT-7 partly)。
- **prefix 不統一** — `_build_nursing_observations`/`_build_immunizations` (`fhir_r4_adapter.py:870,1065`) が他 13 個の `_bb_*` に混在 (EXT-6)。
- **enricher registry が list (O(n) lookup)** — `_ENRICHERS: list` (`enrichers.py:43`)。3 件なので性能は無関係だが、first-wins skip が test override を阻む (EXT-8)。

### Output Adapters (FHIR R4 + CSV)

統一されている点:
- JP localization dict が `fhir_r4_adapter.py` に正しく隔離され、enrichment path は language-neutral (AD-44 準拠)。`hospital_course_extractor`/`narrative_generator`/`llm_service` に JP dict 参照ゼロ (FA-6)。

ズレている点:
- **monolith** — `fhir_r4_adapter.py` は 3542 行、54 関数、15+ resource type、~14 JP dict を 1 ファイルに集約 (FA-1 / MOD-9)。AD-56 registry 自体は正しく実装されている。
- **wrap 契約の例外** — `_build_vital_observations` だけが `_entry()` で wrap 済み dict を返す (`fhir_r4_adapter.py:2636,2685,2736`)。他の全 `_build_*` は raw resource dict を返す。`_bb_vitals` が unwrap して辻褄を合わせているが、4 つ目の vital 追加時に double-wrap する罠 (FA-3)。
- **procedure display lookup の重複** — `_procedure_display` (`fhir_r4_adapter.py:1577`) は単一 code のみ、`_resolve_procedure_name` (`hospital_course_extractor.py:288`) は 3 code field 全てを試す。FHIR adapter の caller (`:3050-3056`) は `procedure_code` のみ渡すため、`procedure_code_jp` のみセットの場合に display が空 (FA-5)。
- **CSV adapter が country を無視** — `convert_cif_to_csv` に country 引数が無く (`csv_adapter.py:13`)、`CsvAdapter.convert` が `ctx.country` を drop (`adapters_builtin.py:17-20`)。FHIR adapter は `country=ctx.country` を渡す (FA-9)。
- **vital LOINC display の hardcode と乖離** — `_vital_map` (`fhir_r4_adapter.py:2524-2531`) のインライン display が `loinc.yaml` と不一致 (例: `8867-4` が `脈拍` vs loinc.yaml `心拍数`、`2708-6` が `Oxygen saturation` vs `Oxygen saturation in Arterial blood`) (FA-8)。

### YAML / Data-Driven パターン

統一されている点:
- code lookup architecture は健全 — `code_lookup` が ICD/LOINC/SNOMED/RxNorm display を一貫して解決、`load_code_mapping()` も一貫適用 (CODES-1)。
- `observation/engine.py` の科学パラメータ (BIOLOGICAL_CV 等) はインライン Python が正解 (OBS-1)。

ズレている点:
- **encounter protocol が Pydantic 非検証** — `encounter/protocol.py:15-38` は raw `dict[str,Any]` を返し、`except Exception: pass` (`:35`) が YAML parse error を握り潰す。`disease/protocol.py` の `DiseaseProtocol(BaseModel)` と非対称、AD-18 違反。46 YAML が無検証 (ENC-1)。
- **HL7 URI の hardcode** — `fhir_r4_adapter.py` に ~25-28 個の HL7/LOINC/SNOMED/UCUM URI が string literal で埋め込まれ `get_system_uri()` を bypass (URI-1 / FA-2 / CODES-4)。特に `observation-category` は `_BUILTIN_URIS` に登録済みなのに 5 箇所で hardcode (`:1628,2422,2545,2656,2697`)、UCUM は 16 箇所 hardcode で `get_system_uri('ucum')` 呼び出しゼロ。
- **display 表の分散・重複**:
  - `_DEPT_DISPLAY_JA` (19 entry, `:428-448`) vs `_DEPARTMENT_DISPLAY` (10 entry, `:2141-2152`) — 同概念の言語別分割表。EN 表は 9 department 欠落で US 出力に silent fallback バグ (DUP-1)。
  - `_MED_TERMS_JA` (~149 entry, `:54-203`) と `_MED_CATEGORY_JA` がインライン Python だが drug name は YAML 駆動 (DUP-2)。
  - `CONDITION_NAMES` (`activator.py:60-108`) が `code_lookup()` の display を重複 (DUP-3)。
  - `_CONDITION_SHORT_NAME` (`:1780-1833`) — clinical 略称表。ただし CLAUDE.md が明示的に使用を指示しており、authoritative ICD text とは別概念 (DUP-4 partly、移動見送り推奨)。
- **dead import / stale docstring** — `load_terminology` は `fhir_r4_adapter.py:17` で import されるが未使用、対象 YAML も migration 済 (LOC-2 / CODES-3)。`locale/loader.py:4-11` docstring が `japan/` (実体は `jp/`) と削除済 terminology file を参照 (CODES-11)。
- **loader bypass** — `activator.py:384-390` が `chronic_medications.yaml` を直接 `yaml.safe_load`、`locale/loader.py:89` の `load_chronic_medications()` (lru_cache 付き) を迂回 (LOC-1)。
- **R69 fallback の hardcode** — `diagnosis/engine.py:193,207` が `'Illness, unspecified'` を literal return、同ファイルの `_display()` を bypass。JP 出力で英語表示になる (DIAG-1)。
- **JP interpretation の不整合** — `determine_flag()` が locale range を渡されず (`inpatient.py:604,1615`, `outpatient.py:178`, `emergency.py:146`)、JP 出力で `Observation.interpretation` (H/L) が US default に対して計算される一方 `referenceRange` は JCCLS 値を表示 (OBS-3)。

### Data Generation & Determinism (AD-16/AD-17)

統一されている点:
- 全 venue simulator が return-based で CIF を構築 (`inpatient.py:402`, `outpatient.py:254`, `emergency.py:228`)、共有 collection への直接書き込みゼロ (DET-7)。
- stdlib `random` 使用ゼロ (DET-8)。

ズレている点:
- **`_prev_diet` function-object global state** (`inpatient.py:761,774-776`) — AD-16 を実際に破る (DET-4, 詳細は概要参照)。
- **`generate_observations` wrapper の未抽出** — 同一ロジックが 4 箇所に重複 (`inpatient.py:580-612`, `:1611-1623`, `outpatient.py:156-187`, `emergency.py:124-155`)。inpatient main path のみ specimen-rejection / hemolysis 分岐を持ち、ED 患者は検体喪失しない silent な臨床不整合 (DET-1, TODO.md:323)。
- **identity の sub-seed が非 keyed** — `assign.py:33` が `master_seed + offset` の単一共有 RNG。他 3 enricher は per-patient の sha256 keyed RNG (DET-3)。
- **baseline fallback dict の乖離** — `outpatient.py:149-154` (WBC 6500, CRP 0.5, HbA1c 6.5) vs `emergency.py:107-109` (WBC 7500, CRP 1.0, HbA1c 5.6) (DET-6, TODO.md:310)。
- **DES engine 未配線** — `_handle_outpatient`/`_handle_ed_visit` が空 stub (`des_engine.py:300-307`)、`DESEngine` は engine.py から未参照 (DET-5)。doc gap のみ。

### codes + locale 分離

統一されている点 (good):
- 英語ファースト invariant が全 10 system / 1004 codes で 0 欠落、test で enforce (CODES-1)。
- terminology file の codes/ migration 完了、locale に display text 残存ゼロ (CODES-2)。
- diagnosis code coverage test が 3 source 網羅 + WHO format guard (CODES-5)。

ズレている点:
- **RxNorm CUI 18631 の捏造 display** — `code_mapping_drug.yaml:8-9` が Amoxicillin/Clavulanate と Azithromycin 双方を `18631` に map、`rxnorm.yaml:68-70` が両者を連結した非実在 display を持つ (CODES-7, `high`)。NLM 権威に反する。
- **非診断コードの coverage test 欠如** — RxNorm/YJ/CPT/K-codes/CVX に diagnosis 相当の emittable-code test が無い (CODES-6)。現状は clean だが CODES-7 を捕捉できなかった。
- 軽微: RBC が JP map のみ US map 欠落 (CODES-9, US で未 emit なら意図的)、`drug_ja` 分岐が production 到達不能 (CODES-10)。

---

## 3. リファクタリング候補 (優先順位付き)

confirmed / partly-confirmed のみ。value/effort 順。コンセプト適合 = 修正が CLAUDE.md/AD の原則に明確に沿うか。

| id | 対象 (file:line) | 問題 | 推奨 | effort | risk | コンセプト適合 |
|---|---|---|---|---|---|---|
| DET-4 | `inpatient.py:761,774-776` | `_prev_diet` が function-object に process 寿命の global state を蓄積 (AD-16 違反) | `_run_daily_loop` の local 変数化、`getattr` 撤去 | small | low (golden 差分は汚染依存時のみ) | ◎ AD-16 中核 |
| FA-4 | `csv_adapter.py:94,96`; `narrative_generator.py:94` | 存在しない `*_diagnosis_name` を読み常に空 (AD-30 違反、実害) | `code_lookup(system, code, lang)` に置換、import 追加 | small | CSV golden 更新要 | ◎ AD-30 |
| CODES-7 | `code_mapping_drug.yaml:8-9`; `rxnorm.yaml:68-70` | CUI 18631 を 2 薬剤で共有、捏造 display | NLM rxnav で正 CUI 取得、分離登録 | small | US MedicationRequest golden 更新要 | ◎ 権威出典 |
| LOC-2/CODES-3 | `fhir_r4_adapter.py:17` | `load_terminology` dead import | import 削除 | small | none | ○ |
| LOC-1 | `activator.py:384-390` | `chronic_medications.yaml` を loader 迂回で直読み | `load_chronic_medications()` に置換 | small | none | ○ canonical loader |
| DIAG-1 | `diagnosis/engine.py:193,207` | R69 を literal return、`_display()` bypass (JP で英語化) | `_display('R69')` に置換 | small | JP golden (R69 は稀) | ○ 言語中立 |
| CODES-11 | `locale/loader.py:4-11` | docstring が `japan/` + 削除済 file 参照 | docstring 更新 | small | none | ○ |
| TYP-8 | `types/__pycache__/narrative*.pyc` | source 無き stale pyc (gitignore 済) | `find -delete` でローカル掃除 | small | none | ○ |
| TYP-3 | `output.py:52-55` | 4 フィールドが bare `list` (型は encounter.py に既存) | `encounter.py` から import し型付け | small | none (注釈のみ) | ◎ type-location |
| TYP-6 | `types/__init__.py` | star import で stdlib/Pydantic 名漏洩 | 5 file に `__all__` 追加 | small | none | ○ |
| EXT-6 | `fhir_r4_adapter.py:870,1065` | `_build_*` prefix が `_bb_*` に混在 | `_bb_` に rename + test import 更新 | small | test のみ | ○ |
| EXT-7 | `output/__init__.py` | `register_bundle_builder` 未 export | `__init__.py` から再 export (file split せず) | small | none | ○ AD-56 |
| DET-2/EXT-4 | `immunization/enricher.py:19`; `nursing_enricher.py:28`; `microbiology.py:39` | `_sub_seed` 3 重コピペ、OFFSET 衝突 test 無 | `helpers.py` に `derive_sub_seed` 抽出 + 一意性 test | small | low (式不変なら golden 不変) | ◎ AD-16 |
| MOD-7/TYP-5 | `activator.py:13`; `population/engine.py:589` | private `_sample_given_name` を cross-module import | `locale/names.py` に public 昇格 | small | none (rng 引数渡し) | ◎ encapsulation |
| OBS-3 | `inpatient.py:604,1615`; `outpatient.py:178`; `emergency.py:146` | JP で interpretation が US default 計算 (referenceRange と不整合) | `reference_ranges=load_reference_ranges(country)` を渡す | small | JP H/L flag golden 更新要 | ◎ JP compliance |
| DET-6 | `outpatient.py:149-154`; `emergency.py:107-109` | baseline fallback の WBC/CRP/HbA1c 乖離 | `observation/engine.py` に単一 `_BASELINE_LAB_NORMALS` | small | fallback path のみ golden | ○ |
| EXT-5 | `enrichers.py:79,93,106`; `config.py:128` | `module_enabled()` 未配線 | enricher の enabled を `module_enabled(default=...)` 経由に | small | none (default 維持) | ◎ AD-56 |
| EXT-8/EXT-3 | `enrichers.py:43,49` | enricher registry が list + first-wins | `dict[str, Enricher]` 化 (last-wins + warning) | small | none (order 整数不変) | ○ |
| ENC-1 | `encounter/protocol.py:15-38` | Pydantic 非検証、error 握り潰し | `EncounterConditionProtocol(BaseModel)` + `extra='allow'` | small | none (検証 wrapper) | ◎ AD-18 |
| MOD-4/TYP-2 | `staff/engine.py:17,31` | `StaffMember`/`StaffRoster` が module 内 | `types/staff.py` へ移動、`__init__` 再 export 先行 | small | none (import 破壊管理) | ◎ type-location |
| MOD-6 | `facility/hospital_state.py:17` | `HospitalState` が module 内 | `types/facility.py` へ移動 | small | none | ◎ type-location |
| MOD-5 | `disease/protocol.py:15` | `DiseaseProtocol` が module 内 (loader 密結合) | `disease/__init__.py` 経由 export (移動は任意) | small | none | ○ borderline |
| DET-3 | `assign.py:33,40,42` | identity sub-seed が非 keyed | `derive_sub_seed(.., person_id/household_id)` per member | small | JP identity golden 更新 (意図的) | ○ |
| FA-3 | `fhir_r4_adapter.py:2636,2685,2736` | vital builder のみ wrap 済 dict 返却 | `_entry()` 撤去し raw 返却、`_bb_vitals` を extend | small | none (NDJSON 不変) | ○ |
| FA-5 | `fhir_r4_adapter.py:3056` | procedure display が 1 code のみ参照 | `_resolve_procedure_name(proc, lang)` に委譲 | small | jp-only code で golden | ○ DRY |
| FA-9 | `csv_adapter.py:13`; `adapters_builtin.py:17` | CSV が `ctx.country` 無視 | `country='US'` 引数追加 (FA-4 と連動) | small | diagnoses.csv のみ | ○ |
| DUP-3 | `activator.py:60-108`; `outpatient.py:230` | `CONDITION_NAMES` が `code_lookup` 重複 | `code_lookup('icd-10-cm', code, 'en')` に置換 | small | display 文字列が長形に | ○ AD-30 |
| CODES-6 | (新規 test) | 非診断 code coverage test 欠如 | `test_nondiagnosis_code_coverage.py` 追加 | small | none (additive) | ◎ |
| DET-1 | `inpatient.py:580`; `outpatient.py:156`; `emergency.py:124` | `generate_observations` wrapper 4 重複、pre-analytical 分岐の不整合 | `_resolve_lab_orders(.., pre_analytical=)` を helpers.py に抽出 | medium | golden risk (RNG draw 順) | ◎ DRY |
| URI-1/FA-2/CODES-4 | `fhir_r4_adapter.py` (~25-28 箇所) | HL7/LOINC/SNOMED/UCUM URI hardcode | `_BUILTIN_URIS` 拡張 + `get_system_uri()` 置換、URI assert test 先行 | medium | URI 値不変なら golden 不変 | ◎ URI ルール |
| MOD-2/TYP-2 | `population/engine.py:18,34,81` | `PersonRecord` 等が module 内 | `types/population.py` へ移動 (再 export 先行) | medium | none (import 多数) | ◎ type-location |
| MOD-3 | `procedure/engine.py:17,426` | `ProcedureRecord`/`RehabSession` が module 内 | `types/procedure.py` へ移動、CIF 型付け、adapter を typed access に | medium | CIF serialize path 検証要 | ◎ type-location |
| DUP-1 | `fhir_r4_adapter.py:428,2141` | dept display 表が言語別分割、EN 9 件欠落 | `locale/shared/department_display.yaml` に統合 | small | US dept display golden | ○ |
| DUP-2 | `fhir_r4_adapter.py:32-203` | `_MED_TERMS_JA`/`_MED_CATEGORY_JA` インライン | `locale/shared/med_terms_ja.yaml` に移行 | small | JP med text golden | ○ |
| MOD-11 | `fhir_r4_adapter.py:1780-1833` | `_CONDITION_SHORT_NAME` が codes/ 重複 | `short_name` field を codes YAML に + `lookup(field=)` | medium | Condition.code.text golden 更新 | ○ (DUP-4 と緊張) |
| MOD-1/TYP-1 | 全 `__init__.py` | 17/18 が空、公式 API surface 無 | 境界を跨ぐ型/関数を `__init__` で再 export | medium | none (caller 移行は段階的) | ◎ |
| MOD-12 | 17 README | 依存 heading 不統一 (`## 依存関係`) | `## Dependencies` に標準化 + CI lint | small | none (doc のみ) | ○ |
| EXT-1/EXT-3 | `fhir_r4_adapter.py:1119,1140` | builder に metadata 無、identity-check 脆弱 | `available_builders()` + name-based dedup (BundleBuilder 型は use case 待ち) | small | none | ○ (過剰実装は回避) |
| EXT-2 | 3 registry | builtins ロード 3 パターン | enricher を lazy `_ensure_builtins()` 化 (任意) | small | low | △ 意図的差異あり |
| TYP-7 | `clinical.py:94` | `DiagnosticAccuracyConfig` dead code | 削除 (or `SimulatorConfig` に配線) | small | 削除は none | ○ |
| FA-8 | `fhir_r4_adapter.py:2524-2531` | vital LOINC display が loinc.yaml と乖離 | `_loinc_coding()` 化 (loinc.yaml ja 確認後) | small | vital display golden 更新 | ○ (要権威確認) |
| FA-1/MOD-9 | `fhir_r4_adapter.py` (3542 行) | monolith | `_localization.py` から段階抽出、各抽出後 e2e | large | high (golden) | ○ (急がない) |

**defer 推奨 (reject 含む)**: MOD-8 (`DiagnosisCandidate`/`DifferentialDiagnosis` は真に module-local、cross-module leak 無 — 先回り移動は reject)。PHY-1 (physiology の条件分岐は DSL 無しに YAML 化不可、係数変更は全 golden 破壊 — condition 数 15 まで据え置き)。OBS-2 (4 qualitative test は安定、~8 超で YAML 化)。DET-5 (DES 統合は別 feature)。DUP-4 (clinical 略称は authoritative ICD text と別概念、2 つ目 adapter 登場まで据え置き)。CODES-9/CODES-10 (軽微、scope 確認後)。

---

## 4. 共通化 (commonalization) の見直し

コンセプトに合致し、かつ重複を実際に減らす共通化のみ。

### 4.1 sub-seed 導出 helper (DET-2 / EXT-4)
- **現状**: `_sub_seed(master, key)` の同一 3 行実装が `immunization/enricher.py:19` (offset `0x494D`)、`nursing_enricher.py:28` (`0x4E55`)、`microbiology.py:39` (`_encounter_seed`, `770_077`) にコピペ。OFFSET 衝突を防ぐ test が存在しない。
- **共有 API**: `clinosim/simulator/helpers.py` に
  ```
  def derive_sub_seed(master: int, module_offset: int, key: str) -> int
  ```
  式は `sha256(key.encode()).digest()[:6]` + offset を**完全に維持**。各モジュールは自身の OFFSET 定数を渡す (変更しない)。
- **determinism/golden 安全性**: 式が byte 数・modulus・endianness 込みで不変なら RNG stream は不変 → golden 不変。**先に** `derive_sub_seed(42, 0x4E55, 'pid-1') == <precomputed>` の unit test を書き、各ローカルコピー削除前に green を確認。加えて「全登録 OFFSET が distinct」の test を新設。`identity/assign.py:33` の単純式 (key hash 無) はそのまま残す (1 RNG/population pass の設計)。

### 4.2 lab order 解決 wrapper (DET-1)
- **現状**: order→canonical_lab_name→generate_lab_result→determine_flag→OrderResult→append が 4 箇所重複。inpatient main path のみ 2% specimen-rejection / 3% hemolysis 分岐を持ち、ED/outpatient には無い (臨床不整合)。
- **共有 API**: `clinosim/simulator/helpers.py` に
  ```
  def _resolve_lab_orders(orders, true_labs, patient, rng, *,
      hospital_state=None, hospital_ops=None, roster,
      country: str, pre_analytical: bool = False) -> list[OrderResult]
  ```
  `pre_analytical=True` は inpatient main path のみ。各 venue が自身の rng を渡す → per-order draw 順は不変。`country` を加えれば OBS-3 (locale range を `determine_flag` に渡す) も同時解決できる。
- **determinism/golden 安全性**: pre-analytical 分岐は同一 order iteration 内の chance-gated 継続なので既存 draw 数を変えない。抽出後に `pytest -m e2e` で golden を diff。OBS-3 の range 注入を含める場合は JP H/L flag golden の更新が発生 (意図的)。

### 4.3 registry helper / metadata (EXT-1 / EXT-3 / EXT-8)
- **現状**: 3 registry が冪等性・ロード・storage で三者三様。builder の identity-check が最も脆い。
- **共有 API**: 全 registry の完全統一は不要 (last-wins=format override / first-wins=二重登録防止 という意味的差異は意図的)。最小修正:
  - bundle builder に `available_builders() -> list[str]` introspection を追加し、`register_bundle_builder` の dedup を identity から name-based に。
  - enricher を `dict[str, Enricher]` 化 (`run_stage` は `sorted(values, key=lambda e:(e.order,e.name))`)、name 上書き時に warning log。
  - `BundleBuilder` dataclass / `enabled` predicate は**具体的 use case (内部 gate できない country-gated builder) が出るまで導入しない** — 既存全 `_bb_*` に lambda を強制するのは pure churn。
- **determinism/golden 安全性**: order 整数が不変なら sort 結果は不変 → golden 不変。builder list は FHIR entry 順に影響するが順序非依存。e2e で before/after 確認。

### 4.4 dept display / med terms の YAML 統合 (DUP-1 / DUP-2)
- **現状**: 言語別に分割された Python dict。EN dept 表は 9 件欠落 (US silent bug)。
- **共有 API**: `locale/shared/department_display.yaml` (`{key:{en,ja}}`) + `load_department_display()`、`locale/shared/med_terms_ja.yaml` + `load_med_terms_ja()` (lru_cache)。`drug_names_ja.yaml` が既存の手本。
- **safety**: display-only。US dept display (9 件) と JP med text の golden 更新が発生。CIF 不変。

### 4.5 sub-seed 以外で抽出**しない**もの
- physiology 係数 (PHY-1)、observation 科学パラメータ (OBS-1) は co-located が正解 — YAML 化は I/O 依存を増やすだけで保守性向上なし、変更時はどのみち code review が必要。

---

## 5. 既に良い設計 (維持・横展開)

- **`observation/engine.py` の pure function engine** (MOD-13 / OBS-1) — cross-module import ゼロ、全 context を引数で受ける。他 module refactor 時の規範。CLAUDE.md に「no cross-module deps の例」として明記推奨。
- **return-based CIF contribution** (DET-7) — 全 venue が `return CIFPatientRecord(...)`、共有 collection 直書きゼロ。AD-17 を完全遵守。
- **stdlib random 不使用** (DET-8) — `import random` ゼロ。`grep` pre-commit hook で回帰防止を検討。
- **AD-18 Pydantic/dataclass 分離** (TYP-9) — `types/` 内 0 違反。
- **`types/` の clean layer 分離** (TYP-10) — `modules/`/`simulator/` への逆依存ゼロ、内部 acyclic。type 移動 (MOD-2,3,4,6) 時もこの不変条件を死守。
- **英語ファースト invariant** (CODES-1) — 全 10 system / 1004 codes で test + fallback chain により enforce。
- **terminology の codes/ migration 完了** (CODES-2)。
- **diagnosis code coverage test** (CODES-5) — 3 source 網羅 + WHO format guard。CODES-6 で同パターンを RxNorm/YJ/CPT/K-codes/CVX に横展開すべき。
- **enrichment path の language-neutral 隔離** (FA-6 / AD-44) — JP dict が `fhir_r4_adapter.py` 外に漏れない。FA-1 split 時もこの境界を守る (`_localization.py` を extractor/narrative/llm_service から import させない)。
- **AD-56 registry の正しい実装** — `register_bundle_builder` (`:1138`)、`register_output_adapter`、`register_enricher` は `_build_bundle` を編集せず拡張可能。

---

## 6. 推奨実装順序

### Phase 1 — golden に触れない安全な即効修正 (single PR 可)
1. dead code / cosmetic: LOC-2/CODES-3 (dead import 削除)、CODES-11 (docstring)、TYP-8 (pyc 掃除)、TYP-7 (`DiagnosticAccuracyConfig` 削除)。
2. loader 正規化: LOC-1 (`load_chronic_medications` 経由)。
3. 型注釈のみ: TYP-3 (CIF 4 フィールド型付け)、TYP-6 (`__all__` 追加)。
4. internal rename / 再 export: EXT-6 (`_bb_` 統一)、EXT-7 (`register_bundle_builder` 再 export)、FA-3 (vital wrap 撤去 — NDJSON 不変)。
5. encapsulation: MOD-7/TYP-5 (`_sample_given_name` を `locale/names.py` 昇格)。
6. 検証 wrapper: ENC-1 (`EncounterConditionProtocol` + `extra='allow'`)。
→ 各ステップ後 `pytest -m unit`、PR 末で `pytest -x`。

### Phase 2 — determinism / 正しさ修正 (golden 更新を伴うが意図的)
7. **DET-4** (`_prev_diet` local 化) — 最優先。先に e2e で diet-order 数を記録。
8. **共有 sub-seed helper** (DET-2/EXT-4) — precomputed test 先行、式不変確認。OFFSET 一意性 test 新設。
9. **FA-4 + FA-9 + DUP-3** (ghost field → `code_lookup`、CSV に country 注入) — CSV golden 更新。
10. **CODES-7** (RxNorm CUI 修正) — NLM rxnav 照合、US med golden 更新。**CODES-6** (非診断 coverage test) を同時に追加し回帰防止。
11. DIAG-1 (R69 `_display()`)、OBS-3 (locale range 注入 — DET-1 と合流可)、DET-6 (baseline 統一)。

### Phase 3 — 構造リファクタ (type-location / registry、段階 PR)
12. type 移動 (各 1 PR、再 export 先行 → engine import 切替 → caller 移行): MOD-4 (staff) → MOD-6 (facility) → MOD-2 (population) → MOD-3 (procedure)。MOD-5 (disease) は `__init__` export のみ。
13. MOD-1/TYP-1 (`__init__.py` 公式 surface) を type 移動と並走。
14. registry helper (EXT-1/EXT-3/EXT-8 — name-based dedup、enricher dict 化、`available_builders()`)、EXT-5 (`module_enabled` 配線、default 維持)。
15. **DET-1** (`_resolve_lab_orders` 抽出) — RNG draw 順を e2e diff で検証。
16. URI-1/FA-2/CODES-4 (URI を `get_system_uri` 経由に、assert test 先行)。
17. DUP-1/DUP-2 (dept/med term の YAML 化)、MOD-11 (`short_name` を codes/ に — DUP-4 の緊張を踏まえ codes/data 内別ファイル or locale 配置を別途判断)、FA-5/FA-8 (procedure/vital display 統一)。

### Defer (別 feature branch / 据え置き)
- **FA-1/MOD-9** (3542 行 split) — high golden risk。Phase 2/3 完了後、`_localization.py` から段階抽出し各抽出後に e2e。急がない。
- DET-3 (identity keyed sub-seed) — JP identity golden が変わるため、announce 付きで単独 PR。
- DET-5 (DES 統合)、PHY-1 (physiology DSL)、MOD-8 (preemptive 移動 reject)、DUP-4 (2 つ目 adapter まで)、CODES-9/10 (scope 確認後)。
- MOD-12 (README heading 統一 + CI lint) — doc-only、任意のタイミング。