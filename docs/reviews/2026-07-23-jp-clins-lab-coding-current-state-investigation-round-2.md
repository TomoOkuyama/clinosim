# JP-CLINS 検体検査コーディング 追補調査 report (2 巡目)

**作成**: 2026-07-23(session 66)
**依頼スコープ**: 調査 only、コード変更・PR 作成なし
**前 report**: `docs/reviews/2026-07-23-jp-clins-lab-coding-current-state-investigation.md`
**位置付け**: 差し戻しではなく追補。1 巡目 §1 実測 / §4 hardcode 分岐 / §6 RNG 分離論証はそのまま有効

---

## 0. 依頼者による前提訂正の受領

以下 3 点、認識を更新して以降の判断に反映:

- **(a)** 全 slice は `S 0..1`(MustSupport but not required)、slicing Open。「LocalCode 常に必須」等は IG 散文規定で FHIR 制約ではない → 1 slice も match しなくても validation error は出ない。**現状 data は既に silent-pass している可能性が高い**。
  - 1 巡目 report §2.1「1 slice も match しない」の言外意図は「エラー中」ではなく「静寂状態」。移行は「エラー修正」ではなく「自主的な仕様準拠」で、Fixed Value display と required binding という**新しいエラー面を自ら作りに行く**投資。
- **(b)** discriminator は `value:system` + `value:display` の 2 つ。全一致で match、片方外れなら slice not matched。**現在 emit(system=CoreLabo かつ display=白血書)を仮に system だけ差し替えると、`wbc` slice の Fixed display=`WBC` と食い違って silent 素通り**する(Open slicing のため rejection にならない)。
  - v6 の `MedicationCodeNocoded_CS#NOCODED` 12,891 発火はエラー面で「派手に出る」だった。今回は逆で**「静かに非準拠」になる**リスク。1 巡目 §0 表 #3「v6 同型」は「リスクの所在」としては正しいが、「現れ方」は反転。
- **(c)** 1 巡目 §3 マッピング判定に事実誤り(下 §D 参照)。

---

## A. 調査項目 1 【最優先】ValueSet 190 個の構造(concept 列挙 vs filter)

### 事実(機械集計)

`../fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package/ValueSet-jp-clins-valueset-*.json` を全 190 file 集計:

| include 種別 | 件数 | 中身 |
|---|---:|---|
| `filter` のみ | 188 | 例(K の場合):`{"system": ".../JP_CLINS_ObsLabResult_CoreLabo_CS", "filter": [{"property": "concept", "op": "descendent-of", "value": "K"}]}` |
| `system` のみ(集約 VS) | 2 | `ValueSet-jp-clins-valueset-corelaboJLAC10-vs.json` と JLAC11 版 = ルート集約 VS |
| `concept` 列挙 | **0** | 該当なし |

**結論**: 190 VS はすべて `filter: descendent-of` 参照型。**CoreLabo/InfectionLabo CodeSystem の実体が無ければ binding 解決不能**。1 巡目 §5.3「190 VS から Fixed display registry を生成」の approach は **成立しない**(VS 側は Fixed display を持たず、CS 側の実 concept が必要)。

### 対応: Fixed display registry の別ルート

Fixed display 情報は **VS ではなく StructureDefinition の slice 定義**にある(`Observation.code.coding:coreLaboJLAC10/<slice>.display` の `fixedString`)。実際に機械抽出できた(下 §D)。VS はあくまで binding target であり、slice match の判定材料。

---

## B. 調査項目 2 validator 実測(display 不一致検出)

### 事実(検討結果)

**私の環境からは validator 実行不可**(workspace:5 = fhir-jp-validator worker への依頼案件)。以下、依頼書 draft:

**依頼内容 (workspace:5 向け)**:

以下 3 case を `../fhir-jp-validator/test-cases/jp-clins/` に追加し、v30-flavor tx=8181 で単体 validation して issue の severity + message を報告:

```
case 1: silent-mismatch case
  system = http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS
  code   = 2A991000002327101   # WBC 用の 17 桁 (仮、実 canonical は要 spec 参照)
  display = "白血球数"           # 日本語(Fixed は "WBC")
  meta.profile: JP_Observation_LabResult_eCS
  期待挙動: slice discriminator に含まれる value:display が不一致
           → wbc slice に match せず、Open slicing で silent-pass の想定
           validator が silent なら「移行しても validator では担保されない」

case 2: correct-fixed-display case
  同上、display = "WBC"
  期待挙動: wbc slice match → 全 binding 評価に進む(binding 解決可否は fragment CS 依存)

case 3: fragment-out-of-scope case
  system = 同上
  code   = <fragment 外の 17 桁 code>
  display = "WBC"
  期待挙動: system-code combo の validation で issue(info/warning)
```

### 推測(実測前)

- **case 1** は Open slicing により silent-pass の可能性大(1 巡目訂正 (a)(b) の spec 読解に基づく)。もしそうなら「仕様準拠は validator 側では担保できず、生成側の自律責務」となる。
- **case 2** で fragment/CS 実体解決に失敗する場合、これ以上 validator では確認できない = **fhir-jp-validator 側 Phase 2 で CoreLabo/InfectionLabo/MEDIS の CS 実体を load しない限り、投資対効果を validator で数値化不能**。

### 結論(判断への影響)

- 移行の投資対効果は「validator error 減」では測れない可能性(silent-pass の場合、投資後も v?? 総 error 数は変わらないか微小変化のみ)。
- **測定指標を「validator error 数」から「slice match 率 (自主計測)」に切り替える** 必要が出る。case 1 が silent-pass だった場合、workspace:5 で slice match dashboard を作るか、clinosim 側で emit 前 dry-run 集計を作るのが現実的。

**→ workspace:5 に上記 3 case 依頼を出すか、判断待ち**。

---

## C. 調査項目 3 display 供給経路 全洗い出し(display 軸監査)

1 巡目 §4 は system 軸監査で、依頼側指定ミス。今回中心リスク = 「**JLAC/MEDIS の system に load される display に何が入るか**」。

### 事実: lab Observation display 供給経路(全 6 stage)

lab Observation.code.coding[0].display の値が emit されるまでの full 経路:

| Stage | 場所 | 処理 | JP 出力への影響 |
|---|---|---|---|
| **Stage 1: 上流入力** | `clinosim/simulator/outpatient.py:220` / emergency.py / inpatient.py | `canonical_lab_name(test_name)` で protocol の内部 name を canonical 分析物 name(例 `"Troponin"` → `"Troponin_I"`)に正規化 → `OrderResult.lab_name` にセット | 内部 canonical は英語コード(WBC, Cre, K, Glucose 等) |
| **Stage 2: alias 解決** | `clinosim/modules/observation/engine.py:37 canonical_lab_name` | `lab_aliases.yaml` で name variant を canonical に集約 | Data-driven, no display transform |
| **Stage 3: emit 内 display 決定** | `_fhir_observations.py:59` `lab_name = result.get("lab_name") or order.get("display_name", "Unknown")` | order 上の `display_name` は疾患 protocol YAML に依存(例 "白血球数" / "Complete Blood Count" 等 verbose ラベル) | ここで既に日本語混入可能 |
| **Stage 4: code lookup による overwrite** | `_fhir_observations.py:82-84` `display_name = code_lookup(code_system_key, code_value, lang)` — JP path なら `code_lookup("jlac10", "2A010", "ja")` = **`clinosim/codes/data/jlac10.yaml`** の 5 桁 code → ja value | ⚠️ **ここで日本語 display が primary coding に入る**。yaml 値は例:`白血球数`、`カリウム`、`グルコース` 等の日本語 |
| **Stage 4b: fallback** | `_fhir_observations.py:83-84` `if not display_name or display_name == code_value: display_name = lab_name` | code_lookup が None を返した場合、stage 3 の `lab_name`(canonical 英語 or protocol 由来ラベル)にフォールバック |
| **Stage 5: secondary LOINC の display** | `_fhir_observations.py:141-152` — JP path で `us_code_map[lab_name]` から LOINC code を取得、`code_lookup("loinc", loinc_code, "en")` で英語 display 取得 | secondary は必ず英語(LOINC LONG_COMMON_NAME) |
| **Stage 6: walker post-processing** | `fhir_r4_adapter.py:2087 _strip_japanese_display_on_english_only_systems` は JP output で English-only CS(LOINC/SNOMED 等)から日本語 display を消す。allowlist prefix に **JLAC/MEDIS/JP-CLINS URI は含まれず**、primary coding は素通り | JLAC の日本語 display はここでは何もされない = そのまま出力 |

### 事実: display 逆方向 walker(英→日 localize)

**逆方向 walker(英語 → 日本語)は存在しない**。全経路:

- code_lookup + yaml 内 ja field で「初めから日本語」で提供
- 個別 `_localize_display(en_label, country, JA_MAP)` = 決まった英語ラベル(例 "Vital Signs", "Laboratory")の JP マップから引く hardcoded 変換

つまり lab display の日本語化ソースは 100% **`clinosim/codes/data/jlac10.yaml`** の ja field。

### 該当箇所 grep 集計(display setter / overwriter / localize)

| # | Location | 処理 | 対 lab-display 関与 |
|---|---|---|---|
| 1 | `_fhir_observations.py:82` `code_lookup(code_system_key, code_value, lang)` | primary display 決定 | ✅ 中心 |
| 2 | `_fhir_observations.py:84` `display_name = lab_name` (fallback) | code_lookup None 時 | ✅ 中心 |
| 3 | `_fhir_observations.py:130` `"display": display_name` の emit | ✅ 中心 |
| 4 | `_fhir_observations.py:131` `"text": display_name` の emit | ✅ code.text はここ |
| 5 | `_fhir_observations.py:145` `code_lookup("loinc", loinc_code, "en")` | secondary LOINC 英語 display | secondary、Fixed slice 対象外 |
| 6 | `_fhir_observations.py:59` `order.get("display_name")` fallback | order 上のラベル(疾患 protocol) | 疾患 YAML 由来の日本語混入経路 |
| 7 | `clinosim/codes/data/jlac10.yaml` の `ja:` field | 実データ | ✅ 供給源 |
| 8 | `clinosim/modules/observation/engine.py:37 canonical_lab_name` | 内部名 canonical 化 | 上流、display には触れない |

### 移行影響見積り

- **中心リスク**: system URI だけ CoreLabo に差し替えて display を触らないと `display=日本語` が CoreLabo slice の Fixed display(英語)と不一致 → wbc slice match せず、Open slice で silent pass。**system + display + code の 3 点セットで動かす**必要。
- **display の実 override は #1(code_lookup 経由)の一択**が primary。**`jlac10.yaml` の ja field を Fixed display に書き換える**か、**Stage 4 で `code_lookup(code_system_key, code_value, "en")` にする** or **slice-name 別 Fixed display registry を bypass** で参照するか、いずれか。
- `_localize_display("Vital Signs" 等 hardcoded 英ラベル + JA マップ)` は lab には無関与。
- 影響 module: `_fhir_observations.py` の `_build_lab_observation`(2 行変更)+ `codes/data/jlac10.yaml`(display 値方針決定)or 新 `clinosim/codes/data/jp_clins_labo_slice_display.yaml`(spec-anchored Fixed registry を独立管理する場合)。
- **横展開漏れ**: lab display setter は `_fhir_observations.py` 内に集約されており、他 file への leak なし(grep 確認済)。逆方向 walker も存在しないので追加検出無し。

---

## D. 調査項目 4 43 項目 slice 一覧の機械抽出(手写経禁止)

### 事実(機械抽出、`StructureDefinition-JP-Observation-LabResult-eCS.json` から)

`Observation.code.coding:<slice-name>.display` の `fixedString` を全 element 走査で抽出。**元 SD が single source of truth**。

**JLAC10 CoreLabo = 55 slices**、JLAC11 CoreLabo = 55 slices、JLAC10 InfectionLabo = 38 slices、JLAC11 InfectionLabo = 38 slices。

**CoreLabo/JLAC10 の全 55 slice → Fixed display**(snapshot: `/tmp/jlac10_slice_registry.json`):

| slice | Fixed display | | slice | Fixed display | | slice | Fixed display |
|---|---|---|---|---|---|---|---|
| abo-bld | 血液型-ABO | | fbg | FBG | | pt-inr | PT-INR |
| alb | ALB | | ftg | FTG | | pt-ratio | PT比 |
| alp | ALP | | ggt | GGT | | pt-sec | PT-秒 |
| alt | ALT | | hb | Hb | | rbc | RBC |
| amy | AMY | | hba1c-ngsp | HbA1c-NGSP | | rh-bld | 血液型-Rh |
| aptt | APTT | | hdl-c | HDL-C | | t-bil | T-Bil |
| ast | AST | | k | K | | t-cho | T-CHO |
| bg | BG | | ld | LD | | tg | TG |
| bnp | BNP | | ldl-c | LDL-C | | tp | TP |
| bun | BUN | | na | Na | | u-ac | U-A/C |
| ca | Ca | | nt-probnp | NT-proBNP | | u-bld | U-Bld |
| cbg | CBG | | plt | PLT | | u-bld-HalfQty | U-Bld-半定量 |
| che | ChE | | pt-act | PT-活性% | | u-glu | U-Glu |
| ck | CK | | | | | u-glu-HalfQty | U-Glu-半定量 |
| cl | Cl | | | | | u-pc | U-P/C |
| cre | Cre | | | | | ua | UA |
| crp | CRP | | | | | utp | U-TP |
| crp-class | CRP-class | | | | | utp-HalfQty | U-TP-半定量 |
| ctg | CTG | | | | | wbc | WBC |
| cys-c | Cys-C | | | | | | |
| d-bil | D-Bil | | | | | | |
| dd | DD | | | | | | |
| dd-class | **DD-定性** | | | | | | |

**依頼者提供の slice 一覧との差分**: 依頼者提供の JLAC10 CoreLabo 一覧に含まれる `dd-class` は spec SD 上では **`DD-定性`**(日本語混じり)、`u-glu-HalfQty` などは **CamelCase の HalfQty**、`u-p/c` は **`U-P/C`**(スラッシュ含む)= 手写経では取り違いやすい部分あり。**機械抽出値を single source of truth に**。

### v29 display 別件数 → 実 slice mapping 再計算

現行 34 unique JP display のうち、CoreLabo/JLAC10 slice に確実に mapping できる件数:

| 現行 display | v29 件数 | 想定 slice | mapping 確度 |
|---|---:|---|---|
| クレアチニン | 478 | `cre` (Cre) | 高 |
| グルコース | 393 | **`bg` / `fbg` / `cbg` の 3 択** | **要 disambig(空腹・随時・血液採取タイミング)** |
| カリウム | 271 | `k` (K) | 高 |
| ナトリウム | 214 | `na` (Na) | 高 |
| 白血球数 | 160 | `wbc` (WBC) | 高 |
| AST | 154 | `ast` (AST) | 高 |
| ALT | 149 | `alt` (ALT) | 高 |
| CRP | 134 | `crp` (CRP) or `crp-class`(定性)| 高(class 未使用と仮定) |
| ヘモグロビン | 121 | `hb` (Hb) | 高 |
| 尿素窒素 | 61 | `bun` (BUN) | 高 |
| プロトロンビン時間 | 43 | **`pt-sec`/`pt-ratio`/`pt-act`/`pt-inr` の 4 択** | **要 disambig(結果形式)** |
| **動脈血 pH / pCO2 / pO2 / 重炭酸塩** | 各 38 (計 152) | **slice に無い** | MEDIS or Uncoded 行き |
| **BNP** | 36 | `bnp` (BNP) | 高 |
| カルシウム | 27 | `ca` (Ca) | 高 |
| 血小板数 | 27 | `plt` (PLT) | 高 |
| **乳酸** | 27 | **slice に無い** | MEDIS or Uncoded |
| **トロポニン I** | 16 | **slice に無い**(`ck` はあるが Troponin_I は別) | MEDIS or Uncoded |
| **CK-MB** | 16 | **slice に無い**(`ck` は総 CK) | MEDIS or Uncoded |
| **培養同定 / 薬剤感受性** | 各 7 (計 14) | **spec 明示スコープ外**(細菌検査) | 別扱い、`_bb_microbiology` |
| HbA1c | 6 | `hba1c-ngsp` (HbA1c-NGSP) | 高 |
| アルブミン | 6 | `alb` (ALB) | 高 |
| TG | 4 | `tg` (TG) | 高 |
| HDL | 4 | `hdl-c` (HDL-C) | 高 |
| **プロカルシトニン** | 4 | **slice に無い** | MEDIS or Uncoded |
| **eGFR** | 1 | **slice に無い** | MEDIS or Uncoded |
| aPTT | 1 | `aptt` (APTT) | 高 |
| **D-dimer** | 1 | `dd` (DD) | 高(class 未使用と仮定) |
| **TSH** | 1 | **slice に無い** | MEDIS or Uncoded |
| **Fibrinogen** | 1 | **slice に無い** | MEDIS or Uncoded |
| コレステロール | 1 | `t-cho` (T-CHO) | 高 |

### カバー率再計算(前提明示)

| 前提 | CoreLabo 該当 件数 | 該当率 (2,523 中) |
|---|---:|---:|
| **前提 A: グルコース 393 を disambig 実装しない場合** | 1,898 | **75.2%** |
| **前提 B: グルコース 393 を BG/FBG/CBG に振り分け実装 + PT 43 を disambig 実装** | 2,334 | **92.5%** |
| 微生物 14 件(スコープ外)| — | — |
| **CoreLabo 非該当**(pH/pCO2/pO2/HCO3/乳酸/トロポニン/CK-MB/プロカルシトニン/eGFR/TSH/Fibrinogen)| 219 | 8.7% → MEDIS or Uncoded |
| **感染症 5 項目** | 0 | 生成 profile に該当分析物なし |

**1 巡目 §3「90%+」の前提**: グルコース disambig 実装を暗黙前提にした数字(前提 B 相当)= 依頼者指摘通り、前提明示が不足していた。**明示前提込みで再掲**: 前提 A では **75.2%**、前提 B では **92.5%**。

### 移行影響見積り

- **disambig 実装 (グルコース / PT)** = physiology の空腹状態・PT 結果形式 を order/result に持ち回す必要。`OrderResult` type 拡張 or `order.display_name` 表記規約(例 `"Glucose_fasting"` / `"Glucose_random"`)。
- **CoreLabo 非該当 219 件** = spec 適用規則(散文)に従い MEDIS 推奨 or 不可なら Uncoded 必須。**Uncoded は concept 1 個の固定 URI+code**なので実装 trivial。依頼者提示の代替案「Phase 1 = CoreLabo + Uncoded fallback / Phase 2 = MEDIS」に沿えば、**MEDIS マスター入手 / 17 桁 mapping 作業不要で完全 spec 準拠**。
- **Fixed display registry の実装** = 上記 55 slice の snapshot ファイル(`clinosim/codes/data/jp_clins_corelabo_jlac10_slice_display.yaml` 等)を SD から script 抽出 + commit。**手写経禁止 rule** ([[feedback_fhirserver_actual_canonical_verify]] の派生 rule)遵守。
- 影響 module: `clinosim/codes/data/`(新 slice-display registry file 1-4 種)、`clinosim/locale/jp/code_mapping_lab.yaml`(内部名 → slice-name mapping への書き換え)、`clinosim/modules/observation/engine.py`(disambig helper 追加)、`clinosim/modules/output/_fhir_observations.py` の primary coding 組立 logic 再設計。

---

## E. 代替案(Phase 1 = CoreLabo + Uncoded)への見積り影響

依頼者提示の中間解「Phase 1 = CoreLabo 上位項目 + Uncoded fallback / Phase 2 = MEDIS 拡充」を採用する場合の見積り差分:

| 項目 | 全 MEDIS マッピング案(1 巡目) | Phase 1 = CoreLabo + Uncoded 案 |
|---|---|---|
| MEDIS マスター入手 | 必須(桁違いに大きい)| **不要** |
| 17 桁 code mapping 作業 | 全 34 unique 分 | **CoreLabo 該当分のみ**(disambig 前提 B なら 92.5% 分の 17 桁 mapping) |
| `_TX_SERVER_VERIFIED_MEDIS_17DIGIT_CODES` snapshot | 必須(fragment 対応)| **不要**(Uncoded は concept 1 個で fragment 問題無関係) |
| CoreLabo 非該当 219 件 | MEDIS 17 桁を無理やり mapping | **Uncoded concept 1 個で完全準拠**、日本語検査項目名は LocalCode slice display + `code.text` |
| RNG 影響 | 変わらない | **変わらない**(Phase 1 は emit stage 変更のみ、value 生成は unchanged) |
| Phase 2 に持ち越す作業 | 全 34 項目 mapping + fragment 対応 | 219 件 の中で MEDIS registry 入手可能な範囲を後付け拡充(scope 判断) |

**Phase 1 スコープ**(推奨概算):

1. `clinosim/codes/data/jp_clins_corelabo_jlac10_slice_display.yaml` 新設(55 slice、SD から script 抽出、手写経禁止)。
2. `clinosim/codes/data/jp_clins_uncoded_labresult_cs.yaml`(concept 1 個、URI + code + Fixed display "未標準化コード項目(JLAC)")。
3. `clinosim/codes/data/jp_clins_localcode_labresult_cs.yaml`(concept 1 個、URI + code + Fixed display "施設固有コード項目")— **常時 emit 対象**、日本語検査項目名を `display` に載せる場合は MEDIS/LocalCode どちらの slice の display 制約に該当するか要 spec 再確認。
4. `clinosim/locale/jp/code_mapping_lab.yaml` を「内部名 → CoreLabo slice-name(該当時)+ 17 桁 code」に置き換え。
5. `_build_lab_observation` の primary coding 組立 logic:
   - CoreLabo 該当 → CoreLabo CS URI + 17 桁 code + Fixed display
   - 非該当 → Uncoded CS URI + `99999999999999999` + Fixed display
   - **常に** LocalCode CS URI + 施設固有 code + Fixed display を併記(2 coding 化)
   - LOINC secondary は削除 or country 分岐で残す判断
6. `code.text` は 1..1 → 日本語検査項目名を明示セット(現行 `display_name` 同等)。

**Phase 1 見積り**: 中規模、~2-3 日 scope(spec 精読 + slice mapping curation 含む)。session 65-66 の hotfix cycle 24h より大きい。

---

## F. RNG 影響 再確認

- 移行 (Phase 1 or 2) いずれも coding system + display 変更のみ = **RNG 呼び出し回数・順序 変わらない**([[feedback_rng_preservation_for_population_changes]] rule 対象外)。
- `code_mapping_lab.yaml` iteration 順序への依存箇所は 1 巡目 §6 で grep 済 = 依存 code path 無し。
- disambig 実装(グルコース BG/FBG/CBG、PT 4 種)は order/result 側の名前決定 = 疾患 protocol YAML 側修正で吸収可能、physiology 側 RNG 順序に影響しない見込み(実装時 grep 再確認要)。

---

## G. Summary(fact-only、判断はしない)

| # | 項目 | 事実 |
|---|---|---|
| 1 | 190 VS 構造 | **filter: descendent-of 型 188 file + system-only 集約 2 file、concept 列挙 0 file**。CoreLabo/InfectionLabo CS 実体が binding 解決に必須 |
| 1 | Fixed display registry の source | VS ではなく **StructureDefinition slice 定義**の `fixedString` = 機械抽出済(§D) |
| 2 | validator 実測 | 私環境からは workspace:5 依頼案件。3 test case 依頼書 draft 済。silent-pass 想定なら「validator で担保不能、生成側自律責務」 |
| 3 | display 供給経路 | 6 stage grep 済、中心は `_fhir_observations.py:82 code_lookup(code_system_key, code_value, lang)` = jlac10.yaml の ja field。逆方向 walker 存在しない、他 file への leak 無し |
| 4 | CoreLabo/JLAC10 slice | 55 slice、Fixed display 抽出済(snapshot `/tmp/jlac10_slice_registry.json`)。手写経で取り違えやすい部分(DD-定性、U-A/C 等)含む |
| 4 | カバー率再計算 | **前提 A(disambig 実装なし): 75.2%(1,898/2,523)**、**前提 B(グルコース + PT disambig 実装): 92.5%(2,334/2,523)**。1 巡目「90%+」は前提 B 暗黙 |
| 4 | 感染症 5 項目 | 0 件、生成 profile に該当分析物なし |
| 4 | スコープ外 | 培養同定 + 薬剤感受性 14 件、`_bb_microbiology` 別扱い |
| E | Phase 1 = CoreLabo + Uncoded | MEDIS マスター入手 / fragment snapshot 不要、完全 spec 準拠。RNG 影響なし。~2-3 日 scope |
| F | RNG 影響 | いずれの案でも coding 変更のみ、RNG 順序変わらない見込み |

---

## H. 実装参照 index(追補)

- 190 VS 集計 script(このレポート実行時使用): `python3` inline(SD file: `../fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package/`)
- slice registry snapshot: `/tmp/jlac10_slice_registry.json`(next chain で `clinosim/codes/data/` に commit する候補)
- SD 元: `StructureDefinition-JP-Observation-LabResult-eCS.json`(同 package)
- primary display 決定: `clinosim/modules/output/_fhir_observations.py:59, 82-84, 130-131`
- secondary LOINC 決定: `clinosim/modules/output/_fhir_observations.py:141-152`
- yaml source: `clinosim/codes/data/jlac10.yaml`(現行 45 entry、全 5 桁分析物コード、ja field が primary display source)
- 上流入力: `clinosim/modules/observation/engine.py:37 canonical_lab_name` + `reference_data/lab_aliases.yaml` + `lab_panels.yaml`
- walker safety(JP-CLINS URI 対象外確認): `clinosim/modules/output/fhir_r4_adapter.py:2058-2065 _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES`

以上、追補調査完了。判断はユーザー側で。
