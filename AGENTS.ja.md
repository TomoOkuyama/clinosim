# clinosim — AGENTS.ja.md

> **AI コーディングエージェント向け**: 本 file は自動化コーディング
> エージェント向けの canonical 指示書。
> [AGENTS.md convention](https://agentmd.dev) に従い、全 agent
> (Claude Code、Codex、Cursor、Gemini CLI、Copilot 等) に適用されます。
> 人間コントリビュータは [`CONTRIBUTING.ja.md`](CONTRIBUTING.ja.md)
> を参照してください。
>
> Claude Code ユーザーは [`CLAUDE.md`](CLAUDE.md) も引き続き参照可
> — 本 file への薄い pointer で後方互換性を保っています。
>
> 英語版 (canonical): [`AGENTS.md`](AGENTS.md)。

## プロジェクト概要

clinosim は population 駆動 / physiology ベースの合成 EHR data
simulator。ユーザー向け概要は `README.md` (英語) / `README.ja.md`
(日本語)、完全 architecture (ADR 群) は `DESIGN.md` (→
`docs/architecture/` 3 file に split)、roadmap は
[`docs/roadmap.md`](docs/roadmap.md) (GitHub Issues board 指定)、
モジュール別 reference は各 `modules/<name>/README.md` /
`README.ja.md`。

## Quick navigation

| Looking for | Read |
|---|---|
| ★ プロジェクトコンセプト + パイプライン概説 (最初に読む) | [`docs/design-guides/project-concept-and-design.md`](docs/design-guides/project-concept-and-design.md) |
| ★ 実装ルール抽出 (must-follow invariant) | [`docs/design-guides/implementation-rules.md`](docs/design-guides/implementation-rules.md) |
| ★ ドキュメント + code-quality ポリシー (全 contributor 順守) | [`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md) |
| ★ データがどう生成されるか (end-to-end walkthrough) | [`docs/design-guides/data-generation-walkthrough.md`](docs/design-guides/data-generation-walkthrough.md) |
| モジュール概観 (33 モジュール一覧) | [`MODULES.ja.md`](MODULES.ja.md) |
| Scenario / medication flag (`causes_X` / `on_warfarin`) | [`SCENARIO_FLAGS.ja.md`](SCENARIO_FLAGS.ja.md) |
| Architecture + ADR 表 (55+) | [`DESIGN.ja.md`](DESIGN.ja.md) |
| Module author HOW-TO + PR 検証ガイド | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) (英語) |
| 新 module template (boilerplate) | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| Roadmap | [`docs/roadmap.md`](docs/roadmap.md) (GitHub Issues board) |
| ★ Audit-cycle ワークフロー + by-design 除外 registry | [`docs/audit-cycles/README.md`](docs/audit-cycles/README.md) + [`docs/audit-cycles/by-design-registry.md`](docs/audit-cycles/by-design-registry.md) (英語) |

## 言語規約

- **Code**: Python 3.11+
- **Documentation + コメント言語ペア**:
  [`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md)
  §2.4 (documentation-file 言語ペア) と §4 (source code コメント —
  英語 default; JP-Core / JP-CLINS profile invariant、JLAC10 /
  JJ1017 / MEDIS code system 固有事項、および日本語 authoritative
  source からの verbatim 引用のみ日本語) に従うこと。同ポリシーが
  全 contributor 向けの canonical ルールで、本 AGENTS では複製しない。
- **ユーザーとのコミュニケーション**: 日本語。

### Canonical vocabulary (Issue #565)

review で drift が出る繰り返し命名。canonical form を採用し
anti-pattern は review コメントで直す。

| Concept | Canonical | Anti-patterns |
|---|---|---|
| Pass-through context object (parameter) | `ctx` | `context` |
| Hospital-operations dict (`config/hospital_operations.yaml` から load) | `hospital_ops` | `hospital_config`, `ops_config`, `hospital_cfg` |
| Silent behaviour バグを表す語 (prose) | `silent-no-op` (ハイフン) | `silent-no-op` (spaced) |
| 導出値を表す動詞 (function prefix) | `derive_X` | `compute_`, `calculate_`, `determine_` (Issue #564) |
| Bundle-builder (`list[dict]` 返却、`_BUNDLE_BUILDERS` 登録) | `_bb_X` | 返却型が `list` なのに `_build_X` (Issue #558) |
| 単一 resource / fragment builder (`dict` 返却) | `_build_X` | (anti-pattern なし; そのまま) |

Docstring style: **Google 風** (signature が非自明なとき Args /
Returns / Raises)。NumPy style は使わない (legacy 4 docstring は
本節追加 PR で移行済)。signature が自明なら bare prose も可。

一部の canonical parameter 名 (例: `hospital_config` → `hospital_ops`)
は該当 dataclass field 名が旧名を持つため drift が残っている。
module-by-module で cleanup 中 (linked issue 参照)。

## Country / locale 規約

- **Default country = US**。CLI subcommand と programmatic API は
  値未指定時に `country="US"`。コード内 fallback も必ず US 既定 —
  JP へ既定してはいけない。Anti-pattern: `x.get(country_key) or
  x.get("japan", {})` や `x if is_us(country) else "JP"` (どちらも
  規約を反転する)。
- **JP は opt-in**。明示 `--country JP` (CLI) または
  `country="JP"` (API) 経由。JP 専用モジュール — JP Core /
  JP-CLINS profile 適用、JCCLS reference range、JST (`+09:00`)
  timestamp appender、MHLW ICD system 経路、MEDIS code emit、
  保険者番号 lookup、JP 固有表示文字列 — は
  `clinosim.modules._shared` の `is_jp(country)` で gate し、
  非 JP コホートで no-op すること。
- **将来の US 固有 profile 対応** (US Core / USCDI) も同様に
  `is_us(country)` で gate する予定。default cohort (`--country`
  なし) は汎用 FHIR R4 を emit、明示 `--country US` で US Core を
  追加適用する予定。
- **Fallback 方向**: `x if is_jp(country) else "us"` を使い、
  `x if is_us(country) else "jp"` は使わない。pre-commit / CI
  grep が新規の `else "japan"` / `else "JP"` fallback を reject。
- **Locale-gate regression test**
  (`tests/regression/test_us_cohort_no_jp_literals.py` と兄弟
  `test_jp_cohort_no_us_literals.py`) が US cohort に JP 固有
  literal (`+09:00`、JP-CLINS / JP Core profile URI、MEDIS /
  MHLW / JLAC10 system URI) を含まないこと、および JP cohort に
  US 固有 literal を含まないことを assert する。

## コード標準

- Formatter: ruff
- 型検査: mypy (strict mode)
- Line length: 100
- 型: YAML load 済み config には Pydantic BaseModel (AD-18)。
  runtime 型は `@dataclass`。
- 全型は `clinosim/types/` に定義 — モジュールコード内でデータ型を
  定義しないこと。
- 公開 API 表面: module `__init__.py` で export したもののみ。

## Architecture ルール

### データフロー + 所有

- **CIF はシミュレーションの唯一の出力** (AD-17) — format adapter
  (FHIR、CSV) は CIF を読み、simulation 内部を読まない。
- **CIF はコードのみ保持、表示テキストは保持しない** (AD-30) —
  `ClinicalDiagnosis.admission_diagnosis_code` + `_system`、
  `_name` なし。表示は出力時に `clinosim.codes` 経由で解決。
- **コードが truth** — 内部 test 名 (例 `"WBC"`) は
  `locale/<country>/code_mapping_*.yaml` 経由で標準コード (LOINC)
  にマップされる。表示テキストは `clinosim/codes/data/<system>.yaml`。

### 詳細な ADR 節

本 file の英語版
([`AGENTS.md`](AGENTS.md) 「Two-pass CIF generation invariant (AD-65)」
以降) は各 ADR (AD-16 / AD-30 / AD-32 / AD-55 / AD-56 / AD-57 /
AD-58 / AD-59 / AD-60 / AD-61 / AD-62 / AD-63 / AD-64 / AD-65 /
AD-66 / AD-67 / AD-68 / AD-69) と Phase 3a / 3b-1 / 3b-2 / 3b-3 /
3b-5 chain の詳細を保持しています。JA 話者が英語版へ深入りする
前に把握すべき hot-spot は以下:

- **Sub-seed 中央 registry**: 新 enricher module は
  [`clinosim/seeding.py`](clinosim/seeding.py) の
  `ENRICHER_SEED_OFFSETS` に 16-bit hex-ASCII offset (例
  `0x494D = "IM"`、`0x4445 = "DE"`、`0x4841 = "HA"`) を登録する
  こと。dict は import 時に assert が duplicate を catch する。
- **`normalize_probabilities(probs, fallback="raise")`** を全 15
  YAML-sourced callsite (7 モジュール: code_status / population /
  clinical_course / hai / family_history / observation /
  care_level) に適用済み。新規 `rng.choice(p=…)` は本 helper 経由。
- **Import 時 canonical-constants validation**: 外部 ID (SNOMED /
  LOINC / antibiotic key / probability weight) を参照する全 YAML
  は load 時に canonical set と cross-check し、未知 key / 総和 0
  で `ValueError` を raise すること。silent `dict.get(key)` fall
  through は PR-90 class silent-no-op risk。
- **AD-59 per-order lab RNG 分離**: 全 lab order (panel child +
  個別 scalar order 両方) は specimen-rejection / hemolysis /
  technician / noise を **per-order sub-rng** から draw
  (`simulator/seeding.py:panel_specimen_seed` /
  `individual_lab_seed`) — 患者 master RNG を使わない。
- **`scenario_flags_from_protocol` / `medication_flags_from_context`**
  helper — [`SCENARIO_FLAGS.ja.md`](SCENARIO_FLAGS.ja.md) 参照。
  新 disease YAML の `causes_X` flag / 薬剤駆動 lab 効果を追加する
  ときは helper を通す (J5 pattern 防止)。
- **`classify_lab_specs` helper** (PR1): lab order 生成
  (`place_admission_orders` / `place_daily_lab_orders`) は必ず
  `clinosim.modules.order.panel_grouping.classify_lab_specs` を
  通し、panel member が同一 `ordered_datetime` + `panel_key` を
  共有するようにする。呼び出し先 inline の if/elif は禁止。
- **`_o(order, name, default)` dual-access**: Order object を読む
  FHIR builder は必ず `_o()` helper
  (`clinosim.modules._shared.get_attr_or_key` を包む) を使い、
  dict (production JSON 逆シリアライズ CIF) と Order dataclass
  (test fixture) 両方をサポートする。
- **Imaging chain DRY** (AD-62): multi-view → multi-series 展開は
  `clinosim/modules/imaging/engine._expand_views_to_series`。新規
  imaging order 呼び出しは
  `clinosim.modules.order.engine.place_imaging_orders` 経由 MUST。
- **Narrative generation DRY** (AD-63): 臨床文書 template rendering
  は `clinosim/modules/document/narrative/` を通す。
- **`ClinicalDocument.sections` + `format_type` invariant** (AD-63,
  Task 8): 全 emission site で両 field 必須。sections 欠落は
  Composition builder が `"section": []` (FHIR R4 cardinality 違反)
  を silent emit する。format_type 欠落は builder dispatch が
  silent free_text default になり DocumentReference が emit される。
- **`document` は 6 番目の always-on Module** (AD-63): POST_ENCOUNTER
  order=95 で `ClinicalDocument` record + `ClinicalImpressionRecord`
  を生成。
- **`nursing_assignment` 命名規約** (AD-64): `clinosim/modules/nursing/`
  は異なる stage の 2 enricher を持つ — (1) `nursing_enricher`
  (POST_ENCOUNTER order=94) = 主担当看護師割当、(2) observation
  層 nursing flowsheet enricher (POST_RECORDS order=20) =
  NEWS2 / GCS / Braden / Morse。code コメント中は前者を
  `nursing_assignment`、後者を `nursing_flowsheets` と呼び混同を
  防ぐ。
- **`DocumentTypeSpec.encounter_types_supported` invariant** (AD-64):
  encounter 種別限定 spec は必ず明示 allowlist を宣言。空 tuple は
  「全 encounter type と一致」を意味する後方互換 default であり、
  「disable」ではない。inpatient 限定 spec は必ず
  `[inpatient, icu, rehab_inpatient]` を明示すること。
- **CareTeam 2-name scope invariant** (AD-64): `_fhir_care_team.py`
  は attending physician + primary nurse (最大 2 participant) のみ
  emit。attending は `attending_physician_id` が空でも常に emit
  (`"UNKNOWN"` placeholder)、nurse は `primary_nurse_id` が非空時
  のみ。`CareTeam.participant[]` は決して `[]` にしない。
- **Two-pass CIF 生成 invariant** (AD-65, 2026-07-02):
  `cif/structural/patients/<enc>.json` (構造化、Stage 1 で
  immutable) と `cif/narratives/<version>/documents/<enc>/<doc>.json`
  (narrative、Stage 2 で version 化可) を必ず file 層分離。inline
  混在禁止。`document_enricher` (POST_ENCOUNTER) は
  `ClinicalDocument` stub のみ生成し、narrative content
  (text / sections / facts_used) を populate しない。populate すると
  Stage 2 差替時 silent-no-op risk。narrative は post-simulation
  two-pass の `TemplateNarrativePass.run(cif_dir, version_id)` が
  populate。`NarrativePass` walk 順は (doc_type, language) group
  単位で Bedrock prompt cache (5 分 TTL) hit rate 最大化。
- **AD-66 rule 1**: Profile YAML 変更は必ず golden regenerate +
  同一 commit に含めること。`tests/fixtures/patient_profiles/<name>.yaml`
  を編集したら `clinosim regenerate-goldens --profile <name>` で
  `<name>.golden.json` を再生成、両者を同一 commit に含める。片方
  だけ commit すると次回 `pytest -m regression` が fail = ship-blocker。
- **AD-66 rule 2**: 意図的 template 変更後に予期しない goldens 差分 =
  regression 疑い。narrative template logic を意図的に変更した際、
  意図した profile 以外の golden にも diff が入ったら narrative
  pass の regression 疑い。commit 前に必ず調査。「全部再生成したから
  green」= silent regression 隠蔽の常套手段 (PR-90 教訓)。

### モジュール独立性

- `clinosim/modules/` 配下の各モジュールは `clinosim/types/`、
  `clinosim/codes/`、`clinosim/locale/`、および自 README の
  Dependencies 節に列挙した他モジュールにのみ依存可。
- **LLM 呼び出しは `llm_service` 経由のみ** (AD-11) — 他モジュール
  は Ollama / Anthropic API を直接呼ばない。
- **seed で決定論的** (AD-16) — 各モジュールは自 sub-seed から
  `numpy.random.Generator` を作る。`random.random()` や共有
  global state は絶対に使わない。

### EHR data enrichment — Base vs Module (AD-55) + 拡張性 (AD-56)

- **近ければ本体、細部は opt-in module**。Base (near-essential):
  常時 enabled で core 拡張 (`types` / `population` / `observation`
  / `simulator` / `output`)。Specialized / optional data → opt-in
  module (`identity` 同型)、`SimulatorConfig.modules` +
  `config.module_enabled(name)` で gate。**Always-on Module** =
  near-essential clinical cascade (HAI without antibiotic、device
  without HAI は臨床整合欠落): `enabled=lambda c: True` で登録、
  upstream `extensions[X]` slot が空のときのみ no-op。例:
  `device` (PR-A)、`hai` (PR-B)、`antibiotic` (PR3b-1)、
  `imaging` (Tier 1 #2、AD-62)、`allergy` (Tier 1 #3、AD-63)、
  `document` (Tier 1 #3、AD-63)、`triage` (Tier 1 #3 α-min-2、AD-64)、
  `nursing_assignment` (Tier 1 #3 α-min-2、AD-64)。
- **FHIR resource 追加**は `register_bundle_builder()` (AD-56) 経由
  — `_build_bundle()` を編集しない。Builder は raw resource
  `(ctx) -> list[resource]` を返す。
- **出力フォーマット追加**は `register_output_adapter()` (AD-58) 経由
  — CLI `--format` dispatch を編集しない。Adapter は CIF +
  `clinosim.codes` + `clinosim.locale` のみを読む。
- **post-population / post-records pass 追加**は `simulator/enrichers.py`
  (`register_builtin_enrichers`) で `Enricher` を register する
  — `run_beta` に inline しない。Enricher は自 sub-seed を導出、
  order は決定論のため固定。
- **モジュールは `CIFPatientRecord` を編集しない** — `CIFPatientRecord.extensions[<module>]`
  に書く。core 型に typed field を追加できるのは Base データのみ。
- これらの経路の refactor は golden / e2e 出力 + 決定論を保持する
  こと。

### Snapshot semantics (AD-32)

- `--end` flag = **snapshot date**。以降 life event 未生成。
- Snapshot 後に discharge 予定の入院患者は
  `Encounter.status = "in-progress"`、`discharge_datetime` なし。
- Partial data のみ (snapshot 日までの labs / vitals / orders /
  MAR)。
- 進行中 encounter の primary `Condition.clinicalStatus = "active"`。

## Testing

- `pytest -m unit` — module 別 unit test (<30s)
- `pytest -m integration` — module chain test (<5min)
- `pytest -m e2e` — golden file 比較 (<30min)
- `pytest -x` — 全 suite (234 test; unit+integration ~2 分、
  e2e golden ~8 分)
- commit 前に unit test を必ず走らせる。

## Development ワークフロー — Issue → PR → Merge

**master 直接 push 禁止**。fix / feature は必ず PR/Merge 経由。
完全な contributor ワークフロー (fork + branch、DCO signoff、
tests、CI gate、merge policy) は
[`CONTRIBUTING.ja.md`](CONTRIBUTING.ja.md) 参照。

AGENTS 固有の追加事項:

- **Commit trailer**: `Co-Authored-By: <agent-model>` +
  `Claude-Session: <url>` を DCO `Signed-off-by:` と併記し、
  agent authored commit を attributable に保つ。
- **Adversarial review** (大 chain で推奨): PR に `/code-review`
  を実行、merge 前に fix commit を加える。
- **scope-discipline**: 1 PR = 1 論点 (silent-drop fix / lint sweep
  等の横断作業は別 PR に分割)。複数 chain 並行時は chain 別 branch
  + 別 PR。

### ★ CI 待ちで手を止めない — 別 Issue を別ブランチで並行

CI は integration shard 込みで 10-15 分。**idle で待たない**。PR を
出したら `master` に戻り、次 Issue を別 branch で開始する。

```bash
# Issue A: 実装 → push → PR 作成 (CI が走り始める)
git switch -c fix/<A>-<slug> master
# ... 実装 ...
git commit --signoff -m "..." && git push -u origin fix/<A>-<slug>
gh pr create --base master ...

# CI を待たず Issue B へ
git switch master && git pull --ff-only origin master
git switch -c fix/<B>-<slug>
# ... 実装 ...

# A の CI が緑になったら merge、master 更新してから B を続行
gh pr merge <A の PR 番号> --squash --delete-branch
git switch master && git pull --ff-only origin master
```

**並行可能な Issue の条件**:

- **触るファイルが重ならないこと**。着手前に各 Issue が触る file /
  symbol を grep して重なりを確認。重なる場合は並行させず順番に。
- **依存関係のある Issue は並行させない**。例: `#468` → `#466`
  は同 `inpatient.py` の退院時刻を扱うため必ず順番に。

**master が進んだら作業中 branch を rebase**:

```bash
git switch fix/<B>-<slug>
git rebase master          # 衝突したら重なり判定誤りの signal
```

**待つべき場面**: merge 直前の最終確認、および **取り消せない操作
の直前** (`gh issue delete` / force push)。並行作業で state が動いて
いる可能性があるため、**承認時 HEAD と merge 時 HEAD が同一である
こと**を確認する。

**hotfix 例外**: 本番 blocker (CI 全落ち / silent-drop 検出) は
master 直接 push OK、ただし同一 session 内で post-hoc Issue + 説明
comment を残すこと。

## モジュール修正時のチェックリスト

1. 該当 module の `README.md` (JA なら `README.ja.md`) を先に読む
2. 変更を加える
3. `MODULES.md` の dependency 表で下流影響を確認
4. API / データ構造が変わったら module の README を更新
5. 共有データ型が変わったら `clinosim/types/*.py` を更新
6. 新 code を追加するときは `clinosim/codes/data/<system>.yaml` に
   最低 `en` field 付きで追加
7. Test 実行: `pytest -x -q`

## FHIR 出力ルール (全 resource builder 必須)

- **多言語 coding**: Condition + Procedure は dual `coding[]` — primary
  language + interop language を emit。`display == code` は絶対に
  emit しない。
- **`code.text`**: 臨床略称
  (`_CONDITION_SHORT_NAME` の "COPD" 等、"Other chronic obstructive
  pulmonary disease" ではない) を使う。Procedure は `code_lookup()`
  で解決。
- **薬剤 text**: `_strip_protocol_prefix()` で protocol prefix
  (DVT_prophylaxis:、antipyretic: 等) を剥がす。
  `medicationCodeableConcept.text` = 薬剤名のみ。
- **referenceRange + interpretation**: 数値 observation では両者
  必須かつ consistent (FHIR R5 Note 5)。Lab interpretation は
  value vs referenceRange から再計算。
- **JP localization**: `country="JP"` のとき全 `display` / `text`
  / `name` field は日本語。enum 値は `_localize_display()`、
  薬剤 / procedure 名は `code_lookup()` または
  `_localize_drug_name()`。
- **US 出力**: 100 % 英語。全 field に日本語文字が入らないこと。
- **JP Core / JP-CLINS profile URI・slice system URI は必ず spec
  の `fixedUri` を直接引用**。JP Core StructureDefinition JSON
  (`iris4h-ai/jp_core/package/StructureDefinition-*.json` または
  jpfhir.jp 該当 spec) の `Element.system.fixedUri` /
  `Element.fixedUri` を grep で直接取得して使う。推測 URI や
  plausible naming に基づく URI 命名は **禁止** — spec と不一致
  だと HAPI validator が silent-no-op (URI があるので通ってしまうが
  profile slice discriminator が match せず validation error は
  消えない)。新規 JP Core slice 対応 PR は
  `tests/unit/output/test_fhir_jp_core_p14_slices.py` のように
  **URI を module 定数として pin する test を必ず追加** (regression
  防衛)。同ルールが JP-eCheckup / JP-CLINS / SS-MIX2 の profile
  URI にも適用。

## Enrichment architecture (narrative prompt)

- **Enrichment は言語中立** (AD-44): extraction 関数は target
  language に関わらず英語構造化データを産出、LLM が prompt 言語
  指示に基づいて翻訳する。
- **enrichment 内の locale 固有操作は 2 つのみ**:
  1. `code_lookup(system, code, language)` — target 言語の公式
     診断略称を返す。
  2. CRP unit 変換 (mg/L → mg/dL、JP) — 数学的変換であり翻訳ではない
     (AD-42)。
- **薬剤名 / procedure 名 / 合併症 label / event description は
  事前翻訳しない**。LLM が処理。
- **FHIR adapter localization は別系統** — FHIR 出力経路 (LLM を
  通らない) は自前辞書 (`drug_names_ja.yaml`, `_PROCEDURE_NAME_JA`,
  `_CONDITION_SHORT_NAME` 等) を使う。

## AD-30 (CIF は言語中立) 強制

- CIF は **コードのみ**保存、表示テキストは保存しない。表示は
  出力時 `clinosim.codes.lookup()` で解決。
- `ProcedureRecord` は `procedure_code`, `procedure_code_jp`,
  `procedure_code_us` を持つ — `procedure_name` は持たない。
- `Order.display_name` と `MAR.drug_name` の薬剤名は英語
  (pragmatic exception — RxNorm 統合が未完のため)。
- 診断表示は FHIR export / enrichment 時に `code_lookup()` で取得。

## 現在の実装フェーズ

**v0.2** — population 駆動 simulation + 全 FHIR R4 Bulk Data
Export、multi-country (US/JP)、32 疾患 + 46 ED/外来病態、snapshot
date サポート、opt-in JP 保険加入 (FHIR Coverage、AD-54)、および
完全な **AD-55 Base data-enrichment set**: microbiology、心マーカー、
nursing flowsheet、immunization、family history、code status、
拡張 SDOH (smoking / alcohol / JP 要介護度)。FHIR adapter は
per-theme `_fhir_*` builder module に split (FA-1)。

**Silent-no-op 防御 triplet** が全 codebase に配線済 (PR #102 /
#103 2026-06-27): (1) canonical constants (例 `HAI_TYPES`) を
module level に定義、(2) `_validate_*(data) -> None` を 5 主要
YAML loader (`_validate_microbiology` PR-A 7 cross-refs +
`_validate_hai_organisms` + `_validate_demographics` +
`_validate_names` + `_validate_addresses`) に配線 (import 時
fail-loud)、(3) `normalize_probabilities(..., fallback="raise")` を
全 **15 YAML-sourced callsite** (7 モジュール) に適用。

**Foundation polish 完了** — PR-B1 chain: hand-rolled
`global X; if X is None: ...` sentinel pattern を全 6 loader で
撤廃し `@lru_cache(maxsize=1)` 統一済。同時に silent skip
(`try/except pass`) も削除。byte-diff invariant 保持 (37/37 NDJSON
sha256 IDENTICAL)。

**PR3b-3 HAI culture S/I/R-driven narrow / de-escalation chain 完了** —
4-stage adversarial chain converged。same antibiotic enricher Pass 2
が `extensions["antibiotic"]` の empirical regimen を walk、
`MicrobiologyResult.hai_event_id` backref で culture を lookup、
per-(hai_type, organism) `narrow_ladder.yaml` (4-way validation) で
narrow target を選択、3 outcome (SWITCH = 新
`intent="narrowed"` regimen / ELIMINATION = 非 target empirical
discontinue / NO_CHANGE) を dispatch。FHIR
`MedicationRequest.status="stopped"` を new `OrderStatus.STOPPED` +
`_map_order_status_to_fhir` で emit。

**Tier 1 #2 Imaging chain α-min 完了** (2026-06-30, AD-62) —
`modules/imaging/` always-on POST_ENCOUNTER Module (order=90) が
`ImagingStudyRecord` を `extensions["imaging"]` に emit。imaging
encounter あたり 4 FHIR resource (`ImagingStudy` (urn:dicom:uid、
DCM modality、multi-series)、`Endpoint` (WADO-RS placeholder)、
radiology `DiagnosticReport` (findings + impression + conclusion)、
`ServiceRequest` (imaging category))。15-check `lift_firing_proof`
(AD-60)。

**FHIR completeness chain 完了** (2026-07-06, AD-67/68/69) — 「不完全な
FHIR element state」を除去する 9-chain effort。fix-point registry
(`docs/design-notes/2026-07-06-fix-point-registry.md`) 3 クラス
(**C1 silent-drop** / **C2 degenerate** / **C3 missing-structure**)
定義下で管理。ランディング:
(1) **FP-SEV-MODEL / AD-67** — 重症度の single source of truth:
disease-YAML `severity.distribution` × `modifiers` を canonical 化。
(2) **FP-YAML-2b / AD-68** — 未接続だった `archetype_modifiers` (23
YAML) を `select_archetype` に配線。
(3) **FP-YAML-3 / AD-69** — `DiseaseProtocol` に `extra="forbid"`。
その他 FP-YAML-1 / FP-I10 / FP-ARCH-1 / FP-COMPLETENESS-GATE。
残 backlog は fix-point registry 参照。

詳細な roadmap は [`docs/roadmap.md`](docs/roadmap.md) → GitHub
Issues board。

## 主要ディレクトリ

```
clinosim/
  codes/           <- ★ 国際コード体系 (locale 非依存、EN-first)
    data/          <- icd-10-cm.yaml, loinc.yaml, rxnorm.yaml, ...
    loader.py      <- lookup() API
  locale/          <- 国 / 文化固有データ (names, addresses, reference range)
    jp/, us/, shared/
  config/          <- 病院 config YAML (50-bed, 10-bed 等) + LLM config
  types/           <- 全データ型定義 (Pydantic / dataclass)
  modules/         <- 機能モジュール (33 パッケージ、各 README あり)
    identity/      <- ★ 住民識別子 + 保険番号 (JP、opt-in; AD-54)
    immunization/  <- 成人ワクチン接種歴 (AD-55 Base; AD-56 enricher)
    family_history/<- 第 1 度近親 疾患歴 (AD-55 Base)
    code_status/   <- 蘇生方針 (AD-55 Base)
    care_level/    <- JP 要介護度 (AD-55 Base、JP 限定)
    device/        <- ★ ICU デバイス配置 (AD-55 Module, PR-A)
    hai/           <- ★ CDC NHSN HAI サンプリング (AD-55 Module, PR-B)
    output/        <- CIF → format adapter; fhir_r4/ + per-domain builder (FA-1)
  simulator/       <- top-level orchestration (run_beta, run_forced, CLI)
    enrichers.py   <- ★ Base / opt-in module pass の enricher registry (AD-56)
tests/             <- test code (unit / integration / e2e)
```

## 病院 config

各病院は `clinosim/config/hospital_*.yaml` の YAML で定義:

- `hospital_operations.yaml` — 50 床コミュニティ病院 (default)
- `hospital_small.yaml` — 10 床 clinic
- `hospital_large.yaml` — 200 床 regional hospital (full service)
- Custom は `--hospital-config PATH` で対応

必須 field: `recommended_population`, `available_departments`,
`department_rollup`, `wards`, `ward_capacity`, `resource_capacity`,
`staffing`。

`available_departments` list が生成される医師を決定する。
`department_rollup` map は granular specialty (例 pulmonology) を
available department (例 internal_medicine) に fold — 全 sub-specialty
を持たない病院向け。

## LLM setup

Default: local Ollama (API key / cloud account 不要)。

```bash
# Ollama install
brew install ollama    # macOS
# または: curl -fsSL https://ollama.com/install.sh | sh   # Linux

# Default model pull
ollama pull qwen:7b

# (Optional) narrative 用高品質 model (VRAM ~40GB 必要)
ollama pull llama3.1:70b
```

Config file:
- `clinosim/config/llm_service.yaml` — default (local Ollama)
- `clinosim/config/llm_service.bedrock.yaml` — AWS Bedrock
  (Claude Sonnet 4, IAM role 付き EC2)
- `clinosim/config/llm_service.cloud.yaml` — cloud (Anthropic API、
  `ANTHROPIC_API_KEY` 必要)

JUDGMENT と NARRATIVE で異なる provider を使える (AD-24)。詳細は
`modules/llm_service/README.md` (英語) / `README.ja.md`。

LLM は **構造データ生成には不要**。LLM 無しなら template-based
narrative を使う。

## Disease protocol YAML file

`clinosim/modules/disease/reference_data/` に配置。load 時 Pydantic
model (`DiseaseProtocol`) で validate。

新疾患追加:

1. `clinosim/modules/disease/reference_data/<disease_id>.yaml` を作成。
2. 既存疾患を template として参照。
3. 必須: `disease_id`, `chief_complaint` (多言語 dict), `department`,
   `icd_codes`, `target_los`, `course_archetypes`,
   `outcome_benchmarks`。
4. `clinosim/locale/<country>/demographics.yaml` の incidence list
   に追加。
5. **全 `icd_codes` 値 (primary + variants) を code data に登録**
   — 下記「診断コード coverage」参照。skip すると FHIR Condition
   表示が authoritative entry ではなく prefix-match の approximate
   text にフォールバックする。
6. Test: `clinosim test-disease <disease_id>` +
   `pytest tests/unit/test_diagnosis_code_coverage.py`。

engine コード変更不要。

### 診断コード coverage (疾患 / encounter 追加 / 編集時 REQUIRED)

`codes/data/*.yaml` は意図的な **subset** (clinosim が emit する
code のみ)。不変量「emit 可能な全診断 code が authoritative entry
に解決する」は `tests/unit/test_diagnosis_code_coverage.py` で強制。
診断 code は 3 source で FHIR Condition に到達し全て test 対象:
(1) disease `icd_codes` (primary + variants)、(2) encounter
`icd10_code`、(3) `modules/diagnosis/reference_data/builtin_differentials.yaml`
の組込差別 / progression 表 (`differentials[*].icd` +
`diagnosis_progression` code) (working / differential 診断)。
各新規 / 変更 code `C` は authoritative source (NLM ICD-10-CM API
`clinicaltables.nlm.nih.gov/api/icd10cm`、WHO ICD-10 browser
`icd.who.int/browse10`) で verify — **絶対に捏造しない** — 後:

- **US billable**: `C` が valid billable ICD-10-CM leaf なら
  `codes/data/icd-10-cm.yaml` に追加 (`en` + `ja`)。`C` が非 billable
  category / header または WHO-only (例 `I21.2`, `I50.0`, `N30.9`)
  なら `code_mapping_diagnosis/us.yaml` に `C → <billable leaf>`
  entry を追加し leaf を `icd-10-cm.yaml` に登録。
- **JP (WHO)**: `code_mapping_diagnosis/jp.yaml.get(C, C)` は
  `codes/data/icd-10.yaml` に存在する **true WHO ICD-10 code
  (3-4 文字)** でなければならない。`C` が ICD-10-CM 粒度
  (5-7 文字、7 文字目拡張、`X` placeholder — 例 `A41.01`,
  `S06.0X0A`) なら jp map に WHO 親への fold entry
  (`A41.01 → A41.0`) を追加し、WHO code を `icd-10.yaml` に登録。
  JP は CM 粒度 code を emit せず `icd-10-cm.yaml` fallback もしない
  (`test_jp_never_emits_cm_granular_code` +
  `test_icd10_who_file_has_no_cm_granular_codes` で強制)。

`pytest tests/unit/test_diagnosis_code_coverage.py` — green で
coverage 完全。

## Encounter (ED/outpatient) protocol YAML file

`clinosim/modules/encounter/reference_data/` に配置。ED 訪問と外来
encounter をカバーする 46 病態。

新 encounter 種別追加:

1. `<condition_id>.yaml` を作成 (`condition_id`, `icd10_code`,
   `icd10_display`, `chief_complaint` (多言語 dict), `encounter_type`,
   `department`, `severity_distribution`, `workup`, `treatment`,
   `discharge_instructions`)。
2. 上記「診断コード coverage」に従い **`icd10_code` を code data に
   登録** (US billable は `icd-10-cm.yaml` / map、JP は
   `icd-10.yaml`)。
3. Test: `clinosim test-encounter <condition_id>` +
   `pytest tests/unit/test_diagnosis_code_coverage.py`。

## 新 code 追加

ICD / LOINC / RxNorm 等の新 code 追加手順:

1. `clinosim/codes/data/<system>.yaml` を編集。
2. 必須: `en` field (公式英語 description)。
3. 任意: `ja` field (翻訳)。
4. Source は authoritative (CMS, NLM, AMA, WHO, JCCLS, MHLW) であること。

```yaml
codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"   # ← 必須
    ja: "急性腎盂腎炎"                         # ← 任意
```

## 新言語追加

`clinosim/codes/data/*.yaml` の entry に新言語 key を追加:

```yaml
N10:
  en: "Acute tubulo-interstitial nephritis"
  ja: "急性腎盂腎炎"
  de: "Akute tubulointerstitielle Nephritis"   # ← new language
```

要求言語が欠落していれば loader は英語に fallback する。

## Common pitfall

- ❌ **CIF に表示テキストを保存しない**。CIF はコード + system key
  のみ。表示は出力時解決。
- ❌ **FHIR system URI を hardcode しない**。
  `clinosim.codes.get_system_uri(system_key)` を使う。
- ❌ **`en` entry 無しで code を追加しない**。英語必須。
- ❌ **`random.random()` を使わない**。常に parameter 経由で
  渡された seeded `numpy.random.Generator` を使う。
- ❌ **`llm_service` の外から LLM API を呼ばない**。
- ❌ **モジュールコード内でデータ型を定義しない**。全 shared type は
  `clinosim/types/`。
- ❌ **locale 固有データと code system データを重複させない**。
  Code system は `codes/`、文化データは `locale/`。

英語版 (canonical): [`AGENTS.md`](AGENTS.md)。
