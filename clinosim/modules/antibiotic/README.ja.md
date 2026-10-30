# `clinosim.modules.antibiotic` — HAI empirical + narrow 抗菌薬 regimen

## 概要

always-on の HAI cascade 3 番目 ([`device`](../device/README.ja.md) →
[`hai`](../hai/README.ja.md) → 本モジュール → observation microbiology
emitter)。`extensions["hai"]` を消費し、snapshot 手前の onset を持つ
HAI event 各々について IDSA 2009 / 2016 empirical regimen と
(PR3b-3 Pass 2) S/I/R 駆動 narrow / de-escalation regimen を
materialize する。生成される regimen は既存の `fhir_r4/medications/medications.py`
builder が emit する `Order(MEDICATION)` 1 件 + `MedicationAdministration`
N 件になるため、新 builder は不要。

## Scope

- **In scope**: `ANTIBIOTIC_DRUGS` canonical drug-key dict (抗菌薬名の
  単一情報源 — YAML loader は drug_key 文字列を import 時に検証)、
  `load_hai_empirical` + `load_narrow_ladder` (共に per-validator
  6-layer 防御を持つ YAML loader)、`build_regimens` + `generate_mar_doses`、
  `_drug_slug` + `_check_fhir_id_length` (FHIR id 長 guard —
  `id` cardinality 制限厳守の Issue 追跡契約)、POST_ENCOUNTER
  `enrich_antibiotic` enricher (S/I/R 駆動 narrowing の same-enricher
  Pass 2 — `NarrowOutcome` enum + `select_narrow_target` +
  `narrow_outcome` + `narrow_duration_days`)、AD-32 future-onset skip
  (POST_ENCOUNTER 後に truncate される HAI event を pre-skip して
  orphan Order/MAR を防止)。
- **In scope (audit)**: [`audit.py`](audit.py) — 2 番目の per-module
  AD-60 audit plug-in。lift_firing_proof は合成 CAUTI HAIEvent に対して
  `enrich_antibiotic` を実行 (期待: regimen 1 件、`drug_key="ceftriaxone"`、
  `duration_days=7`、MEDICATION Order 1 件、MAR 7 件)。
  PR3b-2 拡張で `antibiogram_firing_proof` を追加 (合成 CLABSI +
  S. aureus HAIEvent → 6 susceptibility 行、vancomycin always-S
  sentinel、cefazolin non-degenerate probe)。PR3b-3 で narrow proof
  (合成 CLABSI MSSA → cefazolin へ SWITCH) を追加。import 時 validator
  は narrow-rate band と NHSN resistance band も検証。
- **Out of scope**: HAI event サンプリング
  ([`hai`](../hai/README.ja.md))、microbiology culture emission
  ([`observation.microbiology`](../observation/microbiology.py))、
  FHIR MedicationRequest / MedicationAdministration serialization
  ([`output/fhir_r4/medications/`](../output/fhir_r4/medications/README.ja.md))、
  narrow-target 用量 / 頻度 default — これは
  [`_narrow_dose_defaults.py`](_narrow_dose_defaults.py) が所有。

## Public API

```python
from clinosim.modules.antibiotic import (
    ANTIBIOTIC_DRUGS,                    # canonical {drug_key: {"name": display}}
    ANTIBIOTIC_LOINC_LOOKUP,             # observation.microbiology から再 export
)
from clinosim.modules.antibiotic.engine import (
    FREQ_PER_DAY,                        # dose 頻度 → doses/day 表
    load_hai_empirical,                  # () -> dict[hai_type, regimen] (@lru_cache)
    load_narrow_ladder,                  # () -> dict[hai_type, {organism_snomed: [drug_key, ...]}] (@lru_cache)
    build_regimens,                      # (hai_event, start_datetime) -> list[AntibioticRegimen]
    generate_mar_doses,                  # (regimen, snapshot_datetime, order_id, encounter_end_datetime=None)
                                         #   -> list[MedicationAdministration]
    NarrowOutcome,                       # Enum {SWITCH, ELIMINATION, NO_CHANGE}
    select_narrow_target,                # (susceptibilities, ladder_for_organism) -> drug_key | None
    narrow_outcome,                      # (narrow_target, empirical_regimens) -> NarrowOutcome
    narrow_duration_days,                # (empirical_start, reported, total_course) -> int
)
from clinosim.modules.antibiotic.enricher import enrich_antibiotic  # POST_ENCOUNTER entry
```

## 決定論

- サブ seed オフセット `0x4142` (`"AB"`, PR3b-1) は
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["antibiotic"]` として予約済みだが、enricher は
  乱数を引かない。regimen・MAR schedule・narrowing はすべて HAI event、
  `hai_empirical.yaml`、microbiology 結果の決定論的関数。
- PR3b-3 narrowing は **新 RNG 追加なし** —
  `select_narrow_target` は microbiology 層で既に確定した susceptibility
  に対して pure。
- AD-32 future-onset skip: snapshot より後の onset を持つ HAI event は
  pre-skip され、POST_ENCOUNTER 後の HAI 切り詰めで orphan order を
  生成しない。
- MAR は snapshot と encounter の `discharge_datetime` の早い方で打ち
  切る (Issue #1312)。empirical order は onset 日 08:00、narrowed
  regimen は culture の `reported_datetime` 開始 (snapshot より後なら
  skip)。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`、`set_attr_or_key`、
  `get_or_create_container`、`sanitize_id_token`。
- `clinosim.modules.hai` — `HAI_TYPES`、`load_hai_antibiogram`
  (narrow ladder 検証)。
- `clinosim.modules.order.engine` — `parse_dose_string`。
- `clinosim.modules.observation.microbiology` —
  `antibiotic_loinc_lookup` (`ANTIBIOTIC_LOINC_LOOKUP` として再 export)。
- `clinosim.modules.antibiotic._narrow_dose_defaults` — 薬剤別
  narrow-target 用量 + 頻度 default。
- `clinosim.audit.registry` (`audit.py` 経由) — AD-60 audit 登録。
- `clinosim.types.antibiotic` — `AntibioticRegimen`。
- `clinosim.types.encounter` — `MedicationAdministration`, `Order`,
  `OrderType`, `OrderStatus`。
- `clinosim.types.hai` — `HAIEvent`、`clinosim.types.microbiology` —
  `SusceptibilityResult`。
- `yaml`。

## 定数と設定

- **`ANTIBIOTIC_DRUGS`** (`__init__.py`) — canonical drug-key dict。
  key は lowercase snake_case (`vancomycin`, `piperacillin_tazobactam`,
  `ceftriaxone`, `ampicillin`, `cefazolin`, `gentamicin`,
  `meropenem`, `ciprofloxacin`, `trimethoprim_sulfamethoxazole`,
  `cefepime` …) で microbiology antibiotics 節 +
  `ANTIBIOTIC_LOINC_LOOKUP` と一致。YAML loader は全 `drug_key`
  文字列を import 時に本 dict と cross-validate する (PR-90 教訓)。
- **`FREQ_PER_DAY`** (`engine.py`) — dose 頻度文字列 → doses/day
  (`"q24h" → 1`, `"q12h" → 2`, `"q8h" → 3`, `"q6h" → 4`,
  `"q4h" → 6`)。
  `generate_mar_doses` が消費する。
- **Reference YAML**:
  - [`reference_data/hai_empirical.yaml`](reference_data/hai_empirical.yaml)
    — HAI type 別 IDSA 2009/2016 empirical regimen。`load_hai_empirical`
    が hai_type key を `HAI_TYPES` と双方向に、全 drug_key を
    `ANTIBIOTIC_DRUGS` に対して検証。
  - [`reference_data/narrow_ladder.yaml`](reference_data/narrow_ladder.yaml)
    — per (HAI type, organism SNOMED) narrow target ladder。loader
    `_validate_narrow_ladder` が `HAI_TYPES` + `hai_antibiogram.yaml`
    + `ANTIBIOTIC_DRUGS` と cross-validate し、antibiogram の全
    (HAI type, organism) に ladder entry があることも要求
    (reverse coverage)。
- **Narrow-target 用量 default** ([`_narrow_dose_defaults.py`](_narrow_dose_defaults.py)、
  Issue #637) — enricher の `_narrow_dose_frequency` が返す薬剤別
  (dose_string, frequency) pair。
- **FHIR ID prefix** (`engine.py`) — `ABX_REGIMEN_ID_PREFIX`,
  `ABX_ORDER_REQ_PREFIX`, `ABX_ORDER_ID_PREFIX` (`ABX_NARROW_SUFFIX`
  は定義が残るが付与されなくなった — narrowed regimen は
  `abx-{hai_id}-{slug}` で、intent は `medication_intent="narrowed"`
  で表す)。
  `_check_fhir_id_length` が全 emission site で FHIR `id`
  cardinality を強制 (Issue 追跡。`_DRUG_SLUG_OVERRIDES` は長さ
  budget 超過を引き起こす薬剤名を扱う)。
- **`AntibioticRegimen.discontinuation_datetime`** — PR3b-3 narrowing
  が populate する forward-compat slot (`intent="narrowed"` regimen が
  置換された empirical entry の `discontinuation_datetime =
  reported_datetime` を設定し、以降の MAR を切り詰め、対応する
  `Order.status = OrderStatus.STOPPED` にする。medications builder は
  それを `MedicationRequest.status="stopped"` として emit)。

## ディレクトリ構造

```
clinosim/modules/antibiotic/
  __init__.py                        ANTIBIOTIC_DRUGS + ANTIBIOTIC_LOINC_LOOKUP を再 export
  engine.py                          build_regimens + generate_mar_doses + narrow_* helper + loader + validator
  enricher.py                        POST_ENCOUNTER enrich_antibiotic (Pass 1 empirical + Pass 2 narrowing)
  audit.py                           AD-60 audit plug-in (2 番目の per-Module) — lift_firing_proof (empirical + antibiogram + narrow)
  _narrow_dose_defaults.py           narrow-target 用量 + 頻度 default (Issue #637)
  reference_data/
    hai_empirical.yaml               HAI type 別 IDSA empirical regimen
    narrow_ladder.yaml               per (HAI type × organism) narrow ladder
```

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
で登録:

- `name="antibiotic"`, `stage=POST_ENCOUNTER`, `order=85`,
  `enabled=lambda c: True`。`hai` (order=80) の後に走り
  `extensions["hai"]` が populate 済みの状態で発火。
- `audit.py` module は import 時に AD-60 audit framework に登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) | POST_ENCOUNTER order=85 登録。 |
| Audit registry | [`clinosim/modules/antibiotic/audit.py`](audit.py) | AD-60 audit plug-in。 |
| HAI module | [`clinosim/modules/hai/enricher.py`](../hai/enricher.py)、[`clinosim/modules/hai/__init__.py`](../hai/__init__.py) | `ANTIBIOTIC_LOINC_LOOKUP` を cross-import。 |
| Clinical audit axis | [`clinosim/audit/axes/clinical.py`](../../audit/axes/clinical.py) | narrow-rate gate 用に `ANTIBIOTIC_LOINC_LOOKUP` と `ABX_*` id prefix を import。 |
| FHIR medications builder | [`clinosim/modules/output/fhir_r4/medications/`](../output/fhir_r4/medications/README.ja.md) | 追加された `Order` + MAR record から `MedicationRequest` + `MedicationAdministration` を emit (discontinued empirical は `status="stopped"`)。 |

## テスト

```bash
pytest tests/unit -k antibiotic -q
pytest tests/integration -k "antibiotic" -q
clinosim audit run -d <cohort_dir> --module antibiotic
```

個別ファイル:

- [`tests/unit/test_antibiotic_code_lookup.py`](../../../tests/unit/test_antibiotic_code_lookup.py)
  — `ANTIBIOTIC_LOINC_LOOKUP` coverage。
- [`tests/unit/test_antibiotic_engine.py`](../../../tests/unit/test_antibiotic_engine.py)
  — `build_regimens` + narrow-selection helper。
- [`tests/unit/test_antibiotic_enricher_unit.py`](../../../tests/unit/test_antibiotic_enricher_unit.py)
  — enricher Pass 1 + Pass 2 unit。
- [`tests/unit/test_antibiotic_types.py`](../../../tests/unit/test_antibiotic_types.py),
  [`tests/unit/types/test_antibiotic_discontinuation.py`](../../../tests/unit/types/test_antibiotic_discontinuation.py)
  — dataclass shape (`discontinuation_datetime` slot 含む)。
- [`tests/unit/test_antibiotic_id_length.py`](../../../tests/unit/test_antibiotic_id_length.py)
  — `_check_fhir_id_length` guard。
- [`tests/unit/test_antibiotic_yaml_loader.py`](../../../tests/unit/test_antibiotic_yaml_loader.py)
  — 6-layer loader validator。
- [`tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py`](../../../tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py)
  — LOINC lookup の単一情報源化。
- [`tests/integration/test_antibiotic_forced_e2e.py`](../../../tests/integration/test_antibiotic_forced_e2e.py),
  [`test_antibiotic_audit.py`](../../../tests/integration/test_antibiotic_audit.py)
  — end-to-end + AD-60 audit run。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
