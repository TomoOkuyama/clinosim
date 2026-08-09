# clinosim

> **臨床的にリアルな病院データシミュレータ** — 仮想病院から FHIR R4 EHR データを生成。

[![CI](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml)
[![Docs](https://github.com/TomoOkuyama/clinosim/actions/workflows/docs.yml/badge.svg?branch=master)](https://tomookuyama.github.io/clinosim/)
[![PyPI](https://img.shields.io/pypi/v/clinosim.svg?label=PyPI&color=blue)](https://pypi.org/project/clinosim/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4%20Bulk-orange)](https://hl7.org/fhir/uv/bulkdata/)

📚 **ドキュメントサイト**: [tomookuyama.github.io/clinosim](https://tomookuyama.github.io/clinosim/)

🇬🇧 **English version**: [README.md](README.md)

> ⚠️ **個人プロジェクト注記**: 本プロジェクトは独立した個人プロジェクトであり、いかなる企業・組織の公式製品でも**ありません**。設計判断とコードは `pyproject.toml` に記載された個人 contributor の責任下にあります。
>
> ⚠️ **synthetic データのみ**: 生成物は完全に **synthetic** です。clinosim は実患者データや PHI / PII を取り込まず、参照せず、再現しません。生成データは**臨床用途を意図しておらず**、診断・治療・ケア判断に用いてはいけません。

## clinosim が行うこと

clinosim は **population から前向きシミュレーション** で合成 EHR データを生成します。全患者が隠れた **13 変数の生理学的状態** を保持し、全 observation (labs / vitals / medications / diagnoses) はその状態から導出される — 結果として **臨床的整合性が構造的に保証** されます。

主なユースケース:

- 医療 AI / ML モデル訓練データ
- EHR システムのテスト・QA
- 臨床研究手法の開発
- 教育用症例データセット

---

## なぜ clinosim か

大半の合成 EHR ツールは疾患分布からサンプリングします。**clinosim は疾患を実行します。** 慢性腎臓病 (CKD) 患者は無関係な受診でも ED 血清 Cre が上昇。ワルファリン患者は PT-INR 治療域に収まる。敗血症患者は WBC / CRP / lactate カスケードを示す。

3 つの具体的差別化:

- **構造的臨床整合性。** 事後フィルタではなく、生理モデルが不整合な labs を不可能にする。
- **JP + US ネイティブ。** JP Core プロファイル 16 主要 FHIR リソース準拠、JLAC10 / MHLW YJ コード、JP 氏名・住所・保険が標準装備。英語ツールに翻訳を後付けしたのではない。
- **YAML 駆動拡張。** 32 入院疾患 + 46 ED / 外来疾患はすべてデータファイル、コードではない。疾患追加 = YAML 編集。

### Synthea との比較

[Synthea](https://synthetichealth.github.io/synthea/) (MITRE の広く使われる状態遷移型シミュレータ) と clinosim は異なる角度から合成 EHR に取り組みます。両者とも OSS で FHIR を出力する — 違いはモデリング手法と locale カバレッジ。

| 次元 | clinosim | Synthea |
|---|---|---|
| モデリング手法 | 生理駆動前向きシミュレーション (患者ごとの 13 変数隠れ状態) | 疾患ごとの状態遷移モジュール |
| labs / vitals 間整合性 | 共有生理状態で保証 | モジュール単位で独立 |
| ネイティブ FHIR R4 出力 | Bulk Data Access NDJSON、ResourceType ごと 1 file | 患者ごと 1 FHIR R4 JSON |
| JP Core プロファイル準拠 | 16 リソース | 設計目標外 |
| Multi-locale (US + JP) | 両方 first-class | US 中心、i18n はコミュニティモジュール |
| 決定性保証 | 同一 seed で MINOR release 内は byte 同一 | Per-run seed 決定性 |
| 拡張モデル | YAML 駆動 (file 編集、コード変更なし) | Java module (`.json` 状態機械 + code) |
| Runtime | Python 3.11+ | Java 11+ |
| License | MIT | Apache 2.0 |

**使い分け:**

- **clinosim** — 臨床整合的 labs / vitals、JP 出力、Java を触らず疾患定義を反復したい場合。
- **Synthea** — 広範な US 集団、成熟した US 疾患モジュール、成熟した下流ツール群。

### サンプル出力 — 生理駆動 lab 一例

慢性ワルファリン治療中の心房細動 JP 患者に対し、clinosim は以下の PT-INR Observation を発行します:

```json
{
  "resourceType": "Observation",
  "id": "lab-enc-jp-042-15-pt-inr",
  "meta": { "profile": [
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"
  ]},
  "status": "final",
  "code": {"coding": [
    { "system": "urn:oid:1.2.392.200119.4.504", "code": "2B160000002327101",
      "display": "PT-INR" },
    { "system": "http://loinc.org", "code": "6301-6",
      "display": "INR in Platelet poor plasma by Coagulation assay" }
  ]},
  "subject": {"reference": "Patient/jp-042"},
  "effectiveDateTime": "2026-04-15T08:00:00+09:00",
  "valueQuantity": {"value": 2.7, "unit": "{INR}",
    "system": "http://unitsofmeasure.org", "code": "{INR}"},
  "referenceRange": [{
    "low": {"value": 2.0}, "high": {"value": 3.0},
    "text": "Warfarin therapeutic (AF stroke prevention)"
  }],
  "interpretation": [{"coding": [{
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "code": "N",
    "display": "Normal"
  }]}]
}
```

注目点: INR 値 2.7 は「PT-INR normal range」からサンプリングされたのではありません。生理エンジンが chronic-medication list からワルファリンを検出し、患者を 2.0 – 3.0 治療域に配置、referenceRange と interpretation を整合させました。seed を変更 → 別の (依然治療域内) 値。ワルファリン削除 → 次の run で正常域 (~1.0) INR。これが「構造的臨床整合性」の実践的意味です。

### パイプライン図

![clinosim エンドツーエンドパイプライン: population 生成 → 生理 + encounter シミュレーション → enricher stages → CIF → format adapters → NDJSON 出力](docs/assets/pipeline.svg)

段階的な walkthrough は [`docs/design-guides/data-generation-walkthrough.md` (English)](docs/design-guides/data-generation-walkthrough.md) 参照 (日本語版は今後対応)。

---

## インストール

**Python 3.11 以降が必要。**

```bash
pip install clinosim
```

開発用 install (clone から):

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## クイックスタート

小規模 US コホート生成 + FHIR 出力確認:

```bash
clinosim simulate --country US --population 100 --seed 42 \
  --output ./out --format fhir-r4
ls ./out/fhir_r4/          # Patient.ndjson, Encounter.ndjson, ...
```

JP Core プロファイル付き日本コホート生成:

```bash
clinosim simulate --country JP --population 100 --seed 42 \
  --output ./out-jp --format fhir-r4
```

名前付きプリセット (再現可能リリース):

```bash
clinosim dataset list                           # 利用可能プリセット表示
clinosim dataset build jp-100 --output ./jp-100-out
```

## 設定

実行時設定は `clinosim/config/*.yaml` からロードします。以下は主要 CLI フラグと環境変数。完全リファレンスは [`docs/reference/cli.md` (English)](docs/reference/cli.md) を参照。

### 主要 CLI フラグ (`clinosim simulate`)

| フラグ | デフォルト | 意味 |
|---|---|---|
| `--country {US,JP}` | `US` | Locale — 氏名・住所・保険・コード体系を制御 |
| `--population N` | 病院設定の catchment デフォルト | 集団サイズ (人) |
| `--seed N` | `42` | 決定性 seed (AD-16 不変条件) |
| `--start YYYY-MM-DD` / `--end YYYY-MM-DD` | 今日を snapshot とする過去 1 年 | シミュレーション窓 |
| `--output PATH` | `./output` | 出力ディレクトリ |
| `--format {cif,fhir-r4,csv}` | `cif` | 1 つ以上の出力フォーマット |
| `--hospital-config PATH` | `hospital_operations.yaml` | 病院形状オーバーライド YAML |

### 主要環境変数

| 変数 | デフォルト | 意味 |
|---|---|---|
| `CLINOSIM_JP_CLINS_PKG_DIR` | 未設定 | JP-CLINS パッケージディレクトリのパス (JP-CLINS lab-compliance gate で必須、[`docs/jp-clins.md` (English)](docs/jp-clins.md) 参照) |
| `AWS_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS デフォルトチェーン | AWS Bedrock ナラティブプロバイダー (`--provider bedrock`) 使用時のみ必要 |

## アーキテクチャ一覧

- **[`clinosim/simulator/`](clinosim/simulator/README.ja.md)** — メイン
  シミュレーションエンジン + CLI。
- **[`clinosim/modules/`](clinosim/modules/)** — 32 の臨床・運用
  モジュール、各 module に `README.md` / `README.ja.md`。
- **[`clinosim/modules/output/fhir_r4/`](clinosim/modules/output/fhir_r4/README.ja.md)**
  — FHIR R4 発行サブシステム (臨床ドメイン別 10 サブパッケージ)。
- **[`clinosim/types/`](clinosim/types/README.ja.md)** — 共有データ型
  (dataclass)。
- **[`clinosim/audit/`](clinosim/audit/README.ja.md)** — 内部 per-module
  PR 検証 gate。
- **[`clinosim/eval/`](clinosim/eval/README.ja.md)** — 公開コホート
  評価フレームワーク。
- **[`clinosim/locale/`](clinosim/locale/README.ja.md)** — 国別データ
  バンドル (US / JP)。

より深いアーキテクチャ資料:

- **[`docs/architecture/` (English)](docs/architecture/README.md)** —
  設計原則、module 構造、依存グラフ、data flow、ADR 履歴。
- **[`docs/reference/modules.md` (English)](docs/reference/modules.md)**
  — 1 ページ module リファレンス。

## データ品質

clinosim の真のゴールは **FHIR R4 + JP Core 準拠出力 + 臨床整合性 +
JP-locale 品質** です。出力データを変更する PR は 3-axis Data Quality
Review (構造 / 臨床 / JP-language) で gate される — [audit framework
(English)](clinosim/audit/README.md) が駆動。

公式評価 (公開 gate) は `clinosim eval` — [`clinosim/eval/`
(English)](clinosim/eval/README.md) と [`docs/eval.md`
(English)](docs/eval.md) 参照。

## コントリビュート

- **[`CONTRIBUTING.md` (English)](CONTRIBUTING.md)** — Issue 起票、変更
  提案、PR 開設方法 (DCO signoff 要件を含む)。
- **[`docs/design-guides/documentation-and-code-quality-policy.md`
  (English)](docs/design-guides/documentation-and-code-quality-policy.md)**
  — ドキュメント言語ペアリング (EN + JA)、ソースコードコメント言語
  ルール、self-contained OSS 品質基準、定数ドキュメント化ルール、
  dead-code hygiene。**全 PR がこのポリシーに照らしてレビュー**。
- **[`docs/CONTRIBUTING-modules.md`
  (English)](docs/CONTRIBUTING-modules.md)** — 新 module / FHIR
  builder 追加の実践プレイブック。
- **[`AGENTS.md` (English)](AGENTS.md)** — clinosim で作業する AI
  coding agent 向け canonical instructions。

CI 要件: `Unit tests (Py 3.12)` / `Integration tests (shard 1/3, 2/3,
3/3)` / `Signed-off-by check` / `mkdocs build` / `Build sdist +
wheel` / `ruff dead-code (F401 / F841)` / `vulture dead-code`。
完全一覧は [`CONTRIBUTING.md` (English)](CONTRIBUTING.md) 参照。

## ガバナンス・コミュニティ

| ドキュメント | 目的 |
|---|---|
| [`CODE_OF_CONDUCT.md` (English)](CODE_OF_CONDUCT.md) | Contributor Covenant 2.1 |
| [`SECURITY.md` (English)](SECURITY.md) | GitHub Security Advisories 経由の非公開脆弱性報告方法 |
| [`CITATION.cff`](CITATION.cff) | machine-readable 引用メタデータ (GitHub の `Cite this repository` ボタン) |
| [`CHANGELOG.md` (English)](CHANGELOG.md) | Keep a Changelog 形式、[SemVer](https://semver.org/) 契約 |
| [Issue テンプレート](.github/ISSUE_TEMPLATE/) | 構造化された bug report / feature request フォーム |
| [`good first issue` label](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue) | 初心者向け open task |

## ライセンス

MIT — [`LICENSE`](LICENSE) 参照。

各コード体系のデータは元レジストリのライセンスに従う:

- ICD-10-CM, RxNorm: パブリックドメイン
- LOINC: LOINC License (商用利用無料)
- WHO ICD-10: WHO 利用規約
- CPT: AMA Copyright (educational / research subset)
- JLAC10, YJ, K-codes: 厚生労働省 / JCCLS 公開データ

## 引用

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2026},
  url    = {https://github.com/TomoOkuyama/clinosim}
}
```
