# antibiotic Module(AD-55 always-on Module、Phase 3b-1)

> HAI 発症後の **経験的抗菌薬投与** を IDSA guideline に従って生成する always-on モジュール。
> `extensions["hai"]` を consume し、`record.orders`(MedicationRequest)+ `record.medication_administrations`(MAR)+ `extensions["antibiotic"]` の 3 経路に書き込む。

## 概要

- POST_ENCOUNTER stage、order=85(`hai=80` の後)
- **Always-on**(`enabled=lambda c: True`、device/hai と pattern 統一)
  - AD-55 **near-essential clinical cascade** カテゴリ:HAI 発症 → 抗菌薬投与は IDSA guideline で省略不可、`HAI を出すが薬は出さない` 状態は臨床的にあり得ない
- 既存 `_fhir_medications.py` builder を再利用(新 FHIR builder ゼロ)
- 後続 PR3b-2(S/I/R)/ PR3b-3(narrow)/ PR3b-4(decay)が `extensions["antibiotic"]` を consume
- `inpatient.py` の AD-32 truncation が POST_ENCOUNTER **後** に走るため、enricher 内で future-onset HAI events を pre-skip し orphan Order/MAR を防ぐ

## 役割

CLABSI / CAUTI / VAP の 3 HAI type に対し、IDSA guideline に沿う経験的レジメン(organism-agnostic)を materialize する:

| HAI type | レジメン | duration | 出典 |
|---|---|---|---|
| CLABSI | Vancomycin q12h + Piperacillin/Tazobactam q6h | 14 days | IDSA 2009 (Mermel LA et al., CID 49:1-45) |
| CAUTI | Ceftriaxone q24h | 7 days | IDSA 2009 (Hooton TM et al., CID 50:625-63) |
| VAP | Vancomycin q12h + Piperacillin/Tazobactam q6h | 7 days | IDSA/ATS 2016 (Kalil AC et al., CID 63:e61-e111) |

## Dependencies(他モジュール)

- `clinosim/types/antibiotic.py` — `AntibioticRegimen`
- `clinosim/types/encounter.py` — `Order`, `OrderType`, `MedicationAdministration`
- `clinosim/types/hai.py` — `HAIEvent`(`extensions["hai"]` で consume)
- `clinosim/modules/hai/__init__.py` — `HAI_TYPES`(YAML cross-validation)
- `clinosim/modules/_shared.py` — `get_attr_or_key`
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142`
- `clinosim/audit/registry.py` — `ModuleAuditSpec`, `register_audit_module`
- `clinosim/codes/data/{rxnorm,yj}.yaml` — drug 表示の照合先
- `clinosim/locale/{us,jp}/code_mapping_drug.yaml` — drug_key → RxNorm/YJ

## Consumers(本モジュールを使う側)

- `clinosim/modules/output/_fhir_medications.py` — `record.orders`(MedicationRequest)+ `record.medication_administrations`(MAR)を読んで FHIR resource を emit
- `clinosim/modules/output/csv_adapter.py` — `record.medication_administrations` を `medication_administrations.csv` に書き出し
- `clinosim/modules/output/hospital_course_extractor.py` — MAR を walk して退院サマリーテキストに反映
- 後続 PR:
  - ~~PR3b-2~~: ✓ done 2026-06-26 — `ANTIBIOTIC_LOINC_LOOKUP` が `hai` モジュールの `load_hai_antibiogram()` cross-validation + `_append_hai_culture()` susceptibility Observation code 付与に使用された。本モジュールは LOINC 供給側として参照される。
  - ~~PR3b-3~~: ✓ done 2026-06-27 — narrow / de-escalation chain。同 enricher 2-pass で `extensions["antibiotic"][i].intent == "empirical"` を読み、`MicrobiologyResult.hai_event_id` backref で培養を引いて narrow target を選定。`discontinuation_datetime` set + `intent="narrowed"` 後継 regimen emit + FHIR `MedicationRequest.status="stopped"` + audit clinical axis に NHSN R-rate / empty rate / narrow rate gate 配線(下記 "Narrow / de-escalation (PR3b-3)" 節参照)。
  - PR3b-4: `extensions["antibiotic"][i].start_datetime` を WBC/CRP forward-delta decay の起点として使用

## Narrow / de-escalation (PR3b-3、2026-06-27)

**目的**: PR3b-2 culture S/I/R 結果に応じて empirical → narrow に de-escalation(IDSA antimicrobial stewardship core concept)。

**Pass 2 trigger**: `MicrobiologyResult.reported_datetime`(= HAI onset + 2d、`modules/hai/enricher.py` で hardcoded)。AD-32: `snapshot < reported_datetime` なら narrow skip(empirical 継続)。

**ladder schema** (`reference_data/narrow_ladder.yaml`):
- per-(hai_type, organism_snomed) 三段ネスト、narrow → broad で書く
- import 時 3-way cross-validation: `HAI_TYPES` + `hai_antibiogram.yaml` + `ANTIBIOTIC_DRUGS`(silent-no-op 防御 3 層目)
- walk algo: `interpretation == "S"` のみ accept、I/R/missing は次候補へ skip

**3 outcomes(narrowing by elimination)**:
| Case | Example | Action |
|---|---|---|
| **(i) switch** | CLABSI/MSSA(cefazolin S, empirical={vanc + pip-tazo}) | 全 empirical を discontinue(`discontinuation_datetime = reported`)+ 新 `AntibioticRegimen(intent="narrowed")` + Order + MAR 追加 |
| **(ii) elimination** | CLABSI/MRSA(cefazolin R, vanc S) | 該当 empirical(vanc)は継続、他(pip-tazo)を discontinue。新 regimen 追加なし |
| **(iii) no change** | CAUTI/E.coli/ESBL-(ceftriaxone S, single empirical) | 何も変更しない |

**FHIR**: `MedicationRequest.status` を `OrderStatus` から map(`_map_order_status_to_fhir`):
- `stopped` → FHIR `"stopped"`(PR3b-3 で discontinue した empirical)
- `cancelled` → FHIR `"cancelled"`
- else → FHIR `"active"`(narrow regimen を含む)

**audit gates**(`clinosim/audit/axes/clinical.py:run()` 3 ブロック):
1. **NHSN R-rate** per (hai_type, antibiotic) cohort — `_NHSN_RESISTANCE_BANDS` 配線、MRSA / ESBL+ / etc. の population-level R-rate を NHSN AR 2018-2020 band で gate
2. **empty susceptibility rate** per HAI cohort — `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` 配線、panel-eligible cultures(E.faecalis / C.albicans 除外)で empty rate ≤ 5%
3. **narrow rate** per (hai_type, organism) cohort — 新 `_NARROW_RATE_BANDS`、narrow が発火した event 比率を band で gate(MSSA CLABSI 40-60% / E.coli CAUTI 10-30% / etc.)

各 gate は `n < 30` で WARN、それ以外で PASS/FAIL、per-cohort observed 値を `result.info` に記録(DQR visibility)。

**lift_firing_proof PR3b-3 拡張** (`audit.py:_pr3b3_narrow_proof_checks`): synthetic CLABSI/MSSA case を `enrich_antibiotic` に流し、narrow target = cefazolin / 両 empirical discontinuation_datetime / 1 新 narrowed regimen / drug_key / intent の 6 equality_checks を verify。combined proof で計 17 checks(8 PR3b-1 + 3 PR3b-2 + 6 PR3b-3)。

**Determinism (AD-16)**: 新 RNG 追加なし。`select_narrow_target` は pure function(susceptibility は既に hai enricher の sub-seed で決定済)。enricher cascade order(70 → 80 → 85)不変。byte-diff invariant は意図的に破壊(新 narrow Order/MAR 追加 + empirical MAR truncation + FHIR status 変化、新機能 PR で audit run が primary gate)。

## Public API

- `clinosim.modules.antibiotic.ANTIBIOTIC_DRUGS: dict[str, dict[str, str]]` — canonical drug metadata dict; key = lowercase snake_case drug key (e.g. `"vancomycin"`), value = `{"name": str, "rxnorm": str, "yj": str}`. Phase 3b-2 refactor: tuple → dict (byte-identity preserved; FHIR emission unchanged).
- `clinosim.modules.antibiotic.ANTIBIOTIC_LOINC_LOOKUP: dict[str, str]` — antibiotic_key → susceptibility LOINC code, loaded from `observation/reference_data/microbiology.yaml` at import time. Used by `load_hai_antibiogram()` cross-validation + `_append_hai_culture()` for Observation code. Example: `{"vancomycin": "18991-2", "cefepime": "18879-7", ...}`.
- `clinosim.modules.antibiotic.engine.load_hai_empirical()` — YAML loader + import-time validation
- `clinosim.modules.antibiotic.engine.build_regimens(hai_event, start_datetime)` — HAIEvent → `list[AntibioticRegimen]`
- `clinosim.modules.antibiotic.engine.generate_mar_doses(regimen, snapshot_datetime, order_id)` — regimen → `list[MedicationAdministration]`(snapshot truncation 適用)
- `clinosim.modules.antibiotic.enricher.enrich_antibiotic(ctx)` — POST_ENCOUNTER entry point

## データ構造

`AntibioticRegimen`(`clinosim/types/antibiotic.py`):

```python
@dataclass
class AntibioticRegimen:
    regimen_id: str
    hai_event_id: str              # ← cross-module 連結ポイント
    encounter_id: str
    drug_key: str                  # canonical(ANTIBIOTIC_DRUGS key)
    dose: str
    route: str
    frequency: str                 # q24h / q12h / q6h
    start_datetime: datetime       # HAI onset_date の 08:00
    duration_days: int             # IDSA: CLABSI/VAP=14, CAUTI=7
    intent: str                    # "empirical"(PR3b-3 で "narrowed" を追加)
    discontinuation_datetime: datetime | None = None  # ← PR3b-3 forward-compat reserve
```

`extensions["antibiotic"] = list[AntibioticRegimen]` で保持。

**`discontinuation_datetime` forward-compat reserve (Phase 3b-2)**: PR3b-3 (narrow / de-escalation chain) が empirical → narrowed de-escalation を materialize する際に set する予定。PR3b-1/3b-2 では常に `None`。PR3b-3 が `intent == "empirical"` を読んで de-escalation 候補を選定し、`discontinuation_datetime` + 後継 `intent="narrowed"` regimen を emit する。

## Reference data

- `reference_data/hai_empirical.yaml` — IDSA guideline ベース、HAI type × drugs × dose/route/freq/duration
- 出典は YAML 内コメントに明記(IDSA 2009 CLABSI / IDSA 2009 CAUTI / IDSA-ATS 2016 VAP)
- impl 時に NLM RxNav(Vancomycin RxCUI 11124、tty=IN 認証)+ MEDIS-DC HOT/YJ master(YJ 6113400 既存 sepsis.yaml 整合)で照合済

## Determinism(AD-16)

- per-patient sub-rng: `derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["antibiotic"]=0x4142, patient_id)`
- PR3b-1 は確率的サンプリングを行わない(全 HAI に同じ empirical レジメン適用)→ sub-rng は将来用に予約(`engine.py` 内で `np.random.Generator` import せず)
- main RNG 不動 = 既存 golden file は影響なし(HAI 不在のとき完全 no-op)

## ForcedScenario testing infrastructure

PR3b-1 Task 7b で `ForcedScenario.force_hai_event: dict | None = None` を新設。形式:

```python
ForcedScenario(
    disease_id="sepsis",
    count=20,
    severity="severe",
    archetype="treatment_resistant",
    force_hai_event={
        "hai_type": "cauti",
        "onset_offset_days": 3,
        "organism_snomed": "112283007",
    },
)
```

`enrich_hai` が `ForcedScenario.force_hai_event` を読み取り、Poisson per-line-day sampling を bypass。`hai_type` がマッチする device(`indwelling_catheter` → cauti 等)に対し決定論的に HAI event を生成。PR-B baseline test の `pytest.skip` を retroactive に解消するための基盤(device placement は依然 stochastic、ICU transfer 条件依存)。

## Audit(AD-60)

- 同 PR で `audit.py` を新規追加(本格運用 2 例目、`hai` に続く)
- `canonical_constants`: `HAI_TYPES` + `ANTIBIOTIC_DRUGS`(tuple → dict refactor 後も同一 canonical_constants チェック)
- `yaml_keys_to_validate`: `hai_empirical.yaml` の `hai_empirical` キー
- `clinical_acceptance`: per-HAI-type expected drugs + duration + min_mar_per_event
  - CLABSI: T80.211A、Vanc + Pip-Tazo × 14d、min MAR=84
  - CAUTI: T83.511A、Ceftriaxone × 7d、min MAR=7
  - VAP: J95.851、Vanc + Pip-Tazo × 7d、min MAR=42
- `lift_firing_proof`: 合成 CAUTI record を `enrich_antibiotic` で drive、closed-form delta(Ceftriaxone q24h × 7d = 7 MAR、first/last datetime 厳密一致)= PR-90 class silent no-op gate

**Phase 3b-2 拡張 (`audit.py`)**:
- `_ABX_LOINCS: frozenset[str]` — PR3b-3 までは未配線の deferred placeholder。audit.py 内でコメント参照のみ；structural_obs_codes には未登録（categorical S/I/R Observation は numeric structural check 非対象、判断は audit.py の design docstring 参照）。
- `_NHSN_RESISTANCE_BANDS: list[dict]` — CDC NHSN AR 2018-2020 推奨バンド (CLABSI MRSA 40-55%、CAUTI ESBL 12-22%、VAP MRSA 30-45%)。PR3b-3 で clinical axis に組み込み予定 (TODO comment in audit.py)。
- `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE: float = 0.05` — susceptibilities が空の MicrobiologyResult の比率上限。PR3b-3 clinical axis で enforcement 予定。
- `antibiogram_firing_proof`: PR-94 `equality_checks` 形式の closed-form proof。合成 CLABSI S. aureus record を `_append_hai_culture` に drive、Vancomycin susceptibility = S (`[1.00, 0.00, 0.00]`) を `ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]` (非 hardcode) で参照して厳密一致確認。

## Test

- `tests/unit/test_antibiotic_types.py`
- `tests/unit/test_antibiotic_yaml_loader.py`
- `tests/unit/test_antibiotic_engine.py`
- `tests/unit/test_antibiotic_enricher_unit.py`
- `tests/unit/test_antibiotic_code_lookup.py`
- `tests/unit/test_enricher_seed_offsets.py`(antibiotic 追加 case を extend)
- `tests/unit/test_forced_scenario_hai.py`(Task 7b、force_hai_event 機構)
- `tests/integration/test_antibiotic_forced_e2e.py`(forced scenario via run_forced)
- `tests/integration/test_antibiotic_audit.py`(AD-60 plug-in)

## 主要ファイル一覧

```
clinosim/modules/antibiotic/
  __init__.py             # ANTIBIOTIC_DRUGS (dict[str, dict[str, str]]) + ANTIBIOTIC_LOINC_LOOKUP
  engine.py               # load_hai_empirical / build_regimens / generate_mar_doses
  enricher.py             # enrich_antibiotic (POST_ENCOUNTER, order=85, always-on)
  audit.py                # AD-60 plug-in (PR3b-2 拡張: _ABX_LOINCS / _NHSN_RESISTANCE_BANDS /
                          #   HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE / antibiogram_firing_proof)
  reference_data/
    hai_empirical.yaml    # IDSA 2009/2016 guideline
  README.md               # 本ファイル
```
