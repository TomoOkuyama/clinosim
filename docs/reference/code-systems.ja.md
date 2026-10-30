<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# コードシステムと権威ソース

`clinosim/codes/` は国際標準コードシステムを集約、全て英語 display
付き (日本語はオプション)。

| Key | Name | 用途 | 権威ソース |
| --- | --- | --- | --- |
| `icd-10-cm` | ICD-10-CM | US 診断 | [CMS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) |
| `icd-10` | WHO ICD-10 | JP 診断 | [WHO](https://icd.who.int/browse10/) |
| `loinc` | LOINC | 検査、vital、臨床文書型 | [Regenstrief](https://loinc.org/) |
| `snomed-ct` | SNOMED CT (subset) | Procedure category、performer role、body site、outcome、complication | [SNOMED International](https://www.snomed.org/) |
| `jlac10` | JLAC10 | JP 検査コード | [JCCLS](https://www.jccls.org/) |
| `rxnorm` | RxNorm | US 薬剤 | [NLM](https://www.nlm.nih.gov/research/umls/rxnorm/) |
| `yj` | YJ codes | JP 薬剤 | MHLW 薬価基準 |
| `hot7` | MEDIS HOT7 | JP 薬剤 (HOT 形式コード。JP の薬剤 emit はコード形式ごとに HOT7 / HOT9 / HOT13 / YJ の URI を選択) | [MEDIS](https://www.medis.or.jp/) |
| `medis-disease-keyno` | MEDIS 病名管理番号 | JP Condition の `medisRecordNo` slice (JP-CLINS) | [MEDIS](https://www.medis.or.jp/) |
| `cvx` | CVX | 予防接種 | [CDC IIS](https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx) |
| `cpt` | CPT | US 手技 | [AMA](https://www.ama-assn.org/practice-management/cpt) |
| `k-codes` | K codes | JP 診療報酬手技 | MHLW 診療報酬点数表 |

臨床文書型は以下の LOINC コードを使用 (入院医師文書のみ掲載。看護・外来 /
ED・JP 専用文書を含む国別の全一覧は
[`../clinical_documents.md`](../clinical_documents.md#document-scope) を参照):

| 文書 | LOINC | 備考 |
| --- | --- | --- |
| History and physical note | `34117-2` | 入院時生成 |
| Progress note | `11506-3` | 入院中に毎日生成 |
| Discharge summary note | `18842-5` | 退院時生成 (死亡 encounter では同コードの死亡退院サマリーが置き換え) |
| Death certificate | `64297-5` | 死亡で終了した encounter で生成 |
| Surgical operation note | `11504-8` | 外科手技ごとに生成 |
| Procedure note | `28570-0` | 侵襲的ベッドサイド手技ごとに生成 |

### コードシステム使用 (FHIR Observation 例)

```python
from clinosim.codes import lookup, get_system_uri

# CIF データはコードのみ
crp_code = "1988-5"  # LOINC

# FHIR Observation を構築
obs = {
    "resourceType": "Observation",
    "code": {
        "coding": [{
            "system": get_system_uri("loinc"),
            "code": crp_code,
            "display": lookup("loinc", crp_code, "en"),
        }],
    },
    "valueQuantity": {"value": 38.2, "unit": "mg/L"},
}
```

詳細は `clinosim/codes/README.ja.md` 参照。

---
