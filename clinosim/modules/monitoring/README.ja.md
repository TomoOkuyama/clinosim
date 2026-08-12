# clinosim.modules.monitoring (日本語)

慢性薬剤に対応する標準的モニタリング検査を自動注入するパイプライン。
`POST_RECORDS` enricher で各患者の `current_medications` を走査し、薬剤ごとに
定められた検査 (例: ワルファリン → PT-INR) を既存 encounter に注入する。
[Issue #736](https://github.com/TomoOkuyama/clinosim/issues/736) で顕在化した
「慢性薬剤起点のモニタリング検査が emit されない」ギャップを METAで
[#757](https://github.com/TomoOkuyama/clinosim/issues/757) として集約し、
その pass 2 (warfarin/INR) の実装。

導入前の simulator は以下 3 経路のみで lab order を生成:

1. 疾患 YAML の `laboratory` block — encounter × disease 単位
2. 入院 / 退院 protocol
3. 抗菌薬 / 手技 モジュール

いずれも `patient.current_medications` を参照しないため、warfarin 服用中で
sepsis / MI / AF が起きた患者は「その疾患 YAML が偶然 PT-INR を発火した場合のみ」
INR を得た。外来 HTN follow-up だけの warfarin 患者は INR ゼロ (p=500 seed 42 で
warfarin 6 名 中 0 名が INR あり)。

## パイプライン

`enrich_medication_monitoring` (POST_RECORDS) は全 encounter record 構築後に走り、
各患者 record に対して以下を実施:

1. mapping YAML の薬剤名を `current_medications` list と大小無視で substring match
   (英名 + 日本名 + 商品名バリエーションをカバー、`physiology.engine._WARFARIN_NAMES`
   と同じ pattern)。
2. 一致薬剤ごとに定義されたモニタリング検査を `_inject_monitoring_lab` で
   1 つ以上の適合 encounter に注入 (MVP は「record 内で最初の外来 encounter、
   無ければ最初の encounter」)。頻度スケジュール実装は follow-up PR。
3. record が既に該当検査の order/lab_result を持っていれば skip
   (疾患 YAML が emit した PT-INR 等を二重計上しない)。
4. lab 値は `physiology.engine.derive_lab_values` に該当薬剤 flag (warfarin なら
   `on_warfarin=True`) を渡して導出、`apply_realistic_variability` で
   共有ノイズ + 生理限界 clamp を通過させる。

## RNG 独立性

Enricher 内の乱数 (ノイズ + micro-jitter) は
`np.random.default_rng(derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["medication_monitoring"], patient_id))`
から取得。他 enricher (care_level, family_history, ...) と同じ pattern で
master RNG は触らず、`medication_monitoring.yaml` 編集は該当患者以外の
record に影響しない。

## Mapping YAML

`reference_data/medication_monitoring.yaml`。schema:

```yaml
mappings:
  Warfarin:                                    # 薬剤名 (current_medications と大小無視 substring match)
    aliases: ["ワルファリン", "coumadin"]      # 別名 (任意)
    monitoring:
      - lab: PT_INR                             # 内部 analyte 名 (observation/engine.py と一致)
        loinc: "6301-6"                         # 発 Order display 用の observation code
        rationale: "Anticoagulation therapeutic monitoring — INR target 2.0-3.0."
```

新規 drug → lab pair 追加は YAML 単独編集で完結。META #757 が挙げた頻度制御
(daily vs monthly、導入期 vs 維持期) は schema に未実装 — pass 2 (この PR) は
#736 の即時ギャップ解消を目的に「1 encounter 1 発」の MVP を出荷。
`frequency: {induction: "1-3d", maintenance: "monthly"}` 対応は follow-up。

## テスト

`tests/unit/test_medication_monitoring.py` で以下をカバー: mapping loader
round-trip、alias 一致、非 warfarin 患者で no-op、同 seed 反復実行で決定論的、
既存 PT-INR order との重複回避。

## Non-goal (META #757 に準ずる)

- モニタリング guideline を網羅しない (`medication_monitoring.yaml` に載る pair
  のみ、long tail は範囲外)。
- 投与量調整 causal loop (INR が warfarin 用量調整 → 次の INR)。simulator は
  観測を emit するのみで治療応答は modelしない。
- 実世界頻度への完全一致は非目標 (目標 ±50%、simulator は合成データ)。
