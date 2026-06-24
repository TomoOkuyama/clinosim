# device — ICU デバイス留置 (CVC / 膀胱留置カテーテル / 人工呼吸器)

> AD-55 Module: ICU 入室患者に対して中心静脈カテーテル・膀胱留置カテーテル・人工呼吸器の留置を generate し、FHIR Device + DeviceUseStatement として出力する opt-in 軽量モジュール。Phase 2 `modules/hai` が `extensions["device"]` を消費して CLABSI/CAUTI/VAP の発症判定に使う前提の cross-module dependency point を確立。

## 概要 / 役割

- post_records enricher として各 `CIFPatientRecord` を巡り、`record.icu_transferred == True` かつ inpatient encounter に対して 3 種の留置デバイスを `extensions["device"]` に書き込みます。
- 留置判定は `reference_data/devices.yaml` の `placement_criteria` を physiology state + altered_consciousness から導出した indication token と突き合わせるデータ駆動方式。
- 留置 / 抜去日は inpatient encounter の `admission_datetime` / `discharge_datetime` を採用 (Phase 1 simplification — CIF には ICU 専用 sub-period が未だ存在しないため)。
- main RNG stream は触らず、`ENRICHER_SEED_OFFSETS["device"] = 0x4445` から導出した patient-id-scoped sub-seed のみ消費。AD-16 / AD-56 完全準拠。

## 設計原則

| Principle | Source |
|---|---|
| AD-16 deterministic (per-patient sub-seed via `derive_sub_seed`) | DESIGN.md AD-16 |
| AD-55 Module opt-in (post_records enricher, `extensions` slot) | DESIGN.md AD-55 / AD-56 |
| AD-56 builder + enricher registry | DESIGN.md AD-56 |
| BNP-pattern surgical: physiology state 不変、formula-only | DESIGN.md AD-57 |
| sub-seed 16-bit hex ASCII convention (`0x4445` = "DE") | CLAUDE.md "AD-55 enricher patterns" |
| 新型を `clinosim/types/` に置く (engine 内に定義しない) | CLAUDE.md "All types defined in clinosim/types/" |

## ディレクトリ構造

```
clinosim/modules/device/
  __init__.py            # public API: load_devices_config, place_devices_for_encounter
  engine.py              # core pure functions (indication 評価 + 留置)
  enricher.py            # AD-56 post_records enricher (enrich_device)
  reference_data/
    devices.yaml         # SNOMED コード + placement_criteria
  README.md              # this file
```

## API Reference

```python
def load_devices_config() -> dict[str, Any]:
    """reference_data/devices.yaml を @lru_cache で読み込み返す。"""

def place_devices_for_encounter(
    record: CIFPatientRecord,
    encounter: Encounter,
    rng: np.random.Generator,
    devices_config: dict[str, Any],
) -> list[DeviceRecord]:
    """1 つの encounter に対する DeviceRecord list を返す。

    非 ICU 患者 / 非 inpatient encounter / 適応なしのときは [] を返す。
    """

def enrich_device(ctx) -> None:
    """post_records enricher entry point.

    ctx.records を巡り、`extensions["device"]` に list[DeviceRecord] を書く。
    1 件以上 device が生成されたときのみ extensions に key を立てる。
    """
```

## データ構造

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `DeviceRecord` | `clinosim/types/device.py` (`@dataclass`) | `device_id`, `encounter_id`, `device_type`, `snomed_code`, `placement_date`, `removal_date`, `placement_indication` | `CIFPatientRecord.extensions["device"]` 配下の dataclass list、FHIR Device + DeviceUseStatement の入力 |

CIF 上の location: `CIFPatientRecord.extensions["device"]: list[DeviceRecord]` (typed dataclass を extensions slot に格納する確立 pattern — code_status / care_level / family_history と同型)。

## Indication token (engine 内)

| Token | 由来 | 利用 |
|---|---|---|
| `severity_moderate_plus` | `record.icu_transferred AND encounter.encounter_type == INPATIENT` | CVC + indwelling catheter |
| `altered_consciousness` | `vital_signs[i].gcs_score < 13` (encounter scope walk) | indwelling catheter |
| `hypoxia` | `state.perfusion_status < 0.4` (SpO2 不在の Phase 1 proxy) | ventilator |
| `high_respiratory_demand` | `state.respiratory_fraction > 0.7` | ventilator |

留置判定は `reference_data/devices.yaml` の `placement_criteria` の `any:` 句を walk して met-set との交差をチェックする (`_indications_met`)。`all:` / `not:` 句は YAGNI で未実装。

## Dependencies

| Dependency | Why |
|---|---|
| `clinosim/types/device` | DeviceRecord |
| `clinosim/types/clinical` | PhysiologicalState |
| `clinosim/types/encounter` | Encounter, EncounterType, VitalSignRecord |
| `clinosim/types/output` | CIFPatientRecord |
| `clinosim/codes/` | (FHIR builder 経由) snomed-ct display lookup |
| `clinosim/simulator/seeding` | ENRICHER_SEED_OFFSETS, derive_sub_seed |
| `clinosim/modules/_shared` | get_attr_or_key (dict/dataclass dual access) |

## Consumers

| Caller | How it uses this module | Impact tier |
|---|---|---|
| `clinosim/simulator/enrichers.py` | `register_builtin_enrichers()` で `enrich_device` を post_records phase に登録 | core (build pipeline) |
| `clinosim/modules/output/_fhir_device.py` | `extensions["device"]` を読んで Device + DeviceUseStatement を emit | medium (FHIR output) |
| `tests/unit/test_device_engine.py` | engine unit tests (16) | guard |
| `tests/unit/test_device_enricher.py` | enricher unit tests (5) | guard |
| `tests/unit/test_device_snomed_coverage.py` | SNOMED コード照合 smoke (6 parametrize) | guard |
| `tests/integration/test_device_extension_persistence.py` | CIF JSON round-trip | guard |
| `tests/integration/test_device_fhir_output.py` | 小規模 ICU cohort FHIR 出力検証 | guard |

> Phase 2 で `clinosim/modules/hai/enricher.py` が `record.extensions["device"]` を消費し、device-line-days から CLABSI/CAUTI/VAP の発症を sample する予定。device は read-only 上流、hai は read-only downstream の cleanest cross-module dependency point。

## SNOMED CT 権威照合

すべての device SNOMED コードは `tx.fhir.org` の `$expand` text search を経由して SNOMED CT International 版で照合済 (PR-A Task 1):

| code | en (権威表示) | ja (clinosim 訳) |
|---|---|---|
| 52124006 | Central venous catheter | 中心静脈カテーテル |
| 23973005 | Indwelling urinary catheter | 膀胱留置カテーテル |
| 706172005 | Ventilator | 人工呼吸器 |

> Spec の暫定値 `467021000` (indwelling urinary catheter) は SNOMED CT International 版に **存在しなかった** ため、authoritative な `23973005` に置換。Spec の "Mechanical ventilator" 表記は SNOMED preferred term "Ventilator" 単独に補正。PR #80 の LOINC `2B010` fabrication 事案と同型予防。

## Phase 1 simplification (scope cap)

- **ICU sub-period 未表現**: CIF v0.2 に ICU sub-period が無いため、`placement_date` = inpatient `admission_datetime`、`removal_date` = `discharge_datetime` を採用。実 ICU line-days より若干長くなる傾向 (admission → ICU transfer の lag、step-down ward 期間)。Phase 2 HAI 発症率を実態に合わせ calibrate する設計余地。
- **末梢静脈ライン (peripheral IV) 不採用**: ほぼ全入院に存在しデータが膨らむ + HAI 無関係。Phase 5+ で必要時に追加。
- **Device sub-type 集約**: PICC / Foley / 圧支援モード等は generic SNOMED コードに集約。
- **LOS-mid evolution 未実装**: 入院日固定の留置、退院日固定の抜去。Phase 5+ で per-day check loop に拡張可能。
- **vasopressor / GCS<9 等の細条件**: Phase 2-3 で必要時拡張。

## 拡張ガイド

新規 device type を追加するときは:
1. `clinosim/codes/data/snomed-ct.yaml` に SNOMED コード追加 (tx.fhir.org `$expand` で照合必須)
2. `reference_data/devices.yaml` に `<type_name>: {snomed_code, snomed_display_en, snomed_display_ja, placement_criteria}` を追記
3. 必要なら `engine._evaluate_indications` に新 indication token を追加
4. 既存 unit test (`test_device_engine.py`) に新 type 用テストケース追加
5. 3-axis DQR cohort で追加 type の出現分布を audit

詳細は [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 参照。

## 関連

- [DESIGN.md](../../../DESIGN.md) AD-55 (Base vs Module) / AD-56 (enricher registry) / AD-57 (BNP-pattern surgical)
- [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) — モジュール作成 + PR 検証ガイド
- [MODULES.md](../../../MODULES.md) — 全 module 俯瞰
- 関連モジュール: `output/_fhir_device.py` (builder)、Phase 2 `modules/hai` (consumer)
- 関連 spec / plan:
  - `docs/superpowers/specs/2026-06-24-device-module-design.md`
  - `docs/superpowers/plans/2026-06-24-device-module-pra.md`
- DQR review: `docs/reviews/2026-06-24-device-module-data-quality-review.md`
