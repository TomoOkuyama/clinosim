# health_checkup — JP-eCheckup 事業者健診 opt-in module

## 概要 / 役割

日本の労働安全衛生法に基づく **事業者健診** (annual employer-provided
health checkup) を JP コホートに追加する opt-in POST_RECORDS enricher。

40 歳以上の成人患者から決定的 30% サブセット
(SHA-256 hash on `patient_id`、`HEALTH_CHECKUP_SUBSET_RATE` で調整可)
を選定し、simulation snapshot 手前の日付に 1 年 1 回の CHECKUP encounter
+ 法定健診項目 5 種 (BMI / 収縮期 BP / 拡張期 BP / HbA1c / LDL コレステロール)
+ HEALTH_CHECKUP_REPORT の ClinicalDocument stub (narrative=None) を追加する。

## 設計原則

| Principle | Source |
|---|---|
| opt-in (default OFF) — 急性期病院想定を保つ | `SimulatorConfig.modules["health_checkup"]` gate |
| JP-only | country=="JP" gate |
| AD-16 deterministic — new RNG 追加なし、hash-based 選定 | DESIGN.md AD-16 |
| AD-55 Base 拡張 (Module registered as POST_RECORDS enricher) | DESIGN.md AD-55 / AD-56 |
| Stage 1 emits stub, Stage 2 populates narrative | DESIGN.md AD-65 (two-pass CIF generation) |

## ディレクトリ構造

```
clinosim/modules/health_checkup/
  __init__.py            # public API: enrich_health_checkup, HEALTH_CHECKUP_SUBSET_RATE
  engine.py              # POST_RECORDS enricher body
  README.md              # this file
```

reference_data/ は現状なし(日本語 5 種の LOINC / JLAC10 codes は
`clinosim/codes/data/*.yaml` の canonical set を lookup で使用)。

## Public API

`__init__.py` に export される 2 symbols:

- `enrich_health_checkup(records, config, rng)` — enricher entry point
  (POST_RECORDS stage で `clinosim.simulator.enrichers.register_builtin_enrichers`
  経由で dispatch される)。
- `HEALTH_CHECKUP_SUBSET_RATE: float = 0.30` — subset selection rate。
  試験や calibration で調整可能。

## Dependencies

- `clinosim/types/` (`PatientRecord`, `EncounterRecord`, `ClinicalDocument`,
  `ObservationRecord`)
- `clinosim/codes/` (LOINC / JLAC10 lookups for the 5 lab items)
- `clinosim/simulator/enrichers.py` (Enricher registry)
- `numpy` (`np.random.Generator`; only used for deterministic-shape API,
  actual randomness comes from patient_id hash)

## FHIR emit path

Stage 1 が emit した `ClinicalDocument(document_type="HEALTH_CHECKUP_REPORT")`
stub は Stage 2 の `TemplateNarrativePass` が populate、`_fhir_composition.py`
の JP-eCheckup builder が Composition.section の `text.div` を埋める。

## Opt-in の使い方

```python
from clinosim.simulator.engine import run_beta
from clinosim.simulator.config import SimulatorConfig

config = SimulatorConfig(
    country="JP",
    modules={"health_checkup": True},   # opt-in
    ...,
)
run_beta(config, ...)
```

## Test

- `tests/unit/modules/health_checkup/` — enricher-level determinism / subset
  selection / observation emission tests
- `tests/integration/test_jp_echeckup_composition.py` — JP-eCheckup FHIR
  Composition end-to-end

## Related

- 追加履歴: session 47 P2-13 PR3 sub-PR-A
- 関連 FHIR builder: `clinosim/modules/output/_fhir_composition.py` (JP-eCheckup)
