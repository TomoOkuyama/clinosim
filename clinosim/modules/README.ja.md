# `clinosim.modules` — モジュール索引

## 目的

`clinosim/modules/` は clinosim における全生成モジュールの集約
ディレクトリです。各サブディレクトリが合成パイプラインの一断面
(患者生成、臨床状態、ケアイベント、出力アダプタ、…) を所有し、
それぞれ独自の `README.md` + `README.ja.md` / 参照 YAML データ /
audit フックを備えます。

本ページは **ナビゲーション索引** — 各モジュール 1 行、機能領域で
グルーピングし、各子ディレクトリの README にリンクしています。
詳細な設計議論は個別 module のドキュメントに、モジュール間の相互
作用は [`docs/architecture/`](../../docs/architecture/README.md)
にあります (英語)。

## 全モジュール共通の設計慣習

- **ボイラープレート**: 各モジュールは
  [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)
  と [`TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md)
  の正規レイアウトに従う。
- **決定論的**: 乱数を引く module は sub-seeded RNG stream を使用し、
  `(country, population, seed, dates)` タプル固定でコホート出力が
  byte 再現する (AD-16)。
- **データ駆動**: 臨床パラメータは engine の隣の
  `reference_data/*.yaml` に置き、Python リテラルに置かない — 最後の
  インライン閾値を除去した campaign は [Issue #637](https://github.com/TomoOkuyama/clinosim/issues/637) 参照。
- **出力は locale 対応、コアは locale 非依存**: engine は中立 CIF を
  生成し、[`output/`](output/README.ja.md) アダプタが国別に描画する。
  コード体系は [`clinosim.codes`](../codes/README.ja.md) から取得。

## モジュール索引

### 患者生成

| モジュール | 役割 |
| --- | --- |
| [`population/`](population/README.ja.md) | 患者コホートのサンプリング — 人口統計、ライフイベント、コホート規模の決定論性。 |
| [`patient/`](patient/README.ja.md) | サンプリング済患者の activation — identity・慢性疾患・常用薬の付与。 |
| [`identity/`](identity/README.ja.md) | 国別プラガブルな患者識別子と保険記録 (`providers/*.py`)。 |
| [`sdoh/`](sdoh/README.ja.md) | 健康の社会的決定要因 — 住居 / 就労 / 教育 / 保険。 |
| [`family_history/`](family_history/README.ja.md) | 家族歴レコード生成。 |

### 臨床状態

| モジュール | 役割 |
| --- | --- |
| [`physiology/`](physiology/README.ja.md) | 13 変数の生理学的状態エンジン — lab / vital が構造的に整合するための load-bearing コア。 |
| [`clinical_course/`](clinical_course/README.ja.md) | 臨床経過エンジン — 疾患重症度と回復の時間発展を駆動。 |
| [`disease/`](disease/README.ja.md) | 疾患プロトコル registry — 32 inpatient 疾患 + 46 ED/外来病態を YAML で。 |

### ケアイベント

| モジュール | 役割 |
| --- | --- |
| [`encounter/`](encounter/README.ja.md) | Encounter プロトコル registry — inpatient / ED / 外来の形状。 |
| [`triage/`](triage/README.ja.md) | ED トリアージ判定。 |
| [`diagnosis/`](diagnosis/README.ja.md) | Bayesian 鑑別診断エンジン — 入院 → 確定診断の連鎖。 |
| [`order/`](order/README.ja.md) | Order エンジン — lab / 画像 / 薬 / 手技を encounter に発行。 |
| [`procedure/`](procedure/README.ja.md) | 外科的・治療的手技の生成。 |
| [`imaging/`](imaging/README.ja.md) | 画像メタデータチェーン (オーダ → 結果)。 |
| [`device/`](device/README.ja.md) | ICU デバイス留置 (CVC / 膀胱留置カテーテル / 人工呼吸器)。 |

### 観察・治療

| モジュール | 役割 |
| --- | --- |
| [`observation/`](observation/README.ja.md) | physiology 状態から駆動される検査・バイタル生成。 |
| [`nursing/`](nursing/README.ja.md) | 看護アセスメント + ワークフロー (NEWS2, GCS, Braden, Morse, …)。 |
| [`antibiotic/`](antibiotic/README.ja.md) | エンピリック抗菌薬選択と用量設計。 |
| [`allergy/`](allergy/README.ja.md) | 患者アレルギー生成。 |
| [`immunization/`](immunization/README.ja.md) | 予防接種歴。 |
| [`health_checkup/`](health_checkup/README.ja.md) | JP 事業者健診 (opt-in)。 |

### ケア運営

| モジュール | 役割 |
| --- | --- |
| [`facility/`](facility/README.ja.md) | 施設・部門定義と病院運営状態。 |
| [`healthcare_system/`](healthcare_system/README.ja.md) | 国別医療制度モデル。 |
| [`staff/`](staff/README.ja.md) | 医療従事者ロスター生成・割り当て。 |
| [`care_level/`](care_level/README.ja.md) | ケアレベル / ADL スコアリング。 |
| [`code_status/`](code_status/README.ja.md) | Advance directive / コードステータス設定。 |
| [`hai/`](hai/README.ja.md) | 病院関連感染サンプリング (CLABSI / CAUTI / VAP)。 |

### ドキュメント

| モジュール | 役割 |
| --- | --- |
| [`document/`](document/README.ja.md) | 臨床文書組み立て (退院サマリ、経過記録、…)。 |
| [`llm_service/`](llm_service/README.ja.md) | ナラティブ生成向け LLM プロバイダ統合 (Bedrock / Ollama / mock、`llm_service/providers/` 配下でプラグイン登録)。 |

### 出力・検証

| モジュール | 役割 |
| --- | --- |
| [`output/`](output/README.ja.md) | 出力アダプタの入口 (FHIR R4 NDJSON, HL7 v2, CDA, CSV)。 |
| [`validator/`](validator/README.ja.md) | 臨床事前分布に対するリアリズムベンチマークと一貫性チェック。 |

## 相互参照

- **フレームワークドキュメント**:
  - [`clinosim.audit`](../audit/README.ja.md) — module 単位の内部 PR 検証 gate。
  - [`clinosim.eval`](../eval/README.ja.md) — 公開コホート評価。
  - [`clinosim.codes`](../codes/README.ja.md) — 臨床コード体系 (LOINC / ICD / RxNorm / …)。
  - [`clinosim.benchmarks`](../benchmarks/README.ja.md) — early-warning baseline 指標。
- **コントリビューションガイド**:
  - [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md) — 新規 module 追加手順 (英語)。
  - [`docs/add-your-country.md`](../../docs/add-your-country.md) — 新規国追加手順 (locale + identity provider + healthcare system) (英語)。
- **アーキテクチャ**:
  - [`docs/architecture/`](../../docs/architecture/README.md) — データフロー / module 依存グラフ / 設計原則 / ADR 履歴 (英語)。
