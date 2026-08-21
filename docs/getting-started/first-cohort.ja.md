# はじめてのコホート — FHIR 出力を読む

このウォークスルーは、clinosim の FHIR R4 出力で 1 つの生理駆動
検査値がどう見えるかを示します。
[`quick-start.ja.md`](quick-start.ja.md) の続き。

## JP warfarin コホートを生成

```bash
clinosim simulate --country JP --population 100 --seed 42 \
  --output ./out-jp --format fhir-r4
```

心房細動で慢性 warfarin 治療中の患者を選ぶ。その `Observation.ndjson`
は以下のような PT-INR エントリを含む:

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

## なぜ意味があるか

注目: INR 値 `2.7` は「PT-INR 正常範囲」からサンプリングされたので
はない。生理エンジンが慢性薬リストから warfarin を検出し、この患者
を 2.0 – 3.0 治療域に置き、reference range と interpretation を
それに合わせて選んだ。

- seed を変える → 別の、依然として治療域内の値。
- warfarin を除去 → 次回実行で正常 (~1.0) INR。

これが実践における「構造による臨床整合性」の意味。

## 出力のどこを見るか

| ファイル | 内容 |
| --- | --- |
| `Patient.ndjson` | Demographics、識別子、保険 |
| `Encounter.ndjson` | 入院、退院、encounter 期間 |
| `Observation.ndjson` | 検査、vital — 上の PT-INR 含む |
| `MedicationRequest.ndjson` | INR band を駆動した warfarin オーダー |
| `Condition.ndjson` | warfarin の理由としての心房細動 |

## 次に読むもの

- 完全な CLI リファレンス: [`configuration.ja.md`](configuration.ja.md)。
- 生理モデルの背後にあるアーキテクチャ:
  [`../architecture/README.md`](../architecture/README.md)。
- 公開コホートスコアリング gate:
  [`../eval.ja.md`](../eval.ja.md)。
