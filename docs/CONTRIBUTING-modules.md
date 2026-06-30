# コントリビューターガイド: モジュール/プラグインの追加

このドキュメントは、新しいコントリビューターが clinosim に **モジュール/プラグインを追加し、データを生成し、どのデータ/コードを使うかを正しく選択する** ための実践 playbook です。アーキテクチャ原則 (ADR) は `DESIGN.md`、規約の総覧は `CLAUDE.md` を参照してください。本書はそれらと重複せず、**HOW-TO** に集中します。

> **本書は CIF 生成 layer(Layers 1-3 = 参照 YAML、loader、CIF generation module)が中心** です。**FHIR builder layer(Layer 4 = `_fhir_*.py`)を追加・拡張する場合は** [`docs/design-guides/fhir-data-generation-logic.md`](design-guides/fhir-data-generation-logic.md) を参照してください(BundleContext / code_lookup / 多言語 display / identifier system 規約 / register_bundle_builder)。

> **新規モジュール作成時**: [`.github/TEMPLATE_MODULE_README.md`](../.github/TEMPLATE_MODULE_README.md) をコピーして開始。全 22 module の俯瞰は [`MODULES.md`](../MODULES.md) を参照。PR 検証手段の選び方は本書の「PR 検証ガイド: byte-diff vs 3-axis DQR」セクション参照。

実コードの正本パス:
- Enricher registry: `clinosim/simulator/enrichers.py`
- Output adapter registry: `clinosim/modules/output/adapter.py`
- FHIR bundle builder registry: `clinosim/modules/output/fhir_r4_adapter.py`
- 共有型: `clinosim/types/`
- コードシステム: `clinosim/codes/`
- locale データ: `clinosim/locale/`

---

## 判断: Base か Module か

新しいデータ/機能を追加するとき、最初に **Base (always-on, core を拡張)** か **opt-in Module (`SimulatorConfig.modules` + `config.module_enabled()` でゲート)** か **always-on Module = near-essential clinical cascade**(AD-55 PR3b-1 supplement、2026-06-25 追加: 上流 `extensions[X]` の存在を前提に clinically coherent な拡張を不可避的に出すモジュール。例 `device`/`hai`/`antibiotic`/`imaging`)を決めます (AD-55)。

**always-on Module 先例 (2026-06-30 時点):**
- `device` (PR-A): ICU デバイス配置 (POST_ENCOUNTER order=70)
- `hai` (PR-B): CDC NHSN HAI サンプリング (POST_ENCOUNTER order=80)。`extensions["device"]` の存在を前提。
- `antibiotic` (PR3b-1): HAI 経験的抗菌薬 (POST_ENCOUNTER order=85)。`extensions["hai"]` の存在を前提。
- `imaging` (Tier 1 #2, AD-62): 画像診断メタデータチェーン (POST_ENCOUNTER order=90)。disease YAML の `imaging_orders` が存在する encounter でのみ `extensions["imaging"]` を生成し、ImagingStudy + Endpoint + 放射線科 DR + imaging SR を emit する。upstream extensions に依存しない (device/hai とは独立)。

### 決定チェックリスト

以下にすべて Yes なら **Base**。1 つでも No 寄りなら **opt-in Module**。

1. ほぼすべての EHR で必須のデータか? (例: 入院基本情報、vital、検査結果)
2. 国/テーマに依存せず、ほぼ全 encounter に存在するか?
3. CIF の core 型 (`CIFPatientRecord` / `CIFDataset`) に typed field として常時持たせるべきか?

逆に、以下に当てはまるなら **opt-in Module**:

- 特定テーマ 1 つに閉じている (`identity` = 在留番号/保険番号, `immunization` = 予防接種)
- 特定国でのみ意味がある (JP 保険番号など) / ユーザーが OFF にしたい可能性がある
- core 型を汚さず `CIFPatientRecord.extensions[<module>]` に書ける

### ゲートの実装 (opt-in の場合)

opt-in module は `Enricher.enabled` で gate します。`config.module_enabled(name, default=...)` を使うのが正しい作法です (AD-56)。

```python
# clinosim/simulator/enrichers.py の register_builtin_enrichers() 内
register_enricher(Enricher(
    name="immunization",
    stage=POST_RECORDS,
    run=run_immunization_enricher,
    order=200,
    enabled=lambda c: c.module_enabled("immunization", default=True),
))
```

> **注意 (EXT-5):** 現状 `module_enabled()` は production で未配線で、`modules` dict は dead key になっています。新規 module は上記のように `module_enabled` 経由で gate し、advertised な AD-56 ゲートを実際に有効化してください。`default=True` を保てば既存 golden は不変です。

### locale 依存の signature 規約

locale 別データ(国別 prevalence、reference range、code mapping 等)をロードする関数は、**`country: str` パラメータを必ず受け取り**、対象外の国では `{}` / `""` 等の no-op 値を早期 return します:

```python
from functools import lru_cache

@lru_cache(maxsize=2)
def load_rates(country: str = "JP") -> dict:
    """Load rates for ``country``. Returns {} for unsupported countries."""
    if str(country).upper() != "JP":
        return {}
    with open(_LOCALE / "jp" / "...") as f:
        return yaml.safe_load(f)
```

理由 — モジュールが現状 1 国対応(例: care_level は JP 専用)であっても、signature を統一しておけば将来 US 対応を追加する際に caller の API を変えずに済みます。`_LOCALE / "jp" / ...` のように country 引数なしでハードコードするのは consistency bug です。

`@lru_cache(maxsize=...)` を併用して反復ロードを避ける(他モジュール — immunization / family_history / code_status — もこのパターン)。

---

## モジュールの構造

各モジュールは `clinosim/modules/<name>/` 配下の 1 パッケージで、**他モジュールへの依存は README の Dependencies に明記したものだけ** に限定します。

### 正準レイアウト (canonical layout)

```
clinosim/modules/<name>/
  __init__.py            <- public API を __all__ で re-export (空にしない)
  engine.py              <- pure-function 群。cross-module import を持たない
  protocol.py            <- (任意) YAML を Pydantic で validate して load
  reference_data/*.yaml  <- データ駆動の定義 (Pydantic で検証)
  README.md              <- 日本語 + 英語技術用語。## Dependencies を持つ
```

### 共有ヘルパは `clinosim/modules/_shared.py` に集約する

複数 enricher で同じ helper を持つ場合(例: `get_attr_or_key(obj, name, default)` で dict / dataclass 両対応の属性アクセス)、各モジュールに local 定義を書かず **`clinosim/modules/_shared.py`** に置きます。新規モジュールも以下のように import します:

```python
from clinosim.modules._shared import get_attr_or_key as _get
```

`as _get` alias で短い local 名を維持し、call site の可読性も保ちます。新しい cross-module helper を追加する場合は **2 モジュール以上で実需が生じたタイミング**で `_shared.py` に昇格させます(YAGNI — 1 モジュールしか使わないなら local 定義のまま)。

現在 `_shared.py` に集約されている helper(PR-A 2026-06-26 で `normalize_probabilities` 追加):

- `get_attr_or_key(obj, name, default)` — dict/dataclass 両対応の属性アクセス
- `normalize_probabilities(probs, fallback="uniform") -> np.ndarray` — 確率配列を 1.0 へ正規化(下記「確率サンプリング規約」参照)

### パス定数の正規形(PR-A 2026-06-26 で確立)

モジュールが reference_data や locale データを読み込むときの**正規パターン**:

```python
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"        # reference_data/ を持つなら
_LOCALE = _HERE.parents[1] / "locale"      # clinosim/locale/ を参照するなら
```

call site では `_REF_DIR / "X.yaml"` / `_LOCALE / country / "X.yaml"` で path を組み立て、`Path(__file__).parent / ...` の inline を避けます。理由:

- `_HERE` を起点にすると `parents[N]` の `N` が module の深さに依存しないので **fragile な `.parents[2]` 問題**(immunization の旧パターン)が避けられます。
- 命名統一(`_REFERENCE_DATA_DIR` / `_DATA` / `_HAI_REF_DIR` のような揺れを廃止)で grep / refactor が容易。
- データ専用 module variant も同じ`_HERE` + `_REF_DIR` を採用。

### `@lru_cache` の `maxsize` 規約(PR-A 2026-06-26 で確立)

| loader の signature | `maxsize` |
|---|---|
| `load_X() -> dict`(no parameter) | `1` |
| `load_X(country: str) -> dict` | `2`(US + JP) |
| `load_X(country: str, language: str)` | `4`(将来の多言語拡張用、現在は未使用) |

`maxsize` は eviction policy にしか効きませんが、**意図を読みやすくする load-bearing な signal** です。`maxsize=4` を country-only loader に付けるとレビュアーが「将来 4 国対応?」と誤解します。

**PR-B1 (2026-06-27) + adversarial fix で完成**: 残存していた hand-rolled cache pattern(`global X; if X is None: ... else return X` を **6 loader**で使用)を撤廃し、全 module の loader が `@lru_cache` 標準。touch 対象は `clinosim/modules/encounter/protocol.py:load_all_encounter_conditions` / `clinosim/simulator/helpers.py:_load_all_disease_protocols` / `clinosim/modules/output/_fhir_diagnostic_report.py:load_panel_groups` / `clinosim/modules/output/_fhir_localization.py` の `_load_med_terms_ja` + `_load_drug_names_ja` + `_load_department_display`。新規 module で global mutable `_cache` 変数を導入することは禁止(`test_*` で `load_X.cache_clear()` を使う標準テスト pattern と相反するため)。同 PR で `clinosim/simulator/helpers.py:_load_all_disease_protocols` の `try/except pass` silent skip も削除済(silent-no-op 防御強化、PR #102 silent-no-op 防御 3 層との整合)。**brainstorming Step 1 での sweep grep は `grep -i "cache\|state\|memo"` 等の意味フィルタを使わず、`grep -E "^_[A-Za-z_]+: *.+ *= *None"` の generic sentinel pattern を必ず使うこと**(PR-B1 adversarial review 教訓: 意味フィルタが `_drug_names_ja` 等の cache を false-negative)。

### 確率サンプリング規約(PR-A 2026-06-26 で確立)

`rng.choice(items, p=weights)` を呼ぶ前に **必ず `normalize_probabilities()` でラップ**します:

```python
from clinosim.modules._shared import normalize_probabilities

probs = normalize_probabilities(weights)   # idempotent on already-normalized arrays
idx = int(rng.choice(len(items), p=probs))
```

理由:`numpy.random.Generator.choice` は `p=` を**自動正規化しません**(sum ≠ 1.0 で `ValueError`)。YAML を手作業で正規化していると、編集ミスで sum が崩れた瞬間に silent regression / runtime crash になります。`normalize_probabilities` は

- すでに正規化済みなら `np.asarray(probs, dtype=float)` と byte-identical(byte-diff invariant 保持)
- 非正規化なら正規化
- sum=0 なら uniform fallback(`fallback="raise"` で `ValueError` も可)
- 負の重みは `ValueError`

の挙動。inline literal(`p=[0.6, 0.4]` 等)は正規化済が自明なので migration 不要です。

### Import 時 cross-validation(canonical-constants gate)

YAML data に外部 ID(SNOMED / LOINC / antibiotic key 等)を埋めるモジュールは、**load 時に canonical 集合へ cross-check** し、未知のキーは `ValueError` で loud-fail します(silent-no-op の構造的防御 — PR-90 教訓)。先例:

- `clinosim/modules/hai/__init__.py:load_hai_antibiogram` — `HAI_TYPES` × `hai_organisms.yaml` SNOMED × `ANTIBIOTIC_LOINC_LOOKUP` の 3-way 検証
- `clinosim/modules/observation/microbiology.py:_validate_microbiology` — organism antibiogram key を `antibiotics` set と照合(PR-A 2026-06-26 で silent skip から ValueError へ移行、Fix #100/#101 で 7 cross-refs に拡張)
- `clinosim/modules/antibiotic/audit.py:_validate_nhsn_resistance_bands` — `_NHSN_RESISTANCE_BANDS` の cohort/antibiotic を canonical に対し検証
- `clinosim/modules/hai/engine.py:_validate_hai_organisms` — `hai_organisms.yaml` を `HAI_TYPES` × SNOMED non-empty × non-negative weight × non-zero-sum で検証(本 PR 2026-06-27)
- `clinosim/locale/loader.py:_validate_demographics` / `_validate_names` / `_validate_addresses` — `demographics.yaml` の lifestyle_distribution + `names.yaml` の surnames/given_names + `addresses.yaml` の cities を、各 weight の非負 + sum > 0 で検証(本 PR 2026-06-27、4 主要 loader 完備)
- `clinosim/modules/antibiotic/engine.py:_validate_narrow_ladder` — `narrow_ladder.yaml` を **4-way 検証**: `HAI_TYPES` × `hai_antibiogram.yaml` (forward + reverse-coverage) × `ANTIBIOTIC_DRUGS` + 空コンテナ(top-level / drug list)拒否(PR3b-3 + adversarial-2 stage-3、reverse-coverage は新組織追加時の silent no-op 防御)
- `clinosim/modules/antibiotic/audit.py:_validate_narrow_rate_bands` — `_NARROW_RATE_BANDS` cohort string format (per-hai_type のみ、no slash) + 必須 key + [0, 1] 範囲 + 空 list 拒否(PR3b-3 adversarial-1 / 2、cohort string typo 防御)
- `clinosim/modules/hai/engine.py:_validate_hai_rates` — `per_day_risk ∈ [0, 1]` + `source_device_type ∈ load_devices_config()["devices"]` (HAI sibling sweep 2026-06-29)
- `clinosim/modules/hai/engine.py:_validate_hai_codes` — `icd10_us_billable` / `icd10_jp_who` / `snomed` を `_code_in_data()` で authoritative cs.codes 直接 membership 検証(HAI sibling sweep 2026-06-29)
- `clinosim/modules/hai/engine.py:_validate_hai_specimens` — `specimen_snomed` / `test_loinc` を `_code_in_data()` で authoritative 検証(HAI sibling sweep 2026-06-29)
- `clinosim/modules/hai/lab_lift.py:_validate_hai_lab_lift_config` — `ramp_peak_days > 0` + lift values ∈ [0, 1] + HAI_TYPES forward-coverage(HAI sibling sweep 2026-06-29、inline check から refactor)

新規 module で外部 ID 参照 YAML または確率重み YAML を作る場合は同パターンを必須化してください(`_validate_X(data)` を `load_X` 内で wire、`fallback="raise"` と組み合わせて後方防御も同時に確保)。**Reverse-coverage**(canonical set ⊆ data set)も忘れずに wire — adv-1 stage-2 sibling sweep で発覚した通り、forward-only validation は新 canonical 追加時の silent no-op を防げない。

### Per-dimensional cohort filter(PR3b-3 D1+D2, 2026-06-29)

監査 clinical-axis の gate が per-(dim1, dim2, ...) cohort の threshold で calibrate されているが gate filter が dimension を捨てている場合、production scale で threshold の意味が崩壊する(現状は n<30 WARN guard でマスクされる)。例: PR3b-3 D1 は band `clabsi/3092008/cefazolin`(S.aureus only)を `hai_type` only で filter していた = S.aureus + S.epidermidis + E.coli 混在計測。D2 は empty-rate threshold(5%)が NHSN panel-eligible denominator 想定なのに全 HAI cohort denominator で計測 = E.faecalis / C.albicans no-panel が分子・分母 inflate。

**新ルール**: 監査 gate を実装するとき、band cohort key の各 dimension を gate filter が消費しているか確認する。消費していない dimension は cohort key から除くか、その dimension の lookup map を build して filter に組込む。**lookup map は (country, audit-run) 内で 1 回 build して複数 gate で再利用**(D1 R-rate + D2 empty-rate が `_organism_per_encounter` を共有する pattern が precedent)。

- 先例: `clinosim/audit/axes/clinical.py:_organism_per_encounter` — `Observation.ndjson` mb-org-* を 1 pass 走査して `{enc_id: {organism_snomed, ...}}` を build、D1 + D2 で再利用
- 先例: `clinosim/audit/axes/clinical.py:_panel_eligible_organisms` — `load_hai_antibiogram()` keys から panel-eligible set を derive(no-panel は hard-coded list でなく antibiogram 不在で auto-exclude)

### Validator ordering & reverse-staleness(PR3b-3 chain stage-2/3, 2026-06-29)

監査 module の `audit.py` が canonical-constants validator + reverse-coverage validator を定義する場合、以下 3 原則を守ること:

1. **All validators MUST run BEFORE `register_audit_module`**: validator が失敗したときに stale spec が registry に入らないことを保証する。先例 `clinosim/modules/antibiotic/audit.py:656-658` で `_validate_narrow_rate_bands` + `_validate_nhsn_resistance_bands` + `_validate_narrow_ladder_at_import` が全て register の前に invoked。
2. **Forward-coverage + reverse-coverage の対称性**: band 集合が "every (dim1, dim2) in canonical YAML が covered or explicitly exempt" を要求する場合(reverse)、同じ集合に "every canonical HAI_TYPE has at least one band"(forward)も要求する。両方 missing → 新 dimension 追加時の silent no-op risk。先例 `_validate_narrow_rate_bands`(forward)+ `_validate_nhsn_resistance_bands`(reverse + forward via band)。
3. **Reverse-coverage の staleness check**: exempt list を持つ validator は「exempt 中の entry が現 YAML データに本当に存在するか」も check。dropping an organism from YAML が stale exempt を残す silent risk を防ぐ。先例 `_validate_nhsn_resistance_bands` の `_NHSN_REVERSE_COVERAGE_EXEMPT` staleness ループ。

regression test pattern:`inspect.getsource()` で source 内 `_validate_*()` 呼び出し position が `register_audit_module(` よりも小さいことを assert(`tests/integration/test_antibiotic_audit.py:test_validators_run_before_register_audit_module` precedent)。

### Cross-module canonical URI constants(PR3b-5, 2026-06-29)

FHIR builder と audit reader が共有する canonical URI(system / identifier
URI 等)を hard-coded literal で書かないこと。**writer 側 module(`clinosim/modules/output/_fhir_*.py`)に module-level 定数として定義 + reader 側がそれを import する pattern**を踏襲。rename 時に reader 側で ImportError が triggered され、silent-no-op skip を防御する(同パターン:`MB_ORG_ID_PREFIX` PR #113 / `ABX_ORDER_ID_PREFIX` PR #114 / `HAI_EVENT_ID_SYSTEM` PR3b-5)。

定数命名規約:
- ID prefix:`<BUILDER_PREFIX>_<RESOURCE>_ID_PREFIX = "..."`(例 `MB_ORG_ID_PREFIX`)
- system URI(canonical):`<DOMAIN>_<CONCEPT>_SYSTEM = "..."`(例 `HAI_EVENT_ID_SYSTEM`)
- 内部 URI には **urn-form** を使用:`urn:clinosim:identifier:<purpose>`(identifier system 用、例 `HAI_EVENT_ID_SYSTEM = "urn:clinosim:identifier:hai-event-id"`)または `urn:clinosim:<resource>:<concept>`(その他 resource 用、例 `_fhir_practitioner.py` の `"urn:clinosim:staff"`)。pr117-adv-1 で http-form と urn-form が両方混在していた状態を urn-form に統一(JP Core / US Core / HL7 IG に登録ない内部 concept のみ urn-form を許容)

contract test pattern:`assert clinical_axis.CONSTANT is mb_builder.CONSTANT`(同一 object identity 確認、import path 一致を pin)。先例 `tests/unit/test_clinical_axis_per_organism.py:test_hai_event_id_system_canonical_constant_shared`。

### データ専用モジュール (variant)

`modules/sdoh/` のように、**reference データ + loader のみ** を持ち、generation / assignment logic を持たないモジュール variant も認められます (PR2 2026-06-24 で確立)。`clinosim/codes/` が同パターンの先例です。

判定基準:
- データは存在するが、generation / assignment は別の場所 (patient activator / FHIR output builder / 他モジュール enricher) で行われる
- 複数の consumer から参照される共通参照データを集約したい
- 将来同テーマのデータ拡張余地が高い

レイアウト:

```
clinosim/modules/<name>/
  __init__.py            <- public API (loader 関数を export)
  engine.py              <- @lru_cache 付き loader のみ (assignment 関数なし OK)
  reference_data/*.yaml  <- データ駆動の定義
  README.md              <- 他モジュールと同型
```

enricher.py は **不要** (post_records enricher の登録なし)。`ENRICHER_SEED_OFFSETS` への登録も **不要** (RNG draw なし)。

### canonical な「pure-function engine」(MOD-13 が手本)

`observation/engine.py` は **cross-module import がゼロ** で、physiology 値・reference range などすべての文脈を関数引数で受け取ります。新規 engine はこれを手本にしてください。

```python
# 良い例: 文脈は引数で受ける。clinosim.modules.* を import しない
def generate_lab_result(canon: str, true_value: float, rng: np.random.Generator,
                        reference_ranges: dict | None = None) -> float:
    ...
```

### 型は `clinosim/types/` に置く (engine 内に定義しない)

**共有 runtime 型はモジュール内に定義してはいけません** (CLAUDE.md: "All types defined in `clinosim/types/`")。

- `@dataclass` → runtime 型 (例: `clinosim/types/patient.py`, `encounter.py`, `output.py`)
- Pydantic `BaseModel` → YAML-loaded config 型 (AD-18, 例: `clinosim/types/config.py`)

> **既知の負債 (MOD-2..6, TYP-2):** `PersonRecord`/`LifeEvent`/`HospitalizationSummary` (population/engine.py)、`StaffMember`/`StaffRoster` (staff/engine.py)、`ProcedureRecord`/`RehabSession` (procedure/engine.py)、`HospitalState` (facility/hospital_state.py)、`DiseaseProtocol` (disease/protocol.py) は engine 内に残っています。**新規型はこの轍を踏まず最初から `clinosim/types/<name>.py` に定義し、`clinosim/types/__init__.py` に `__all__` で export** してください。loader 関数 (`load_disease_protocol` 等) は module 側に残し、型を types から import します。

### YAML は Pydantic で validate する

`disease/protocol.py` が正しい手本です。`DiseaseProtocol(BaseModel)` を `load_disease_protocol()` で `model_validate()` します。

> **アンチパターン (ENC-1):** `encounter/protocol.py` は 46 YAML を `dict[str,Any]` のまま返し、`except Exception: pass` でパースエラーを握り潰しています。**新規 YAML protocol は必ず Pydantic でラップ** し、`extra="allow"` で段階導入してください。bare `except` 禁止。

### `__init__.py` で public API を明示する

> **既知の負債 (MOD-1, TYP-1):** 18 モジュール中 17 の `__init__.py` が空 (0 byte) で、caller が `from clinosim.modules.population.engine import LifeEvent` のように内部に直接到達しています。`identity/__init__.py` のみが正しく `__all__` で export しています。**新規モジュールは `__init__.py` に public surface を re-export** し、caller は `.engine` ではなく `from clinosim.modules.<name> import X` を使ってください。

### README に `## Dependencies` を書く

許可された依存先 (`clinosim/types/`, `clinosim/codes/`, `clinosim/locale/`, README に列挙した他モジュール) を `## Dependencies` (英語見出し、`identity/README.md` に合わせる) で明記します。

---

## データ生成の作法

### 決定論コントラクト (AD-16 / AD-17)

- **CIF が唯一の simulation 出力** (AD-17)。venue simulator は `return CIFPatientRecord(...)` で record を **返す** だけ。共有コレクションへ直接書いたり output adapter を呼んだりしない (DET-7 が手本: `inpatient.py:402` 等が return-based)。
- **`random.random()` / stdlib `random` 禁止** (AD-16, DET-8)。必ず引数で渡された `np.random.Generator` を使う。module-level の可変 global state も禁止。
  - **違反例 (DET-4):** `_generate_vitals._prev_diet` のように関数オブジェクト属性へ状態を溜めると、`FORCED-0001` 等の決定論 ID を共有する複数テスト呼び出しで stale 状態を読みます。状態は呼び出しスコープの local 変数に閉じること。

### PR 検証ガイド: byte-diff vs 3-axis DQR

**真の goal**: CIF データを **FHIR R4 + JP Core 準拠** の正確な出力に変換すること + 臨床的整合性 + JP localization 品質。

PR の性質によって適切な検証手段が異なります:

| PR の性質 | 検証手段 | 何を保証するか |
|---|---|---|
| **Pure mechanical refactor** (例: 内部構造整理、helper 共通化、registry 中央化、ファイル分割) | **byte-diff** — master と branch で同 seed/設定で生成した 11 NDJSON が sha256 IDENTICAL | refactor 前後で **出力が一切変わっていない** = no-regression gate |
| **新機能 / リアリティ改善** (例: 新 analyte 追加、scenario flag 追加、medication coupling 追加、新疾患追加) | **`clinosim audit run`** — 4 軸 (structural / clinical / jp_language / silent_no_op) を一括検証。Module 著者は `clinosim/modules/<name>/audit.py` に `ModuleAuditSpec` を register する。レポートは `docs/reviews/<date>-<topic>-audit.md` に保存 | **FHIR R4 / JP Core 適合性 + 臨床整合性 + JP language 品質 + silent-no-op gate** (PR-90 class of bug 再発防止) = goal achievement gate |
| **Pure docs update** (例: README 更新、新 doc 作成) | regression check (テスト緑) + manual link review | code 変更がないこと |
| **混合** (refactor + 小さな behavior change) | byte-diff で意図的変化のみあることを確認 + DQR で goal 維持を確認 | 両方 |

**byte-diff は手段、3-axis DQR が真の goal テスト**:

- refactor PR で byte-diff を使うのは「behavior 変えていない」を mechanical に確認する shortcut。output が変わると refactor の主張が嘘になるため。
- 新機能 PR では byte-diff は **完全一致でなくて OK** (意図的に変わる)。3-axis DQR が真のゴール — FHIR/JP Core 規格適合性、臨床的妥当性 (warfarin patient の INR 2-3 等)、JP localization 品質 (display 文字列、JLAC10 ja の権威出典準拠) — を verify する。
- 例: Phase 2a (D-dimer / causes_vte) は新機能なので、9 NDJSON は byte-identical で残り 2 つ (Observation / DR) が意図的に変化。3-axis DQR で PE/DVT/CI 患者の D-dimer が VTE-positive 帯にあるか + JLAC10 2B140 ja JCCLS 公式日本語名であるか等を verify。

#### byte-diff の実施手順

1. master HEAD で `python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/<topic>_byte_diff/master/us` (JP も同様)
2. branch HEAD で同じコマンドを `scratchpad/<topic>_byte_diff/branch/us` に出力
3. sha256 比較スクリプトを実行 (PR1/PR2 の `scratchpad/refactor_pr*_byte_diff/compare.py` を template として参照)
4. 全 11 NDJSON が IDENTICAL であることを確認 (refactor PR の gate)
5. 結果を `scratchpad/<topic>_byte_diff_results.md` に書き、PR 本体に commit

#### 3-axis DQR の実施手順

1. US p≥10000 + JP p≥5000 で生成 (大規模 cohort で cohort-emergent 現象を捕捉)
2. 3 軸監査スクリプトを実行 (Phase 2a/2b の `scratchpad/phase2*_dqr/dqr_audit.py` を template として参照):
   - **構造**: refRange 100%, interpretation 100%, display≠code 100%, id 重複 0
   - **臨床**: 期待される疾患ごとの lab 値域 (DKA HCO3 / ACS Troponin / VTE D-dimer / AF chronic INR therapeutic 等)
   - **JP language**: US 日本語混入 0、JP display 文字列が JCCLS-JSLM / MHLW 等の権威出典準拠
3. 全 axes PASS を確認
4. 結果を `docs/reviews/<date>-<topic>-data-quality-review.md` に書き、PR 本体に commit

### physiology state から導出する

可能な限り、lab/vital は患者の physiology state (true value) から導出します。生成 chain は次に funnel させてください:

```
order → canonical_lab_name → generate_lab_result(true_value, rng) → determine_flag(canon, observed, sex, reference_ranges)
```

> **注意 (OBS-3):** `determine_flag()` には locale reference range を渡してください。現状 call site (`inpatient.py:604`, `outpatient.py:178`, `emergency.py:146` 等) が `reference_ranges=` を渡さず、JP 出力で interpretation が US default で計算される不整合があります。新規 call は `reference_ranges=load_reference_ranges(country).get("ranges", {})` を渡すこと。
>
> **注意 (DET-6):** fallback baseline lab 値を venue ごとに別定義しないこと (`outpatient.py` の WBC 6500 と `emergency.py` の WBC 7500 が乖離)。observation/engine.py 側の単一定数を import してください。

### sub-seed 導出ルール (コピーすべき正確なパターン)

各 enricher/module は **master seed から自分専用の sub-stream を導出** し、メイン random stream には触れません。derive 式は `clinosim/simulator/seeding.py:derive_sub_seed(master, module_offset, key)` に集約済 (AD-16 / AD-59)。

```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed

# 患者/encounter ごとに fresh な Generator を作る
rng = np.random.default_rng(
    derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["my_module"], patient_id)
)
```

`key` には patient_id / household_id / encounter_id など **per-entity な一意キー** を必ず混ぜます (DET-3: identity module は integer-only の sub-seed で per-patient keying を欠く既知の不整合)。

**新モジュールのオフセット登録**: モジュール作成時、sub-seed の数値オフセットを **`clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`** に登録します。convention は **16-bit hex ASCII (2 文字)** — モジュール名から覚えやすい 2 文字を選ぶ:

```python
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # 例外: legacy decimal (grandfathered)
    "microbiology":   770_077,    # 例外: legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
    "nursing":        0x4E55,     # "NU"
    # 新モジュール例: "device" = 0x4456 ("DV"), "hai" = 0x4841 ("HA")
}
```

モジュール側はローカル定数を持たず、registry から import します。dict 末尾の `assert len(set(...values())) == len(...)` が重複オフセットを import 時に検出します(誤って既存モジュールの RNG ストリームを汚染するのを構造的に防ぐ)。

### CIF への書き込み: Base か extensions か (decision tree)

判定フロー:

1. **すべての EHR で必須のデータか?**
   - YES → 質問 2 へ
   - NO  → `extensions["module_name"]` (opt-in module data)
2. **将来削除しないコアフィールドか?**
   - YES → 質問 3 へ
   - NO  → `extensions`
3. **複数モジュール / FHIR builder が参照するか?**
   - YES → `CIFPatientRecord` typed field
   - NO  → `extensions`

決定 matrix:

| 軸 | typed field | extensions |
|---|---|---|
| Always-on Base data | ✓ | |
| Opt-in module data | | ✓ |
| 共通 core EHR field | ✓ | |
| Theme-specific | | ✓ |
| 例 | `immunizations` / `family_history` / `code_status` / `care_level` | `nursing` extensions (always-on だが specialized) |
| Persistence | `asdict` で完全シリアライズ | dict、explicit シリアライズ |

**例外明文化 (TYP-4)**: always-on の Base enricher で typed field を使ってよい (例 `nursing_risk_assessments`)。**新規 opt-in module は必ず `extensions[<module>]` を使う**。

> **PR2 教訓 (data-only variant)**: `modules/sdoh/` のような data-only module variant は **データを CIF に書かない** — patient activator が `PatientProfile.smoking_status` 等の既存 field を更新するため、本質的に Base data。新モジュールで CIF 書き込みが不要なら、この判定フローはスキップ。

```python
# opt-in module enricher 内
rec.extensions["my_module"] = [asdict(r) for r in my_records]

# always-on Base enricher 内 (例外: TYP-4)
rec.my_typed_field = [asdict(r) for r in my_records]
```

---

## 拡張点の使い方

**3 つの registry はいずれも core dispatch を編集せず、登録だけで拡張** します。core を直接編集してはいけません。

### A. FHIR リソースを追加する (`register_bundle_builder`, AD-56)

`_build_bundle()` を編集しない。builder は `(ctx: BundleContext) -> list[dict]` の pure 関数で raw resource を返します (Bundle entry でラップしない — registry が `_entry()` で一律ラップする)。

```python
# clinosim/modules/output/fhir_r4_adapter.py
def _bb_my_resource(ctx: BundleContext) -> list[dict]:
    # ctx fields: record, country, roster_map, hospital_config, patient_data,
    #             patient_id, primary_dx_code, admit_dx_code, primary_enc_id, patient_sex, ...
    if ctx.country != "JP":          # 国 gate は builder 内で行う
        return []
    return [{"resourceType": "...", "id": f"...-{ctx.primary_enc_id}", ...}]

register_bundle_builder(_bb_my_resource)
```

- 命名は `_bb_*` prefix で統一 (EXT-6: `_build_nursing_observations` 等は旧式)。
- `Resource.id` は型内で globally unique に。encounter-scoped id (`lab-{encounter_id}-...`) を使う (FA-7)。
- **double-wrap 注意 (FA-3):** builder は raw resource dict を返す。`_entry()` を builder 内で呼ばない。

**Canonical example — `_bb_service_requests` (PR1, 2026-06-29, `_fhir_service_request.py`):**

```python
# clinosim/modules/output/_fhir_service_request.py
from clinosim.modules.output.fhir_r4_adapter import register_bundle_builder, BundleContext
from clinosim.modules.order.panel_grouping import classify_lab_specs

def _bb_service_requests(ctx: BundleContext) -> list[dict]:
    """Emit 1 ServiceRequest per panel instance + 1 per stand-alone lab order."""
    resources: list[dict] = []
    orders = _collect_lab_orders(ctx.record)       # walk all encounters' orders
    for group_key, group_orders in _group_by_panel(orders):
        sr = _build_service_request(group_key, group_orders, ctx)
        resources.append(sr)
    return resources

register_bundle_builder(_bb_service_requests)
```

Key patterns illustrated:
- `ctx.record` is the `CIFPatientRecord` (dict in production JSON path, dataclass in tests).
  Always access fields via `_o(order, "field_name", default)` (`get_attr_or_key` wrapper, see
  `clinosim/modules/_shared.py`) to support both paths — unit tests may pass dataclass
  instances while the production path deserializes to dict.
- Panel grouping logic lives in `clinosim/modules/order/panel_grouping.py:classify_lab_specs`.
  Never inline a panel-detection if/elif in the builder. [AD-61]
- Both dict-path and dataclass-path MUST be covered by tests: a subprocess integration smoke
  test exercises the production dict path (see `tests/integration/test_service_request.py`).

See [`clinosim/modules/output/_fhir_service_request.py`](../clinosim/modules/output/_fhir_service_request.py) for the full implementation.

### B. 出力フォーマットを追加する (`register_output_adapter`, AD-58)

CLI の `--format` dispatch を編集しない。`OutputAdapter` Protocol を満たすクラスを `adapters_builtin.py` パターンで登録します。adapter は **CIF + `clinosim.codes` + `clinosim.locale` のみ** に依存できます。

```python
# clinosim/modules/output/adapter.py の Protocol:
#   format_id: str / description: str / subdir: str
#   def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None
class MyFormatAdapter:
    format_id = "my-format"
    description = "My export format"
    subdir = "my_format"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        from clinosim.modules.output.my_converter import convert_cif_to_myformat
        convert_cif_to_myformat(cif_dir, out_dir, country=ctx.country)  # ctx.country を渡す

register_output_adapter(MyFormatAdapter())
```

builtin は `_ensure_builtins()` が `adapters_builtin` を import して self-register します。新規 builtin はそこに `register_output_adapter(...)` を追加してください。

> **注意 (FA-9):** `ctx.country` を必ず使う。CSV adapter は現状 `ctx.country` を捨てている既知の負債があります。

### C. post-pass を追加する (Enricher, AD-56)

`run_beta` にインライン化しない。`Enricher` を `register_builtin_enrichers()` (`enrichers.py`) で登録します。

```python
# clinosim/simulator/enrichers.py
@dataclass  # 実体は既存の Enricher dataclass
# Enricher(name, stage, run: Callable[[EnricherContext], None], order=100, enabled=lambda c: True)

def run_my_pass(ctx: EnricherContext) -> None:
    # ctx fields: config, master_seed, population, records
    rng_seed = _sub_seed(ctx.master_seed, "my-pass")  # 自前 sub-seed (メイン stream に触れない)
    for rec in ctx.records:
        rec.extensions["my_module"] = ...

register_enricher(Enricher(
    name="my_module",
    stage=POST_RECORDS,                 # or POST_POPULATION
    run=run_my_pass,
    order=300,                          # 昇順実行。order は固定 = 決定論
    enabled=lambda c: c.module_enabled("my_module", default=True),
))
```

- stage は `POST_POPULATION` (population 生成後/simulation 前、`ctx.population` を mutate) または `POST_RECORDS` (record 生成後、`ctx.records` を読み/extend)。
- registry は name で idempotent。order 整数が実行順 = 決定論を支配します。

---

## 何のデータ/コードを使うか

### codes と locale の分離

- **`clinosim/codes/`** = 国際標準コードシステム (locale 非依存, EN-first)。`icd-10-cm.yaml`, `icd-10.yaml`, `loinc.yaml`, `rxnorm.yaml`, `yj.yaml`, `cpt.yaml`, `k-codes.yaml`, `cvx.yaml` 等。
- **`clinosim/locale/`** = 国/文化依存データのみ (氏名, 住所, reference range, `code_mapping_*`)。terminology は codes/ へ移行済み (CODES-2)。**locale に display text を置かない。**

### display は `lookup()` で解決する (AD-30)

CIF は **コードのみ** 保持。display は出力時に解決します。

```python
from clinosim.codes import lookup as code_lookup
name = code_lookup("icd-10-cm", "I50.9", "en")  # 見つからなければ code 自身/EN fallback
```

> **アンチパターン (DUP-3, FA-4, DIAG-1):** `CONDITION_NAMES` (patient/activator.py) のような display dict を新設しない。`csv_adapter.py` / `narrative_generator.py` の `admission_diagnosis_name` 等は CIF に存在しない ghost field で常に空。新規コードは `code_lookup(system, code, lang)` を使う。

### URI は `get_system_uri()` で解決する

```python
from clinosim.codes import get_system_uri
uri = get_system_uri("snomed-ct")  # FHIR system URI を文字列リテラルで書かない
```

> **アンチパターン (URI-1, CODES-4, FA-2):** SNOMED/LOINC/UCUM/HL7 URI を生文字列で埋め込まない (現状 fhir_r4_adapter.py に多数残存)。新規キーは `codes/loader.py` の `_BUILTIN_URIS` に正準 HL7 URI を登録してから `get_system_uri()` を使う。

### internal-name → 標準コードは `code_mapping`

内部テスト名 (`"WBC"`) → 標準コードは `locale/<country>/code_mapping_*.yaml` で解決します (`load_code_mapping()`)。YAML を直 `yaml.safe_load` せず canonical loader を通すこと (LOC-1)。

### 権威出典 / English-first / コード coverage

- **権威出典のみ:** CMS (ICD-10-CM), NLM (RxNorm, ICD-10-CM API `clinicaltables.nlm.nih.gov/api/icd10cm`), WHO (ICD-10, `icd.who.int/browse10`), Regenstrief (LOINC), AMA (CPT), JCCLS/JSLM (JLAC10), MHLW (YJ, K codes)。**コードを fabricate しない** (CODES-7: RxNorm CUI 18631 を 2 薬で共有した fabricated display が実例)。
- **English-first:** `codes/data/*.yaml` の全エントリに `en` 必須、他言語 (`ja` 等) は任意 (CODES-1)。
- **emittable な診断コードは全て登録:** disease の `icd_codes` (primary + variants)、encounter の `icd10_code`、`builtin_differentials.yaml` の `differentials[*].icd` + `diagnosis_progression`。US billable は `icd-10-cm.yaml`、非 billable は `code_mapping_diagnosis/us.yaml` で billable leaf へ。JP は WHO 3-4 桁を `icd-10.yaml` に (CM 粒度は `code_mapping_diagnosis/jp.yaml` で WHO 親へ畳む)。追加後は必ず:

```bash
pytest tests/unit/test_diagnosis_code_coverage.py
```

> RxNorm/YJ/CPT/K-codes/CVX には同等の coverage test がまだありません (CODES-6)。drug/procedure コードを追加したら手動で mapping → codes の存在を確認してください。

---

## 追加時チェックリスト

順番に実行:

1. **対象モジュールの `README.md` を読む** (Dependencies と既存 API を把握)。
2. **共有型を `clinosim/types/<name>.py` に定義** し `types/__init__.py` に `__all__` で export (engine 内に定義しない)。`@dataclass` = runtime, Pydantic = config (AD-18)。
3. **データ駆動なら `reference_data/*.yaml` + Pydantic 検証** (`model_validate`)。bare `except` 禁止。
4. **決定論 sub-seed** を式どおりに導出 (per-entity key を混ぜる)。`random.random()` / global state 禁止。
5. **適切な registry で登録:** FHIR → `register_bundle_builder`、出力形式 → `register_output_adapter`、post-pass → `register_enricher`。core dispatch / `_build_bundle` / `run_beta` / CLI `--format` を編集しない。
6. **コード coverage:** 新規/変更コードを権威出典で照合 → `codes/data/<system>.yaml` (`en` 必須) または `code_mapping_*` に登録 → `pytest tests/unit/test_diagnosis_code_coverage.py`。
7. **README / types を更新** (API・データ構造が変わったら)。`README.md` の依存グラフで downstream 影響を確認。
8. **`pytest -x -q`** (unit 必須、commit 前)。出力に影響しうるなら `pytest -m e2e` で golden を確認。
9. **生成された CIF + FHIR を臨床的整合性で監査** (lab/vital が physiology と整合、診断コードが正しく解決、JP 出力に英語が混入しないか、URI/reference 整合)。

---

## よくある落とし穴

**Do**
- engine は pure function、文脈は引数で渡す (`observation/engine.py` が手本)。
- 型は `clinosim/types/`、display は `code_lookup()`、URI は `get_system_uri()`。
- venue simulator は `CIFPatientRecord` を **return**、opt-in は `extensions[<module>]` に書く。
- sub-seed に per-entity key を混ぜ、各 entity ごとに fresh な `default_rng` を作る。
- YAML は Pydantic で validate、canonical loader (`locale/loader.py`, `codes/loader.py`) を通す。

**Don't**
- ❌ CIF に display text を保存しない (codes のみ。AD-30)。
- ❌ FHIR system URI / 診断 display を生文字列でハードコードしない (URI-1, MOD-11, DUP-1/2/3, FA-2/4/8)。
- ❌ `random.random()` / stdlib `random` / module-level 可変 global を使わない (AD-16; DET-4 の `_prev_diet` が反面教師)。
- ❌ core dispatch (`_build_bundle`, `run_beta`, CLI `--format`) を編集しない — registry で拡張する。
- ❌ 共有型を engine 内に定義しない (MOD-2..6)。`__init__.py` を空のままにせず public API を export する (MOD-1/TYP-1)。
- ❌ private 関数 (`_sample_given_name` 等) を他モジュールから import しない (MOD-7/TYP-5) — locale の public utility に昇格させる。
- ❌ コードを fabricate しない / `except Exception: pass` で YAML エラーを握り潰さない (CODES-7, ENC-1)。
- ❌ `ctx.country` を捨てない (FA-9)。`determine_flag()` に locale reference range を渡し忘れない (OBS-3)。
- ❌ venue ごとに baseline 値や lookup table を別定義して乖離させない (DET-6, DUP-1)。