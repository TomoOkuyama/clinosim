# Third-party terminologies bundled with clinosim

[日本語](THIRD_PARTY_TERMINOLOGIES.ja.md)

clinosim is MIT-licensed (see [`LICENSE`](LICENSE)). The repository also ships codes and code-system text taken from third-party terminologies. This file lists, for each of them, what is bundled, where it came from and which license page the owner publishes. It records facts only; it contains no legal conclusion and does not say what a user may or may not do with the data. Licensing decisions belong to the maintainer (see [Open questions for the maintainer](#5-open-questions-for-the-maintainer)).

- **As of:** 2026-11-28. The facts come from the files' own `metadata` blocks and header comments, [`clinosim/codes/authoritative/README.md`](clinosim/codes/authoritative/README.md) and counts made on the files; the license pages in section 4 were opened on 2026-11-28.
- **"License not confirmed"** means that the owner's license page could not be read, or that the page read names no license for this content. It is not a statement that no license applies.
- **What is distributed:** the sdist includes `clinosim/**/*.yaml` and `clinosim/**/*.json` (`[tool.hatch.build.targets.sdist]` in [`pyproject.toml`](pyproject.toml)), so every file below is in it. The wheel target packages `clinosim` (`packages = ["clinosim"]`), and the comment on the sdist section states that the wheel ships the YAML data without a hint; the wheel contents were not built and listed for this file.
- **Not bundled:** the JP-CLINS `clinical-information-sharing` and `jpfhir-terminology` FHIR packages. The lab-coding loader reads them at run time from `$CLINOSIM_JP_CLINS_PKG_DIR`, the `~/.fhir/packages/` cache or a sibling `../fhir-jp-validator` checkout (`clinosim/modules/output/fhir_r4/labs/coding_package.py::_find_pkg_files`).

## 1. Snapshots in `clinosim/codes/authoritative/`

These JSON files are verification references: unit tests compare the curated displays of `clinosim/codes/data/` with them, and `yj_medis_hot_used.json` is also read at run time by `clinosim/codes/yj.py`. "Entries" is the number of concepts in the file (`len(concept)`, or the number of keys of `codes`).

| File | Source as recorded in the file | Edition / version as recorded | Obtained (date, from) | What is copied | Entries |
|---|---|---|---|---|---|
| `icd10cm_2027_cms.json` | CMS ICD-10-CM code descriptions in tabular order | FY2027 (`icd10cm_order_2027.txt`) | 2026-11-10, `https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip`; later additions from the same file | code, CMS long description, billable flag | 602 |
| `icd10_who_tx.json` | WHO ICD-10 as packaged in `fhir.tx.support.r4 0.37.0` (`CodeSystem-icd-10.json`, content `complete`) | package 0.37.0; later additions "ICD-10-EN 2019-covid-expanded" on tx.fhir.org | 2026-07-19, `https://github.com/iryohjoho/fhir-jp-validator` `tx-server-build/`; additions by tx.fhir.org `$lookup` from 2026-11-16 | code, display, definition (409), properties such as kind / parent / inclusion (421), designations (4) | 427 |
| `icd10_mhlw_2013_ja.json` | 厚生労働省 疾病、傷害及び死因の統計分類 基本分類表 (ICD-10 2013年版準拠) | 2013 | 2026-11-01, `https://www.mhlw.go.jp/toukei/sippei/xls/kihon2013.xlsx`; additions from the same file to 2026-11-27 | code, official Japanese name | 475 (the source table has 15,296 codes per the metadata) |
| `loinc_2_83_tx.json` | LOINC as served by tx.fhir.org | LOINC 2.83 | 2026-11-10, `https://tx.fhir.org/r4/CodeSystem/$lookup` | code, LONG_COMMON_NAME, SHORTNAME (367), other English designations, status | 373 |
| `snomed_ct_tx.json` | SNOMED CT International Edition via tx.fhir.org | `http://snomed.info/sct/900000000000207008/version/20250201`; 8 concepts added from edition 20260701 | 2026-11-10 (additions 2026-11-24 and 2026-11-26), tx.fhir.org `$lookup` | code, preferred term, synonyms, fully specified name | 288 |
| `snomed_allergy_tx.json` | SNOMED CT International Edition via tx.fhir.org | 2025-02-01 | 2026-11-10, tx.fhir.org R4 `CodeSystem/$lookup` | code, display, fully specified name, inactive flag | 12 |
| `rxnorm_rxnav_snapshot.json` | RxNav (NLM) `/REST/rxcui/{code}/historystatus` | not recorded | 2026-10-28 (SCD entries 2026-11-09), RxNav REST API | RxCUI, status, name, term type | 1,451 |
| `yj_medis_hot_used.json` | MEDIS-DC 医薬品HOTコードマスター (`MEDIS20260831.TXT`); filtered from `JP_MedicationCodeYJ_CS_full.json`, the complete YJ CodeSystem (23,923 concepts, `content` `complete`) that the repository shipped until Issue #4026 | 2026.8.31 (the removed file's CodeSystem `version`) | fetch date not recorded (the removed file recorded none; its refresh script named the download page `https://www2.medis.or.jp/hcode/`); filtered 2026-11-28 | code, and the `ja` name of the code in `yj.yaml` (no other master text) | 272 |
| `yj_medis_hot_20261031.json` | MEDIS-DC 医薬品HOTコードマスター (2026-10-31) and the jpfhir-terminology 2.2606.0 YJ CodeSystem (fragment) | master 2026-10-31; package 2.2606.0 | 2026-11-10, `https://www2.medis.or.jp/hcode/moto_data/h20261031.zip` | code, product name (販売名), other product names (2) | 268 |
| `yj_tx_fragment.json` | jpfhir-terminology 2.2606.0 `CodeSystem-jp-medicationcodeyj-cs.json` (content `fragment`) | 2.2606.0 | 2026-07-19, `https://github.com/iryohjoho/fhir-jp-validator` `tx-server-build/` | code, display | 9 |
| `yj_mhlw_snapshot.json` | 厚生労働省 薬価基準収載品目リスト及び後発医薬品に関する情報 (令和8年6月12日適用) | applied 2026-06-12 | 2026-10-31, `https://www.mhlw.go.jp/topics/2026/04/xls/tp20260612-01_05.xlsx` | per YJ code: ingredient name, product name (3 with the list's own code) | 224 |
| `shinryo_koui_ssk_20261013_ja.json` | 社会保険診療報酬支払基金 基本マスター 医科診療行為マスター (`s_ALL20261013.csv`; some rows from `s_ALL20261102.csv`) | 2026-10-13 and 2026-11-02 masters | 2026-11-01 (rows added 2026-11-06, 2026-11-21, 2026-11-23), `https://www.ssk.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html` | per code, up to 8 master names | 49 codes, 149 names |
| `jlac10_jslm_137.json` | 日本臨床検査医学会 (JSLM) 検査項目コード委員会「JLAC10コード表_臨床検査」 | version 137 (2026-06), source sha256 recorded | 2026-11-10, `https://www.jslm.org/committees/code/137jlac10_1.xlsx` (sheet 分析物コード) | analyte code, Japanese name, abbreviation (37), English name | 53 |
| `jfagy_jpfhir_terminology.json` | jpfhir-terminology 2.2606.0 (the JFAGY allergen CodeSystems) | package 2.2606.0; CodeSystem versions 2026.5.31, 2026.6.15, 2024.7.9 | 2026-11-10, `https://jpfhir.jp/fhir/core/terminology/igv-2.2606.0/package.tgz` (sha256 recorded) | system, CodeSystem version, content mode, code, display | 6 |

## 2. Curated code files in `clinosim/codes/data/` that copy source text

`clinosim/codes/data/` holds 85 YAML files. The table lists those whose entries carry codes of a third-party system together with text from that system (display, name). "Version" is `metadata.version` as written in the file; where it differs from the snapshot of section 1, both are shown. "Match" was counted on 2026-11-28 by comparing each entry with the snapshot.

| File | System and owner as recorded | Version recorded | Entries | What is copied | Match with the snapshot |
|---|---|---|---|---|---|
| `icd-10-cm.yaml` | ICD-10-CM, CMS / NCHS | `2024` (snapshot: FY2027) | 621 (`en`), 193 (`ja`) | `en` = CMS long description; `ja` on CM-only codes is a clinosim translation (file header) | 602 of 621 `en` equal the snapshot (19 codes not in it) |
| `icd-10.yaml` | WHO ICD-10; `ja` from MHLW 基本分類表 | `WHO 2019` | 491 | `en` = WHO display; `ja` = MHLW official name, verbatim | `en`: 427 of 491 equal a WHO snapshot term; `ja`: 475 of 491 equal the MHLW snapshot |
| `loinc.yaml` | LOINC, Regenstrief Institute | `2.76` (snapshot: 2.83) | 373 | `en` = a LOINC designation (LONG_COMMON_NAME unless noted); the source of `ja` is not recorded | 373 of 373 |
| `snomed-ct.yaml` | SNOMED CT, SNOMED International | `2024-03` (snapshot: 2025-02-01 / 20260701) | 289 | `en` = preferred term, synonym or FSN; the source of `ja` is not recorded | 286 of 289 |
| `rxnorm.yaml` | RxNorm, NLM | `2024` | 1,450 (`en`), 241 (`ja`) | `en` = drug name | 1,269 of 1,450 `en` equal the RxNav name |
| `rxnorm_scd.yaml` | RxNorm SCD via NLM RxNav | fetched 2026-11-09 | 204 drugs, 1,225 RxCUIs | RxCUI, strength, unit (no names) | — |
| `yj.yaml` | YJ code (MHLW 薬価基準 YJ / MEDIS HOT-YJ master / JP Core) | `2024` | 272 | `ja` = product name (販売名); `en` = English ingredient name | `ja`: 268 equal the MEDIS 2026-10-31 snapshot; all 272 codes are in `yj_medis_hot_used.json` |
| `jlac10.yaml` | JLAC10, JSLM | `137` | 53 | `ja` = master name or abbreviation; `en` English name | 48 of 53 `ja` equal the master's name or abbreviation |
| `k-codes.yaml` | 診療報酬点数表 (MHLW), checked against the 診療行為マスター | `2024` | 49 | `ja` = master name, or the 区分 name it starts with (file header); `en` = an English rendering (file header) | 23 of 49 `ja` equal a master name exactly |
| `cpt.yaml` | CPT, American Medical Association | `2024` | 95 | English and Japanese labels. The header says "CPT is proprietary (AMA license)" and "not yet machine-verified"; whether the `en` labels are AMA descriptor text is not recorded | no snapshot |
| `cvx.yaml` | CVX, CDC IIS | `2026-06` | 39 | `en` checked against the CDC CVX list (file header) | no snapshot |
| `medis-disease-keyno.yaml` | MEDIS 標準病名マスター 病名管理番号, taken from the jpfhir-terminology 2.2606.0 CodeSystem `medis-codesystem-diseasekanricodes` (fragment of MEDIS 5.18) | `5.18-fragment-seed` | 2 | code and MEDIS name | — |
| `mhlw-medication-usage-code.yaml` | MHLW MedicationUsage_ePrescription CodeSystem (jpfhir-terminology 2.2606.0) | `2.2606.0` | 13 | code and Japanese usage text | — |
| `hl7-*.yaml` (25 files) | HL7 Terminology (THO) | not recorded | 126 | code with an `en` display, and a `ja` display in 23 of the 25 files | — |
| `jpfhir-*.yaml`, `jp-*.yaml` (except `jp-care-level.yaml`), `mhlw-checkup-*.yaml`, `medication-nocoded.yaml` (22 files) | JP Core, JP-CLINS, JP-eCheckup and jpfhir-terminology CodeSystems (JAMI), MHLW health-checkup codes | per file, e.g. JP-CLINS 1.13.0, JP-eCheckup 1.7.0, jpfhir-terminology 2.2606.0 | 116 codes, plus 10 JP-CLINS eDischargeSummary sections | code with `en` and `ja` displays | — |
| `dicom-modality.yaml` | DICOM PS3.3 Table C.7-1 (NEMA) | not recorded | 8 | code with an English name; `ja` = "the common JIS / JRS (Japan Radiological Society) katakana forms" (file header) | — |
| `omb-race.yaml`, `omb-ethnicity.yaml` | CDC race and ethnicity CodeSystem (OID 2.16.840.1.113883.6.238), OMB categories | `2024` | 6 + 2 | code and English name | — |
| `bcp-47-language.yaml` | IETF BCP 47 | not recorded | 2 | language tags | — |
| `jis-x-0401-prefectures.yaml` | JIS X 0401:2010 都道府県コード | `2010` | 47 | prefecture name to 2-digit code | — |
| `ucum-aliases.yaml` | UCUM | `2.1` | 10 | clinosim unit token to UCUM code | — |
| `hot7.yaml` | MEDIS HOT7 | `2024` | 0 | system URI only, no codes (Issue #2347) | — |

The other files of `clinosim/codes/data/` are written for clinosim (for example `condition-short-name.yaml`, `clinosim-*.yaml`, `jp-care-level.yaml`, `drugs.yaml`, `valuesets.yaml`) or map clinosim keys to codes without source text (`loinc-maps.yaml`, `snomed-maps.yaml`, `procedure-phrase-to-snomed.yaml`, `procedure-snomed-metadata.yaml`, `icd10-condition-bodysite-crosswalk.yaml`, `frequency-tokens.yaml`). `drugs.yaml` (275 drugs) holds RxNorm and YJ codes with English and Japanese drug names and aliases, some of which are brand names.

## 3. Codes referenced elsewhere

- `clinosim/locale/<country>/code_mapping_*.yaml` map clinosim-internal names to ICD-10 / ICD-10-CM, LOINC, JLAC10, RxNorm, K codes and discharge-disposition codes. They hold codes only; their displays are resolved from `clinosim/codes/data/`. Comments in `clinosim/locale/jp/checkup_report_items.yaml` quote five MHLW health-checkup item names.
- Module `reference_data/` files refer to SNOMED CT, LOINC, ICD-10, RxNorm, CVX and K codes by value with clinosim-written labels. One file carries LOINC display text next to the codes: `clinosim/modules/observation/reference_data/lab_panels.yaml` (8 panel codes with an English `display`, 6 of which equal a LOINC 2.83 designation in `loinc_2_83_tx.json`).
- No other JSON file under `clinosim/`, and no FHIR CodeSystem resource in `tests/`, is tracked in git.

## 4. License pages published by the owners

Each row gives the page that was opened on 2026-11-28 and what it shows. Quotes are verbatim. A row says "license not confirmed" when the page could not be read or names no license for this content.

| Terminology | Owner | Page read (title — URL) | License as published |
|---|---|---|---|
| ICD-10-CM | CMS / NCHS | "ICD-10 \| CMS" — https://www.cms.gov/medicare/coding-billing/icd-10-codes | The page has no copyright or license statement for the files. **License not confirmed.** |
| ICD-10 (WHO) | World Health Organization | "International Statistical Classification of Diseases and Related Health Problems (ICD)" — https://www.who.int/standards/classifications/classification-of-diseases ; "Copyright, Licensing and Permissions" — https://www.who.int/about/policies/publishing/copyright ; "User Guide" — https://icd.who.int/browse10/Help/en | The ICD page names a license for ICD-11 only ("ICD-11 is distributed under Creative Commons Attribution-NoDerivs 3.0 IGO license."). The copyright page has a section "Licensing of WHO Classifications" that refers to ICD-11. No license statement for ICD-10 was found. **License not confirmed.** |
| ICD-10 Japanese names, drug-price list | 厚生労働省 (MHLW) | 「利用規約・リンク・著作権等｜厚生労働省」 — https://www.mhlw.go.jp/chosakuken/index.html | 「公共データ利用規約（第1.0版）」（PDL1.0）, applied "権利表記の記載がない限り" (unless a rights notice says otherwise). Whether the two Excel files carry their own rights notice was not checked. |
| LOINC | Regenstrief Institute | https://loinc.org/license/ and https://loinc.org/kb/license/ | Both returned HTTP 403. **License not confirmed.** (`clinosim/codes/README.md` previously named it "LOINC License".) |
| SNOMED CT | SNOMED International | "Get SNOMED CT \| SNOMED International" — https://www.snomed.org/get-snomed | The page names the "Affiliate License Agreement" and states "SNOMED International does not charge for Affiliate Licensing or for use of SNOMED CT in Member countries." |
| RxNorm | U.S. National Library of Medicine | "RxNorm Terms of Service" — https://www.nlm.nih.gov/research/umls/rxnorm/docs/termsofservice.html | "RxNorm Terms of Service". Its first sentence: "The full RxNorm dataset includes government-created and proprietary names and codes for clinical drugs." |
| CPT | American Medical Association | https://www.ama-assn.org/practice-management/cpt/cpt-licensing | HTTP 403. **License not confirmed.** |
| CVX | CDC | "IIS: Current HL7 Standard Code Set" — https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx ; "Use of Agency Materials \| Other \| CDC" — https://www.cdc.gov/other/agencymaterials.html | The CVX page has no license statement. The agency page begins: "Most of the information on the CDC and ATSDR websites is not subject to copyright, is in the public domain". **License for CVX not confirmed.** |
| YJ codes and names (医薬品HOTコードマスター), 標準病名マスター | MEDIS-DC (一般財団法人医療情報システム開発センター) | 「医薬品HOTコードマスター」 — https://www2.medis.or.jp/hcode/ ; 「MEDIS 標準マスター総合サイト」 — https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html ; 「ICD10対応標準病名マスター　トップページ」 — https://www2.medis.or.jp/stdcd/byomei/ | The HOT page states no terms. The standard-master page, under 【標準マスターの使用について】, states 「どなたでも自由にダウンロードして使用できます。」, 「ただし、医療機関以外での使用若しくは配布目的で利用する場合は、「使用許諾申請書（pdf; 97KB）」を提出し、許可を得る必要があります。」 and 「使用許諾を必要とするマスター種は次の通りです。」 followed by a list that begins 「医薬品HOTコードマスター、病名マスター」, and 「ダウンロードしたマスターを改変し配布する場合は、MEDIS-DCの標準マスターを利用したことを必ず明記してください。」 No license name is given. |
| 医科診療行為マスター | 社会保険診療報酬支払基金 (now 医療情報基盤・診療報酬審査支払機構) | https://www.ssk.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html redirects to 「医科診療行為マスター｜医療情報基盤・診療報酬審査支払機構」 — https://www.hpdx.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html | No terms for the master files on the page; the site-wide terms page (`/riyo.html`) was not read. **License not confirmed.** |
| JLAC10 | 日本臨床検査医学会 (JSLM) | 「検査項目コード委員会」 — https://www.jslm.org/committees/code/ | 「JLAC10コードについては、従来どおりJLAC10コード表およびJLAC10適用細則に基づき、各利用主体における運用に応じてご利用ください。」 No license is named. **License not confirmed.** |
| JP Core, JP-CLINS, JP-eCheckup, jpfhir-terminology (incl. JFAGY) | 日本医療情報学会 (JAMI) FHIR 日本実装検討 WG | "HL7 FHIR Jp Core Implementation Guide(Jp Core実装ガイド)" — https://jpfhir.jp/fhir/core/ | "IG © 2022+ FHIR Japanese implementation research working group in Japan Association of Medical Informatics (JAMI)." No license is named. The license files inside the packages were not read. **License not confirmed.** |
| HL7 Terminology (THO) | HL7 International | https://terminology.hl7.org/license.html, https://terminology.hl7.org/ and https://build.fhir.org/ig/HL7/UTG/license.html (each served a page titled "Redirect File" with no license text); https://www.hl7.org/legal/ippolicy.cfm (no content returned) | **License not confirmed.** (`clinosim/codes/README.md` previously stated CC BY-SA 4.0.) |
| UCUM | Regenstrief Institute (UCUM Organization) | "UCUM / License" — https://ucum.org/license | "UCUM Copyright Notice and License" |
| DICOM | NEMA | "Current Edition" — https://www.dicomstandard.org/current | The page says the standard's "copyright owned by the National Electrical Manufacturers Association"; no license is named. **License not confirmed.** |
| CDC race and ethnicity codes, IETF BCP 47, JIS X 0401 | CDC, IETF, JISC | not read | **License not confirmed.** |

tx.fhir.org, RxNav and the `fhir.tx.support.r4` package were used as distribution channels; their own terms were not read.

## 5. Open questions for the maintainer

Each question names the facts that raise it. They are listed for a decision, not answered here.

1. **The complete YJ CodeSystem.** Until Issue #4026 the repository shipped `JP_MedicationCodeYJ_CS_full.json`, a complete code system (23,923 concepts, `content` `complete`) built from the MEDIS 医薬品HOTコードマスター and read at run time; its `copyright` field said "MEDIS-DC retains ownership; clinosim redistributes for FHIR terminology resolution alongside the upstream tx-server fragment. Contact hot@medis.or.jp for licensing questions." The file is no longer in the source tree or in a package built from it: `yj_medis_hot_used.json` lists the 272 codes of `yj.yaml`, all of which the full file listed, with the names `yj.yaml` already held, and the complete file remains in the git history and in any package built before that change. The MEDIS standard-master page carries the sentences on 使用許諾申請書 and on the masters that need it quoted in section 4. The repository records no application or permission. The question that remains open is whether the shipped YJ codes and names, and the file in the history and in earlier packages, need any action.
2. **Other MEDIS-derived names.** `yj_medis_hot_20261031.json` (268 product names), the `ja` field of `yj.yaml` (272 product names, repeated in `yj_medis_hot_used.json`) and `medis-disease-keyno.yaml` (2 disease names) copy MEDIS master text. The MEDIS page carries the sentence 「ダウンロードしたマスターを改変し配布する場合は、MEDIS-DCの標準マスターを利用したことを必ず明記してください。」 (section 4); the repository has no attribution file.
3. **CPT descriptors.** `cpt.yaml` ships 95 CPT codes with English labels. Its header calls CPT "proprietary (AMA license)"; the AMA license page could not be read; whether the labels are AMA descriptor text is not recorded.
4. **SNOMED CT text.** 288 + 12 concepts are shipped with preferred terms, synonyms and fully specified names, and `snomed-ct.yaml` carries 289 English terms. The SNOMED page names an Affiliate License and refers to Member countries; the package is distributed through PyPI and GitHub without a country restriction.
5. **LOINC text.** 373 codes with LONG_COMMON_NAME, SHORTNAME and other designations are shipped; the LOINC license page could not be read.
6. **WHO ICD-10 content.** `icd10_who_tx.json` copies displays, definitions and inclusion terms of 427 codes from a package whose source is marked `complete`; no ICD-10 license statement was found on the WHO pages read.
7. **Japanese masters without a named license.** 医科診療行為マスター names (149), JLAC10 master names (53) and the JAMI CodeSystem displays (section 2) are shipped; the pages read name no license.
8. **Attribution text.** The repository has no NOTICE file and no attribution text for any terminology; `README.md` points to this file.
9. **Version metadata.** `metadata.version` of several files differs from the edition of their snapshot (`loinc.yaml` 2.76 vs 2.83, `snomed-ct.yaml` 2024-03 vs 2025-02-01, `icd-10-cm.yaml` 2024 vs FY2027); `rxnorm.yaml`, `yj.yaml`, `k-codes.yaml` and `cpt.yaml` say `2024`. Which edition should be stated as the bundled one is open.

## 6. Contributor rule

When a pull request adds or changes codes or code-system text (also stated in [`docs/design-guides/code-mapping-and-localization-spec.md`](docs/design-guides/code-mapping-and-localization-spec.md) §8):

- name the source (organization, edition or version, the file or service the code and its text came from) and its license name and URL as the source publishes them, and flag a source whose license has not been confirmed;
- do not paste descriptor text (display names, synonyms, definitions) from a source whose license has not been checked;
- record a new snapshot, a new code system or a new source in this file (en and ja), with its counts.

## 7. What the existing docs tell a contributor, and what is missing

What is there:

- [`AGENTS.md`](AGENTS.md) "Adding a new code": edit `clinosim/codes/data/<system>.yaml`, an `en` field with the official English description is required, the source must be authoritative "(CMS, NLM, AMA, WHO, JCCLS, MHLW)"; "Diagnosis code coverage" names the NLM ICD-10-CM API and the WHO ICD-10 browser.
- [`docs/design-guides/code-mapping-and-localization-spec.md`](docs/design-guides/code-mapping-and-localization-spec.md) §8: a table of the authority per system, register the code, update the snapshot, add the mapping, run the coverage tests.
- [`clinosim/codes/authoritative/README.md`](clinosim/codes/authoritative/README.md): one row per snapshot with source and fetch date, the cross-check semantics, a refresh workflow.
- [`docs/design-guides/code-display-authoritative-sync.md`](docs/design-guides/code-display-authoritative-sync.md): the display cross-check framework.

Where it is incomplete:

- Until this change no document asked for the license of a source, and no document said what may be copied (codes, display names, full code systems).
- The authority lists disagree: `clinosim/codes/README.md` names JCCLS as the source of JLAC10 and `AGENTS.md` lists JCCLS among the authorities, while the JLAC10 data files and the spec name JSLM. The "Adding a new code" list of `AGENTS.md` does not name Regenstrief, SNOMED International, MEDIS, CDC or JSLM, which the data files cite (its "Code systems and locale data" bullet adds Regenstrief).
- The refresh workflow of `clinosim/codes/authoritative/README.md` starts from `../fhir-jp-validator/tx-server-build/`, a checkout outside the repository, and calls the extraction scripts "TBD"; three exist (`scripts/refresh_authoritative_loinc.py`, `scripts/refresh_authoritative_yj.py`, `scripts/refresh_authoritative_yj_used.py`), the other snapshots have none.
- The snapshot `metadata` blocks use different keys for the same facts (`source` / `source_package`; `fetched` / `fetched_at` / `extracted_at` / `retrieved`), and `yj_medis_hot_used.json` records no fetch date (`fetched` is `null`, as the file it was filtered from recorded none); no document prescribes the provenance fields of a new snapshot.
- The "Licensing and provenance" list of `clinosim/codes/README.md` stated license terms without the pages they came from; it now points here.
