# clinosim

**臨床的にリアルな病院データシミュレータ** — 仮想病院から FHIR R4
の EHR データを生成。

!!! warning "個人プロジェクトに関する免責"
    これは個人プロジェクトであり、いかなる企業・組織の **公式製品
    ではありません**。

!!! warning "合成データのみ"
    出力は **全て合成データ** です。clinosim は実患者データや PHI/
    PII を取り込み・参照・再現しません。出力は **臨床用途を意図
    しておらず**、いかなる診断・治療・ケア判断にも依拠してはなり
    ません。

---

## clinosim とは

多くの合成 EHR ツールは疾患分布からのサンプリングでレコードを生成
します。**clinosim は疾患を走らせます。** 各患者は隠れた 14 変数の
生理学状態 (`clinosim/types/clinical.py::PhysiologicalState`) を保持
し、あらゆる検査 / vital / 薬剤はその状態から導出されます。

3 つの具体的な差別化ポイント:

- **構造による臨床整合性。** post-hoc フィルタではなく、生理学モデル
  が矛盾した検査値を不可能にします。
- **JP + US ネイティブ対応。** 16 の主要 FHIR リソース型に対する
  JP Core プロファイル準拠、JLAC10 / MHLW YJ コード、JP 氏名 / 住所
  / 保険を標準装備。
- **YAML 駆動拡張。** 32 の入院疾患 + 46 の ED / 外来症例は全て
  データファイルであり、コードではありません。

---

## 30 秒で開始

```bash
pip install clinosim                                     # (PyPI 公開準備中)
# または: pip install "git+https://github.com/TomoOkuyama/clinosim.git@master"

clinosim dataset build jp-100 --output ./jp-100          # 約 30 秒
clinosim eval -d ./jp-100                                # 評価
```

詳細ウォークスルー: [Installation](getting-started/installation.md) →
[Quick start](getting-started/quick-start.md)。

---

## 次に読むもの

<div class="grid cards" markdown>

-   :material-book-open-outline: **Concepts**

    ---

    集団 → CIF → FHIR パイプラインがエンドツーエンドで動作する仕組み。

    [→ Data generation walkthrough](design-guides/data-generation-walkthrough.md)

-   :material-database-outline: **Datasets**

    ---

    4 つの名前付きプリセットデータセット (US/JP × 100/1000) + 自作方法。

    [→ Datasets reference](reference/datasets.md)

-   :material-chart-line: **Evaluation**

    ---

    生成コホートを structural / clinical / locale の 3 軸でスコア化。

    [→ `clinosim eval`](eval.md)

-   :material-code-braces: **Guides**

    ---

    モジュール追加、疾患 YAML 拡張、新しい FHIR ビルダー配線。

    [→ Adding a module](CONTRIBUTING-modules.md)

</div>

---

## Synthea との比較

[Synthea](https://synthetichealth.github.io/synthea/) は state-transition
アプローチで合成 EHR を生成し、clinosim は生理学シミュレーションで
生成します。詳細な side-by-side は
[README](https://github.com/TomoOkuyama/clinosim#how-clinosim-compares-to-synthea)
参照。

---

## ライセンス

MIT。リポジトリルートの
[LICENSE](https://github.com/TomoOkuyama/clinosim/blob/master/LICENSE)
参照。
