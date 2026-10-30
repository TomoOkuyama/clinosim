# `clinosim.modules.immunization` — ワクチン接種歴合成

## 概要

国別 (CVX ベース) の接種スケジュール (最低年齢、プログラム開始日、頻度、
月、EHR 保持期間、年齢 × 性別 coverage) を元に、患者ごとの接種歴 (成人
スケジュール、小児定期 series、US では妊娠時の母体 Tdap) を生成し
`CIFPatientRecord.immunizations` に格納、可能なら各接種を encounter に
紐付ける AD-55 Base (always-on) モジュール。下流の FHIR + CSV adapter が `Immunization`
リソースと `immunizations.csv` を出力する。実 EHR 挙動に合わせ、
一部のスケジュール接種は明示的な拒否 (`status="not-done"`) として記録される。

## Scope

- **In scope**: schedule エントリごとの `annual` / `every_n_years` /
  `once` / `pediatric_series` サンプリング、年齢 × 性別 coverage lookup
  (小児 series は dose 単位の `coverage_by_sex`)、接種日配置 (annual →
  `seasonal_distribution` から月を抽選、無ければ固定 `season_month`、
  every_n_years → `interval_years` step、once → `wave_epochs` があれば
  epoch/月を抽選、無ければ資格期間内で uniform、pediatric_series →
  dose ごとの `[age_days_min, age_days_max]` 窓を標準 well-child 受診
  月齢に snap、1 回欠けた series は以降打ち切り)、US 母体 Tdap (CVX 115、
  中絶以外の各妊娠の 27–36 週、coverage 0.78)、
  `IMMUNIZATION_NOT_DONE_RECORDING_RATE` レートでの拒否記録、既存
  encounter への紐付けと window 内 orphan への付随接種 encounter 合成
  (「Encounter 紐付け」節参照)、合成 lot number 生成 (構造 placeholder、
  正式 batch ではない)、閏日 (Feb 29) 生まれの非閏年 Feb 28 clamp、
  任意 `history_years` の EHR 保持期間 (flu → 10 y 等)。
- **Out of scope**: 小児接種歴の遡及モデリング、副反応 / 副作用生成、
  simulator の encounter loop での接種受診スケジューリング (接種
  encounter は enricher が事後合成するのみ)、
  FHIR / CSV serialization ([`clinosim.modules.output`](../output/README.ja.md))、
  CVX の表示テキスト
  ([`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml))。

## Public API

`__init__.py` は空。呼び出し側は engine + enricher から直接 import:

```python
from clinosim.modules.immunization.engine import (
    generate_immunizations,          # (patient, schedule, as_of, rng, nurse_ids=None)
                                     #   -> list[ImmunizationRecord] (接種日昇順)
    generate_pregnancy_tdap,         # (patient, as_of, rng, country, default_nurse="")
                                     #   -> list[ImmunizationRecord] (US のみ)
    load_schedule,                   # (country) -> {vaccine_name: {cvx, min_age, frequency, ...}}
    IMMUNIZATION_NOT_DONE_RECORDING_RATE,  # 0.02
)
from clinosim.modules.immunization.enricher import enrich_immunizations
```

`load_schedule` は unsupported country に対して `{}` を返す
(2026-07-02 grand-design 契約)。enricher は空 map で no-op。

## 決定論

- サブ seed オフセット `0x494D` (`"IM"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["immunization"]` に登録済み。
- 患者単位 RNG:
  `derive_sub_seed(master_seed, offset, patient_id)`。患者主 RNG 列は
  消費しない。`generate_pregnancy_tdap` は schedule pass 後の同じ患者
  単位 generator から draw する。
- 小児 dose は well-child anchor 月齢 + 決定論的 0..+6 日 scatter
  (`_det_hash(pid, anchor) % 7`) に snap。dose ごとの rng offset は
  cursor 維持のため draw した上で捨てる。
- 付随接種 encounter の id は
  `ENC-VAX-{patient_id}-{sha256(patient|date|synth-vax)[:12]}`。
  (患者, 日付) で key するため同日の接種は 1 encounter に集約される。
- **Lot number は SHA-256 で決定論化 (Python builtin `hash()` は使わない)**。
  Python 標準の文字列ハッシュは interpreter 起動ごとに salt される
  (`PYTHONHASHSEED`) ため、同一 seed でも lot number が run 間で変わる
  drift があった。P1-7 が `reproduce.sh` の determinism gate で検出、
  `engine.py` の `_det_hash` が現在 lot number 生成を担当。
- 担当看護師 (`administered_by`) の割り当ては
  `nurse_ids[sum(ord(c) for c in patient_id) % len(nurse_ids)]` で
  決定論的に選出 (RM-3、実 JP practice に整合)。

## 累積記録レート vs シーズン単位レート

schedule YAML の `coverage_by_age_sex` は **1 回スケジュール分の接種確率**
を保持している。annual (flu) の場合は **per-season 接種率** (MHLW 接種率統計
/ CDC FluVaxView と一致)、`once` の場合は「これまでに接種済み」の生涯到達率。

**集計 audit 値を誤読しないこと。** `history_years=10` により annual flu の
10 年分が保持されるため、65+ 患者が flu の Immunization を ≥1 件持つ確率は
per-season 0.55 でも ≈1.0 に達する。COVID と PPSV23 の once 抽選と合わせて、
「65+ 患者のうち ≥1 Immunization 記録を持つ割合」の集計値は 100% に近づく。
これは正しい EHR 挙動 — 病院通院中の高齢患者は複数年の接種歴を carrying して
いるのが実態。

その集計値を per-season 統計 (MHLW インフルエンザ 65+ ~53% 等) と比較する
のは apples-to-oranges 誤り。正しい audit は per-vaccine, per-scheduled-dose
レートを比較する:

```python
# annual: 総接種数 / (対象患者数 × history_years)
# once:   接種済患者数 / 対象患者数
```

audit script
[`scripts/audit_realworld_stats_jp.py`](../../../scripts/audit_realworld_stats_jp.py)
はこの正しい metric を用いる。

## Snapshot (AD-32)

`as_of = ctx.config.snapshot_date` があればその日、なければレコード内
最終 encounter の入院日 (どちらも無ければ `ValueError`)。いずれも患者の
`date_of_death` で上限を切る。`occurrence_date > as_of` は skip し、
in-progress snapshot でのバックデート出力を防ぐ。

## Encounter 紐付け

`enrich_immunizations` は患者の全レコードから encounter を集約し、
`_align_to_encounters` (決定論、rng なし) で:

1. 入院期間内の接種日はその入院に紐付け、日付は維持 (新生児室での
   B 型肝炎出生時接種など)。
2. それ以外は ±60 日以内で最も近い外来 encounter に snap し
   `encounter_id` を記録。

紐付かず simulation window 開始 (`config.time_range[0]`) より前の接種は
`primary_source=False` とし未紐付けのまま残す。window 内の orphan には
外来 `ENC-VAX-*` encounter (department `primary_care`、入院時診断 `Z23`、
attending は primary-care 医師 roster から決定論選出) を合成し、患者
あたり 1 回だけ host する。`ENC-VAX-*` が存在すれば
`document.engine.document_enricher` を再実行して文書 stub を付与する。

## 依存

- `clinosim.modules._shared` — `is_us` / `is_jp`,
  `get_attr_or_key` / `set_attr_or_key`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.encounter` — `ImmunizationRecord` (engine 関数内で
  遅延 import)、付随 encounter 用の `Encounter` / `EncounterStatus` /
  `EncounterType`。
- `clinosim.codes` (間接、FHIR builder 経由) — CVX 表示 lookup。
- `numpy` — coverage サンプリングの `np.random.Generator`。
- `hashlib.sha256` — `_det_hash` 経由、lot number 決定論化。

他 module への依存は、付随 encounter の文書生成用に
`clinosim.modules.document.engine.document_enricher` を遅延 import する
のみ。

## 定数と設定

- module レベル定数 (`engine.py`):
  - `IMMUNIZATION_NOT_DONE_RECORDING_RATE = 0.02` — coverage draw
    失敗時に `status="not-done"` を明示記録する per-scheduled-dose
    確率。silent no-show と区別された、記録された拒否 / 延期を表す。
    `annual` / `every_n_years` / `pediatric_series` ブランチと母体
    Tdap に適用。`once` ブランチは `not-done` を出さない。
- Locale schedule (本 module に `reference_data/` は無い):
  - [`clinosim/locale/us/immunization_schedule.yaml`](../../locale/us/immunization_schedule.yaml)
    — CDC ACIP schedule。現状 18 エントリ: 成人 5 (Influenza,
    COVID-19 mRNA, PPSV23, Tdap, RZV Shingrix) + 小児 13
    (`pediatric_series` 12 + 小児インフルエンザ annual)。
  - [`clinosim/locale/jp/immunization_schedule.yaml`](../../locale/jp/immunization_schedule.yaml)
    — MHLW 定期接種 schedule。現状 13 エントリ: 成人 3
    (Influenza, COVID-19 mRNA, PPSV23) + 小児 `pediatric_series` 10。
- Schedule エントリ shape:
  | キー | 意味 |
  | --- | --- |
  | `cvx` | CDC CVX コード (文字列)。 |
  | `min_age` | 接種資格の最低年齢。 |
  | `frequency` | `"annual"` / `"once"` / `"every_n_years"` / `"pediatric_series"`。 |
  | `interval_years` | `every_n_years` 時のみ。年間隔。 |
  | `season_month` | `annual` 時のみ。`seasonal_distribution` が無い場合の固定接種月 (既定 10)。 |
  | `seasonal_distribution` | `annual` 時のみ。シーズン内の月抽選用 `{month: weight}`。 |
  | `wave_epochs` | `once` 時のみ。`start` / `end` / `age_weight` / `monthly_curve` を持つ epoch 列。 |
  | `doses` | `pediatric_series` 時のみ。dose ごとに `age_days_min` / `age_days_max` / `dose_number` / `coverage_by_sex`。 |
  | `available_from` | プログラム開始日 (`YYYY-MM-DD`)。 |
  | `history_years` | 任意。EHR 保持期間 (flu → 10 y 等)。 |
  | `coverage_by_age_sex` | `{"age_band": {sex: rate}}` (0-1、小児 series 以外)。 |
  | `program_type` | 小児エントリ (`mandatory` / `elective`)。情報用で engine は読まない。 |
- CVX コード表:
  [`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)
  — 34 コード。
  FHIR system URI: `http://hl7.org/fhir/sid/cvx`。

## ディレクトリ構造

```
clinosim/modules/immunization/
  __init__.py                     空 (Public API 節参照)
  engine.py                       generate_immunizations + load_schedule + helpers
  enricher.py                     POST_RECORDS enrichment (患者単位サブ RNG)
```

**`reference_data/` ディレクトリと `audit.py` は存在しない** — 国別
データは `clinosim/locale/` 配下にあり、`ModuleAuditSpec` は登録して
いない。検証は下記 test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="immunization"`, `stage=POST_RECORDS`, `order=30`,
  `enabled=lambda c: True`。
- `nursing` (order 20) の後、`family_history` (order 40) の前に実行。
  POST_ENCOUNTER の `document` enricher 実行後に `ENC-VAX-*` encounter
  を追加するため、自身で `document_enricher` を再実行する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`L327` 付近, `L417` 付近) | `record["immunizations"]` から `immunizations.csv` を書き出し。 |
| FHIR `Immunization` builder | [`clinosim/modules/output/fhir_r4/procedures/immunization.py`](../output/fhir_r4/procedures/immunization.py) | 記録ごとに FHIR R4 `Immunization` を 1 件出力。id は structural key `{patient_id}-{index}` (identifier に保持) から導出した `imm-<12hex>`、`vaccineCode` = CVX + locale 表示、`occurrenceDateTime` = 接種日、`primarySource` は記録値 (window 前の接種は `false`)、`encounter` は `encounter_id` から (emit 時キーワード照合が fallback)、`not-done` は `statusReason` PATOBJ、`dose_number` を `protocolApplied[0].doseNumberPositiveInt` に、`administered_by` が非空なら `performer` に反映、`_synthetic_lot` を `lotNumber` に emit。 |
| Enricher registry | [`clinosim/simulator/enrichers.py:241`](../../simulator/enrichers.py) | POST_RECORDS 登録。 |

## テスト

```bash
pytest tests/unit -k immunization -q         # engine
pytest tests/integration -k immunization -q  # enricher + FHIR 出力
```

個別ファイル:

- [`tests/unit/test_immunization.py`](../../../tests/unit/test_immunization.py)
  — engine サンプリング / lot-number 決定論。
- [`tests/integration/test_immunization_enricher.py`](../../../tests/integration/test_immunization_enricher.py)
  — enricher 決定論 + 看護師 roster 割り当て。
- [`tests/integration/test_fhir_immunization.py`](../../../tests/integration/test_fhir_immunization.py)
  — `Immunization` 出力の end-to-end。
- [`tests/unit/modules/immunization/`](../../../tests/unit/modules/immunization/)
  — encounter 紐付け、付随接種 encounter、同日統合、文書 dispatch、
  well-child 集約、US 小児 schedule、妊娠 Tdap。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
