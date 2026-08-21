# Quick start

## 同梱データセットプリセットをビルド

```bash
clinosim dataset list                                    # プリセット一覧
# jp-100      JP コホート、100 患者、2026-01-01 〜 2026-03-31 (3 ヶ月)
# jp-1000     JP コホート、1000 患者、2026-01-01 〜 2026-06-30 (6 ヶ月)
# us-100      US コホート、100 患者、2026-01-01 〜 2026-03-31 (3 ヶ月)
# us-1000     US コホート、1000 患者、2026-01-01 〜 2026-06-30 (6 ヶ月)

clinosim dataset build jp-100 --output ./jp-100          # ~30 秒
```

出力レイアウト:

```
jp-100/
├── cif/                         # canonical intermediate format
└── fhir_r4/
    ├── Patient.ndjson
    ├── Encounter.ndjson
    ├── Condition.ndjson
    ├── Observation.ndjson
    ├── ...
    └── manifest.json            # FHIR Bulk manifest
```

詳細: [Datasets](../reference/datasets.md)。

## 独自コホートを生成

```bash
# JP、500 患者、3 ヶ月
clinosim simulate \
    --country JP --population 500 --seed 42 \
    --start 2026-01-01 --end 2026-03-31 \
    --output ./my-cohort --format fhir

# US、1000 患者、12 ヶ月
clinosim simulate \
    --country US --population 1000 --seed 42 \
    --start 2025-07-01 --end 2026-06-30 \
    --output ./my-us-cohort --format fhir
```

決定的 — 同一 seed + 同一パラメータ = バイト同一出力。いつでも検証:

```bash
bash scripts/reproduce.sh
```

基礎保証は [Reproducibility](../development/reproducibility.ja.md)
参照。

## コホートを採点

```bash
clinosim eval -d ./jp-100                                # Markdown を stdout
clinosim eval -d ./jp-100 --json report.json --md report.md
```

完全リファレンス: [Evaluation](../eval.ja.md)。

## 次に読むもの

- **出力内の生理駆動検査値を読む** —
  [Your first cohort — reading the FHIR output](first-cohort.ja.md)
- **完全な CLI リファレンスと環境変数** —
  [Configuration](configuration.ja.md)
- **モデルを理解する** —
  [Concepts / Data generation walkthrough](../design-guides/data-generation-walkthrough.md)
- **疾患 YAML を拡張** —
  [Adding a module](../CONTRIBUTING-modules.ja.md)
- **自マシンで再現性を検証** —
  [Reproducibility](../development/reproducibility.ja.md)
