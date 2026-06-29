# hai — 病院関連感染 (CLABSI / CAUTI / VAP) サンプリング

> AD-55 Module: PR-A `extensions["device"]` を consume して CDC NHSN baseline per-line-day risk rate で CLABSI / CAUTI / VAP の発症を確率サンプリングし、FHIR Condition + culture chain を emit する opt-in 軽量モジュール。device + HAI 4-PR シリーズ Phase 2、PR-A で確立した cross-module dependency point の初の利用例。

## 概要 / 役割

- post_records enricher として各 `CIFPatientRecord.extensions["device"]` を walk し、各 device の line-days × CDC NHSN per-day risk rate (0.0010-0.0015) で確率発症を判定。
- 発症時:
  1. `HAIEvent` を `extensions["hai"]` に append (ICD + SNOMED + onset_date + organism + source_device_id)
  2. `MicrobiologyResult` を `record.microbiology` に append (specimen + organism + culture)
- 既存の `_fhir_microbiology.py` builder が culture chain (Specimen + Observation + DiagnosticReport) を **自動 emit** = 新 culture builder 不要。
- 新 `_fhir_hai.py` builder は HAI Condition のみ emit (ICD-10 + SNOMED dual coding、US billable / JP WHO 4-char)。
- main RNG stream は触らず、`ENRICHER_SEED_OFFSETS["hai"] = 0x4841` から導出した patient-id-scoped sub-seed のみ消費。AD-16 / AD-56 完全準拠。

## 設計原則

| Principle | Source |
|---|---|
| AD-16 deterministic (per-patient sub-seed) | DESIGN.md AD-16 |
| AD-55 Module opt-in (post_records enricher, `extensions` slot) | DESIGN.md AD-55 / AD-56 |
| AD-56 builder + enricher registry | DESIGN.md AD-56 |
| BNP-pattern surgical: physiology state 不変、observation-time formula | DESIGN.md AD-57 |
| sub-seed 16-bit hex ASCII convention (`0x4841` = "HA") | CLAUDE.md "AD-55 enricher patterns" |
| Cross-module dependency: PR-A → PR-B one-way (hai reads device, never writes) | spec §"Cross-module dependency point" |
| CDC NHSN baseline rate calibration | `reference_data/hai_rates.yaml` |
| CDC ≥48h HAI definition (onset_offset ≥ 2) | engine.py `sample_hai_onset` |

## ディレクトリ構造

```
clinosim/modules/hai/
  __init__.py            # public API
  engine.py              # pure functions (sampling + organism + date arithmetic)
  enricher.py            # AD-56 post_records enricher (enrich_hai)
  reference_data/
    hai_rates.yaml       # CDC NHSN per-line-day risk rates (CLABSI/CAUTI/VAP)
    hai_codes.yaml       # ICD-10-CM + WHO ICD-10 + SNOMED for 3 HAI conditions
    hai_organisms.yaml   # CDC NHSN top organism distributions per HAI type
    hai_specimens.yaml   # Specimen SNOMED + culture LOINC per HAI type
    hai_antibiogram.yaml # CDC NHSN AR 2018-2020 susceptibility rates per organism (Phase 3b-2)
  README.md              # this file
```

## API Reference

```python
def load_hai_rates() -> dict[str, Any]:
    """reference_data/hai_rates.yaml を @lru_cache で読み込み返す。"""

def load_hai_codes() -> dict[str, Any]:
    """reference_data/hai_codes.yaml を @lru_cache で読み込み返す。"""

def load_hai_organisms() -> dict[str, Any]:
    """reference_data/hai_organisms.yaml を @lru_cache で読み込み返す。

    Import 時に `_validate_hai_organisms(data)` を実行(本 PR 2026-06-27 追加):
    - top-level key `hai_organisms` が dict
    - 各 hai_type ⊆ `HAI_TYPES = ("clabsi", "cauti", "vap")` canonical set
    - 各 hai_type の organism list non-empty
    - 各 entry の `snomed` が non-empty string
    - 各 entry の `weight` が numeric かつ >= 0
    - 各 hai_type の weight sum > 0(= `_sample_organism` の
      `normalize_probabilities(..., fallback="raise")` 前提条件)

    silent-no-op 防御 3 層の上流(import-time)層。後方層 = `engine.py:85`
    `_sample_organism` の `fallback="raise"`。
    """

def load_hai_specimens() -> dict[str, Any]:
    """reference_data/hai_specimens.yaml を @lru_cache で読み込み返す。"""

def load_hai_antibiogram() -> dict[str, Any]:
    """reference_data/hai_antibiogram.yaml を @lru_cache で読み込み返す (Phase 3b-2)。

    形式: {hai_type: {organism_snomed: {antibiotic_key: [S_rate, I_rate, R_rate]}}}
    Import 時に HAI_TYPES + hai_organisms.yaml (有効 SNOMED) + ANTIBIOTIC_LOINC_LOOKUP
    (有効 antibiotic key) の 3-way cross-validation を実行。不整合は ImportError を raise。
    出典: CDC NHSN Antibiotic Resistance 2018-2020 AR report。
    """

def sample_hai_onset(
    device: DeviceRecord, rate_cfg: dict, rng: np.random.Generator,
) -> tuple[bool, int | None]:
    """1 device に対する HAI 発症判定。

    Returns (False, None) 発症なし
            (True, k)     placement_date + k 日目に発症 (k は 2 ≤ k < line_days)
    """

def enrich_hai(ctx) -> None:
    """post_records enricher entry point.

    ctx.records を巡り、各患者の extensions["device"] から HAI を sample、
    extensions["hai"] (list[HAIEvent]) + record.microbiology
    (MicrobiologyResult append) を書く。Phase 3b-2 では _append_hai_culture が
    antibiogram を参照して MicrobiologyResult.susceptibilities を populate する。
    """
```

## データ構造

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `HAIEvent` | `clinosim/types/hai.py` (`@dataclass`) | `hai_id`, `encounter_id`, `hai_type`, `source_device_id`, `icd10_code`, `snomed_code`, `onset_date`, `organism_snomed`, `culture_specimen_id` | `CIFPatientRecord.extensions["hai"]` 配下 |
| `MicrobiologyResult` (既存) | `clinosim/types/microbiology.py` | `encounter_id`, `specimen`, `specimen_snomed`, `test_loinc`, `organism_snomed`, `growth`, `quantitation`, **`hai_event_id`** (Phase 3b-2), `susceptibilities` | `record.microbiology` append、既存 `_fhir_microbiology.py` で自動 emit |

CIF 上の location:
- HAI metadata: `CIFPatientRecord.extensions["hai"]: list[HAIEvent]` (typed dataclass を extensions slot に格納)
- Culture chain: `CIFPatientRecord.microbiology: list[MicrobiologyResult]` (Base typed field、append のみ)

**`hai_event_id` backref convention (Phase 3b-2)**: HAI 由来の `MicrobiologyResult` は `hai_event_id = HAIEvent.hai_id` をセットする。これにより FHIR 出力層が同一 HAI event に紐づく Condition と DiagnosticReport を相互参照できる。Community microbiology (非 HAI culture — sepsis/pneumonia/UTI の通常経路) は `hai_event_id = ""` のままで今後も変更なし。

**PR3b-5 FHIR emission (2026-06-29)**: `MicrobiologyResult.hai_event_id` が non-empty なとき、`Observation.identifier[].system = HAI_EVENT_ID_SYSTEM` + matching value を Specimen / mb-org-* / mb-sus-* / DiagnosticReport の 4 FHIR resource type に emit する。Community culture (`hai_event_id == ""`) は identifier 不在で出力 byte-identical 維持。audit clinical axis D1 R-rate gate は `_hai_specimens` 経由でこの identifier を読んで community-acquired culture susceptibilities を HAI band から除外(C2 解消)。

## CDC NHSN baseline rates

`reference_data/hai_rates.yaml` (per-line-day risk):

| HAI | per_day_risk | source_device_type | CDC NHSN per 1000 days |
|---|---|---|---|
| CLABSI | 0.0010 | cvc | 1.0 |
| CAUTI | 0.0014 | indwelling_catheter | 1.4 |
| VAP | 0.0015 | mechanical_ventilator | 1.5 |

出典: CDC NHSN Annual HAI Report 2018-2020 ICU mixed wards average (https://www.cdc.gov/nhsn/datastat)

## Organism distribution

`reference_data/hai_organisms.yaml` (weight sums to 1.0 per HAI type, CDC NHSN HAI Annual Report):

- **CLABSI 主要菌**: S. aureus 0.20 / S. epidermidis 0.18 / C. albicans 0.15 / E. faecalis 0.13 / K. pneumoniae 0.10 / E. coli 0.10 / P. aeruginosa 0.09
- **CAUTI 主要菌**: E. coli 0.27 / C. albicans 0.18 / E. faecalis 0.16 / K. pneumoniae 0.13 / P. aeruginosa 0.10 / P. mirabilis 0.06
- **VAP 主要菌**: S. aureus 0.24 / P. aeruginosa 0.17 / K. pneumoniae 0.10 / E. coli 0.08 / E. cloacae 0.08 / A. baumannii 0.05 / S. maltophilia 0.04

全 11 organism SNOMED は tx.fhir.org `$expand` で照合済 (Task 1)。

## Dependencies

| Dependency | Why |
|---|---|
| `clinosim/types/hai` | HAIEvent |
| `clinosim/types/device` | DeviceRecord (consumed from extensions["device"]) |
| `clinosim/types/microbiology` | MicrobiologyResult (appended to record.microbiology) |
| `clinosim/codes/` | (FHIR builder + culture builder 経由) ICD-10-CM/WHO/SNOMED/LOINC lookup |
| `clinosim/simulator/seeding` | ENRICHER_SEED_OFFSETS, derive_sub_seed |
| `clinosim/modules/_shared` | get_attr_or_key (dict/dataclass dual access) |
| `clinosim/modules/device` (data flow only) | PR-A の extensions["device"] を読む |
| `clinosim/modules/antibiotic` (Phase 3b-2) | `ANTIBIOTIC_LOINC_LOOKUP` — antibiogram antibiotic_key → LOINC の照合に使用 (import-time cross-validation) |

## Consumers

| Caller | How it uses this module | Impact tier |
|---|---|---|
| `clinosim/simulator/enrichers.py` | `register_builtin_enrichers()` で `enrich_hai` を **POST_ENCOUNTER** phase に登録 (order=80、Phase 3a で POST_RECORDS から移行) | core (build pipeline) |
| `clinosim/simulator/inpatient.py` | encounter 完了直後に `run_stage(POST_ENCOUNTER, ...)` で hai を発火させ、続けて `apply_hai_lab_lift(record, encounter, state_history, admission_time)` で同 encounter の WBC + CRP に forward-delta 適用 (Phase 3a) | core (build pipeline) |
| `clinosim/modules/output/_fhir_hai.py` | `extensions["hai"]` を読んで HAI Condition を emit | medium (FHIR output) |
| `clinosim/modules/output/_fhir_microbiology.py` (既存) | `record.microbiology` を読んで HAI culture (Specimen + Observation + DR) を emit | medium (cross-cutting; PR-B が culture を append しても既存 builder が変更なく動く) |
| `clinosim/modules/antibiotic/enricher.py` (PR3b-3 Pass 2) | `MicrobiologyResult.hai_event_id` backref を読んで empirical → narrow de-escalation を選定 (`extensions["hai"]` 経由で hai_type + organism_snomed を参照) | medium (downstream consumer; HAI のみが culture + organism を produce する責務) |
| `tests/unit/test_hai_engine.py` | engine unit tests (9) | guard |
| `tests/unit/test_hai_enricher.py` | enricher unit tests (6) | guard |
| `tests/unit/test_hai_codes_coverage.py` | code coverage smoke (9 parametrize) | guard |
| `tests/integration/test_hai_extension_persistence.py` | CIF JSON round-trip | guard |
| `tests/integration/test_hai_fhir_output.py` | 小規模 ICU cohort full pipeline | guard |

## Cross-module dependency pattern (PR-A → PR-B)

PR-A `modules/device` is the **upstream**, PR-B `modules/hai` is the **downstream**:

```
device enricher (order=70) → record.extensions["device"] = list[DeviceRecord]
                                      ↓ (read only)
hai enricher    (order=80) → record.extensions["hai"]    = list[HAIEvent]
                            + record.microbiology       = list[MicrobiologyResult]
```

これは clinosim で初めて確立された cross-module enricher consumption pattern。Phase 3+ の device-consuming module (例: HAI 治療 antibiotic order、薬剤耐性) は同パターンを踏襲する。

## Phase 2 simplifications (scope cap)

- **Snapshot in-progress device**: `device.removal_date is None` のとき `line_days = 7` の conservative fallback。Phase 3 で simulator snapshot date と統合。
- **At-most-one HAI per device**: 1 DeviceRecord から 1 HAIEvent しか sample しない。Phase 3 で繰り返し感染 (e.g. CRBSI relapse) 対応。
- **Antibiotic empirical / narrow-spectrum order chain**: ~~未実装~~ → **PR3b-1 (2026-06-25) + PR3b-3 (2026-06-27) で実装済**。`modules/antibiotic` が HAI 発症で empirical regimen を emit (PR3b-1)、Pass 2 で culture S/I/R から narrow target を選定 (PR3b-3、`narrow_ladder.yaml`)。3 outcomes (SWITCH / ELIMINATION / NO_CHANGE) で `discontinuation_datetime` set + 新 `intent="narrowed"` regimen emit + FHIR `MedicationRequest.status="stopped"` 出力。
- **Susceptibility (S/I/R)**: ~~`MicrobiologyResult.susceptibilities = []`~~ → **Phase 3b-2 (2026-06-26) で実装済**。`_append_hai_culture` が `load_hai_antibiogram()` を参照し、organism × antibiotic の CDC NHSN AR 2018-2020 比率から S/I/R をサンプリングして `susceptibilities` に populate。既存 `_fhir_microbiology.py` builder が susceptibility Observation (`category=laboratory`) として自動 emit。**PR3b-3 (2026-06-27) で `hai_resistance_bands` + `hai_empty_susceptibilities_max_rate` を clinical axis に active enforcement**(per-(hai_type, antibiotic) R-rate gate + per-HAI cohort empty-rate gate、両 gate に n<30 WARN guard)。**PR3b-3 D1+D2 完成 (2026-06-29)**: R-rate gate は per-(hai_type, organism, antibiotic) filter で MRSA proxy 等が真の per-organism rate を測定。empty-rate gate は panel-eligible denominator で E.faecalis / C.albicans no-panel を auto-exclude(`_organism_per_encounter` + `_panel_eligible_organisms` helpers via `clinosim.audit.axes.clinical`)。
- **WBC/CRP shift**: ~~未実装~~ → **Phase 3a (2026-06-25) で実装済**。`modules/hai/lab_lift.apply_hai_lab_lift` が encounter daily-loop 完了直後に発火、`reference_data/hai_lab_lift.yaml` (CLABSI/VAP 0.35, CAUTI 0.20、ramp 2 日) と per-day state_history から forward-delta を計算し、既存 WBC + CRP 観測値に加算。詳細は下の "Phase 3a" section 参照。
- **Mortality 影響**: HAI 発症 → 死亡率 + は未実装 (Phase 3c outcome benchmarks 連動)。
- **Peripheral IV / arterial line HAI**: Phase 1 device scope 外。

## Phase 3b-2: HAI culture S/I/R susceptibility chain (2026-06-26)

`_append_hai_culture()` が `load_hai_antibiogram()` を呼び出し、サンプリングされた organism の S/I/R 比率を `MicrobiologyResult.susceptibilities` に populate する。既存の `_fhir_microbiology.py` builder が susceptibility Observation として FHIR emit する (変更なし)。

**`hai_antibiogram.yaml` フォーマット**:
```yaml
# reference_data/hai_antibiogram.yaml
# Source: CDC NHSN Antibiotic Resistance Annual Report 2018-2020
clabsi:
  "3092008":   # Staphylococcus aureus SNOMED
    vancomycin: [1.00, 0.00, 0.00]  # [S_rate, I_rate, R_rate]
    ...
cauti:
  ...
vap:
  ...
```

- `hai_type` キーは `HAI_TYPES = ("clabsi", "cauti", "vap")` の lowercase 定数と照合(import-time validation)
- organism SNOMED は `hai_organisms.yaml` 有効 SNOMED セットと照合
- antibiotic_key は `ANTIBIOTIC_LOINC_LOOKUP` キーセットと照合
- `[S, I, R]` は合計 1.0 に近似(浮動小数点許容); import 時に sum 検証

**RNG 使用**: `_append_hai_culture` の S/I/R サンプリングは既存の HAI per-patient sub-rng を再利用(新 RNG ストリーム不要)。main RNG 不動 = AD-16 保証継続。

**Audit**: `modules/antibiotic/audit.py` の `antibiogram_firing_proof` が `_append_hai_culture` を synthetic CLABSI S. aureus record に対して drive し、Vancomycin susceptibility = S ([1.00, 0.00, 0.00]) の closed-form delta を `equality_checks` (PR-94 形式) で検証。**PR3b-3 (2026-06-27) で `_NHSN_RESISTANCE_BANDS` + `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` を clinical axis active enforcement に移行済**(各 gate は n<30 WARN guard で保護)。**PR3b-3 D1+D2 完成 (2026-06-29)**: per-organism R-rate filter + panel-eligible empty-rate filter を `_organism_per_encounter` + `_panel_eligible_organisms` で実装、PR3b-3 chain 完全クローズ。`_pr3b3_narrow_proof_checks` が narrow chain 6 equality_checks を追加し、combined proof は計 17 checks (8 PR3b-1 + 3 PR3b-2 + 6 PR3b-3)。

## Phase 3a: WBC + CRP 観測時 forward-delta lift (2026-06-25)

`extensions["hai"]` を立てた本モジュールに対し、`modules/hai/lab_lift.py` の `apply_hai_lab_lift()` が daily loop 完了直後に encounter の既存 WBC + CRP 値を読み取り、forward 公式で計算した delta を加算する。

**設計 rationale**:
- device + hai の sampling は `record.icu_transferred` + GCS / perfusion 等 daily loop の outcome に依存 → daily loop の **後** に走る必要がある(POST_ENCOUNTER stage)
- HAI 発症が確定した後、同 encounter の WBC + CRP は炎症マーカーなので上昇させたい
- 観測値を直接 reverse-engineer すると noise / circadian を失う → forward-delta で対応:
  - `delta = derive_lab_values(state_snap, lift>0) - derive_lab_values(state_snap, lift=0)`
  - `obs.value += delta`
- `state_snap` は per-day `state_history` から取得 → 当日の真の inflammation level に基づく forward 計算

**公式**:
- `effective_infl = min(1.0, infl + lift_value * ramp_factor)`
- `ramp_factor = min(1.0, max(0, days_since_onset) / ramp_peak_days)` (= 0/0.5/1.0 at day 0/1/2+)
- `lift_value` = `hai_lab_lift.yaml[hai_type]` (CLABSI/VAP 0.35, CAUTI 0.20)
- WBC + CRP は `derive_lab_values` の既存式に `effective_infl` を渡すだけ

**スコープ**:
- 対象 analyte は WBC + CRP のみ。Lactate / Plt / 体温 / SBP は Phase 3c sepsis cascade で同 forward-delta pattern を拡張
- antibiotic empirical → narrow + susceptibility (S/I/R) + WBC/CRP decay phase は Phase 3b
- HAI mortality coupling は Phase 3c

**byte-diff invariant**: main RNG 不動、device + hai per-patient sub-seed 不変。p=2000 cohort では HAI が 0 件 (Poisson rare-event) → Observation 全 byte-IDENTICAL。p=10000 DQR で HAI 発症 cohort の WBC + CRP delta を確認。

## 拡張ガイド

新規 HAI type を追加するときは (例: SSI 手術部位感染、付与 device は不要だが encounter-attached):
1. `clinosim/codes/data/icd-10-cm.yaml` + `icd-10.yaml` + `snomed-ct.yaml` に新コード追加 (NLM/WHO/tx.fhir.org 照合必須)
2. `reference_data/hai_codes.yaml` に新エントリ追加
3. `reference_data/hai_rates.yaml` に per_day_risk + source 追加 (SSI は line-days でなく surgery 経過日数)
4. `engine.py:_DEVICE_TO_HAI` mapping 拡張 or 新 sampling 関数追加
5. 既存 unit test + 新 type 用テストケース追加
6. 3-axis DQR cohort で新 type の出現分布を audit

詳細は [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 参照。

## 関連

- [DESIGN.md](../../../DESIGN.md) AD-55 / AD-56 / AD-57
- [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) — モジュール作成 + PR 検証ガイド
- [MODULES.md](../../../MODULES.md) — 全 module 俯瞰
- 関連モジュール: `output/_fhir_hai.py` (HAI Condition builder)、`output/_fhir_microbiology.py` (culture emit、既存)、`modules/device` (upstream)、`modules/antibiotic` (ANTIBIOTIC_LOINC_LOOKUP 供給 + downstream consumer)
- 関連 spec / plan:
  - `docs/superpowers/specs/2026-06-24-hai-module-design.md`
  - `docs/superpowers/plans/2026-06-24-hai-module-prb.md`
- DQR reviews:
  - `docs/reviews/2026-06-24-hai-module-data-quality-review.md` (Phase PR-B)
  - `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md` (Phase 3b-2)
- ~~PR3b-3 forward-compat reserves~~: ✓ done 2026-06-27 — `MicrobiologyResult.hai_event_id` + `AntibioticRegimen.discontinuation_datetime` + `intent="narrowed"` を Phase 3b-3 (narrow / de-escalation chain) で load-bearing 消費。hai_event_id は antibiotic enricher Pass 2 の backref lookup として、discontinuation_datetime は empirical truncation の時刻として、intent="narrowed" は switch case の新 regimen marker として使用。
