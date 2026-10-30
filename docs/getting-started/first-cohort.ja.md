# はじめてのコホート — FHIR 出力を読む

このウォークスルーは、clinosim の FHIR R4 出力で 1 つの生理駆動
検査値がどう見えるかを示します。
[`quick-start.ja.md`](quick-start.ja.md) の続き。

## JP warfarin コホートを生成

```bash
clinosim simulate --country JP --population 100 --seed 42 \
  --start 2026-01-01 --end 2026-03-31 \
  --output ./out-jp --format fhir-r4
```

`--country JP` には JP-CLINS FHIR パッケージが必要
([インストール](installation.ja.md) 参照)。無い場合は `--allow-legacy`
を渡さない限りエラー終了する。

心房細動で慢性 warfarin 治療中の患者を選ぶ。`fhir_r4/Observation.ndjson`
は以下のような PT-INR エントリを含む (抜粋。`identifier` / `category` /
`encounter` / `performer` / `specimen` 等は省略)。この抜粋は
`--allow-legacy` で生成したため検査コードは旧 5 桁 JLAC10 OID。JP-CLINS
パッケージ導入時は JLAC10 coding が 17 桁の JP-CLINS CoreLabo コードになる:

```json
{
  "resourceType": "Observation",
  "id": "lab-45136ca9d209",
  "meta": { "profile": [
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult",
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
    "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"
  ]},
  "status": "final",
  "code": {"coding": [
    { "system": "urn:oid:1.2.392.200119.4.1005", "code": "2B030",
      "display": "プロトロンビン時間" },
    { "system": "http://loinc.org", "code": "6301-6",
      "display": "INR in Platelet poor plasma by Coagulation assay" }
  ], "text": "プロトロンビン時間"},
  "subject": {"reference": "Patient/pt-cbdea7ced336"},
  "effectiveDateTime": "2026-03-14T10:39:00+09:00",
  "valueQuantity": {"value": 2.6, "unit": "{INR}",
    "system": "http://unitsofmeasure.org", "code": "{INR}"},
  "referenceRange": [{
    "low": {"value": 0.85, "unit": "{INR}"}, "high": {"value": 1.15, "unit": "{INR}"},
    "text": "一般基準値（非ワーファリン服用）"
  }],
  "interpretation": [{"coding": [{
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "code": "H"
  }]}]
}
```

## なぜ意味があるか

注目: INR 値 `2.6` は「PT-INR 正常範囲」からサンプリングされたので
はない。生理エンジンが慢性薬リストから warfarin を検出し、この患者
を 2.0 – 3.0 治療域付近 (目標中心 2.5) に置いた。reference range は
locale の基準値表にある一般 (非ワーファリン) 基準値なので、値はそれに
対して `H` と判定される。

- seed を変える → 別の、依然として治療域内の値。
- warfarin を除去 → 次回実行で正常 (~1.0) INR。

これが実践における「構造による臨床整合性」の意味。

## 出力のどこを見るか

| ファイル | 内容 |
| --- | --- |
| `Patient.ndjson` | Demographics、識別子 |
| `Coverage.ndjson` | 保険 (JP: 被保険者番号。既定で出力、`--no-jp-insurance` で省略) |
| `Encounter.ndjson` | 入院、退院、encounter 期間 |
| `Observation.ndjson` | 検査、vital — 上の PT-INR 含む |
| `MedicationRequest.ndjson` | INR band を駆動した warfarin オーダー |
| `Condition.ndjson` | 心房細動 (warfarin の適応) |

## 次に読むもの

- 完全な CLI リファレンス: [`configuration.ja.md`](configuration.ja.md)。
- 生理モデルの背後にあるアーキテクチャ:
  [`../architecture/README.ja.md`](../architecture/README.ja.md)。
- 公開コホートスコアリング gate:
  [`../eval.ja.md`](../eval.ja.md)。
