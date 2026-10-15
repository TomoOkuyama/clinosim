# `clinosim.modules.metabolic` — BMI 由来・代謝関連慢性疾患

`PersonRecord.bmi` から E66 肥満 ICD コードを決定論的に導出する POST_POPULATION enricher (軸 1) + BMI + HTN + 脂質異常症 + DM の 4 要素 AND から **E88.81 代謝症候群** を導出する POST_POPULATION enricher (軸 2) + BMI + DM で重み付けた SHA Bernoulli で **K76.0 NAFLD** を割り当てる POST_POPULATION enricher (軸 3) を提供する代謝クラスタ関連の慢性疾患エンリッチモジュール。将来軸として **G47.30 OSA**、GLP-1/減量手術管理 を拡張予定 (META #1137 クラスタ 2 スコープ)。

## 目的

Session-102 コホート監査で identify された完結性ギャップを埋め
る: `PersonRecord.bmi` は生成時にセットされ複数の急性イベント
リスク乗数で既に消費されていたが、BMI から導かれる ICD-10 肥満
分類 (E66) は `chronic_conditions` に全く emit されていなかった
(0% emission 対 CDC NHANES 2017-20 の米国成人有病率 ~41%)。

本モジュールは、Layer-1 属性の決定論的関数である ICD コードが
共有 `demographics.yaml:chronic_prevalence` の Bernoulli 抽選
pass を経由しないよう、BMI 駆動の疾患導出を分離する。

## 公開 API

- `e66_bmi_enricher(ctx)` — POST_POPULATION enricher。各患者の
  BMI に基づき適切な E66 サブコードを `chronic_conditions` に
  append する。冪等かつ相互排他 (患者 1 名につき E66 コード 1 つ)。
- `e88_81_syndrome_enricher(ctx)` — POST_POPULATION enricher (order=16、`e66_bmi` の直後)。BMI ≥ 30 + HTN (I10) + 脂質異常症 (E78\*) + DM (E10\* or E11\*) の 4 要素 AND が成立した患者に `E88.81` を append する。冪等、RNG 非消費。
- `k76_0_nafld_enricher(ctx)` — POST_POPULATION enricher (order=17、BMI 由来 2 enricher の直後)。モジュール salt + person_id の SHA256 ハッシュから一様分位点を取り、BMI + DM で重み付けた閾値を下回った患者に `K76.0` を append する。冪等、RNG-neutral (master stream 非消費)。
- `_derive_e66_code(bmi) -> str | None` — BMI 値から ICD-10
  コードへの純粋関数マッピング。BMI < 25 (参照範囲、E66 コード
  なし) では `None` を返す。
- `_derive_metabolic_syndrome(bmi, chronic) -> str | None` — BMI + chronic condition list から `E88.81` もしくは `None` を返す純粋関数。4 要素のいずれかが欠けると `None`。

## 臨床マッピング

WHO + CDC BMI 分類 + ICD-10 2024:

| BMI | 分類 | ICD-10 |
|---|---|---|
| < 25 | 正常 / 低体重 | — |
| 25 – <30 | 過体重 | E66.3 |
| 30 – <40 | 肥満 (Class I + II) | E66.9 |
| ≥ 40 | 高度肥満 (Class III) | E66.01 |

閾値はモジュールレベル定数として宣言 (`_BMI_OVERWEIGHT_
THRESHOLD` 等) ─ 決定論的導出の不変条件を導出コードと同じ
場所に配置するため yaml ではなくコード内で管理。

## Enricher 配線

`clinosim.simulator.enrichers.register_builtin_enrichers` 内で
**POST_POPULATION order=15** に登録 ─ allergy/identity (order
10) の後、natural_death (order 20) の前。E66 コード付与が
`chronic_conditions` を読む下流パスより前に完了するよう配置。

常時有効 (locale / config ゲートなし)。

## 決定論 / RNG

**RNG 消費ゼロ**。本 enricher は `PersonRecord.bmi` の純粋関数。
BMI 分布が E66 閾値を跨がないコホートに対して byte-identity が
保たれ、E66 範囲の患者を含むコホートでも master-stream RNG
状態を乱さずコードが付与される。

`ENRICHER_SEED_OFFSETS` エントリ不要。

## リファレンスデータ

Phase A では無し ─ 閾値は WHO BMI 分類 + ICD-10 2024 に沿った
インライン定数。

将来軸 (E88.81 代謝症候群) で NCEP ATP III 基準 (BMI/腹囲 + HTN +
脂質異常症 + DM パターン一致) をエンコードする
`reference_data/metabolic_syndrome_criteria.yaml` を追加予定。

## テスト

`tests/unit/modules/metabolic/test_e66_bmi_enricher.py`:
- 純粋導出関数の tier 境界テスト 5 件
- enricher 挙動テスト 5 件 (各 tier append + 正常 BMI no-op +
  mutex ガード + 冪等性)
- 混合コホートのスモークテスト 1 件
- 既存 E66 variant pass-through テスト 1 件

## フォローアップ (クラスタ 2 ロードマップ)

- **E88.81 代謝症候群** — BMI + HTN + 脂質異常症 + DM の 4 要素
  AND
- **K76.0 NAFLD** — BMI ≥ 30 + ALT/AST 上昇; 検査値条件付きパス
  (生成後の検査値を enricher が読む) が必要
- **G47.30 閉塞性睡眠時無呼吸症候群** — BMI 相関リスク + 睡眠
  検査プロシージャパス
- **GLP-1 作動薬 / 減量手術管理** — `chronic_medications.yaml`
  サンプラへの E66 条件付きエントリで接続
- **BMI 軌跡** — 現在 `person.bmi` はシム窓内で静的。DM
  glycemic_trajectory の対応物として bmi_trajectory を追加
  すれば、BMI 年次ドリフトとシム途中の E66 ティア再分類が
  実現できる。

## 関連

- `clinosim/modules/allergy/README.ja.md` — POST_POPULATION
  enricher テンプレ参考 (META #1137 で参照されている)
- Issue #1137 (META: 新モジュール — mental_health/ + metabolic/)
- Issue #1126 (クラスタ 2 スコープのトリガー Issue)
