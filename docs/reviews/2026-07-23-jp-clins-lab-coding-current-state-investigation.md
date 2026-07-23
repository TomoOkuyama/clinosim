# JP-CLINS 検体検査結果コーディング 現状調査 report

**作成**: 2026-07-23(session 66)
**依頼スコープ**: 調査 only、コード変更・PR 作成なし
**対象 spec**: JP-CLINS v1.12.0 `JP_Observation_LabResult_eCS`
  https://jpfhir.jp/fhir/eCS/ig/StructureDefinition-JP-Observation-LabResult-eCS.html
**dataset**: v29(master `f0adf356ca`、JP p=100 seed=300、434 patients、lab category Observation 2,523 件)

---

## 0. 依頼者が確定した spec 事実(要点)

| # | 事項 | 内容 |
|---|---|---|
| 1 | 使用可能 CodeSystem | 7 種のみ(LOINC は使わない) — JLAC10/JLAC11 の CoreLabo(43 項目)、JLAC10/JLAC11 の InfectionLabo(5 項目)、MEDIS 17 桁一般、Uncoded、LocalCode |
| 2 | slicing | Open、discriminator = `value:system` + `value:display` |
| 3 | Fixed Value display | 43 + 5 項目の slice は display 固定(例: `coreLaboJLAC10/k` → `K`、`coreLaboJLAC10/ast` → `AST`)、v6 の `MedicationCodeNocoded_CS#NOCODED` 12,891 発火と同型 |
| 4 | display 自由 | MEDIS + LocalCode slice のみ |
| 5 | binding | 全て required、text-only 回避不可 |
| 6 | 適用規則 | LocalCode は常に必須。43 / 5 項目該当なら JLAC 必須。非該当なら MEDIS 推奨・不可時 Uncoded 必須 → **最低 2 coding**、`code.text` は 1..1 |
| 7 | display / text 文字種 | 散文規定、半角カタカナ・全角空白・制御文字禁止(invariant なし、validator 自動検出しない可能性) |
| 8 | Prohibited | valueBoolean/Integer/Range/Ratio/SampledData/Time/DateTime/Period が 0..0、`specimen` 1..1 必須、5 情報送信時 `hasMember` 使用不可、細菌検査/病理はスコープ外 |

---

## 1. 現状の emit 内容

### 1.1 事実

lab category Observation の `code.coding[]` 実測(v29、2,523 件):

| Priority | system URI | 件数 | code 桁数分布 |
|---|---|---:|---|
| primary | `urn:oid:1.2.392.200119.4.1005`(JSLM JLAC10 一般 OID) | 2,523 | 5 桁のみ |
| secondary | `http://loinc.org` | 2,509 | 6 桁=2,259 / 5 桁=148 / 7 桁=102 |

**実 emit sample**:

```
system=urn:oid:1.2.392.200119.4.1005  code=2A010  display=白血球数
system=http://loinc.org               code=6690-2 display=Leukocytes [#/volume] in Blood by Automated count
```

- **primary + secondary の 2 coding 構成**。primary が JLAC10 5 桁 analyte code、secondary は JP dual-coding 用の LOINC。
- 現状 emit は spec が定義する 7 CS のいずれにも system URI 一致していない(JLAC10 OID は JSLM 汎用、CoreLabo/InfectionLabo の JP-CLINS canonical URI ではない)。
- 17 桁 JLAC10 完全形 code は **0 件**(全 5 桁分析物コード)。
- LOINC は spec 定義外 system(Open slice なので rejection ではないが、Fixed Value display slice には該当しない)。

### 1.2 移行影響見積り

- **primary system URI 差替え + 17 桁化**: `_BUILTIN_URIS["jlac10"]` 差替えだけでは不足。CoreLabo(43) / InfectionLabo(5) / MEDIS 一般 の 3 種を項目ごとに分岐する dispatcher が必要。
- **secondary LOINC の扱い**: spec 外 system なので削除候補。ただし US path は LOINC 単独、削除すると `_build_lab_observation` が country 分岐でさらに複雑化。
- **2 coding 化の必須要件**: LocalCode を常に追加する path が必要。分析物 5 桁 → 施設内 code 生成 (仮 slug でも FHIR-legal な CodeSystem URI + code + Fixed display "施設固有コード項目")。
- 影響 module: `clinosim/modules/output/_fhir_observations.py`(`_build_lab_observation`)、`clinosim/codes/loader.py`(`_COUNTRY_SYSTEM_KEYS`/`_BUILTIN_URIS`)、`clinosim/locale/jp/code_mapping_lab.yaml`(5→17 桁への実 mapping 再整備)、`clinosim/codes/data/jlac10.yaml`(display 差替え、Fixed Value 対応)。

---

## 2. 対象 profile

### 2.1 事実

`meta.profile` に 3 stack:

```
http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult   (JP Core)
http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common
http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS (JP-CLINS)
```

- JP Core + JP-CLINS 両方宣言。validator は両 profile の制約を評価する。
- `JP_Observation_LabResult_eCS` が要求する 7 CS + Fixed Value display slice に対して、現状 data は 1 slice も match しない(system URI 不一致 + 17 桁 code 不在 + display Fixed 制約未考慮)。

### 2.2 移行影響見積り

- profile 宣言は既に一致済(取り外し不要)。data 側を profile 要求に合わせる作業のみが scope。
- ただし [[feedback_profile_assertion_requires_data_completeness]](session 66 制定 rule)により、data completeness が満たされるまで PR chain 内で `JP_Observation_LabResult_eCS` を「事実上 no-op assertion」として残す状態は cascade regression vector になり得るため、data 実装 → profile 宣言 の順序を守る必要。

---

## 3. 43 項目 / 感染症 5 項目 カバー率

### 3.1 事実

現行 34 unique display の件数分布(降順、v29 実測):

| # | display | 件数 | 想定 CoreLabo/InfectionLabo/一般 判定 (spec 参照要) |
|---|---|---:|---|
| 1 | クレアチニン | 478 | CoreLabo 濃厚(CRE) |
| 2 | グルコース | 393 | CoreLabo 濃厚(GLU) |
| 3 | カリウム | 271 | CoreLabo 濃厚(K) |
| 4 | ナトリウム | 214 | CoreLabo 濃厚(Na) |
| 5 | 白血球数 | 160 | CoreLabo 濃厚(WBC) |
| 6 | AST | 154 | CoreLabo 濃厚(AST) |
| 7 | ALT | 149 | CoreLabo 濃厚(ALT) |
| 8 | CRP | 134 | CoreLabo 濃厚 |
| 9 | ヘモグロビン | 121 | CoreLabo 濃厚(Hb) |
| 10 | 尿素窒素 | 61 | CoreLabo 濃厚(BUN) |
| 11 | プロトロンビン時間 | 43 | CoreLabo 濃厚(PT-活性% or PT-INR) |
| 12-15 | 動脈血 pH / pCO2 / pO2 / 重炭酸塩 | 各 38 | 血液ガス、CoreLabo 該当かは spec 43 項目リスト確認要 |
| 16 | BNP | 36 | 循環器 marker、43 項目に含まれるかは要確認 |
| 17-19 | カルシウム / 血小板 / 乳酸 | 各 27 | Ca は CoreLabo 濃厚、Plt は CoreLabo 濃厚、Lactate は 43 に含まれる可能性中 |
| 20-21 | トロポニン I / CK-MB | 各 16 | 循環器 marker、43 に含まれる可能性中 |
| 22-23 | 培養同定 / 薬剤感受性 | 各 7 | **spec 明示スコープ外(細菌検査)** |
| 24-25 | HbA1c / アルブミン | 各 6 | HbA1c CoreLabo、Alb CoreLabo 濃厚(ALB) |
| 26-28 | TG / HDL / プロカルシトニン | 各 4 | TG/HDL CoreLabo 濃厚、Procalcitonin は 43 外の可能性中 |
| 29-33 | eGFR / aPTT / D-dimer / TSH / Fibrinogen | 各 1 | 43 該当は eGFR/aPTT/Fibrinogen 濃厚、D-dimer/TSH は要確認 |
| 34 | コレステロール | 1 | CoreLabo 濃厚(T-Cho) |

- **micro カバー計算(粗)**: CoreLabo 濃厚 ≈ 上位 24 unique の大部分 → 総 2,523 件のうち **2,300+ 件(90%+)は 43 項目に該当する見込み**。
- **感染症 5 項目**(梅毒/HBs/HCV/HIV 系): 現状 emit **0 件**。生成 profile に該当項目が入っていない。
- **スコープ外(細菌検査)**: 培養同定 + 薬剤感受性 の 14 件 → JP-CLINS スコープ外、lab result 移行では `_bb_microbiology` 側で対応、この profile とは別扱い。
- **spec 43 項目正式リスト・identifier**(K / ALB / AST / ... / PT-活性% / 血液型-ABO 等)の完全 mapping table は clinosim/ 内に無い。マップ実施には spec doc 参照必要。

### 3.2 移行影響見積り

- 上位 24 項目の分析物 5 桁 code → 17 桁 CoreLabo code への mapping table 新設が必要。各項目ごとに材料・測定法・結果識別を determine する。
- 43 項目 slice ごとの Fixed display に emit 側を合わせる(例: `カリウム` → `K`)。
- 感染症 5 項目は現状 emit 0 = 実装対象追加なら疾患 protocol 側で該当分析物を発生させる scope 拡張が必要(scope 外の可能性高い)。
- 影響 module: `clinosim/locale/jp/code_mapping_lab.yaml`(全面書き替え)、`clinosim/codes/data/`(CoreLabo/InfectionLabo/MEDIS 用の新 CS data 3 個)、`_build_lab_observation` の code dispatch logic 全面書き替え、43 項目 slice 名称の Fixed display registry。

---

## 4. system URI ハードコード分岐箇所の洗い出し

### 4.1 事実

現行の system URI 依存 branching(walker + builder + audit + eval):

| # | Location | 種類 | 判定 key | 影響 |
|---|---|---|---|---|
| 1 | `_fhir_common.py:281,315` | builder | `is_japanese_only_display_system(system_key)` | English 二次 coding 抑制、`icd-10-mhlw` のみ現状該当 |
| 2 | `fhir_r4_adapter.py:2087-2124` | walker `_strip_japanese_display_on_english_only_systems` | prefix match `_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES` = `(http://loinc.org, http://snomed.info/sct, http://terminology.hl7.org/, http://hl7.org/fhir/, http://dicom.nema.org/, http://unitsofmeasure.org)` | JP output で English-only CS の Japanese display 削除 |
| 3 | `fhir_r4_adapter.py:1760-1763` | builder(dosage系) | `system_uri.startswith(_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES)` + `lang != "en"` | 同上、dosage.route 用 |
| 4 | `fhir_r4_adapter.py:1887` | Condition builder | `c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM` | MEDIS disease KeyNumber 有無判定 |
| 5 | `fhir_r4_adapter.py:1931` | Observation identifier | `i.get("system") == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM` | identifier slice min=1 確保 |
| 6 | `fhir_r4_adapter.py:2039` | Observation category | `codings[0].get("system") == _JP_OBSERVATION_CATEGORY_SYSTEM` | category coding 判定 |
| 7 | `_fhir_family_history.py` (session 65 chain) | builder | v3-RoleCode URI prefix 経由で walker 対象化 | 上記 #2 の副作用 |
| 8 | `audit/axes/clinical.py:215` | audit | `i.get("system") == HAI_EVENT_ID_SYSTEM` | HAI identifier 判定 |
| 9 | `eval/axes/locale.py:110` | eval | `c.get("system", "").startswith(_JLAC10_SYSTEM_PREFIXES)` = `("urn:oid:1.2.392.200119.4.1005",)` | JLAC10 使用有無を eval で計測 |
| 10 | `eval/axes/locale.py:149` | eval | 同上 for `_YJ_SYSTEM_PREFIXES` = `("urn:oid:1.2.392.100495.20.2.74",)` | YJ 判定 |
| 11 | `eval/axes/clinical.py:481` | eval | `startswith("urn:oid:1.2.392.100495.20.2.74")` | YJ hardcode |

### 4.2 移行影響見積り

- **#2 walker `_strip_japanese_display_on_english_only_systems`**: JP-CLINS lab CS URI(`http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS` 等 5 種、MEDIS `http://medis.or.jp/CodeSystem/master-JLAC10-17digits`)は prefix `http://jpfhir.jp/` および `http://medis.or.jp/` を持つ = 現行 `_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES` allowlist に**含まれない** → 誤って strip されるリスク**なし**。walker safe。
- **#3 dosage builder**: 上と同じ safety、影響なし。
- **#9 eval JLAC10 prefix**: 現行 `("urn:oid:1.2.392.200119.4.1005",)` は JSLM 一般 OID。JP-CLINS 7 CS への切替後は URI 総入替になるため、eval 側の JLAC10 prefix 判定は **7 CS + MEDIS + fallback 2 = 10 URI** に拡張必要。**現状ハードコードは 1 箇所のみ**、拡張は容易。
- **#1 `is_japanese_only_display_system`**: 新 JP-CLINS lab CS 群を allowlist に追加する場合、English 二次 coding の抑制が発動するため、secondary LOINC を残す設計なら追加すべきでない。
- **横展開漏れリスク箇所**: 上記 11 箇所以外の hardcoded system 依存は grep で追加検出されない範囲。**確定は 11 箇所**、その他は動的 dispatch(`get_system_uri` 経由)なので system URI 追加時に自動追従。

---

## 5. MEDIS CodeSystem の実体確認

### 5.1 事実

`../fhir-jp-validator/` 内で grep 実施:

| 探索対象 | 実体 file の有無 | 詳細 |
|---|---|---|
| `http://medis.or.jp/CodeSystem/master-JLAC10-17digits` | ✅ **1 file 存在** | `tx-server-build/terminology/fhir-server/jpfhir-terminology#2.2606.0/package/CodeSystem-jp-observationlabresultcode-cs.json`。`resourceType=CodeSystem`、`name=JP_ObservationLabResultCode_CS`、**`content=fragment`、concept 数=2,000**(完全 registry ではなく fragment) |
| `http://medis.or.jp/CodeSystem/master-JLAC10-17digits`(NamingSystem) | ✅ **1 file** | `jp_core/package/NamingSystem-jp-medis-observation-jlac10-namingsystem.json` = 命名のみ、code 実体なし |
| `JP_ObservationLabResultCode_VS` | ✅ **1 ValueSet file** | `jpfhir-terminology#2.2606.0/package/ValueSet-jp-observationlabresultcode-vs.json`(参照先 CS が上記 fragment) |
| `JP_CLINS_ObsLabResult_Uncoded_CS` | ✅ 1 CS file、concept 1 | Uncoded fallback、code 固定値 1 個(`99999999999999999`) |
| `JP_CLINS_ObsLabResult_LocalUncoded_CS` | ✅ 1 CS file、concept 1 | LocalUncoded fallback |
| JP-CLINS CoreLabo / InfectionLabo の **CodeSystem** file | ❌ **なし** | CodeSystem-*.json 一覧に該当なし。項目別 `ValueSet-jp-clins-valueset-corelaboJLAC10-*.json` / `ValueSet-jp-clins-valueset-infectionlaboJLAC10-*.json` が **190 file** 存在(項目ごと VS)= slice 定義は VS ベース、CS URI は spec で参照されるが CS 実体は fragment or 項目 VS で管理 |

### 5.2 補足解釈

- MEDIS `master-JLAC10-17digits` は **`content=fragment`**(全 17 桁 code 網羅ではない、抜粋)。session 58/59 の YJ tx-server fragment 問題と同型 pattern → **fragment 外の code を emit すると validator が「システム URI を決定できません」info/warning を返す可能性**あり(session 59 の `_TX_SERVER_VERIFIED_YJ_CODES` fallback pattern の precedent がある)。
- CoreLabo / InfectionLabo の CodeSystem file は無いが、**190 個の項目別 ValueSet** が存在 = 各 slice の binding target。fhirserver 側は VS 経由で validation する。
- **Phase 1** で user が既に fhir-jp-validator 側で MHLW ICD-10 complete CS を load 済 = terminology 側 gap 解消の precedent あり。lab CS も同様に complete registry を load する Phase 2 が可能かは validator 運用者判断。

### 5.3 移行影響見積り

- **MEDIS `master-JLAC10-17digits`**: fragment のため、clinosim 側で emit する 17 桁 code が fragment に含まれるか判定する `_TX_SERVER_VERIFIED_MEDIS_17DIGIT_CODES` snapshot + fallback 分岐が必要(YJ pattern 完全再利用可能)。
- **Uncoded / LocalCode fallback**: concept 各 1、URI + code + Fixed display 固定 = clinosim 側は URI + code 定数を hardcode するだけで済む(session 66 wave 4 教訓に沿い、必ず fhirserver 実測 verify)。
- **CoreLabo/InfectionLabo VS 190 個**: slice ごとの Fixed display をこの 190 VS から抽出して clinosim 側の Fixed display registry を生成する(script 化 + snapshot commit が現実的)。

---

## 6. RNG 呼び出し影響

現行 `_build_lab_observation` は **RNG を呼ばない**(deterministic な code lookup + physiology-driven value のみで構成)。physiology-driven value 生成側の `derive_lab_values` / `apply_hai_lab_lift` 等の RNG 順序も coding.system 変更で変わらない(coding は emit stage、value は simulation stage、独立)。

**したがって coding system 移行では RNG 呼び出し回数・順序は変わらない見込み**。ただし:

- code_mapping_lab.yaml の書き替えで内部 name → code 対応が変わる場合、`load_code_mapping("lab", "JP")` の hash order が変わり、下流 `for name, code in ...` iteration 順序が変わる可能性 → 該当 code path があるか要 audit。現行では iteration 依存の RNG 消費は grep で確認する限り無い([[feedback_rng_preservation_for_population_changes]] rule 対象外)。
- 新規 disease protocol で感染症 5 項目に該当する検査追加(scope 拡張)する場合、physiology / order generation で RNG を追加消費する = deterministic seed の同一値保証を破る。population 追加なしなら RNG 影響なし。

---

## 7. Summary(fact-only)

| # | 項目 | 現状 |
|---|---|---|
| 1 | primary emit system | JLAC10 一般 OID(spec 7 CS のいずれとも不一致) |
| 1 | primary emit code 桁数 | 全 5 桁(spec 17 桁と不一致) |
| 1 | secondary emit | LOINC(spec 未定義 system、Open slice で reject はされないが Fixed display slice に該当しない) |
| 2 | meta.profile | JP Core + JP-CLINS 両方宣言済(data 側で 1 slice も match していない状態) |
| 3 | 43 項目カバー率 | 上位 24 unique display は該当濃厚、粗計 2,300+/2,523(90%+)予想。spec 正式 identifier mapping は未実装 |
| 3 | 感染症 5 項目カバー率 | 0 件(疾患 protocol に該当分析物なし) |
| 3 | スコープ外(細菌検査) | 培養同定/薬剤感受性 14 件、`_bb_microbiology` 側で別扱い |
| 4 | system URI hardcode 分岐 | 11 箇所確認、うち walker(`_strip_japanese_display_on_english_only_systems`)は新 JP-CLINS URI と衝突しない(prefix allowlist 対象外) |
| 5 | MEDIS CS 実体 | fragment(2,000 concept)。session 59 の YJ fragment pattern と同型 |
| 5 | CoreLabo/InfectionLabo CS 実体 | file なし、190 個の項目別 VS がある |
| 5 | Uncoded/LocalUncoded fallback | 各 1 concept、URI + code 定数 hardcode 可能 |
| 6 | RNG 影響 | coding system 差替のみでは RNG 呼び出し回数/順序変わらない見込み |

---

## 8. 実装参照 index

- 主要 emit builder: `clinosim/modules/output/_fhir_observations.py:43-152 _build_lab_observation`
- system dispatch: `clinosim/codes/loader.py:180-192 _COUNTRY_SYSTEM_KEYS`
- URI registry: `clinosim/codes/loader.py:215-260 _BUILTIN_URIS`
- English-only prefix allowlist: `clinosim/modules/output/fhir_r4_adapter.py:2058 _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES`
- Walker: `clinosim/modules/output/fhir_r4_adapter.py:2087 _strip_japanese_display_on_english_only_systems`
- JP code map: `clinosim/locale/jp/code_mapping_lab.yaml`(40 entry、全 5 桁)
- US code map: `clinosim/locale/us/code_mapping_lab.yaml`(53 entry、LOINC)
- JLAC10 display: `clinosim/codes/data/jlac10.yaml`(45 entry、全 5 桁、metadata URI = 一般 OID)
- Precedent(medication usage 用 CLINS Uncoded CS): `clinosim/modules/output/fhir_r4_adapter.py:1230 _JP_CLINS_MEDICATION_USAGE_UNCODED_CS`
- Precedent(fragment CS の verified subset pattern): `clinosim/modules/output/_fhir_medications.py:151-173 _TX_SERVER_VERIFIED_YJ_CODES`

以上、調査完了。判断はユーザー側で。
