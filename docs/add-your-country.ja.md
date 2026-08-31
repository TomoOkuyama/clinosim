# clinosim に国を追加する

*P2-14 (session 48)。本ガイドは、clinosim が新規国向けの locale
適合合成 EHR/EMR データを生成できるように国別パックを追加する手順
を示します。*

## Overview

clinosim の **locale レイヤ** (`clinosim/locale/<country>/`) は
1 国 = 1 フォルダのプラグイン設計です。新規国追加とは:

1. `clinosim/locale/<xx>/` を YAML データファイル一式で作成
2. ISO 3166-1 コードを `_COUNTRY_DIR_MAP` に登録
3. (任意) locale 固有 FHIR プロファイルを適用するかを判断
4. 標準 CLI を country フラグ経由でテスト

Locale データは厳密に **文化 / 規制 / 言語** のみ。国際臨床コード
(ICD-10 / LOINC / RxNorm / SNOMED) は `clinosim/codes/` に残り、
国別作業を必要としません。

## 前提条件

- **権威ある統計ソース** — 人口、血液型分布、慢性疾患 prevalence、
  検査 reference range 用。人口統計データの捏造は禁止 — 政府 / 医学
  会公表を引用。
- **現地臨床コードシステム** の知識 (`icd-10` vs `icd-10-cm` vs
  国別コーディングスキームのいずれを適用するか)。
- **任意**: 下流プロファイル emit 用の国別 FHIR IG (JP Core /
  US Core / DE Basisprofil 等)。

## Quick start

```bash
# 1. JP フォルダを起動 scaffold としてコピー
cp -R clinosim/locale/jp clinosim/locale/xx

# 2. 各 YAML を locale 適合値に置換 (スキーマは下記参照)
# 3. 国マップに登録:
#    clinosim/locale/loader.py:_COUNTRY_DIR_MAP を編集
```

そして:

```bash
clinosim simulate --country XX --population 100 --seed 42 --format fhir-r4 \
    --output ./out
```

## 必須 YAML ファイル

`xx/` ディレクトリは以下を **必ず** 含める必要あり。スキーマコメントと
skeleton 値は `_template/` scaffold (`clinosim/locale/_template/`)
参照。

| File | 目的 | 権威ソースヒント |
|---|---|---|
| `names.yaml` | 姓 + 名 と頻度重み | 国家統計局 / 戸籍 |
| `addresses.yaml` | 地域 (都道府県 / 県 / 州) + 郵便コード | 国営郵便サービス |
| `demographics.yaml` | 年齢分布、血液型、慢性疾患 prevalence (下記スキーマ注記参照)、疾患 incidence、生活習慣 | 政府センサス / 疾患サーベイランス |
| `formatting.yaml` | 日付 / 時刻 / 数値フォーマット | 現地慣習 |
| `code_mapping_diagnosis.yaml` | 内部疾患 id → 国別診断コード | 現地コーディングスキーム |
| `code_mapping_lab.yaml` | 内部検査名 → 国別検査コード | 現地検査コードシステム (JLAC10 / LOINC / 国別) |
| `code_mapping_drug.yaml` | 内部薬剤名 → 国別薬剤コード | 処方コード (YJ / RxNorm / 国別) |
| `code_mapping_procedure.yaml` | 内部手技名 → 国別手技コード | 現地手技スキーム (K コード / CPT / 国別) |
| `reference_range_lab.yaml` | 性別 / 年齢別検査 reference range | 現地臨床学会標準 |

各ファイルはロード時に検証されます; ファイル欠如は組み込みデフォルト
にフォールバックしますが、生成データが真に locale 代表とはならない
ことを意味します。

### `demographics.yaml::chronic_prevalence` スキーマの 2 形式

エントリごとに 2 つの形式を受け付けます:

- **Flat form** (単性別または性別非依存): `sex: F|M|""` +
  `"<lo>-<hi>": <target_marginal>` 年齢帯 pair。共有の population
  master RNG からサンプリング。

  ```yaml
  chronic_prevalence:
    N40:                  # BPH、男性のみ
      sex: M
      "60-99": 0.20
    E11:                  # T2DM、性別非依存
      "40-99": 0.10
  ```

- **`by_sex` form** (性別で非対称な帯域。男性乳がんが C50 全体の
  ~1 % で女性 BC より遅い年齢 peak を持つケース等)。最初の性別 key が
  primary となり (flat form と同一の master RNG からサンプリング)、
  残りの性別 key はすべて `augment_sex_bands` に入り
  `(patient_id, code)` 毎の sub-RNG からサンプリングされる (opposite-sex
  活性化が master stream を cascade しないため)。

  ```yaml
  chronic_prevalence:
    C50:                  # 乳がん — F primary + M ~0.02 %
      by_sex:
        F:
          "40-59": 0.015
          "60-99": 0.030
        M:
          "60-99": 0.0002
  ```

full な挙動 + downstream の sex-conditional 請求コード mapping:
[`reference/oncology-obstetric-service-lines.ja.md`](reference/oncology-obstetric-service-lines.ja.md) §3。

## 任意 YAML ファイル (opt-in モジュール)

対応国が特定 opt-in モジュールをサポートする場合のみ追加:

| File | 追加タイミング | モジュール |
|---|---|---|
| `identity.yaml` | 国民識別子 / 保険番号をモデル化する場合 | `identity` |
| `code_mapping_microbiology.yaml` | 国別 microbiology コーディング | `microbiology` |
| `code_mapping_microbiology_susceptibility.yaml` | 国別感受性報告 | `microbiology` |
| `care_level_rates.yaml` | 長期ケアレベル (JP 要介護度相当) | `care_level` — JP 固有概念、通常スキップ |
| `code_status_rates.yaml` | 蘇生ステータス分布 | `code_status` |
| `family_history_prevalence.yaml` | 一親等家族疾患 prevalence | `family_history` |
| `immunization_schedule.yaml` | 現地予防接種スケジュール | `immunization` |

## コード登録

### 1. `loader.py` に国を登録

```python
# clinosim/locale/loader.py
_COUNTRY_DIR_MAP = {"JP": "jp", "US": "us", "XX": "xx"}
```

ローダーは要求コードがマップにない場合 `country.lower()` にフォール
バックしますが、明示登録が完全性 / 発見可能性のために推奨。

### 2. FHIR プロファイル emit (任意)

国が国別 FHIR IG (JP Core / US Core / German Basisprofil / AU Core
等) を持つ場合、そのプロファイル URL を emit するかを判断。現状の
コードは `clinosim/modules/output/fhir_r4_adapter.py` の
`_apply_jp_core_profile` 経由で `country == "JP"` のときに JP Core
プロファイルを emit。

新規国の場合の選択肢:

1. 国別プロファイル emit をスキップ (安全なデフォルト; リソースは
   ベース FHIR R4 準拠)
2. JP Core と同形状の `_XX_CORE_PROFILES: dict[str, list[str]]`
   レジストリを追加し (session 48 g.1 で形状を統一)、
   `_build_bundle` 内で
   `if country == "XX": _apply_xx_core_profile(resource)` により
   dispatch

### 3. 国別 opt-in モジュール

一部の enricher は `register_builtin_enrichers` 内で country に
gate:

- `identity` — JP でアクティブ (国民健康保険番号); 適応または無効化
- `care_level` — JP のみ; スキップ
- `health_checkup` — JP-eCheckup; 同等物を設計する場合以外はスキップ

## テストチェックリスト

国フォルダ作成後:

- [ ] `clinosim simulate --country XX --population 10 --seed 42 --format cif`
      がエラーなく走行し、空でない CIF 出力を作成
- [ ] `clinosim simulate --country XX --population 10 --format fhir-r4`
      が有効な FHIR R4 リソースを emit
- [ ] 同 seed の 2 実行がバイト同一出力を生成 (決定性チェック —
      clinosim のコア不変条件、AD-16):
      ```bash
      clinosim simulate --country XX --seed 42 -o /tmp/xx-run1
      clinosim simulate --country XX --seed 42 -o /tmp/xx-run2
      diff -r /tmp/xx-run1 /tmp/xx-run2  # manifest transactionTime のみが差分
      ```
- [ ] 氏名 / 住所 / 日付が期待される現地慣習でレンダリング
- [ ] 検査 reference range が権威ソースと一致
- [ ] YAML から emit されるが `clinosim/codes/data/` に不在の
      新規コード追加が
      `pytest tests/unit/test_diagnosis_code_coverage.py` を fail
      させる (期待通り)。適切な `codes/data/*.yaml` に登録
      (`AGENTS.md` の「Diagnosis code coverage」節参照)。

## よくある落とし穴

- **人口統計データを絶対に捏造しない**。全人口統計は公開の権威
  ソース (センサス / 厚生省 / 医学会) に追跡可能でなければならない。
  捏造データは下流で silent-no-op クラスのバグの原因。
- **locale 固有コードを異なる国のバンドルに絶対に emit しない**。
  回帰テスト `test_us_p50_has_no_japanese_language_leakage` が US
  出力を JP leakage から守る; 新規国にも対称ガードを書く。
- **`code_mapping_*.yaml` 内でコードシステムを混在させない**。各
  ファイルは内部名を単一の外部システムにマップ。ファイル単位で分割。
- **LLM で臨床用語を翻訳しない**。国の公式用語 master を参照。
  clinosim の AD-27 ルールは LLM 駆動臨床翻訳を禁止。
- **分布が現実的かを判断する前に population ≥ 100 でテスト**。
  小規模コホートは long-tail サンプリング問題を隠す。

## 次に読むもの

- プロジェクト全体概念: [`docs/design-guides/project-concept-and-design.md`](design-guides/project-concept-and-design.md)
- Locale モジュールリファレンス: [`clinosim/locale/README.ja.md`](../clinosim/locale/README.ja.md)
- 診断コードカバレッジルール: [`AGENTS.md`](../AGENTS.md) §"Diagnosis code coverage"
- 再現性不変条件: [`docs/development/reproducibility.md`](development/reproducibility.md)

## Scaffold テンプレート

`clinosim/locale/_template/` はスキーマコメント付きプレースホルダ
YAML セットを含みます。**これらのプレースホルダは非機能** —
`clinosim simulate --country _template` を実行すると値が TODO マーカー
でありデータではないため失敗します。テンプレートは実国別パックを
authoring する際の必須スキーマ形状を示す目的のみで存在します。
