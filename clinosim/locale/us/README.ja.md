# `clinosim/locale/us/` — US locale データファイル

US コホート向けの国固有データ。`config.country == "US"` のとき、
`clinosim.locale.loader` から再 export されるファイル別ローダー
(実装は `clinosim/locale/loaders/`) が読む。

## スコープ

- US 固有の人口統計分布、入院構成、慢性疾患有病率テーブル、臨床
  コードマッピング。
- 正準の参照元が US と JP のコホートで異なるあらゆるフィールド
  (有病率、検査コードカタログ、診療科 / 専門分野の rollup)。

## 共有 vs locale 固有

国をまたいで同一のデータは `clinosim/locale/shared/` に置き、本
ディレクトリは **US 固有ファイルのみ** を保持する。共有 / 国別の
汎用マージは無い: 各ローダー関数は固定パス
`shared/<file>.yaml` または `<country>/<file>.yaml`
(`clinosim.locale._io._country_dir` で解決) のどちらかを読む。

## 意図的な US / JP 非対称

次の 6 ファイルは `clinosim/locale/jp/` に存在するが、設計上 US の
対応ファイルを持たない:

| JP ファイル | US 対応ファイルが無い理由 |
|---|---|
| `care_level_rates.yaml` | 日本の介護保険は明示的な介護度 (要支援 1-2 + 要介護 1-5) を全国発生率付きで定める。US の Medicare / Medicaid の長期介護経路は同様の段階コード化がされておらず、移植できる全国率テーブルが無い。 |
| `code_mapping_microbiology.yaml` + `code_mapping_microbiology_susceptibility.yaml` | JLAC10 / JSLM が日本の微生物コードマッピングを固定する。US コホートは `clinosim/codes/data/loinc.yaml` の共有 LOINC lookup を直接再利用するため、US 固有マッピングは不要。 |
| `external_organizations.yaml` | JP の MedicationRequest / Encounter リソースは外部の薬局 / 紹介先医療機関名を明示的に参照することが多い。US コホートの encounter は現状これを直接 emit しない。 |
| `patient_instructions_ja.yaml` | 日本語の `MedicationRequest.dosageInstruction.patientInstruction` 定型文テンプレート。JA FHIR emitter (`clinosim/modules/output/fhir_r4/lib/dosage.py`) が直接読む。 |
| `practitioner_qualifications.yaml` | 日本の医籍登録番号 / 専門医制度は固有の値を持つ全国資格レジストリ。US コホートの practitioner プロファイルは現状同等の構造を必要としない。 |

これらの欠落は意図的である — これらの概念を追加する US 側の新規
コントリビュータは、JP ファイルを参考に留め、US 側の必須ミラーと
みなさないこと。US コホートでその概念が必要になった場合 (例: US の
長期介護レベル、US 固有の微生物コード体系)、JP の構造をコピペせず
US ファイルを明示的に追加する。

逆方向に、次の 2 ファイルは本ディレクトリにあり JP の対応ファイルを
持たない:

| US ファイル | JP 対応ファイルが無い理由 |
|---|---|
| `code_mapping_drug.yaml` | JP の薬剤コードは locale マッピングではなく、薬剤 identity カタログ `clinosim/codes/data/drugs.yaml` の YJ 製品コードで、`clinosim.codes.drugs.jp_drug_code` が投与経路で選ぶ (Issue #2347)。`load_code_mapping("drug", "US")` は本ファイルとカタログを union する。 |
| `ckd_under60_prevalence.yaml` | 60 歳未満の US CKD (N18) 有病率バンド (USRDS / NHANES)。`load_ckd_under60_prevalence` が読み、`clinosim/modules/population/` の RNG 中立な 60 歳未満 CKD 付与に使う。ファイルの無い国ではローダーが空のバンドリストを返すため、JP コホートには 60 歳未満 CKD の上乗せは無い。 |

## 新規ファイルの追加

ファイルは自動検出されない: ここに置いた新しい `*.yaml` は、
`clinosim/locale/loaders/` のローダー関数 (`clinosim.locale.loader`
から再 export) が読むようになって初めて読まれる。shared / jp に
対応ファイルがあればそれに倣い、無ければ yaml ヘッダに US 固有の
データ出典を説明する冒頭コメントブロックを追加する。

データが US と JP で同一なら、代わりに `clinosim/locale/shared/` に
追加し、両 locale が自動的に拾うようにする。
