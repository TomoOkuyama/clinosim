# JP-CLINS 検体検査コーディング 3 巡目 report (訂正 + 設計提案)

**作成**: 2026-07-23(session 66)
**依頼スコープ**: 調査 + 設計提案。**実装・PR 作成なし**(validator 側未確認項目 2 件が gate)
**位置付け**: 2 巡目 §A 結論訂正 + §D 算術誤り修正 + §E LocalCode 誤設計修正 + §B test case code 差し替え + ライセンス制約反映 + 7 項目設計案
**前 report**: `docs/reviews/2026-07-23-jp-clins-lab-coding-current-state-investigation-round-2.md`

---

## 0. 訂正の受領

以下 5 点、認識を更新して以降の判断に反映:

- **(A)** CoreLabo/InfectionLabo CS は **実体存在**(2 巡目 §A の grep 漏れが原因)
- **(B)** カバー率 前提 B は PT 43 の二重計上 → 正しくは **2,291 / 2,523 = 90.8%**
- **(C)** LocalCode slice は自由スロット(code + display とも Fixed なし)= 2 巡目 §E の「concept 1 個」設計は LocalUncoded との混同
- **(D)** 2 巡目 §B test case の code `2A991000002327101` は実在しない → 実 code に差し替え要
- **(E)** JP-CLINS は **CC BY-ND 4.0**(著作者: 日本医療情報学会)= 抽出物の commit 禁止、build/起動時にパッケージから抽出する設計に変更

---

## A. 調査 1: CoreLabo/InfectionLabo CS 実体の所在確認

### 事実(機械集計)

CS 実体の探索を **`../fhir-jp-validator/tx-server-build/terminology/` 全域** に拡張し確認:

| CodeSystem | 所在 package | version | content | top concept | 深部 concept |
|---|---|---|---|---:|---:|
| **CoreLabo/JLAC10** `JP_CLINS_ObsLabResult_CoreLabo_CS` | `jpfhir-terminology#2.2606.0` | `2026.03.31` | **complete** | **55** | **778** |
| CoreLabo/JLAC11 | 同上 | 同上 | fragment | 13 | 1,987 |
| **InfectionLabo/JLAC10** `JP_CLINS_ObsLabResult_InfectionLabo_CS` | 同上 | 同上 | **complete** | 1 | 38 |
| InfectionLabo/JLAC11 | 同上 | 同上 | fragment | 1 | 30 |
| MEDIS(参考、17 桁一般)`master-JLAC10-17digits` | 同上 | — | **fragment** | — | 2,000 |

**重要な訂正**: 2 巡目 §A は `clinical-information-sharing#1.12.0/package/` のみを探索していた。CoreLabo/InfectionLabo CS は **jpfhir-terminology#2.2606.0 pkg 側** に格納されている(IG package と terminology package で分離)。**CoreLabo/JLAC10 は `content=complete`、55 親 / 778 code**、user が参照した IG v1.6.0 render と 55 親数一致 ✅。

構造(実測、`WBC` 配下例):

```
Lvl 1  WBC        display="" (空)  ja designation 無し
Lvl 2  2A990000001999952   display="WBC"  ja="白血球数"
Lvl 2  2A990000001930952   display="WBC"  ja="白血球数"
Lvl 2  2A990000001999852   display="WBC"  ja="白血球数"
```

- Lvl 1(親)は SD Fixed display と同名の**内部 FHIR 識別名**、display / ja とも空
- Lvl 2(17 桁 child)は `display=<親名>`、`ja` designation あり(例 `カリウム(K)`、`CRP(定量)` 等)
- WBC parent 配下は **3 codes**(2 巡目 §B 依頼書中の `2A991000002327101` は非在、実 code に差し替え要 = 訂正 (D))

1 親あたり 17 桁 code 数分布(全 55 親):

- min 1、max 41(CRP)、avg 14.1
- top 5: CRP=41、BG=36、FBG=36、CBG=36、NT-proBNP=26
- 「代表 1 code を決定的に選ぶ」→ 決定的な選択規則(例:辞書式最小 code)なら 1 決定可能

### 移行影響見積り(2 巡目 §A / §D 修正)

- **17 桁 code mapping table の手動作成は不要**(user 帰結 (b) 承認)。内部名 → 親コード(Lvl 1)だけ持てば、17 桁は CS から機械取得。
- MEDIS fragment 問題は CoreLabo 非該当項目のみに残る(下 §E 参照)。
- fhirserver が階層 CS の `descendent-of` filter で VS expansion できるかは **validator 側 gate**(末尾参照)。

---

## B. 調査 2: display 供給経路(2 巡目 §C を維持)

**結論変更なし**。2 巡目 §C の 6 stage 追跡は有効:

- **単一変異点** = `_fhir_observations.py:82 code_lookup(code_system_key, code_value, lang)` + `_fhir_observations.py:130-131`
- 逆方向 walker(英→日 localize)不在確認済
- 他 file への leak 無し確認済
- `text` と `display` は同一変数 `display_name` を共有 = 移行時 **分離**が必要(下 §H item 6)

---

## C. 3 巡目 test case 実 code(2 巡目 §B 訂正 (D) 反映)

依頼書 draft の test case を実在 code に差し替え(workspace:2 validator 側依頼想定):

```
case 1: silent-mismatch case (display Fixed 不一致、Open slice silent-pass 想定)
  system  = http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS
  code    = 2A990000001999952   # WBC 配下の実 17 桁 code (CS 実体で確認済)
  display = "白血球数"           # 日本語(SD Fixed は "WBC")
  meta.profile: JP_Observation_LabResult_eCS
  期待: value:display 不一致 → wbc slice not matched → Open slice で silent-pass の想定

case 2: correct-fixed-display case (slice match の baseline 確認)
  同上、display = "WBC"
  期待: wbc slice match → 全 binding 評価(descendent-of filter 解決に依存)

case 3: fragment/hierarchy-out-of-scope case (存在しない code)
  system  = 同上
  code    = 2A991000002327101   # WBC parent 配下に存在しない 17 桁 code
  display = "WBC"
  期待: system-code combo で issue(hierarchy resolve fail の可能性)
```

各 case で issue の severity + message を報告してもらう。

---

## D. 訂正 1: カバー率の算術修正

**2 巡目 §D 前提 B = 2,334 は誤り**(PT 43 の二重計上)。訂正版:

| 前提 | CoreLabo 該当 件数 | 該当率 (2,523 中) | 内訳 |
|---|---:|---:|---|
| **前提 A: disambig 無し** | **1,855** | **73.5%** | PT 43 も disambig 無しなので除外 |
| **前提 B: グルコース + PT 両方 disambig 実装** | **2,291** | **90.8%** | 1,855 + PT 43 + Glucose 393 |
| CoreLabo 非該当(pH/pCO2/pO2/HCO3/乳酸/トロポニン I/CK-MB/プロカルシトニン/eGFR/TSH/Fibrinogen)| **218** | 8.6% | MEDIS or Uncoded 行き |
| 微生物(スコープ外) | 14 | 0.6% | `_bb_microbiology` 別 |
| **合計** | **2,523** | 100% | 検算: 2,291 + 218 + 14 = 2,523 ✅ |

**2 巡目「90%+」は前提 B 相当**(明示不足)。**訂正版明示**:
- disambig 無し = 73.5%
- グルコース(BG/FBG/CBG)+ PT(4 種)disambig 実装 = **90.8%**

**CoreLabo 非該当 219 → 218 も訂正**(2 巡目 §D 表末で `152+27+16+16+4+1+1+1=218`、報告書 219 は算術誤り)。

グルコース disambig 判別は 17 桁の識別コード部で可能(user 提示):
- BG(血糖): `3D010` **`00000`** `02327101`
- FBG(空腹時): `3D010` **`13000`** `...`
- CBG(随時): `3D010` **`12990`** `...`

PT 4 種は末尾 2 桁結果識別コード(51=秒 / 55=比 / 53=活性% / 57=INR)。

---

## E. 訂正 2: LocalCode slice の設計 修正

**2 巡目 §E Phase 1 項目 3 の LocalCode 設計は誤り**。

### 事実(spec 本文の再読)

`coding:localLaboCode` slice の制約:

| 要素 | Fixed | 制約 |
|---|---|---|
| `system` | fixedUri = `http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS` | ✅ 唯一の Fixed |
| `code` | なし | その施設固有の検査項目コード。異なる検体材料に同項目 code がある場合は `検査項目コード + "_" + 検体材料コード`(例 `0198394_082`)。英数字・ハイフン・アンダーバーのみ許容 |
| `display` | なし | その施設での検査項目名。**空白を含まない、なるべく長い文字列名称を推奨** |

→ LocalCode は **日本語検査項目名を載せる自由スロット**。concept 1 個の固定 CS ではない。

2 巡目 §E での混同源: 1 巡目 §5.1 で発見した `JP_CLINS_ObsLabResult_LocalUncoded_CS`(concept 1、`LocalUncoded_CS` = LocalCode 未使用 fallback)を LocalCode 本体と混同していた。**別 slice**。

### 修正版 slice 群(4 種)

| slice | system | code | display | 用途 |
|---|---|---|---|---|
| CoreLabo(43 項目相当) | JP_CLINS_ObsLabResult_CoreLabo_CS(JLAC10 or JLAC11) | 17 桁(CS 実体から取得) | Fixed(親コード名 = "K"/"AST" 等) | 43 項目該当時 |
| InfectionLabo(5 項目相当) | 同 InfectionLabo_CS | 17 桁 | Fixed(HBs-AG-RESULT 等)| 感染症 5 項目時(現状 emit 0)|
| **MEDIS(一般項目)** | `http://medis.or.jp/CodeSystem/master-JLAC10-17digits` | 17 桁(MEDIS 定義) | **自由**(display 自由項目) | fragment ゆえ本 fix chain では非採用 |
| **LocalCode(施設固有)** | `http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS` | **自由**(施設 code、英数字ハイフンアンダーバーのみ) | **自由**(日本語検査項目名 OK、空白不可) | 日本語検査項目名の置き場所 |
| **Uncoded**(未標準化 fallback) | `http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_Uncoded_CS` | Fixed = `99999999999999999` | Fixed = `未標準化コード項目(JLAC)` | 標準化不能時の必須 fallback |

日本語検査項目名は **LocalCode slice の display + `code.text`** に載せる(CoreLabo slice の Fixed display で潰されない)。

---

## F. 新規制約: CC BY-ND 4.0 licensing(訂正 (E) 反映)

### 事実

JP-CLINS(SD ページ・CS ページとも Copyright 欄)= **CC BY-ND 4.0**(著作者: 一般社団法人日本医療情報学会 JAMI)。

CC BY-ND §2(a)(1)(B): Adapted Material の**作成・複製**は許諾、**Share は不許諾**。

### 影響(2 巡目 §E / §H 提案 修正)

| 対象 | 可否 |
|---|---|
| JP-CLINS パッケージを未改変で clinosim repo に同梱 | **可**(Licensed Material の Share は許諾) |
| CS/SD から抽出した yaml/json を public repo に **commit** | **不可**(Adapted Material の Share) |
| 抽出スクリプトの配布 | **可** |
| 生成した合成データに JLAC10 code + display が入る | **可**(用語の通常利用) |
| **スクリプトに実データ埋込**(session 59 `_TX_SERVER_VERIFIED_YJ_CODES` pattern を JLAC10 に applied)| **不可**(スクリプト配布の体裁でデータを配ることになる) |

### 訂正対象

**2 巡目 §E Phase 1 項目 1〜3、§H snapshot commit 案は採用不可**:

- ~~`clinosim/codes/data/jp_clins_corelabo_jlac10_slice_display.yaml` 新設(SD から script 抽出、commit)~~
- ~~slice registry snapshot(`/tmp/jlac10_slice_registry.json`)を `clinosim/codes/data/` に commit~~
- ~~`_TX_SERVER_VERIFIED_MEDIS_17DIGIT_CODES` snapshot(session 59 YJ pattern 再利用)~~

いずれも **build/起動時にパッケージから抽出する設計**に変更(LOINC / SNOMED の既存方式と整合)。

**現状 clinosim にある `clinosim/codes/data/jlac10.yaml`(45 entry、全 5 桁)は clinosim 自作の内部使用 code data**、JP-CLINS からの抽出物ではない = 存在自体は BY-ND 抵触せず、が、CoreLabo 移行で「JP-CLINS 側の親コード + display」を書き写す形になると新規に BY-ND 違反 = **書き写さない**設計にする。

内部名 → 親コード対応表(clinosim 独自の mapping)は BY-ND 対象外 ✅、これは commit 可。

BY 表示義務:
- 同梱パッケージ内 Copyright notice の保持
- `docs/terminology-setup.md` 等に JAMI クレジット + 入手手順を記載

---

## G. 新たに判明した罠: slice 名 ≠ 親コード ≠ Fixed display の 3 空間

user 提示の実例、実測で追認:

| slice 名(SD) | 親コード(CS) | Fixed display(SD) |
|---|---|---|
| `abo-bld` | **`BLD-ABO`**(語順反転) | `血液型-ABO` |
| `rh-bld` | **`BLD-Rh`** | `血液型-Rh` |
| `pt-sec` | `PT-Sec` | `PT-秒` |
| `pt-ratio` | `PT-Ratio` | `PT比` |
| `utp-HalfQty` | `U-TP-HalfQty` | `U-TP-半定量` |
| `u-pc` | `U-P/C` | `U-P/C` |

**登録時は 3 列(slice 名 / 親コード / Fixed display)**を機械抽出で持つ。手写経禁止 rule 継承。

---

## H. 3 巡目 設計提案(実装しない、案のみ)

### H.1 パッケージ配布 + 実行時抽出方式(BY-ND 準拠)

- **同梱**: `terminology/jpfhir-terminology-2.2606.0.tgz`(未改変、JAMI Copyright notice 保持)を `clinosim/` に置く or `docs/terminology-setup.md` で入手手順を記載 + gitignore(LOINC/SNOMED 方式と統一)
- **抽出タイミング**: **初回アクセス時 lazy load**(`@lru_cache(maxsize=1)` 経由)= 起動時オーバヘッド回避、build 時は不要
- **キャッシュ**: `~/.cache/clinosim/jp_clins_labresult_slice_registry.json`(gitignore、ユーザー環境で再生成可能)or in-memory only(prod 起動時 ~ms cost、cache 不要と判断可)
- **memory footprint**: 778 code × 55 親 = 数十 KB、in-memory dict 問題なし

### H.2 内部名 → (親コード, 17 桁 code, Fixed display) 解決経路

| clinosim 内保持 | JP-CLINS 側から実行時取得 |
|---|---|
| `clinosim/locale/jp/code_mapping_lab.yaml`: **内部名 → 親コード** のみ(例: `WBC: WBC`, `Creatinine: Cre`, `K: K`, `Glucose_fasting: FBG`) — clinosim 独自 mapping、BY-ND 対象外 | 親コード → 17 桁 code list(778 rows) |
| glucose/PT の disambig helper | 親コード → Fixed display(SD 由来) |
| Fallback(内部名 → Uncoded)| |

`system_key_for("lab", "JP")` は 3 branch(CoreLabo / InfectionLabo / Uncoded)にディスパッチ = `_COUNTRY_SYSTEM_KEYS` の `dict[str, str]` から 1 値対応の shape 変更が必要(内部名 → system key を返す)。

### H.3 17 桁 code 選択規則(1 親あたり複数 code 対応)

- **決定的選択**: 各親配下 code list を **辞書順 sort → 先頭 1 個を代表**として固定選択
- **seed 非依存**(RNG 消費なし、[[feedback_rng_preservation_for_population_changes]] rule 遵守)
- 例: WBC → `2A990000001930952`(辞書式最小)
- 将来「材料・測定法を synthesize したい」場合は次 chain で疾患 protocol 側に材料 hint を追加、選択規則を拡張(現時点は代表 1 個で十分)

### H.4 グルコース / PT disambiguation 実装方式

- **disambig source**: `OrderResult` type 拡張 or 疾患 protocol YAML の `display_name` 表記規約
  - **推奨: 疾患 protocol YAML 側で名前規約**(`Glucose_fasting` / `Glucose_random` / `Glucose_capillary`)= physiology / RNG 影響なし、type 拡張最小
  - `canonical_lab_name` alias で `Glucose_fasting → FBG` 等 clinosim 内部名にマップ
- **RNG 影響**: 疾患 protocol YAML 側名前決定 = order 生成順序は現状と同じ、physiology 生成 order も同じ → RNG 順序変わらない
- PT 同様(`PT_sec` / `PT_ratio` / `PT_act` / `PT_INR`)

### H.5 CoreLabo 非該当 218 件の Uncoded fallback 経路

- 内部名 mapping で親コードが決まらないもの → 自動的に Uncoded slice に fallback
- 実装: `code_mapping_lab.yaml` に entry が無い + LOINC も (secondary で) 無い場合、**Uncoded CS URI + `99999999999999999` + Fixed display `未標準化コード項目(JLAC)`** を emit
- **完全 spec 準拠**、MEDIS マスター入手 / 17 桁 mapping 作業不要
- 日本語検査項目名は LocalCode slice の display + `code.text` に載せる

### H.6 `code.text` と `display` の分離

現状 `_fhir_observations.py:130-131`:

```python
"code": {
    "coding": [{"system": code_system, "code": code_value, "display": display_name}],
    "text": display_name,  # ← 同一変数を display + text 両方に投入
}
```

移行後:

```python
"code": {
    "coding": [
        # CoreLabo or Uncoded slice
        {"system": corelabo_cs_uri, "code": seventeen_digit_code, "display": FIXED_DISPLAY[parent_code]},
        # LocalCode slice (自由スロット、日本語検査項目名)
        {"system": localcode_cs_uri, "code": local_code, "display": jp_test_name_no_space},
    ],
    "text": jp_test_name,  # ← 日本語(空白 OK、必須 1..1)
}
```

- `display` = 各 slice の Fixed または LocalCode 自由 display(空白なし推奨)
- `text` = 日本語検査項目名(空白 OK、既存 `display_name` 相当)
- **2 変数分離**が必須

### H.7 LOINC secondary coding の扱い

**推奨: 削除**(理由 3 点):

1. spec 未定義 system = Open slice で silent-pass するが Fixed display slice 制約に貢献しない
2. 削除で emit サイズ削減、consumer が LOINC 経由で照合したい場合は clinosim 側 mapping table を別途公開すれば十分
3. secondary attach は session 45 の「JP Core dual-coding」意図で追加された歴史がある、spec 側で JP-CLINS が明示的に「LOINC 使わない」と定義 → 意図が矛盾

**country 分岐で US path のみ残す実装**が clean:
- JP path = CoreLabo + LocalCode の 2 coding(spec 準拠)
- US path = LOINC 単独(現状維持)

---

## I. RNG 影響 再確認(2 巡目 §F を維持)

**変わらない見込み**:
- coding system + display 変更のみ、physiology / order 生成の RNG 順序に影響しない
- disambig は疾患 protocol YAML の名前規約変更 = 生成順序に影響しない設計(§H.4)
- 17 桁 code の決定的選択 = seed 非依存(§H.3)
- `code_mapping_lab.yaml` iteration 依存 code path 無し(2 巡目 §6 で grep 確認済)

---

## J. Summary(fact-only、判断はしない)

| # | 事項 | 事実 |
|---|---|---|
| A | CoreLabo/JLAC10 CS 実体 | **jpfhir-terminology#2.2606.0 pkg** に存在、`content=complete`、55 親 / 778 code。2 巡目 §A grep 漏れ訂正済 |
| A | InfectionLabo/JLAC10 CS 実体 | 同 pkg、complete、38 code |
| A | JLAC11 版 CS | 両方 fragment(将来対応候補) |
| A | 17 桁 mapping table 手動作成 | **不要**、内部名 → 親コードだけあれば CS から機械取得 |
| B | display 供給経路 | 2 巡目 §C 維持(単一変異点 `_fhir_observations.py:82`) |
| C | test case 実 code | `2A990000001999952` (WBC child、実測、CS 実体で確認済) |
| D | カバー率 | **disambig 無し 73.5%(1,855) / グルコース+PT 実装 90.8%(2,291)** |
| D | CoreLabo 非該当 | **218 件**(訂正済) |
| E | LocalCode slice | 自由スロット(concept 1 固定 CS ではない)、日本語検査項目名の置き場所 |
| E | Uncoded slice | concept 1(Fixed code + Fixed display)、CoreLabo 非該当の必須 fallback |
| F | ライセンス | JP-CLINS = CC BY-ND 4.0 = **抽出物 commit 禁止**、build/実行時抽出 |
| G | slice 名 / 親コード / Fixed display 3 空間 | 例:`abo-bld` / `BLD-ABO` / `血液型-ABO` = 手写経禁止、機械抽出必須 |
| H | 設計提案 7 項目 | 実行時 lazy load、内部名 → 親コード保持、17 桁決定的選択、疾患 YAML disambig、Uncoded fallback、text/display 分離、LOINC 削除推奨 |
| I | RNG 影響 | 変わらない見込み |

---

## K. gate(実装着手前の validator 側未確認事項)

以下 2 点が workspace:2 側で解決するまで実装は保留:

1. **fhirserver がカスタム階層 CS に対して `descendent-of` filter による VS expansion を実行できるか**
   - CoreLabo CS は 2 段階層(親 55 + child 778)
   - VS 190 個は全て `filter: descendent-of, value:<親>` 型
   - 動かない場合、CS 存在しても required binding 解決不能

2. **display 不一致が silent-pass するか**(§C test case、実 code 差し替え後)
   - case 1(display 不一致)が silent-pass なら「仕様準拠は validator では担保できず生成側の自律責務」
   - 投資対効果の測定指標が「validator error 減」から「slice match 率 (self-measurement)」に切り替わる

**両者は workspace:2 側で確認、結果共有後に本設計への影響を再評価** → 設計 finalise + 実装 chain 開始。

---

## L. 実装参照 index(3 巡目追補)

- **CoreLabo/JLAC10 CS 実体**: `../fhir-jp-validator/tx-server-build/terminology/fhir-server/jpfhir-terminology#2.2606.0/package/CodeSystem-jp-clins-codesystem-jlac10-corelabo-cs.json` (55 親 / 778 code、`content=complete`、`version=2026.03.31`)
- **InfectionLabo/JLAC10 CS 実体**: 同 pkg `CodeSystem-jp-clins-codesystem-jlac10-infectionlabo-cs.json`
- **LocalUncoded CS**: 1.12.0 pkg `CodeSystem-jp-clins-obslabresult-localuncoded-cs.json`(concept 1、fallback)
- **Uncoded CS**: 同 `CodeSystem-jp-clins-obslabresult-uncoded-cs.json`(concept 1、CoreLabo 非該当時 fallback)
- **SD 元**: `StructureDefinition-JP-Observation-LabResult-eCS.json`(slice 定義 + Fixed display source)
- **VS 190 個**: 全て `filter: descendent-of` 型、CS 実体経由で expand
- **現状 emit builder**: `clinosim/modules/output/_fhir_observations.py:43-152 _build_lab_observation`
- **display 単一変異点**: `_fhir_observations.py:82` `code_lookup(code_system_key, code_value, lang)` + `:130-131` emit
- **system dispatch**: `clinosim/codes/loader.py:180-192 _COUNTRY_SYSTEM_KEYS`(shape 拡張候補)
- **上流 canonical helper**: `clinosim/modules/observation/engine.py:37 canonical_lab_name` + `reference_data/lab_aliases.yaml` + `lab_panels.yaml`
- **walker safety(JP-CLINS URI 対象外確認)**: `_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES` に JP-CLINS URI 含まれず、primary coding は素通り

以上、3 巡目調査 + 設計提案完了。**gate 2 件解決後に実装 chain 開始判断**をユーザー側で。
