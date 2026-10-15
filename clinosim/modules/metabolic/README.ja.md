# `clinosim.modules.metabolic` — BMI 由来・代謝関連慢性疾患

`PersonRecord.bmi` から E66 肥満 ICD コードを決定論的に導出する POST_POPULATION enricher (軸 1) + BMI + HTN + 脂質異常症 + DM の 4 要素 AND から **E88.81 代謝症候群** を導出する POST_POPULATION enricher (軸 2) + BMI + DM で重み付けた SHA Bernoulli で **K76.0 NAFLD** を割り当てる POST_POPULATION enricher (軸 3) + BMI × 性別で重み付けた SHA Bernoulli で **G47.30 OSA** を割り当てる POST_POPULATION enricher (軸 4) + E66.9 / E66.01 患者向けに Semaglutide / Tirzepatide / Liraglutide を `chronic_medications.yaml` 経由で経口 (皮下) 投与する **GLP-1 作動薬薬物療法** (軸 5) を提供する代謝クラスタ関連の慢性疾患エンリッチモジュール。これで META #1137 クラスタ 2 の全軸 (5 軸) が完了。

## 目的

Session-102 コホート監査で identify された完結性ギャップを埋める: `PersonRecord.bmi` は生成時にセットされ複数の急性イベントリスク乗数で既に消費されていたが、BMI から導かれる ICD-10 肥満分類 (E66) は `chronic_conditions` に全く emit されていなかった (0% emission 対 CDC NHANES 2017-20 の米国成人有病率 ~41%)。本モジュールは、Layer-1 属性の決定論的関数である ICD コードが共有 `demographics.yaml:chronic_prevalence` の Bernoulli 抽選 pass を経由しないよう BMI 駆動の疾患導出を分離し、クラスタ 2 の 4 enricher (+ GLP-1 薬物療法層) を単一の contributor 向け seam に集約する。

書き込み対象フィールド: `PersonRecord.chronic_conditions` に ICD-10 コードを append。encounters / labs / `current_medications` を直接触らない — 薬物層 (軸 5) は共有 `chronic_medications.yaml` パイプライン経由で activator を通して提供。

## スコープ

- **スコープ内**: E66 肥満 ICD 導出 (BMI → E66.3 / E66.9 / E66.01)、E88.81 代謝症候群 4 要素 AND、K76.0 NAFLD BMI + DM Bernoulli、G47.30 OSA BMI + 性別 Bernoulli、E66.9 / E66.01 患者の GLP-1 薬物療法 yaml エントリ。
- **スコープ外**: FHIR 直列化 ([`output`](../output/README.md))、コード表示解決 ([`codes`](../../codes/))、ロケールテキスト ([`locale`](../../locale/README.md))、POP_GENERATION 時 chronic_prevalence Bernoulli サンプル (`demographics.yaml`)、BMI 経年推移 (deferred)、K76.0 → ALT/AST ベースライン連動 (deferred, follow-up として追跡)、肥満外科紹介 encounter + 減量カウンセリング procedure コード (deferred, follow-up として追跡)。

## 公開 API

```python
from clinosim.modules.metabolic import (
    e66_bmi_enricher,            # POST_POPULATION order=15; BMI → E66.*
    e88_81_syndrome_enricher,    # POST_POPULATION order=16; 4 要素 AND → E88.81
    k76_0_nafld_enricher,        # POST_POPULATION order=17; BMI + DM SHA → K76.0
    g47_30_osa_enricher,         # POST_POPULATION order=18; BMI × 性別 SHA → G47.30
)
```

4 enricher がモジュールの Python 側唯一の公開面。軸 5 は yaml エントリ (`locale/shared/chronic_medications.yaml` E66.9 / E66.01 ブロック) として ship され Python export を持たない。各 enricher は標準 `ctx` (`.population.persons` を持つ) を受け取り `PersonRecord.chronic_conditions` を in-place で変更する。

内部導出プリミティブ (`_derive_e66_code`, `_derive_metabolic_syndrome`, `_nafld_probability`, `_draw_nafld`, `_derive_nafld_assignment`, `_bmi_tier`, `_osa_probability`, `_draw_osa`, `_derive_osa_assignment`) は leading-underscore でテスト可能だが安定 API ではない — `clinosim/modules/metabolic/` 外からの呼び出しは enricher 経由にする。旧 `_has_code_with_prefix` モジュールローカルヘルパーは共有 `clinosim.codes.has_icd_prefix` に置換済。

## 決定論

- **軸 1-2**: BMI + chronic-condition set の純粋決定論的関数。RNG 消費ゼロ。E66 閾値を跨がない BMI 分布のコホート、または E88.81 4 要素 AND を満たさない chronic-condition set を持つコホートについてバイト同一性を保持。
- **軸 3-4**: SHA-256 per-person Bernoulli。各 enricher は `<module salt>|<person_id>` を 64-bit 分位点にハッシュし、BMI (+ DM / 性別) で重み付けた確率と比較。**RNG-neutral — マスターシミュレーションストリームを一切消費しない**ので、閾値を跨がないコホートではバイト同一性保持。別 salt (`metabolic.nafld.v1` vs `metabolic.osa.v1`) により同一患者の NAFLD / OSA 割り当ては完全相関ではなく統計的独立。
- **軸 5**: chronic-medications activator パイプラインが提供し、共有 per-patient sub-RNG を使用。上流で `ENRICHER_SEED_OFFSETS["chronic_medications"]` に支配されており本モジュールは独自の sub-seed を登録しない。

軸 1-4 で `ENRICHER_SEED_OFFSETS` エントリは不要 (SHA ベースまたは RNG-free)。

## 依存関係

- `clinosim.types.population.PersonRecord` — `.bmi`, `.sex`, `.person_id` を読み `.chronic_conditions` を変更。
- `hashlib` (stdlib) — 軸 3 / 4 Bernoulli draw 用 SHA-256。
- 下流で軸 5 は `clinosim.modules.patient.activator` が patient activation 時に yaml エントリを読む点に依存。

モジュール間 clinosim import なし。登録側 (`clinosim/simulator/enrichers.py`) が 4 enricher を import する。

## 定数と設定

閾値は決定論導出の不変条件を導出コードと近接させるため、yaml ではなく `engine.py` 内のモジュールレベル定数に保持:

- `_BMI_OVERWEIGHT_THRESHOLD = 25.0`, `_BMI_OBESITY_THRESHOLD = 30.0`, `_BMI_MORBID_THRESHOLD = 40.0` — WHO BMI 階層境界 (軸 1-4 の `_bmi_tier` で共用)。
- `_SYNDROME_BMI_THRESHOLD = 30.0`, `_HTN_PREFIXES`, `_DYSLIPIDEMIA_PREFIXES`, `_DM_PREFIXES`, `_SYNDROME_CODE = "E88.81"` — 軸 2 AND 基準。
- `_NAFLD_CODE = "K76.0"`, `_NAFLD_OBESE_PREVALENCE = 0.60`, `_NAFLD_MORBID_PREVALENCE = 0.85`, `_NAFLD_DM_UPLIFT = 1.15`, `_NAFLD_SALT = "metabolic.nafld.v1"` — 軸 3 アンカー (Younossi 2016 肥満サブコホート)。
- `_OSA_CODE = "G47.30"`, `_OSA_PREVALENCE_MALE`, `_OSA_PREVALENCE_FEMALE`, `_OSA_SALT = "metabolic.osa.v1"` — 軸 4 アンカー (Peppard 2013 BMI 階層 × 性別テーブル)。

軸 5 定数は `locale/shared/chronic_medications.yaml` の `E66.9:` / `E66.01:` ブロック (drug 名、用量、route、probability、`exclusive_classes: ["glp1"]`)。将来 NCEP ATP III 3-of-5 緩和を追加する際は軸 2 AND 基準を `reference_data/metabolic_syndrome_criteria.yaml` に外出し可能。

## ディレクトリ構成

```
clinosim/modules/metabolic/
├── __init__.py           # 公開 re-export (4 enricher)
├── engine.py             # 導出プリミティブ + 4 enricher wrapper
├── README.md             # (英語)
└── README.ja.md          # (本ファイル)
```

サブパッケージなし。yaml データファイルなし (定数はインライン、軸 5 薬物療法は共有 chronic_medications yaml 経由)。監査プラグインなし。

## Enricher 配線

`clinosim.simulator.enrichers.register_builtin_enrichers` で登録:

| Enricher | Stage | Order | 前提 |
|---|---|---|---|
| `e66_bmi_enricher` | `POST_POPULATION` | 15 | POP_GENERATION で BMI finalise |
| `e88_81_syndrome_enricher` | `POST_POPULATION` | 16 | chronic_prevalence sampler (HTN/DM/脂質) + E66 enricher |
| `k76_0_nafld_enricher` | `POST_POPULATION` | 17 | BMI + DM finalise |
| `g47_30_osa_enricher` | `POST_POPULATION` | 18 | BMI + 性別 finalise |

4 enricher すべてが allergy / identity (order 10) と `natural_death` (order 20) の間で走る。全常時 on (ロケール/設定 gate なし) — 閾値自体が emit を gate する。

軸 5 は標準 medication activator が `chronic_medications.yaml` を読んで提供; 新規 enricher 登録なし。

## 出力面 (消費側)

- `PersonRecord.chronic_conditions` — append された ICD-10 コードは chronic conditions を読む下流消費者全てに流れる:
  - FHIR Condition 直列化 ([`output/fhir_r4/documents/composition.py`](../output/fhir_r4/documents/composition.py))
  - ナラティブ生成 ([`document/narrative/`](../document/narrative/))
  - `population/aging.py`, `simulator/outpatient.py` のリスク乗数検索
  - DR + consistency validator ([`validator/`](../validator/))
- `locale/shared/chronic_medications.yaml` E66.9 / E66.01 ブロック (軸 5) は `modules/patient/activator.py` → `HomeMedication.drug_name` → 下流処方経路で消費される。

## テスト

`tests/unit/modules/metabolic/`:

- `test_e66_bmi_enricher.py` — 導出境界 5 + enricher 動作 5 + 混合コホート smoke 1 + 既存バリアント通過 1 = 12 件。
- `test_e88_81_syndrome_enricher.py` — 導出 AND 基準 8 + enricher 動作 5 + 混合コホート smoke 1 = 14 件。
- `test_k76_0_nafld_enricher.py` — 確率アンカー + DM-uplift 4 + SHA-draw 4 + 導出 wrapper 2 + enricher 動作 4 (500 人有病率帯 + RNG-neutral cross-seed 含む) = 14 件。
- `test_g47_30_osa_enricher.py` — BMI-tier 境界 1 + 有病率アンカー 4 (M / F / 2:1 比 / 不明性フォールバック) + SHA-draw 4 (K76.0 との salt 分離含む) + 導出 wrapper 2 + enricher 動作 4 (性別勾配可視化 + RNG-neutral cross-seed 含む) = 15 件。

合計 55 件。全 1 秒未満で実行完了; local `_person` + `_Ctx` dataclass 以外の fixture なし。

E2E 検証は `scripts/engine-fingerprint.sh` を US s42 + JP s17 p=500 コホートペアに実行 — 軸毎の commit 履歴にバイト同一性保持の TOTAL ハッシュ before / after を記録。

## オーナーシップ

META #1137 クラスタ-2 スコープと一緒にメンテ。主監査ポイント: `engine.py` モジュール docstring 内の臨床アンカー (Younossi 2016, Peppard 2013)。モジュールが ~600 LOC を超えたら将来軸は sibling axis ファイルで ship すべき — 現 `engine.py` 単一構成は ~430 LOC でレビュー容易だが、クラスタ 2 が更に成長する場合は per-axis split (`e66.py`, `e88_81.py`, …) が必要。

META #1633 と META #1137 で追跡される follow-up:

- **K76.0 NAFLD → ALT/AST ベースライン連動** — 下流 PR で K76.0-chronic 患者に対し liver-enzyme emission を elevated range に振るよう修正、issue スコープの "lab-conditional" 半分を満たす。
- **肥満外科紹介 encounter + 減量カウンセリング procedure** — 軸 5 の GLP-1 薬物療法半分は本モジュールで ship、紹介 encounter + カウンセリング procedure コード emission は新 encounter yaml エントリが必要で chronic-med 追加では済まない。
- **BMI 推移** — 現 `PersonRecord.bmi` は sim window 中 static。`bmi_trajectory` (`glycemic_trajectory` 相当) 導入で BMI 経年ドリフト + E66 階層間 mid-sim 再分類が可能に。

## 関連

- `clinosim/modules/allergy/README.md` — POST_POPULATION enricher テンプレート参照。
- `.github/TEMPLATE_MODULE_README.md` — canonical 11 セクションスケルトン。
- Issue #1137 (META: new modules — mental_health/ + metabolic/) — クローズ済。
- Issue #1126 (クラスタ 2 スコープの motivating issue)。
