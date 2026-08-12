# clinosim.modules.pediatric (日本語)

年齢帯 (0-18) 起点の pediatric encounter 発生モジュール
(Issue [#760](https://github.com/TomoOkuyama/clinosim/issues/760) META)。
[#740](https://github.com/TomoOkuyama/clinosim/issues/740) で顕在化した
「emitted cohort の under-20 患者比率 5% (US baseline) は demographics 通りではなく
"encounter に到達した人" の内訳」ギャップを埋める。

Population sampler の age band 重みは US Census 2020 と一致で正しい
(`demographics.yaml age_distribution` は無変更)。修正は
**encounter-emission layer** — pediatric 用の encounter type
(well-child / immunization / pediatric acute / adolescent behavioural)
を追加する。

## Foundation (pass 1、このファイルで出荷される状態)

- モジュール骨格 + YAML loader + `clinosim/modules/population/engine.py`
  ::`generate_healthcare_calendar` への integration point。
- **Byte-diff 中立**: `reference_data/pediatric_schedule.yaml` に
  encounter type が登録されていない状態ではイベント発生ゼロ、cohort 出力は
  モジュール導入前と bit-identical。

## Follow-up passes

META [#760](https://github.com/TomoOkuyama/clinosim/issues/760) 準拠:

- **Pass 2** — well-child visits (0-18、AAP schedule で通常 1/年 + 乳児 6-8/年)
- **Pass 3** — 予防接種訪問 (0-18、~5 in year-1 + 以降 1-2/年)
- **Pass 4** — 小児 acute (bronchiolitis / pneumonia / otitis media / URI 発熱)
- **Pass 5** — 傷害 (遊び場 / MVA 同乗者、age 5-18) + adolescent behavioural (12-18)

各 pass は下記 schema に基づく純 YAML 編集 + regen による cohort delta 確認。

## YAML schema (段階拡張中、この pass では empty)

`reference_data/pediatric_schedule.yaml`:

```yaml
encounters:
  well_child_infant:                       # 正準 encounter-type key
    age_min: 0                             # inclusive (歳)
    age_max: 1                             # inclusive
    visits_per_year: [6, 7, 8]             # 患者ごとに uniform sampling
    encounter_type: "outpatient"           # engine.py dispatch key
    disease_id: "well_child_infant"        # health_screening dispatch pattern に追従
    visit_reason: "Well-child visit — infant"
```

top-level `encounters:` が空 → イベント発生ゼロ (foundation default)。
エントリを追加すると `calendar.generate_pediatric_events` が
per-patient event 生成を開始。

## RNG 独立性

`generate_pediatric_events(person, year, prng)` は caller
(`generate_healthcare_calendar` の per-person `prng.spawn(1)[0]` pattern)
から sub-RNG を受け取る。master RNG 未触。encounter type 追加が
影響するのは該当 pediatric 患者の下流 stream のみで、無関係な成人 cohort に
波及しない。

## 成功条件 (META #760、close 判断)

- Emitted US cohort の under-20 患者比率 ≥12% (現状 5%)。
  NAMCS 2016 ambulatory-visit distribution 準拠。
- `Patient.birthDate` demographic realism 維持
  (`demographics.yaml age_distribution` 無変更)。
- 全 pediatric 患者 (0-18) で well-child + immunization encounter が非ゼロ。

## テスト

`tests/unit/test_pediatric_calendar.py` で以下をカバー: YAML loader
validation (空 schema round-trip、malformed entry で fail-loud)、空 schema で
event 発生ゼロ (byte-diff neutrality 保証)、mapping ある時 event 数一致 (pass 2+ 拡張)。

## Non-goal (META #760 準ずる)

- 新生児 ICU-level physiology は範囲外 (別 high-fidelity campaign)。
- 実世界 pediatric care-utilization への完全一致は非目標 (目標 ±50%、
  simulator は合成)。
- 成人 encounter engine の restructure は不要 — pediatric emission は
  既存 engine calendar loop に plug-in する。
