# clinosim

> **臨床的にリアルな病院データシミュレータ** — 仮想病院から FHIR R4 EHR データを生成する。

[![CI](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml)
[![Docs](https://github.com/TomoOkuyama/clinosim/actions/workflows/docs.yml/badge.svg?branch=master)](https://tomookuyama.github.io/clinosim/)
[![PyPI](https://img.shields.io/pypi/v/clinosim.svg?label=PyPI&color=blue)](https://pypi.org/project/clinosim/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4%20Bulk-orange)](https://hl7.org/fhir/uv/bulkdata/)

📚 **[ドキュメントサイト (英語)](https://tomookuyama.github.io/clinosim/)**  |  🇺🇸 **[README.md](README.md)**

> ⚠️ **個人プロジェクト免責** — 独立した個人プロジェクトであり、いかなる組織の公式製品でもありません。
>
> ⚠️ **合成データのみ** — 出力はすべて完全合成。臨床用途不可。clinosim は実患者データ / PHI / PII を取り込み・参照・再現しません。

## clinosim とは

clinosim は **集団からの forward シミュレーション** により合成 EHR データを生成します。各患者は隠れた **13 変数の生理学的状態** を持ち、全ての観察 (検査、バイタル、投薬、診断) はその状態から導出されます — したがってデータは **構造的に臨床整合** しています。

主な用途:

- 医療 AI / ML モデルの学習データ
- EHR システムのテスト / QA
- 臨床研究の手法開発
- 教育用症例データセット

## インストール

**Python 3.11 以降が必要です。**

```bash
pip install clinosim
```

clone からの開発インストール:

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## クイックスタート

小規模な US コホートを生成し FHIR 出力を確認:

```bash
clinosim simulate --country US --population 100 --seed 42 \
  --output ./out --format fhir-r4
ls ./out/fhir_r4/          # Patient.ndjson, Encounter.ndjson, ...
```

JP コホート、named-preset データセット、hospital-config override、CLI 全リファレンスは **[docs/getting-started/configuration.md](docs/getting-started/configuration.md)** (英語) 参照。

## 実際の動き

JP のワーファリン服用患者では、clinosim の生理学エンジンが患者を治療域 PT-INR に配置し、その範囲内の lab 値 (例: `2.7`) を発行します — "PT-INR 正常域からサンプリング" ではなく、隠れ状態がその値を選んだ結果です。ワーファリンを外せば、次回実行の INR は ~1.0 に戻ります。

**[完全な JSON walkthrough → docs/getting-started/first-cohort.md](docs/getting-started/first-cohort.md)** (英語)

## なぜ clinosim か

多くの合成 EHR ツールは疾患分布からサンプリングしてレコードを作ります。**clinosim は疾患そのものを走らせます** — CKD 患者は無関係の主訴でも ED で Cre 上昇、敗血症患者は WBC / CRP / lactate カスケードを示します。

- **構造的な臨床整合性** — 生理学モデルにより非整合な lab は不可能。
- **JP + US ネイティブ** — 16 の主要 FHIR resource type に対する JP Core プロファイル準拠、JLAC10 / MHLW YJ コード、JP の氏名 / 住所 / 保険を最初から。
- **YAML 駆動の拡張** — 32 の入院疾患 + 46 の ED / 外来病態はすべてデータファイル、コードではない。

先行事例 (Synthea) との比較: [docs/synthea-comparison.md](docs/synthea-comparison.md) (英語)。

## 詳しくは

| トピック | 場所 |
| --- | --- |
| ドキュメントサイト (英語) | <https://tomookuyama.github.io/clinosim/> |
| アーキテクチャリファレンス (英語) | [`docs/architecture/`](docs/architecture/README.md) |
| モジュール索引 (33 モジュール) | [`clinosim/modules/`](clinosim/modules/README.ja.md) |
| データ品質・評価 (英語) | [`docs/eval.md`](docs/eval.md) |
| JP-CLINS プロファイル対応 (英語) | [`docs/jp-clins.md`](docs/jp-clins.md) |
| コントリビュート (英語) | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| AI エージェント規約 (英語) | [`AGENTS.md`](AGENTS.md) |
| 変更履歴 (英語) | [`CHANGELOG.md`](CHANGELOG.md) |

## コミュニティ

- Code of Conduct — [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1)
- セキュリティポリシー — [`SECURITY.md`](SECURITY.md) (GitHub Security Advisories 経由の非公開報告)
- スターター課題 — [`good first issue`](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue) ラベル
- Issue テンプレート — [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) (構造化されたバグ / 機能フォーム)
- 引用 — GitHub "Cite this repository" ボタン ([`CITATION.cff`](CITATION.cff) が背後)

## ライセンス

MIT — [`LICENSE`](LICENSE) 参照。同梱コード体系データは各上流レジストリのライセンスに従う。詳細は [`clinosim/codes/README.ja.md`](clinosim/codes/README.ja.md)。

---

*注: トップレベル `clinosim/` Python パッケージには意図的に専用 README を置いていません。モジュール単位ドキュメントは [`clinosim/modules/`](clinosim/modules/README.ja.md) 配下、フレームワークドキュメントは各サブシステムと同居 — [`audit/`](clinosim/audit/README.ja.md), [`eval/`](clinosim/eval/README.ja.md), [`codes/`](clinosim/codes/README.ja.md), [`benchmarks/`](clinosim/benchmarks/README.ja.md)。*
