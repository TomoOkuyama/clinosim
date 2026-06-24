# family_history モジュール

第1度近親(母/父/兄弟姉妹)の疾患 family history を合成し、FHIR `FamilyMemberHistory`
+ CSV `family_history.csv` として出力する AD-55 Base(always-on)モジュール。

## 概要

患者ごとに近親を生成し、各近親に **locale 別有病率 × 遺伝倍率** で疾患を割り当てる。
本人が同じ疾患(base ICD)を持つ場合に近親の有病率を引き上げる(遺伝クラスタリング)。

```
P(近親が疾患C) = base_prevalence(C, 近親sex, 近親age帯) × heritability(C)  # 本人がCを持つとき
```

- 続柄: 母(MTH)/父(FTH)/兄弟姉妹(NSIB, 0-2人)。HL7 v3-RoleCode。
- 疾患: 心血管代謝系(E11/I10/I25/I63/I64/E78)+ 主要がん(C50乳/C18大腸/C34肺/C61前立腺)。
- 性別制限: 前立腺=男性のみ、乳がん=女性のみ。
- 近親年齢は本人年齢から導出(親 +25-35歳、兄弟姉妹 ±12歳)。親は高齢で deceased あり得る。

コードのみ保持(AD-30)。表示は出力時に `codes.lookup` で解決。

## データファイル

- `reference_data/family_history.yaml` — **country-neutral な生物学**: 続柄表示、遺伝倍率、
  性別制限、兄弟姉妹数分布、近親年齢オフセット、親死亡確率パラメータ。
- `clinosim/locale/{us,jp}/family_history_prevalence.yaml` — **国別 base 有病率**
  (疾患 × 性別 × 年齢帯)。疫学的な近似値(コードではなく rate)。

## API

```python
generate_family_history(patient_age: int, patient_conditions: list, country: str,
                        rng: np.random.Generator) -> list[FamilyMemberHistoryRecord]
```
`patient_conditions` は str / dict(`code`) / オブジェクト(`.code`)を受容。決定的。

## 配線

- **Enricher**(`simulator/enrichers.py`、stage=`post_records`、order=40、always-on):
  `enrich_family_history`。**person_id 由来の独立サブシード**
  (`derive_sub_seed(master, 0x4648, person_id)`)で encounter 間安定 & 主乱数列不変(AD-16)。
  `CIFPatientRecord.family_history`(typed field、Base)に格納。
- **FHIR**: `modules/output/_fhir_family_history.py` の `_build_family_history` を
  `_BUNDLE_BUILDERS` に登録(AD-56)。患者単位 id(`fmh-{pid}-NN`)で write 時 de-dup。
- **CSV**: `csv_adapter.py` が `family_history.csv` を出力(患者単位 de-dup)。

## 依存

`types/family_history`、`codes`(ICD/v3-RoleCode 表示)、`locale`(有病率)、
`simulator/seeding`(`derive_sub_seed`)。

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/enrichers.py` | `register_builtin_enrichers()` で post_records enricher 登録 | core (enricher registry) |
| `modules/family_history/enricher.py` | 同 module 内の enricher 実装 | core |
| `modules/output/_fhir_family_history.py` | FamilyMemberHistory リソース生成で family_history データ + reference 関数を参照 | medium (FHIR builder) |
| `tests/integration/test_family_history_enricher.py` | enricher integration test | guard |
| `tests/unit/test_family_history_engine.py` | engine unit tests | guard |

## 検証

- 決定論: 同一 seed の US 生成で **byte-diff は新規 `FamilyMemberHistory.ndjson` のみ**、
  既存 NDJSON 全 byte 一致(主乱数列不変を実証)。
- 監査(US 3000): 近親 2.79/患者、疾患 1.79/近親、性別制限違反 0、DM患者の~66%にDM親
  (遺伝倍率が機能)。
