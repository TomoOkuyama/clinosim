# `clinosim.modules` — モジュール索引

## 目的

`clinosim/modules/` は clinosim における全生成モジュールの集約
ディレクトリ。各サブディレクトリが合成 pipeline の一断面
(患者生成、臨床状態、ケアイベント、出力アダプタ、…) を所有し、
それぞれ独自の `README.md` + `README.ja.md` / (該当時) 参照 YAML
data / (該当時) audit フックを備える。

本ページは **ナビゲーション索引** — 各モジュール 1 行、機能領域で
グルーピングし、各子 README にリンクする。詳細な設計議論は個別
module のドキュメントに、より広い architecture view は
[`AGENTS.md`](../../AGENTS.md) と [`DESIGN.md`](../../DESIGN.md) に。

## 全モジュール共通の設計慣習

全 module README は同じ **canonical 11-section 構造** に従う
(s88k full-revision campaign で確立):

1. Title — モジュールパス + 1 行説明
2. Purpose / 概要
3. Scope (In / Out)
4. Public API
5. Determinism / 決定論 (乱数を引かない module は
   `Not applicable — <理由>` として節を保持)
6. Dependencies / 依存
7. Constants and configuration / 定数と設定
8. Directory contents / ディレクトリ構造
9. Enricher wiring / Enricher 配線 (`register_builtin_enrichers` に
   登録しない module は `Not applicable — <理由>` として節を保持)
10. Output surfaces (consumers) / Output surface
11. Testing / テスト
12. Ownership

Optional 挿入: `Snapshot (AD-32)` (immunization),
`Extending` / 拡張 (`sdoh` 等の data-only variant)。

Cross-module invariant:

- **Boilerplate**: 新モジュールは
  [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md)
  から複製。module 追加ワークフローは
  [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)。
- **決定論的**: 乱数を引く module は sub-seeded RNG stream を使用し、
  `(country, population, seed, dates)` タプル固定でコホート出力が
  byte 再現する (AD-16)。sub-seed offset は
  [`clinosim/seeding.py`](../seeding.py) の `ENRICHER_SEED_OFFSETS`。
- **データ駆動**: 臨床パラメータは engine の隣の
  `reference_data/*.yaml` (locale scope data は
  [`clinosim/locale/<country>/`](../locale/)) に置き、Python literal
  に書かない。最後の inline threshold 掃除 campaign は
  [Issue #637](https://github.com/TomoOkuyama/clinosim/issues/637) 参照。
- **出力は locale 対応、コアは locale 非依存**: engine は中立 CIF を
  生成し、[`output/`](output/README.ja.md) アダプタが国別に描画する。
  code system は [`clinosim.codes`](../codes/data/) 側。

## モジュール索引 (33 module)

### 患者生成

| Module | 用途 |
| --- | --- |
| [`population/`](population/README.ja.md) | 集患エリアサンプリング — demographics、月次 acute event、年次 healthcare calendar。 |
| [`patient/`](patient/README.ja.md) | Layer-1 → Layer-2 activation — 生理予備能、baseline vitals、慢性疾患、常用薬を付与。 |
| [`identity/`](identity/README.ja.md) | 国 pluggable な患者 identifier + 保険 record (AD-54、`providers/*.py`)。 |
| [`sdoh/`](sdoh/README.ja.md) | 社会歴参照データ (smoking / alcohol の SNOMED + LOINC — data-only variant)。 |
| [`family_history/`](family_history/README.ja.md) | 第 1 度近親歴合成。 |
| [`pediatric/`](pediatric/README.ja.md) | 小児 encounter 発生 (well-child / 予防接種 / acute / 行動 — Issue #760)。 |

### 臨床状態

| Module | 用途 |
| --- | --- |
| [`physiology/`](physiology/README.ja.md) | 生理 state engine — 全 lab / vital / 薬物応答の導出元。 |
| [`clinical_course/`](clinical_course/README.ja.md) | Trajectory archetype + 日次 `StateChangeDirective` engine。 |
| [`disease/`](disease/README.ja.md) | 疾患 protocol registry (32 YAML) + 重症度 + acuity + 薬剤 vocabulary。 |

### ケアイベント

| Module | 用途 |
| --- | --- |
| [`encounter/`](encounter/README.ja.md) | encounter 条件 registry (46 YAML) + 入院日次 cycle timeline。 |
| [`triage/`](triage/README.ja.md) | ED triage サンプリング (JTAS / ESI、POST_ENCOUNTER order=93)。 |
| [`diagnosis/`](diagnosis/README.ja.md) | Bayesian 鑑別診断 engine + Issue #551 非特異コード定数。 |
| [`order/`](order/README.ja.md) | 発注 + panel grouping + treatment classifier + AD-60 audit。 |
| [`procedure/`](procedure/README.ja.md) | 手術 + bedside 処置 + rehab セッション生成。 |
| [`imaging/`](imaging/README.ja.md) | Imaging study + series + radiology report (Tier 1 #2 chain、AD-60 audit)。 |
| [`device/`](device/README.ja.md) | ICU デバイス配置 (CVC / catheter / ventilator、POST_ENCOUNTER order=70)。 |

### 観測 & 治療

| Module | 用途 |
| --- | --- |
| [`observation/`](observation/README.ja.md) | Lab 値 engine + 看護 flowsheet (NEWS2 / GCS / Braden / Morse) + microbiology。 |
| [`nursing/`](nursing/README.ja.md) | 主担当看護師割当 (POST_ENCOUNTER order=94) — `observation` の nursing_flowsheets とは別。 |
| [`antibiotic/`](antibiotic/README.ja.md) | HAI empirical + narrow ladder regimen + AD-60 audit。 |
| [`allergy/`](allergy/README.ja.md) | 患者アレルギーサンプリング (POST_POPULATION order=10)。 |
| [`immunization/`](immunization/README.ja.md) | CVX スケジュール由来の成人ワクチン接種歴。 |
| [`health_checkup/`](health_checkup/README.ja.md) | JP 事業者健診 (opt-in、POST_RECORDS order=70)。 |
| [`monitoring/`](monitoring/README.ja.md) | 慢性薬 → monitoring lab 注入 (Issue #757)。 |

### ケア運用

| Module | 用途 |
| --- | --- |
| [`facility/`](facility/README.ja.md) | 病院運用 state + queueing 遅延 model。 |
| [`healthcare_system/`](healthcare_system/README.ja.md) | 国 config loader (leaf)。 |
| [`staff/`](staff/README.ja.md) | Staff roster + event 別 `assign_staff` dispatch。 |
| [`care_level/`](care_level/README.ja.md) | JP 要介護度付与 (POST_RECORDS order=60、JP 限定)。 |
| [`code_status/`](code_status/README.ja.md) | 蘇生方針 tier 付与 (POST_RECORDS order=50)。 |
| [`hai/`](hai/README.ja.md) | HAI 発症サンプリング (CLABSI / CAUTI / VAP) + Phase 3a lift + AD-60 audit。 |

### 文書

| Module | 用途 |
| --- | --- |
| [`document/`](document/README.ja.md) | 文書 stub emission (POST_ENCOUNTER order=95) + AD-60 audit + canonical FHIR ID prefix。 |
| [`llm_service/`](llm_service/README.ja.md) | 単一 LLM gateway (AD-11) — Bedrock / Ollama / vLLM / Anthropic / mock を `providers/` で。 |

### 出力 & 検証

| Module | 用途 |
| --- | --- |
| [`output/`](output/README.ja.md) | 出力アダプタ entry (FHIR R4 NDJSON、CIF-JSON、CSV) + FHIR R4 subpackage。 |
| [`validator/`](validator/README.ja.md) | Realism benchmark + consistency check (`clinosim validate` CLI)。 |

## Cross-reference

- **Framework docs**:
  - [`clinosim.audit`](../audit/) — 内部 per-module PR 検証
    (AD-60 plug-in は `hai`, `antibiotic`, `order`, `imaging`,
    `document`, `triage` が登録)。
  - [`clinosim.codes`](../codes/data/) — 臨床コード体系
    (LOINC / ICD / RxNorm / SNOMED / …)。
  - [`clinosim.seeding`](../seeding.py) — canonical
    `ENRICHER_SEED_OFFSETS` 表。
- **Contribution guide**:
  - [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)
    — 新 module 追加手順。
  - [`docs/add-your-country.md`](../../docs/add-your-country.md) —
    新国追加手順 (locale + identity provider + healthcare-system
    config)。
- **Architecture**:
  - [`AGENTS.md`](../../AGENTS.md) — AI-agent 向け指示 + データフロー
    + ADR ポインタ。
  - [`DESIGN.md`](../../DESIGN.md) — ADR 表。
  - [`MODULES.md`](../../MODULES.md) — module 概観 cheat sheet。

英語版: [`README.md`](README.md)。
