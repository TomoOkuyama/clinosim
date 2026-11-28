# clinosim に同梱している第三者の用語体系

[English](THIRD_PARTY_TERMINOLOGIES.md)

clinosim は MIT ライセンスである ([`LICENSE`](LICENSE) 参照)。リポジトリには第三者の用語体系から取ったコードとコード体系の文言も含まれる。このファイルは、それぞれについて何を同梱しているか、どこから取ったか、所有者がどのライセンスページを公開しているかを列挙する。記載は事実のみであり、法的な結論は含まず、利用者がデータで何をしてよいか・いけないかも述べない。ライセンスの判断はメンテナーが行う ([メンテナーへの未決事項](#5-メンテナーへの未決事項) 参照)。

- **時点:** 2026-11-28。事実は各ファイル自身の `metadata` ブロックとヘッダーコメント、[`clinosim/codes/authoritative/README.ja.md`](clinosim/codes/authoritative/README.ja.md)、およびファイルを数えた結果による。4 章のライセンスページは 2026-11-28 に開いた。
- **「ライセンス未確認」** は、所有者のライセンスページを読めなかったか、読んだページにこの内容のライセンスが書かれていなかったことを意味する。ライセンスが存在しないという意味ではない。
- **配布されるもの:** sdist は `clinosim/**/*.yaml` と `clinosim/**/*.json` を含む ([`pyproject.toml`](pyproject.toml) の `[tool.hatch.build.targets.sdist]`) ので、以下のファイルはすべて sdist に入る。wheel のターゲットは `clinosim` をパッケージし (`packages = ["clinosim"]`)、sdist の節のコメントは wheel がヒントなしで YAML データを含めると述べている。このファイルのために wheel をビルドして中身を確認してはいない。
- **同梱していないもの:** JP-CLINS の `clinical-information-sharing` と `jpfhir-terminology` の FHIR パッケージ。検体検査コーディングのローダーは実行時に `$CLINOSIM_JP_CLINS_PKG_DIR`、`~/.fhir/packages/` のキャッシュ、または隣接する `../fhir-jp-validator` チェックアウトから読む (`clinosim/modules/output/fhir_r4/labs/coding_package.py::_find_pkg_files`)。

## 1. `clinosim/codes/authoritative/` のスナップショット

これらの JSON は照合用の参照データである。単体テストが `clinosim/codes/data/` の表示名をこれらと比較し、`JP_MedicationCodeYJ_CS_full.json` は `clinosim/codes/yj.py` が実行時にも読む。「件数」はファイル内の概念数 (`len(concept)`、または `codes` のキー数)。

| ファイル | ファイルに記録された出典 | 記録された版・バージョン | 取得 (日付、取得元) | 複製している内容 | 件数 |
|---|---|---|---|---|---|
| `icd10cm_2027_cms.json` | CMS ICD-10-CM code descriptions in tabular order | FY2027 (`icd10cm_order_2027.txt`) | 2026-11-10、`https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip`。後の追加も同じファイルから | コード、CMS の long description、billable フラグ | 602 |
| `icd10_who_tx.json` | `fhir.tx.support.r4 0.37.0` に収録の WHO ICD-10 (`CodeSystem-icd-10.json`、content `complete`) | パッケージ 0.37.0。後の追加は tx.fhir.org の "ICD-10-EN 2019-covid-expanded" | 2026-07-19、`https://github.com/iryohjoho/fhir-jp-validator` の `tx-server-build/`。2026-11-16 以降の追加は tx.fhir.org `$lookup` | コード、display、definition (409)、kind / parent / inclusion などの property (421)、designation (4) | 427 |
| `icd10_mhlw_2013_ja.json` | 厚生労働省 疾病、傷害及び死因の統計分類 基本分類表 (ICD-10 2013年版準拠) | 2013 | 2026-11-01、`https://www.mhlw.go.jp/toukei/sippei/xls/kihon2013.xlsx`。2026-11-27 まで同じファイルから追加 | コード、日本語の正式名称 | 475 (metadata によれば元の表は 15,296 コード) |
| `loinc_2_83_tx.json` | tx.fhir.org が提供する LOINC | LOINC 2.83 | 2026-11-10、`https://tx.fhir.org/r4/CodeSystem/$lookup` | コード、LONG_COMMON_NAME、SHORTNAME (367)、その他の英語 designation、status | 373 |
| `snomed_ct_tx.json` | tx.fhir.org 経由の SNOMED CT International Edition | `http://snomed.info/sct/900000000000207008/version/20250201`。8 概念は edition 20260701 から追加 | 2026-11-10 (追加 2026-11-24、2026-11-26)、tx.fhir.org `$lookup` | コード、preferred term、synonym、fully specified name | 288 |
| `snomed_allergy_tx.json` | tx.fhir.org 経由の SNOMED CT International Edition | 2025-02-01 | 2026-11-10、tx.fhir.org R4 `CodeSystem/$lookup` | コード、display、fully specified name、inactive フラグ | 12 |
| `rxnorm_rxnav_snapshot.json` | RxNav (NLM) `/REST/rxcui/{code}/historystatus` | 記録なし | 2026-10-28 (SCD は 2026-11-09)、RxNav REST API | RxCUI、status、name、term type | 1,451 |
| `JP_MedicationCodeYJ_CS_full.json` | MEDIS-DC 医薬品HOTコードマスター (`MEDIS20260831.TXT`) を FHIR CodeSystem `http://capstandard.jp/iyaku.info/CodeSystem/YJ-code` として書き出したもの | CodeSystem `version` 2026.8.31、`content` `complete` | 日付の記録なし。更新スクリプト [`scripts/refresh_authoritative_yj_full.py`](scripts/refresh_authoritative_yj_full.py) はダウンロードページ `https://www2.medis.or.jp/hcode/` を挙げる | マスターの全 YJ コードと表示名 (完全なコード体系) | 23,923 |
| `yj_medis_hot_20261031.json` | MEDIS-DC 医薬品HOTコードマスター (2026-10-31) と jpfhir-terminology 2.2606.0 の YJ CodeSystem (fragment) | マスター 2026-10-31、パッケージ 2.2606.0 | 2026-11-10、`https://www2.medis.or.jp/hcode/moto_data/h20261031.zip` | コード、販売名、その他の販売名 (2) | 268 |
| `yj_tx_fragment.json` | jpfhir-terminology 2.2606.0 `CodeSystem-jp-medicationcodeyj-cs.json` (content `fragment`) | 2.2606.0 | 2026-07-19、`https://github.com/iryohjoho/fhir-jp-validator` の `tx-server-build/` | コード、display | 9 |
| `yj_mhlw_snapshot.json` | 厚生労働省 薬価基準収載品目リスト及び後発医薬品に関する情報 (令和8年6月12日適用) | 2026-06-12 適用 | 2026-10-31、`https://www.mhlw.go.jp/topics/2026/04/xls/tp20260612-01_05.xlsx` | YJ コードごとの成分名と品名 (3 件はリスト側のコード付き) | 224 |
| `shinryo_koui_ssk_20261013_ja.json` | 社会保険診療報酬支払基金 基本マスター 医科診療行為マスター (`s_ALL20261013.csv`。一部の行は `s_ALL20261102.csv`) | 2026-10-13 と 2026-11-02 のマスター | 2026-11-01 (行の追加 2026-11-06、2026-11-21、2026-11-23)、`https://www.ssk.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html` | コードごとに最大 8 件のマスター名称 | 49 コード、149 名称 |
| `jlac10_jslm_137.json` | 日本臨床検査医学会 (JSLM) 検査項目コード委員会「JLAC10コード表_臨床検査」 | version 137 (2026-06)、元ファイルの sha256 を記録 | 2026-11-10、`https://www.jslm.org/committees/code/137jlac10_1.xlsx` (シート 分析物コード) | 分析物コード、日本語名、略称 (37)、英名 | 53 |
| `jfagy_jpfhir_terminology.json` | jpfhir-terminology 2.2606.0 (JFAGY アレルゲンの CodeSystem) | パッケージ 2.2606.0。CodeSystem の版 2026.5.31、2026.6.15、2024.7.9 | 2026-11-10、`https://jpfhir.jp/fhir/core/terminology/igv-2.2606.0/package.tgz` (sha256 を記録) | system、CodeSystem の版、content、コード、display | 6 |

## 2. 出典の文言を複製している `clinosim/codes/data/` のファイル

`clinosim/codes/data/` には 85 の YAML ファイルがある。下表は、第三者の体系のコードとその体系の文言 (表示名、名称) を一緒に持つファイルを挙げる。「記録された版」はファイルの `metadata.version` のまま。1 章のスナップショットの版と異なる場合は両方を示す。「一致」は 2026-11-28 に各エントリをスナップショットと比較して数えた。

| ファイル | 記録された体系と所有者 | 記録された版 | 件数 | 複製している内容 | スナップショットとの一致 |
|---|---|---|---|---|---|
| `icd-10-cm.yaml` | ICD-10-CM、CMS / NCHS | `2024` (スナップショット: FY2027) | 621 (`en`)、193 (`ja`) | `en` = CMS の long description。CM のみのコードの `ja` は clinosim の翻訳 (ファイルヘッダー) | `en` 621 件中 602 件がスナップショットと一致 (19 コードはスナップショットにない) |
| `icd-10.yaml` | WHO ICD-10。`ja` は厚労省の基本分類表 | `WHO 2019` | 491 | `en` = WHO の display、`ja` = 厚労省の正式名称 (そのまま) | `en`: 491 件中 427 件が WHO スナップショットの語と一致。`ja`: 491 件中 475 件が厚労省スナップショットと一致 |
| `loinc.yaml` | LOINC、Regenstrief Institute | `2.76` (スナップショット: 2.83) | 373 | `en` = LOINC の designation (注記がなければ LONG_COMMON_NAME)。`ja` の出典は記録なし | 373 件中 373 件 |
| `snomed-ct.yaml` | SNOMED CT、SNOMED International | `2024-03` (スナップショット: 2025-02-01 / 20260701) | 289 | `en` = preferred term、synonym または FSN。`ja` の出典は記録なし | 289 件中 286 件 |
| `rxnorm.yaml` | RxNorm、NLM | `2024` | 1,450 (`en`)、241 (`ja`) | `en` = 薬剤名 | `en` 1,450 件中 1,269 件が RxNav の name と一致 |
| `rxnorm_scd.yaml` | NLM RxNav 経由の RxNorm SCD | 取得 2026-11-09 | 204 薬剤、1,225 RxCUI | RxCUI、規格量、単位 (名称なし) | — |
| `yj.yaml` | YJ コード (厚労省 薬価基準 YJ / MEDIS HOT-YJ マスター / JP Core) | `2024` | 272 | `ja` = 販売名、`en` = 英語の成分名 | `ja`: 268 件が MEDIS 2026-10-31 スナップショットと一致。163 件が完全版 YJ CodeSystem の display と一致 |
| `jlac10.yaml` | JLAC10、JSLM | `137` | 53 | `ja` = マスターの名称または略称、`en` 英名 | `ja` 53 件中 48 件がマスターの名称または略称と一致 |
| `k-codes.yaml` | 診療報酬点数表 (厚労省)。診療行為マスターで照合 | `2024` | 49 | `ja` = マスター名称、またはそれが始まる区分名 (ファイルヘッダー)。`en` = 英訳 (ファイルヘッダー) | `ja` 49 件中 23 件がマスター名称と完全一致 |
| `cpt.yaml` | CPT、American Medical Association | `2024` | 95 | 英語と日本語のラベル。ヘッダーには "CPT is proprietary (AMA license)" と "not yet machine-verified" とある。`en` ラベルが AMA の descriptor の文言かどうかは記録なし | スナップショットなし |
| `cvx.yaml` | CVX、CDC IIS | `2026-06` | 39 | `en` は CDC の CVX 一覧で照合 (ファイルヘッダー) | スナップショットなし |
| `medis-disease-keyno.yaml` | MEDIS 標準病名マスター 病名管理番号。jpfhir-terminology 2.2606.0 の CodeSystem `medis-codesystem-diseasekanricodes` (MEDIS 5.18 の fragment) から | `5.18-fragment-seed` | 2 | コードと MEDIS の名称 | — |
| `mhlw-medication-usage-code.yaml` | 厚労省 MedicationUsage_ePrescription CodeSystem (jpfhir-terminology 2.2606.0) | `2.2606.0` | 13 | コードと日本語の用法文 | — |
| `hl7-*.yaml` (25 ファイル) | HL7 Terminology (THO) | 記録なし | 126 | コードと `en` の display。25 ファイル中 23 ファイルは `ja` の display も持つ | — |
| `jpfhir-*.yaml`、`jp-*.yaml` (`jp-care-level.yaml` を除く)、`mhlw-checkup-*.yaml`、`medication-nocoded.yaml` (22 ファイル) | JP Core、JP-CLINS、JP-eCheckup、jpfhir-terminology の CodeSystem (JAMI)、厚労省の健診コード | ファイルごと。例: JP-CLINS 1.13.0、JP-eCheckup 1.7.0、jpfhir-terminology 2.2606.0 | 116 コード、および JP-CLINS 退院時サマリーの 10 セクション | コードと `en`・`ja` の display | — |
| `dicom-modality.yaml` | DICOM PS3.3 Table C.7-1 (NEMA) | 記録なし | 8 | コードと英語名。`ja` は "the common JIS / JRS (Japan Radiological Society) katakana forms" (ファイルヘッダー) | — |
| `omb-race.yaml`、`omb-ethnicity.yaml` | CDC race and ethnicity CodeSystem (OID 2.16.840.1.113883.6.238)、OMB の区分 | `2024` | 6 + 2 | コードと英語名 | — |
| `bcp-47-language.yaml` | IETF BCP 47 | 記録なし | 2 | 言語タグ | — |
| `jis-x-0401-prefectures.yaml` | JIS X 0401:2010 都道府県コード | `2010` | 47 | 都道府県名から 2 桁コード | — |
| `ucum-aliases.yaml` | UCUM | `2.1` | 10 | clinosim の単位表記から UCUM コード | — |
| `hot7.yaml` | MEDIS HOT7 | `2024` | 0 | システム URI のみ、コードなし (Issue #2347) | — |

`clinosim/codes/data/` のその他のファイルは clinosim のために書かれたもの (例: `condition-short-name.yaml`、`clinosim-*.yaml`、`jp-care-level.yaml`、`drugs.yaml`、`valuesets.yaml`) か、出典の文言なしに clinosim のキーをコードに対応づけるもの (`loinc-maps.yaml`、`snomed-maps.yaml`、`procedure-phrase-to-snomed.yaml`、`procedure-snomed-metadata.yaml`、`icd10-condition-bodysite-crosswalk.yaml`、`frequency-tokens.yaml`) である。`drugs.yaml` (275 薬剤) は RxNorm と YJ のコードを英語・日本語の薬剤名と別名とともに持ち、別名の一部は商品名である。

## 3. その他の場所で参照しているコード

- `clinosim/locale/<country>/code_mapping_*.yaml` は clinosim 内部の名前を ICD-10 / ICD-10-CM、LOINC、JLAC10、RxNorm、K コード、退院時転帰コードに対応づける。持つのはコードだけで、表示名は `clinosim/codes/data/` から解決する。`clinosim/locale/jp/checkup_report_items.yaml` のコメントは厚労省の健診項目名を 5 件引用している。
- モジュールの `reference_data/` は SNOMED CT、LOINC、ICD-10、RxNorm、CVX、K コードを値で参照し、ラベルは clinosim が書いたもの。コードの隣に LOINC の表示文を持つファイルが 1 つある: `clinosim/modules/observation/reference_data/lab_panels.yaml` (英語の `display` を持つパネルコード 8 件。うち 6 件は `loinc_2_83_tx.json` の LOINC 2.83 の designation と一致)。
- `clinosim/` 配下にこれ以外の JSON ファイルはなく、`tests/` に FHIR CodeSystem リソースは git 管理されていない。

## 4. 所有者が公開しているライセンスページ

各行は 2026-11-28 に開いたページとその内容である。引用はそのまま。ページを読めなかった場合、またはこの内容のライセンスが書かれていなかった場合は「ライセンス未確認」とする。

| 用語体系 | 所有者 | 読んだページ (タイトル — URL) | 公表されているライセンス |
|---|---|---|---|
| ICD-10-CM | CMS / NCHS | "ICD-10 \| CMS" — https://www.cms.gov/medicare/coding-billing/icd-10-codes | ファイルの著作権・ライセンスの記載はページにない。**ライセンス未確認。** |
| ICD-10 (WHO) | World Health Organization | "International Statistical Classification of Diseases and Related Health Problems (ICD)" — https://www.who.int/standards/classifications/classification-of-diseases 、"Copyright, Licensing and Permissions" — https://www.who.int/about/policies/publishing/copyright 、"User Guide" — https://icd.who.int/browse10/Help/en | ICD のページがライセンスを示すのは ICD-11 のみ ("ICD-11 is distributed under Creative Commons Attribution-NoDerivs 3.0 IGO license.")。著作権ページには "Licensing of WHO Classifications" の節があり、ICD-11 について述べている。ICD-10 のライセンスの記載は見つからなかった。**ライセンス未確認。** |
| ICD-10 の日本語名称、薬価基準収載品目リスト | 厚生労働省 | 「利用規約・リンク・著作権等｜厚生労働省」 — https://www.mhlw.go.jp/chosakuken/index.html | 「公共データ利用規約（第1.0版）」（PDL1.0）。「権利表記の記載がない限り」適用される。2 つの Excel ファイルに独自の権利表記があるかは確認していない。 |
| LOINC | Regenstrief Institute | https://loinc.org/license/ と https://loinc.org/kb/license/ | どちらも HTTP 403。**ライセンス未確認。** (`clinosim/codes/README.md` は以前 "LOINC License" と記載していた。) |
| SNOMED CT | SNOMED International | "Get SNOMED CT \| SNOMED International" — https://www.snomed.org/get-snomed | "Affiliate License Agreement" を挙げ、"SNOMED International does not charge for Affiliate Licensing or for use of SNOMED CT in Member countries." と記載。 |
| RxNorm | U.S. National Library of Medicine | "RxNorm Terms of Service" — https://www.nlm.nih.gov/research/umls/rxnorm/docs/termsofservice.html | "RxNorm Terms of Service"。最初の文は "The full RxNorm dataset includes government-created and proprietary names and codes for clinical drugs." |
| CPT | American Medical Association | https://www.ama-assn.org/practice-management/cpt/cpt-licensing | HTTP 403。**ライセンス未確認。** |
| CVX | CDC | "IIS: Current HL7 Standard Code Set" — https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx 、"Use of Agency Materials \| Other \| CDC" — https://www.cdc.gov/other/agencymaterials.html | CVX のページにライセンスの記載はない。機関のページは "Most of the information on the CDC and ATSDR websites is not subject to copyright, is in the public domain" で始まる。**CVX のライセンス未確認。** |
| YJ コードと名称 (医薬品HOTコードマスター)、標準病名マスター | MEDIS-DC (一般財団法人医療情報システム開発センター) | 「医薬品HOTコードマスター」 — https://www2.medis.or.jp/hcode/ 、「MEDIS 標準マスター総合サイト」 — https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html 、「ICD10対応標準病名マスター　トップページ」 — https://www2.medis.or.jp/stdcd/byomei/ | HOT のページには条件の記載がない。標準マスターのページは【標準マスターの使用について】の下に「どなたでも自由にダウンロードして使用できます。」「ただし、医療機関以外での使用若しくは配布目的で利用する場合は、「使用許諾申請書（pdf; 97KB）」を提出し、許可を得る必要があります。」「使用許諾を必要とするマスター種は次の通りです。」(続く一覧は「医薬品HOTコードマスター、病名マスター」で始まる)、「ダウンロードしたマスターを改変し配布する場合は、MEDIS-DCの標準マスターを利用したことを必ず明記してください。」と記載。ライセンス名の記載はない。 |
| 医科診療行為マスター | 社会保険診療報酬支払基金 (現 医療情報基盤・診療報酬審査支払機構) | https://www.ssk.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html は「医科診療行為マスター｜医療情報基盤・診療報酬審査支払機構」 — https://www.hpdx.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html にリダイレクトされる | ページにマスターファイルの条件の記載はない。サイト全体の利用条件ページ (`/riyo.html`) は読んでいない。**ライセンス未確認。** |
| JLAC10 | 日本臨床検査医学会 (JSLM) | 「検査項目コード委員会」 — https://www.jslm.org/committees/code/ | 「JLAC10コードについては、従来どおりJLAC10コード表およびJLAC10適用細則に基づき、各利用主体における運用に応じてご利用ください。」ライセンス名の記載はない。**ライセンス未確認。** |
| JP Core、JP-CLINS、JP-eCheckup、jpfhir-terminology (JFAGY を含む) | 日本医療情報学会 (JAMI) FHIR 日本実装検討 WG | "HL7 FHIR Jp Core Implementation Guide(Jp Core実装ガイド)" — https://jpfhir.jp/fhir/core/ | "IG © 2022+ FHIR Japanese implementation research working group in Japan Association of Medical Informatics (JAMI)." ライセンス名の記載はない。パッケージ内のライセンスファイルは読んでいない。**ライセンス未確認。** |
| HL7 Terminology (THO) | HL7 International | https://terminology.hl7.org/license.html 、https://terminology.hl7.org/ 、https://build.fhir.org/ig/HL7/UTG/license.html (いずれも "Redirect File" というタイトルのページでライセンスの文言なし)、https://www.hl7.org/legal/ippolicy.cfm (内容が返らなかった) | **ライセンス未確認。** (`clinosim/codes/README.md` は以前 CC BY-SA 4.0 と記載していた。) |
| UCUM | Regenstrief Institute (UCUM Organization) | "UCUM / License" — https://ucum.org/license | "UCUM Copyright Notice and License" |
| DICOM | NEMA | "Current Edition" — https://www.dicomstandard.org/current | 規格は "copyright owned by the National Electrical Manufacturers Association" と記載。ライセンス名の記載はない。**ライセンス未確認。** |
| CDC race and ethnicity コード、IETF BCP 47、JIS X 0401 | CDC、IETF、JISC | 読んでいない | **ライセンス未確認。** |

tx.fhir.org、RxNav、`fhir.tx.support.r4` パッケージは入手経路として使ったが、それ自体の条件は読んでいない。

## 5. メンテナーへの未決事項

各項目は、それを提起する事実を挙げる。判断のための一覧であり、ここでは答えない。

1. **完全版の YJ CodeSystem。** `JP_MedicationCodeYJ_CS_full.json` は MEDIS 医薬品HOTコードマスターから作った完全なコード体系 (23,923 概念、`content` `complete`) で、実行時に読まれる。その `copyright` フィールドは "MEDIS-DC retains ownership; clinosim redistributes for FHIR terminology resolution alongside the upstream tx-server fragment. Contact hot@medis.or.jp for licensing questions." と書く。MEDIS 標準マスターのページには 4 章に引用した使用許諾申請書と、それが必要なマスター種についての文がある。リポジトリには申請や許諾の記録がない。また `clinosim/codes/authoritative/README.ja.md` は、完全な CodeSystem 定義はそのディレクトリに置かないと書いている。
2. **その他の MEDIS 由来の名称。** `yj_medis_hot_20261031.json` (販売名 268 件)、`yj.yaml` の `ja` (販売名 272 件)、`medis-disease-keyno.yaml` (病名 2 件) は MEDIS マスターの文言を複製している。MEDIS のページには「ダウンロードしたマスターを改変し配布する場合は、MEDIS-DCの標準マスターを利用したことを必ず明記してください。」(4 章) という文がある。リポジトリに帰属表示のファイルはない。
3. **CPT の descriptor。** `cpt.yaml` は英語ラベル付きの CPT コード 95 件を同梱する。ヘッダーは CPT を "proprietary (AMA license)" と書く。AMA のライセンスページは読めなかった。ラベルが AMA の descriptor の文言かどうかは記録がない。
4. **SNOMED CT の文言。** 288 + 12 概念を preferred term、synonym、fully specified name とともに同梱し、`snomed-ct.yaml` は 289 件の英語の語を持つ。SNOMED のページは Affiliate License を挙げ、Member countries に言及している。パッケージは国の制限なく PyPI と GitHub で配布されている。
5. **LOINC の文言。** LONG_COMMON_NAME、SHORTNAME、その他の designation 付きの 373 コードを同梱している。LOINC のライセンスページは読めなかった。
6. **WHO ICD-10 の内容。** `icd10_who_tx.json` は、出典が `complete` とされたパッケージから 427 コードの display、definition、inclusion の文言を複製している。読んだ WHO のページに ICD-10 のライセンスの記載は見つからなかった。
7. **ライセンス名が示されていない日本のマスター。** 医科診療行為マスターの名称 (149)、JLAC10 マスターの名称 (53)、JAMI の CodeSystem の display (2 章) を同梱している。読んだページにライセンス名はない。
8. **帰属表示の文言。** リポジトリには NOTICE ファイルも、どの用語体系の帰属表示もない。`README.md` はこのファイルを指している。
9. **版のメタデータ。** いくつかのファイルの `metadata.version` はスナップショットの版と異なる (`loinc.yaml` 2.76 と 2.83、`snomed-ct.yaml` 2024-03 と 2025-02-01、`icd-10-cm.yaml` 2024 と FY2027)。`rxnorm.yaml`、`yj.yaml`、`k-codes.yaml`、`cpt.yaml` は `2024` とある。どの版を同梱版として示すかは未決。

## 6. コントリビューター向けの規則

コードやコード体系の文言を追加・変更するプルリクエストでは ([`docs/design-guides/code-mapping-and-localization-spec.ja.md`](docs/design-guides/code-mapping-and-localization-spec.ja.md) §8 にも記載):

- 出典 (組織、版またはバージョン、コードと文言を取得したファイルまたはサービス) と、出典が公表しているライセンスの名称と URL を書き、ライセンスを確認できていない出典はその旨を明記する。
- ライセンスを確認していない出典の記述文 (表示名、同義語、定義) は貼り付けない。
- 新しいスナップショット、コード体系、出典はこのファイル (英語版と日本語版) に件数とともに記録する。

## 7. 既存の文書がコントリビューターに伝えていることと、足りないこと

記載されていること:

- [`AGENTS.md`](AGENTS.md) (英語) の "Adding a new code": `clinosim/codes/data/<system>.yaml` を編集する、公式の英語記述の `en` フィールドが必須、出典は権威あるもの "(CMS, NLM, AMA, WHO, JCCLS, MHLW)"。"Diagnosis code coverage" は NLM ICD-10-CM API と WHO ICD-10 ブラウザーを挙げる。
- [`docs/design-guides/code-mapping-and-localization-spec.ja.md`](docs/design-guides/code-mapping-and-localization-spec.ja.md) §8: 体系ごとの照合先の表、コードの登録、スナップショットの更新、対応表の追加、網羅テストの実行。
- [`clinosim/codes/authoritative/README.ja.md`](clinosim/codes/authoritative/README.ja.md): スナップショットごとの出典と取得日、照合の意味、更新手順。
- [`docs/design-guides/code-display-authoritative-sync.ja.md`](docs/design-guides/code-display-authoritative-sync.ja.md): 表示名照合の仕組み。

足りないこと:

- この変更までは、出典のライセンスを求める文書も、何を複製してよいか (コード、表示名、完全なコード体系) を述べる文書もなかった。
- 照合先の一覧が食い違う: `clinosim/codes/README.ja.md` は JLAC10 の出典を JCCLS とし、`AGENTS.md` も照合先に JCCLS を挙げるが、JLAC10 のデータファイルと仕様は JSLM としている。`AGENTS.md` の "Adding a new code" の一覧には、データファイルが挙げる Regenstrief、SNOMED International、MEDIS、CDC、JSLM がない (同ファイルの "Code systems and locale data" の項目は Regenstrief を加えている)。
- `clinosim/codes/authoritative/README.ja.md` の更新手順はリポジトリ外のチェックアウト `../fhir-jp-validator/tx-server-build/` から始まり、抽出スクリプトを「TBD」としている。実際には 3 本 (`scripts/refresh_authoritative_loinc.py`、`scripts/refresh_authoritative_yj.py`、`scripts/refresh_authoritative_yj_full.py`) があり、他のスナップショットにはない。
- スナップショットの `metadata` は同じ事実に別のキーを使う (`source` / `source_package`、`fetched` / `fetched_at` / `extracted_at` / `retrieved`)。`JP_MedicationCodeYJ_CS_full.json` には取得日がない。新しいスナップショットの来歴フィールドを定める文書はない。
- `clinosim/codes/README.ja.md` の「ライセンスと出典」の一覧は、根拠のページを示さずにライセンス条件を書いていた。現在はこのファイルを指している。
