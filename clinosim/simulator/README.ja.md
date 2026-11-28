# `clinosim.simulator` — メインシミュレーションエンジンと CLI

## 目的

`clinosim.simulator` は集団定義と有効化モジュール集合を完全な合成
EHR コホートに変換するトップレベルエントリポイントです。集団生成、
全フェーズ (ライフイベント、健康管理カレンダー、ED 受診、再入院、
退院後フォローアップ) を日付順に進める単一の月次 forward ループ、
日毎の患者軌跡、エンカウンターシミュレーション (入院 / 外来 / ED)、
検査 / vitals / 薬剤のパイプラインステップ、退院ゲートロジック、
enricher パス、出力シリアライズ、`clinosim` CLI サブコマンド (canonical は `simulate`。`generate` は
deprecation alias として残存。他: `test-disease` / `test-encounter` /
`validate` / `list-diseases` / `narrate` / `export-fhir` /
`enumerate` / `diff` / `regenerate-goldens` / `check-narratives`。
加えて、各パッケージから wire される委譲 subparser `audit` /
`dataset` / `eval` / `benchmark`) をオーケストレートします。

## スコープ

- **In scope**: エンドツーエンドのシミュレーションオーケストレー
  ション、CLI サブコマンド、疾患プロトコルロード、per-encounter
  DES-lite イベントスケジューリング、入院 / 外来 / 緊急シミュレータ、
  退院ゲートロジック、enricher オーケストレーション、per-behavior
  閾値定数、RNG seeding + memoize、構造化シミュレーションログ、
  unknown-condition ハンドリング。
- **Out of scope**: 個別疾患生理学
  ([`clinosim/modules/physiology/`](../modules/physiology/README.ja.md))、
  臨床コンテンツ作成 (`clinosim/modules/*/reference_data/`)、FHIR /
  CIF / CSV シリアライズ
  ([`clinosim/modules/output/`](../modules/output/README.ja.md))、
  audit ゲート ([`clinosim/audit/`](../audit/README.ja.md))、
  評価ゲート ([`clinosim/eval/`](../eval/README.ja.md))、プリセット
  データセットビルド ([`clinosim/dataset/`](../dataset/README.ja.md))。

## 公開 API

```python
from clinosim.simulator import (
    run_beta,                     # 集団駆動メインエントリ
    run_forced,                   # 決定的単一シナリオ実行
    run_alpha,                    # 後方互換単一患者実行
    main,                         # CLI エントリ (`clinosim` console_scripts)
    load_all_disease_protocols,   # プロトコルレジストリローダー
)
```

典型的使用:

```python
from clinosim.types.config import SimulatorConfig
from clinosim.simulator import run_beta

config = SimulatorConfig(
    country="JP",
    catchment_population=1000,
    random_seed=42,
    time_range=("2026-01-01", "2026-03-31"),
)
result = run_beta(config)
```

CLI 使用:

```bash
clinosim simulate -p 10000 -o ./output --format cif csv fhir
clinosim test-disease bacterial_pneumonia --archetype treatment_resistant -n 5
```

## 決定性

**AD-16 不変条件 — これはプロジェクト全体の load-bearing な決定性
保証です。** `clinosim.simulator` 内部の全乱数ドローは、master seed
からキー付きサブ seed (`clinosim/seeding.py` の `derive_phase_rng` /
`derive_sub_seed`) で派生するか、呼び出し側から渡された
`numpy.random.Generator` から派生しなければなりません。forward ループ
は各イベントのサブ RNG をイベント自身でキー付けするため、dispatch の
順序がイベント固有の乱数をずらすことはありません。
呼び出し箇所での `random.random()` / `numpy.random.default_rng()`、
壁時計参照、グローバル共有 RNG の導入は review-blocker です。

具体的帰結:

- 同一の `SimulatorConfig` (country / population / seed / 日付範囲)
  + 同一の有効化モジュールレジストリに対して、`run_beta` は毎回、
  IEEE-754 semantics が一致する任意のプラットフォーム上で、バイト
  同一の CIF コホートを生成します。
- [`clinosim/seeding.py`](../seeding.py) (`clinosim.simulator` 外の
  パッケージ直下) が per-phase / per-entity サブ RNG を派生
  (`derive_sub_seed` / `derive_phase_rng`)。`memoize.py` は F4
  スナップショット memoize (`--cache-dir`) を提供。新しい乱数は影響
  する対象をキーにした専用サブ RNG から引き、他の対象の乱数列を
  ずらさない。
- `tests/integration/` 配下の統合テストが代表的集団の固定 seed で
  byte-diff 決定性を pin。

## 依存

- `numpy` — 渡された `numpy.random.Generator` 経由のみ (AD-16 参照)。
- `pyyaml` — 参照データロード用。
- `clinosim.types` — `SimulatorConfig` / `PatientProfile` /
  `Encounter` および他の全 CIF 形状。
- `clinosim.modules.*` — 公開レジストリ経由でロードされる疾患 /
  観察 / 薬剤 / エンカウンター / 出力 / … プロバイダ。
- `clinosim.locale` — 国別データ。
- `clinosim.codes` — emit 時のコード lookup。

## 定数と設定

- **実行時設定** は
  [`SimulatorConfig`](../types/config.py) 経由で
  `clinosim/config/*.yaml` からロード。YAML スキーマは
  [`clinosim/config/README.ja.md`](../config/README.ja.md) 参照。
- **CLI フラグデフォルト** は `cli.py` と各 `cli_*.py` サブコマンド
  ハンドラに存在。`clinosim <subcommand> --help` および
  [`docs/getting-started/configuration.ja.md`](../../docs/getting-started/configuration.ja.md)
  でドキュメント化。
- **Per-behavior 閾値** — 全運用閾値 (ADL スコアリング、MAR 投与
  ウィンドウ、日次ループタイミング、退院ゲート、ED トリアージ、
  forced-scenario ゲート、LOC 遷移、酸素療法トリガ、スケジューリング、
  LOS 形状、unknown-condition 挙動、vitals cadence) は専用の
  `_<area>_thresholds.py` モジュール (14 ファイル、下のディレクトリ
  構成参照) に抽出。単一の定数監査 sweep でシミュレーションロジック
  を歩くことなく全運用チューナブルを発見できる。

## ディレクトリ構成

シミュレーションオーケストレーション:

```
clinosim/simulator/
  __init__.py            公開 API (5 export)
  cli.py                 argparse エントリ、トップレベルサブコマンド
                         dispatch
  engine.py              run_alpha / run_beta / run_forced
  forced_complications.py  run_forced 用のテスト専用強制: プロトコルの合併症を指定日に発症させる
                         (ForcedScenario.force_complications。リファクタリング用コーパス、
                         Issue #3976)
  _setup.py              実行セットアップ / pre-flight ヘルパー (engine が再 export)
  _dispatch.py           病院イベント dispatch + 重複処理
                         (`_dispatch_hospital_events`)
  daily_loop.py          engine から抽出した per-day ループ
  terminal_course.py     院内死亡の直前数時間: 終末期の状態と、それに沿う
                         最終 12 時間の vitals (Issue #2985);
                         死亡時刻より後の検査オーダー・結果は作らない (Issue #3280)
  hospital_ops.py        病院運用オーケストレーション
  inpatient.py           入院エンカウンターシミュレータ
  outpatient.py          外来エンカウンターシミュレータ
  emergency.py           ED エンカウンターシミュレータ
  discharge_gate.py      退院タイミング判定ロジック
  permissive_hypertension.py  許容性高血圧オーダーの期間と降圧薬の保留 (Issue #3557)
  oral_intake.py         AVPU が P / U の間と人工呼吸管理中の絶飲食: 食事オーダーを NPO にし、
                         その間の経口投与を保留。乱数なし (Issue #3552;
                         reference_data/oral_intake.yaml)
  outpatient_order_timing.py  外来オーダーを受診時間内に置く時刻: 10 分後を短い受診では受診時間の一定割合で頭打ちにする (Issue #3918;
                         reference_data/outpatient_order_timing.yaml)
  oxygen_course.py       入院中の補助酸素の経過: オン/オフの状態・デバイス・流量を測定間で引き継ぎ、
                         増減量、離脱、人工呼吸管理中の抜管、呼吸不全合併症に対する非侵襲的陽圧換気、刻みの流量値を決める (Issues #3469, #3632, #3643, #3705;
                         reference_data/oxygen_course.yaml)
  stroke_onset.py        急性脳卒中入院の最終健常確認時刻: 来院時刻からハッシュで引いた発症から来院までの
                         時間を引く。乱数ストリームは消費しない (Issue #3558;
                         reference_data/stroke_onset_to_arrival.yaml)
  vasoactive_support.py  昇圧薬・強心薬の離脱 (MAP 目標達成かつショック離脱) と
                         離脱後に退院まで 1 病日観察する判定 (Issue #3270)
  maintenance_iv_fluid.py  入院時の維持輸液オーダーを、食事が経口になった後 (猶予 1 日)
                         または最大日数で終了する (Issue #3409)
  ketoacidosis_resolution.py  ケトアシドーシスが改善した時点で DKA のインスリン・生理食塩水・
                         カリウムの点滴オーダーを終了し、皮下基礎インスリンへ移行する (Issue #3450)
  mixed_condition.py     混合入院 (condition_type "mixed") の併存疾患: 副診断として
                         コード化し、その疾患プロトコルの入院時オーダーを入院の
                         オーダーに統合し (入院時から、遅れて認識した場合は病日 1-3 から)、
                         治療開始後の数日で発症時の生理軸を元に戻す (Issue #3392)
  delirium.py            せん妄リスク (delirium_susceptibility) が高い患者の意識レベル低下
                         (AVPU) が数日続いた場合にせん妄を導出: 合併症エントリ (発症・
                         持続・回復) と副診断 ICD-10-CM / ICD-10 F05。乱数なし (Issue #3519)
  complication_dx.py     診断名を持つ入院中の合併症を、その合併症自身の発症時刻を持つ
                         `working_diagnoses` エントリにする (入院が既に持つコードは省く。省いた合併症は
                         それを担うコードと共に `clinical_diagnosis.carried_complications` に残す、
                         Issue #3905)。FHIR では
                         副診断の encounter-diagnosis Condition になる。表は
                         `reference_data/complication_diagnosis_codes.yaml`。乱数なし (Issue #3673)。
                         プロトコルが起こしうる合併症トークンは全て、コード化か `non_diagnosis`
                         (病名を持たない事象) に分類する (ガードテスト。`pending` は空で、
                         新しい病名トークンをコード化するまでの置き場)。`distinct_code_categories`
                         (E10, E11, E87, F10, K86, T79, T81) は初回発症規則を完全コードで判定する (Issue #3872)。
                         `protocol_codes` は特定プロトコルでのトークンに別のコードを与える
                         (敗血症性心筋症、熱傷創感染、外傷性横紋筋融解症)。糖尿病入院の低血糖は
                         病型に応じた E10.649 / E11.649 とする (Issue #3907)
  sustained_complication.py  合併症の `sustained_state`: 原因が続く間保たれる状態変数への効果
                         (DIC の消費は敗血症の炎症に従う)。`full_days` の間は全量、その後は
                         解除点へ向けて減衰。その間は合併症の `monitoring_labs` を採血。
                         乱数なし (Issue #3827)
  complication_actions.py  合併症に疾患 YAML が宣言する抗菌薬 `actions`: 表記を 1 つの正規
                         キーに統一し、合併症ごとに指定したプロトコルの第一選択抗菌薬を
                         発症時に薬剤安全性ゲート経由で発注。乱数なし (Issue #3543)。気道の action
                         (`intubation` / `mechanical_ventilation`) は発症時に状態駆動の経路で
                         気道を確保 (人工呼吸器・ICU・絶食・手技) (Issue #3639)。呼吸不全・ARDS の
                         病名は complication_dx.py が日付付きの診断にする (Issue #3673)。
                         抗凝固の action (Issue #3864): `start_anticoagulation` は DVT
                         プロトコルの第一選択のうち、クレアチニンクリアランス (エントリの
                         `renal_adjustment`) と薬剤安全性ゲートが許す最初の薬を発注し、
                         予定していた VTE 予防をその時刻で置き換える。ブロックに経口薬が
                         続く場合はヘパリンを導入期間だけ投与して経口薬へ移り、退院処方が
                         これを継続する。`hold_anticoagulation` は実行中の抗凝固薬と予定の
                         予防薬ごとに中止マーカーを書く (中止後の投与は退院後に
                         `order/supersede.py` が除く)。`IV_PPI` は消化管出血プロトコルの
                         静注 PPI を 3 日間、続けて経口 PPI を発症後 2 週間まで発注する (残りは退院処方が
                         継続, Issue #3896)。スタッフの乱数は
                         `complication_treatment_seed` を使う。C. difficile 腸炎 (Issue #3864):
                         `start_oral_vancomycin` (国・重症度・再発リスクで選び参照データに記述, Issue #3896: 日本は 65 歳以上、
                         免疫抑制の慢性疾患または全身性免疫抑制薬の使用 (Issue #3908) ならフィダキソマイシン 200 mg 1 日 2 回 10 日間、それ以外は
                         非重症ならばメトロニダゾール 500 mg 1 日 3 回 10 日間、重症
                         (白血球 15,000/uL 以上またはクレアチニン 1.5 mg/dL 超) ならバンコマイシン
                         経口 125 mg 1 日 4 回 10 日間。米国はバンコマイシン経口) と
                         `stop_offending_antibiotic` (ニトロイミダゾール以外の実行中の抗菌薬に
                         中止マーカー。退院処方には他の全身抗菌薬を載せず、投与の残りを継続)
  vasopressor_initiation.py  記録された平均血圧が輸液後も低い場合に昇圧薬を開始する
                         (固定病日ではなく生理状態駆動, Issue #3332)
  renal_replacement.py   内科的治療後もカリウム (治療閾値以上) または総 CO2 (10 以下) が続く AKI への間欠的血液透析: 1 回ごとに
                         dialysis_acute の処置を記録し、状態の dialysis_clearance を通じてカリウム・重炭酸・クレアチニン・尿素が
                         改善して戻る。直近の透析は退院を延期する (Issue #3830, KDIGO 2012 5.1.1)
  aki_response.py        急性腎障害 (KDIGO のクレアチニン基準): 活動期間中の薬剤保留
                         (最初に定義を満たしてからピークの 10% 低下まで継続, #3538)、
                         乳酸高値中のメトホルミン保留 (#3539)、退院判定 (Issue #3281)、
                         AKI の発症日を定義を最初に満たしたクレアチニンの時刻にする (#3642)、
                         発熱は専用のより長い上限まで在院を延長し、それでも発熱が続く
                         患者は自宅でなく施設へ退院 (#3637)。腎不全のカリウム高値 (高カリウム血症の
                         治療閾値以上) や総 CO2 低値 (10 mmol/L 以下) も同様に在院を延長し、上限に達しても
                         クレアチニンが回復しない、またはこれらが続く滞在は施設へ退院するため、
                         転帰が「治癒・軽快」になることはない (#3830)
  device_removal.py      尿道・中心静脈カテーテルの留置契機と、適応が終了して
                         抜去する日 (Issue #3516)
  discharge_rx.py        退院時処方ビルダー
  antithrombotic_plan.py 脳梗塞の入院中・退院時の抗血栓療法
                         (プロトコルの `antithrombotic_plan`, Issue #3277)
  enrichers.py           enricher レジストリ (post-population / post-encounter / post-records)
  outpatient_dept.py     外来フォローアップ診療科リゾルバ
  perinatal.py           分娩エンカウンター + 新生児 emit (母の退院処方 = 鎮痛薬 + 母の維持的な常用薬の継続)
  _perinatal_complications.py  分娩合併症が記録に残すもの: `perinatal.yaml complications.effects` による
                         血圧の上書き・検査結果・薬剤オーダー (Issue #3661/#3662)
  complications.py       合併症イベントスキーマヘルパー
  sex_gating.py          ICD-10 診断 dispatch の性別ゲート
  unknown_condition.py   疾患プロトコルを持たない慢性疾患のハンドリング
  encounter_setup.py     エンカウンター構築・終了の共通手順 (オーダー紐付け、
                         admit source / disposition / priority 設定)
  ed_procedures.py       ED 受診内のベッドサイド処置のタイミング
  screening_visit.py     エンカウンタープロトコルに基づく定期スクリーニング
                         受診 (workup + スクリーニング検査)
  adl_ceiling.py         病期つき慢性疾患 (認知症 CDR 病期) による
                         病前 Barthel 項目上限
  sleep_study.py         OSA 患者の初回ポリソムノグラフィーの無呼吸低呼吸指数 (Issue #3837)
  statin_monitoring.py   慢性疾患フォローアップでの脂質モニタリング +
                         スタチン調整
  diagnosis_rules.py     エンカウンターシミュレータの診断コーディング規則表
                         (reference_data/diagnosis_rules.yaml を読む)
  chronic_reconcile.py   患者の慢性疾患の発症日を受診記録と整合させる (Issue #3263)
  implied_chronic.py     入院が含意する慢性疾患。エンカウンターのプロファイルと人物レコードで同じ規則を使う (Issue #3263;
                         reference_data/icu_step_down.yaml           ICU 滞在が一般病棟へ退室する条件 (icu_step_down.py)
  reference_data/stroke_onset_to_arrival.yaml 国別の急性脳卒中の発症から来院までの時間 (stroke_onset.py)
  reference_data/implied_chronic_prevalence.yaml)
  injury_coding.py       疾患 YAML からの外傷入院のコーディング: 診断・手術・外因 (Issue #3258)
  icu_step_down.py       ICU 滞在の一般病棟への退室 (ステップダウン): ICU 水準の支持が記録されなくなる最初の日、
                         無ければ退院前日。死亡や短い入院では無し (Issue #3555; reference_data/icu_step_down.yaml)
  ventricular_rate.py    不整脈入院の心室レート。例: レートコントロールで低下する RVR 伴う AF (Issue #3274)
  sepsis_severity.py     敗血症の退院診断の重症度コード (敗血症性ショック /
                         重症敗血症 / 敗血症) を入院中のバイタル・MAR・検査
                         から決める (Issue #3269)。R65.2x の重症度は
                         A41.x 感染症の後に続く副傷病コードとして記録する
                         (Issue #3448)
  event_refs.py          LifeEvent.disease_id / ConditionEvent.ground_truth_diseases
                         の値の名前空間宣言
```

forward ループとフェーズ (`phases/`、5 モジュール + `__init__.py`):

```
  phases/_forward_loop.py        ForwardContext / EventQueue / run_forward_loop —
                                 run_beta が回す単一の月次ループ
  phases/_healthcare_calendar.py calendar_events_for_year / newborn_calendar_events /
                                 dispatch_calendar_event
  phases/_ed_slot.py             EDSlotSampler / dispatch_ed_slot
  phases/_readmission.py         schedule_readmission / dispatch_readmission
  phases/_post_discharge.py      schedule_post_discharge / dispatch_post_discharge
```

入院中の患者は外来受診しない (Issue #2996)。`dispatch_calendar_event` は
入院期間内に当たったカレンダー受診を退院翌日の同時刻へ延期し (キューに
再投入。暦年をまたぐ場合・スナップショット時点で入院中の場合は取りやめ)、
`dispatch_post_discharge` は後続入院の期間内に当たった退院後フォローアップを
取りやめる (後続入院が自身のフォローアップを予約する)。入院中かどうかの
判定は `_dispatch.InpatientStayIndex` が担う。入院期間内に当たった ED 受診枠も
同様に (繰り延べず) 取りやめる (Issue #3393)。`dispatch_ed_slot` が患者の
アクティベート前に判定する。

がんのサーベイランス処置 (大腸内視鏡・マンモグラフィなど。`chronic_followup.yaml`
の当該ブロックの `procedures:`) はそのがんのために行う (Issue #3868):
`ProcedureRecord.indication_code` が病態を持つ。慢性受診の後にカレンダーが
追加する腫瘍内科サバイバーシップ外来 (`_specialty_fanout_tick`、spec の `fanout`
フラグ) は自身の病態ブロックの処置を取る。無関係な慢性受診は、その期間の
専門外来がまだ後に控えている間 (`_own_visit_follows`、台帳の
`specialty_visits` から判定) はその病態の処置を専門外来に任せ、控えていない
ときは従来どおり受診上で行い、病態を適応とする。乱数は引かない。

予定外来は診療日に行う (Issue #3018)。休診日に当たったカレンダー受診
(慢性疾患フォローアップ、小児・予防接種、化学療法、健診) は次の診療日
(暦年をまたぐ場合は前の診療日) にキューへ入れ、退院後フォローアップは次の
診療日へ移す。休診日は `locale/<country>/clinic_calendar.yaml` を
`clinosim.locale.clinic_calendar` 経由で参照する (JP: 日曜・国民の祝日・休日・
12/29〜1/3、US: 日曜・連邦祝日)。イベントは乱数キーに予定日を使い続けるので
乱数列は動かない。救急受診は対象外。

パイプライン (3 ファイル):

```
  lab_pipeline.py        検査オーダー → サンプル → 結果パイプライン
  vitals_pipeline.py     vitals cadence + キャプチャパイプライン
  medication_pipeline.py 薬剤オーダー → 投与パイプライン
```

決定性とインストルメンテーション (3 ファイル):

```
  memoize.py             F4 スナップショット memoize (`--cache-dir`)
  log.py                 構造化 JSONL シミュレーションログ (simulator.log)
  diff.py                スナップショット差分 → FHIR Bundle transaction (`clinosim diff`)
```

ヘルパー (2 ファイル):

```
  helpers.py             後方互換 re-export facade (modules/disease の
                         load_all_disease_protocols 含む)
  enumerate.py           網羅列挙モード (`clinosim enumerate`)
```

CLI サブコマンドハンドラ (12 ファイル):

```
  cli_common.py          共有 CLI ユーティリティ
  cli_simulate.py        `clinosim simulate` サブコマンド (+ `generate` エイリアス)
  cli_validate.py        `clinosim validate` サブコマンド
  cli_list_diseases.py   `clinosim list-diseases` サブコマンド
  cli_diff.py            `clinosim diff` サブコマンド
  cli_enumerate.py       `clinosim enumerate` サブコマンド
  cli_export_fhir.py     `clinosim export-fhir` サブコマンド
  cli_narrate.py         `clinosim narrate` / `check-narratives` サブコマンド
  cli_regenerate.py      `clinosim regenerate-goldens` サブコマンド
  cli_test_disease.py    `clinosim test-disease` サブコマンド
  cli_test_encounter.py  `clinosim test-encounter` サブコマンド
  cli_catalog_codes.py   `clinosim catalog-codes` サブコマンド (リリースが出力しうる全コードのカタログ、Issue #3763)
```

リファレンスデータ (`reference_data/`、22 YAML):

```
  reference_data/adl_functional_ceilings.yaml  認知症 CDR 病期による病前 Barthel 上限 (adl_ceiling.py)
  reference_data/chronic_propagation.yaml     慢性疾患の伝播 (helpers.py)
  reference_data/diagnosis_rules.yaml         診断コーディング規則 (diagnosis_rules.py)
  reference_data/icd10_sex_restrictions.yaml  ICD-10 の性別ゲート (sex_gating.py)
  reference_data/permissive_hypertension_hold.yaml  許容性高血圧の間、収縮期血圧が上限未満なら保留する降圧薬 (permissive_hypertension.py)
  reference_data/renal_medication_rules.yaml  腎機能別投与規則 (medication_pipeline.py, discharge_rx.py)
  reference_data/renal_antibiotic_dosing.yaml  抗菌薬の腎機能別用量区分 (renal_antibiotic_dose.py)
  reference_data/sleep_study.yaml             ポリソムノグラフィー結果の AHI 重症度帯 (sleep_study.py)
  reference_data/statin_monitoring.yaml       脂質モニタリング / スタチン調整 (statin_monitoring.py)
  reference_data/vasoactive_hold.yaml         昇圧薬・強心薬の持続投与中に保留する薬 (medication_pipeline.py)
  reference_data/complication_actions.yaml    合併症アクションの正規キーと、感染性合併症ごとの経験的治療プロトコル (complication_actions.py)
  reference_data/vasopressor_initiation.yaml  低血圧と輸液後の昇圧薬開始条件 (vasopressor_initiation.py)
  reference_data/vasoactive_weaning.yaml      昇圧薬・強心薬の離脱条件と離脱後の退院判定 (vasoactive_support.py)
  reference_data/oxygen_course.yaml           入院中の補助酸素を減量・中止する条件、人工呼吸の抜管条件、記録する流量の刻み (oxygen_course.py)
  reference_data/outpatient_order_timing.yaml 外来オーダーを受診時間内に置く時刻 (outpatient_order_timing.py)
  reference_data/oral_intake.yaml             AVPU が P / U の間と人工呼吸管理中の絶飲食と、その間に保留する経口投与 (oral_intake.py)
  reference_data/maintenance_iv_fluid.yaml    維持輸液オーダーの終了条件 (maintenance_iv_fluid.py)
  reference_data/ketoacidosis_resolution.yaml DKA の改善基準と静注から皮下インスリンへの移行 (ketoacidosis_resolution.py)
  reference_data/mixed_condition.yaml         混合入院の併存疾患の遅れた認識・回復・オーダー統合 (mixed_condition.py)
  reference_data/delirium_derivation.yaml     導出せん妄のリスク閾値・エピソード規則・コード (delirium.py)
  reference_data/complication_diagnosis_codes.yaml  合併症トークン -> 入院の診断コード (complication_dx.py)
  reference_data/renal_replacement.yaml       透析の適応・1 回の効果・戻り (renal_replacement.py)
  reference_data/aki_response.yaml            AKI の判定・AKI 中に保留する薬剤・退院判定 (aki_response.py)
  reference_data/device_removal.yaml          カテーテルの留置契機と抜去の適応 (device_removal.py)
  reference_data/implied_chronic_prevalence.yaml  入院が含意する慢性疾患の有病率 (implied_chronic.py)
```

抽出済閾値定数 (14 ファイル、`_<area>_thresholds.py`):

```
  _adl_thresholds.py
  _daily_io_thresholds.py
  _daily_loop_thresholds.py
  _discharge_gate_thresholds.py
  _ed_thresholds.py
  _forced_scenario_thresholds.py
  _loc_thresholds.py
  _mar_thresholds.py
  _outpatient_thresholds.py
  _oxygen_therapy_thresholds.py
  _scheduling_thresholds.py
  _stay_thresholds.py
  _unknown_condition_thresholds.py
  _vitals_schedule_thresholds.py
```

## テスト

```bash
pytest tests/unit -k simulator -q          # 単体テスト
pytest tests/integration -q                # エンドツーエンド + byte-diff
```

`clinosim.simulator` を参照するテストファイルは約 300。統合テストは
固定 seed でのフル走行 byte-diff 決定性を網羅。単体テストは個別
パイプラインステージ、退院ゲートエッジケース、閾値定数挙動が中心。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.ja.md) 参照。

英語版: [`README.md`](README.md)。
