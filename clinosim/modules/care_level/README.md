# care_level モジュール

日本の **要介護度(介護保険 区分)** を患者に付与し、FHIR `Observation`(social-history)+
CSV `care_level.csv` として出力する AD-55 Base モジュール(**JP のみ**)。

## 概要

介護保険の認定区分(自立 / 要支援1-2 / 要介護1-5)を **年齢駆動**で確率的に割り当てる。
65歳未満は稀(~2%)、75歳以上で増加(~30%)、85歳以上で過半(~60%)が認定。

- 値: `jp-care-level` コード(自立=`independent` は Observation を出さず `care_level=""`)。
- AD-30: CIF は `jp-care-level` コードのみ保持。表示は出力時解決。
- 権威分類: 厚生労働省 介護保険(要支援/要介護 区分)。国際標準コードがないため
  ローカルコード体系 `codes/data/jp-care-level.yaml`(source=MHLW)。

## データファイル

- `reference_data/care_level.yaml` — レベル一覧(weight ベクトル順)+ 年齢帯。
- `clinosim/locale/jp/care_level_rates.yaml` — 年齢帯ごとの相対 weights(engine が正規化)。

## API

```python
assign_care_level(age: int, country: str, rng: np.random.Generator) -> str
# jp-care-level コード(自立/非JP は "")を返す。決定的。
```

## 配線

- **Enricher**(`simulator/enrichers.py`、stage=`post_records`、order=60、
  **JP のみ** `enabled=lambda c: c.country=="JP"`): `enrich_care_level`。
  **person_id 由来サブシード**(`derive_sub_seed(master, 0x434C, person_id)`)で
  encounter 間安定 & 主乱数列不変(AD-16)。`CIFPatientRecord.care_level` に格納。
- **FHIR**: `modules/output/_fhir_care_level.py` の `_build_care_level` を `_BUNDLE_BUILDERS`
  登録。social-history Observation、value=`jp-care-level` コード、id `carelevel-{pid}`。
- **CSV**: `csv_adapter.py` が `care_level.csv` を出力。

## 依存

`types/output`(`care_level` フィールド)、`codes`(`jp-care-level` 表示)、
`locale/jp`(レート)、`simulator/seeding`。

## 検証

- 決定論: 同一 seed 生成で **byte-diff は新規 carelevel-* Observation のみ**
  (削除0・既存 Observation 変化0)=主乱数列不変。
- 監査(JP 2000): 認定率 <65 2% / 65-74 12% / 75-84 27% / 85+ 57%(年齢駆動が機能)、
  US は要介護度0(JP のみ)。
