# `clinosim/modules/drug_safety/reference_data/`

drug_safety モジュールの YAML スキーマ。5 ファイル
(`contraindications.yaml`, `disease_contraindications.yaml`,
`demographic_gates.yaml`, `allergy_contraindications.yaml`,
`drug_substitution.yaml`) は初回利用時に
(`functools.lru_cache` でキャッシュ)
`clinosim.datafiles.load_validated_yaml` 経由で load される。同関数は
`metadata` header を除き、[`../_models.py`](../_models.py) の
`extra="forbid"` Pydantic model (`ContraindicationsFile`,
`DiseaseContraindicationsFile`, `DemographicGatesFile`,
`AllergyContraindicationsFile`, `DrugSubstitutionFile`) で内容を検証する。typo、未知キー、薬剤
カタログに無い class / drug id、rule id の重複は load 時に
`pydantic.ValidationError` となる。

## 薬剤 class

薬剤の同定・alias・class は薬剤カタログ
(`clinosim/codes/data/drugs.yaml`、Issue #2298) にある。classifier は
自由記述の薬剤名を `clinosim.codes.drugs.identify_drug` で解決し
(id / 名称 / alias の完全一致 → 先頭語 → テキストに含まれる最長の
カタログ名または alias、ASCII は単語境界一致)、class を
`drug_classes` で解決する (ドット区切りの祖先も全て付与:
`anticoagulant.vka` → `anticoagulant`)。薬剤や class の追加は
カタログの編集で行う。

class 体系の規約:

- `anticoagulant.{vka, doac, heparin}`
- `antiplatelet.{cox_inhibitor, p2y12}`
- `nsaid.{non_selective, preferential_cox2, cox2_selective}` (Aspirin は
  `antiplatelet.cox_inhibitor` と `nsaid.non_selective` の両方に属する
  dual-class)
- `ccb.{dhp, non_dhp}`
- `beta_blocker.{cardioselective, non_selective}`
- `acei` / `arb` / `acei_arb` (両者に付く union tag)
- `potassium_supplement`, `electrolyte_supplement`
- `diuretic.{loop, thiazide, k_sparing}`
- `statin`, `cyp3a4_substrate`, `cyp3a4_inhibitor_strong`
- `xanthine_oxidase_inhibitor`, `thiopurine`, `immunosuppressant`
- `ssri`, `snri`, `maoi`, `antidepressant`, `atypical_antidepressant`,
  `antiparkinsonian`
- `benzodiazepine`, `anxiolytic`, `biguanide`, `lithium`
- `analgesic.non_opioid`, `macrolide`
- `antihypertensive`, `antiarrhythmic.class4`

**目安**: 薬剤が属する class は全て付与する。rule は class で照合
されるため、既存 class に追加した薬剤はその class を対象とする全 rule
を自動的に継承する。

## `contraindications.yaml`

class × class の禁忌 rule。rule の追加は YAML 編集のみ。

```yaml
rules:
  - id: <kebab-case の一意な識別子>
    lhs: <カタログ class tag>
    rhs: <カタログ class tag>
    severity: minor | moderate | major | contraindicated
    rationale:
      en: "<1 文の臨床的根拠>"
      ja: "<日本語訳>"
    substitution_hint: <任意の indication tag。代替薬が無ければ null>
    source: "<出典: ガイドライン / DDI データベース / 教科書>"

discharge_reconciliation_rules: [<rule id>, ...]   # 退院処方で reconcile する rule (Issue #2713)

triple_therapy_after_acs:          # ACS 後に抗凝固薬 + DAPT で退院する場合の抗血栓療法 plan
  aspirin_days: <1 以上の int>
  p2y12_with_oac: <カタログ drug id>
  p2y12_dose: "<用量文字列>"
```

`discharge_reconciliation_rules` は `rules` で定義済みの rule id を
指す必要がある (`discharge_reconciliation_rules()` が読む)。
`triple_therapy_after_acs` は `triple_therapy_after_acs_plan()` が
読む。

照合:
- **順序非依存**: `check_pair(A, B) == check_pair(B, A)`。
- **複数 rule hit**: 最も severity の高い rule を採用。

`substitution_hint` は、`suggest_alternative` が
`drug_substitution.yaml` または疾患 YAML の `alternative_*` block
から代替薬を選ぶ際の prior となる indication tag を指す。

severity → default action (`allowed` はどの rule にも hit しない
場合の判定で、rule 側では指定できない):
| severity          | default_action    | narrative surface           |
|-------------------|-------------------|-----------------------------|
| `allowed`         | `emit`            | —                           |
| `minor`           | `emit`            | —                           |
| `moderate`        | `emit_with_note`  | MR.note に caution を付与   |
| `major`           | `skip`            | 代替薬 + skip log entry     |
| `contraindicated` | `skip`            | 代替薬 + skip log entry     |

## `disease_contraindications.yaml`

薬剤 class × 慢性疾患状態の rule。`check_candidate_against_disease_state`
が使用。

```yaml
rules:
  - id: <kebab-case の一意な識別子>
    drug_class: <カタログ class tag (codes/data/drugs.yaml)>
    disease_predicate:
      icd_prefix: [<ICD-10 prefix>]        # 必須、空不可
      stage_in: [<stage 文字列>]           # 任意 (Issue #1769)。entry が一致する stage を持つ必要あり
    severity: minor | moderate | major | contraindicated
    substitution_hint: <任意の indication tag>
    rationale:
      en: "..."
      ja: "..."
    source: "..."
```

`active_conditions` の entry は ICD 文字列単体または `(code, stage)`
tuple。一致した rule は全て返され (rule ごとに `SafetyVerdict` 1 件)、
caller が最も高い severity を選ぶ。

## `demographic_gates.yaml`

年齢 / 性別による「そもそも処方してよいか」の rule。
`demographic.check_demographic_gate` が使用。

```yaml
rules:
  - id: <kebab-case の一意な識別子>
    drug_names: [<大小文字を区別しない部分一致 alias — EN / JA / 商品名>]
    min_age: <0 以上の int>        # 任意 — 患者はこの年齢以上である必要
    sex: male | female             # 任意
    exception_indications: [<ICD-10 prefix>]   # 任意の bypass
    severity: minor | moderate | major | contraindicated
    rationale:
      en: "..."
      ja: "..."
    references: "<出典>"
```

rule は `min_age` / `sex` の少なくとも一方で gate する必要がある。
上限年齢の gate は無い。

複数 rule が発火した場合は最も高い severity の判定を採用 (同順位は
先頭の rule)。

## `allergy_contraindications.yaml`

薬剤 class × 記録済みアレルギー rule (Issue #2924)。
`engine.check_candidate_against_allergies` が読む。

```yaml
rules:
  - id: <kebab-case の一意な識別子>
    allergen_code: "<modules/allergy/reference_data/allergens.yaml の医薬品アレルゲンの SNOMED code>"
    drug_classes: [<カタログ class tag>, ...]     # 候補薬がいずれかに属する
    exclude_classes: [<カタログ class tag>, ...]  # 任意: かつ、いずれにも属さない
    severity: minor | moderate | major | contraindicated
    rationale: {en: "...", ja: "..."}
    substitution_hint: <任意: suggest_alternative の indication tag>
    source: "<出典>"
```

患者に `allergen_code` の有効なアレルギー記録 (clinical status
`active`、refuted でない、「アレルギー歴なし」でない) があると rule が
発火する。`contraindicated` / `major` は薬剤を出さない
(`safety_skip_log` に記録し、`substitution_hint` の代替を
`suggest_alternative` が見つければ置換)。`moderate` / `minor` は注意
note 付きで出す。現行エビデンスで低リスクとされる交差反応 class
(ペニシリンアレルギーでのセフェム系、アスピリンアレルギーでの選択的
COX-2 阻害薬、サルファ剤系抗菌薬アレルギーでの非抗菌薬スルホンアミド)
は `moderate`。

## `drug_substitution.yaml`

汎用 indication → 代替薬 pool。疾患 YAML の `alternative_*` block
(`_indication_tag` 経由) の後、`None` を返す前に参照される。

```yaml
indications:
  <indication_tag>:
    description: "<1 行の説明>"
    alternatives:
      - drug_id: <clinosim/codes/data/drugs.yaml の id>   # 表示名 (en + ja) はカタログから解決
        default_dose: "<中立的な用量文字列>"
        default_route: "<PO | IV | SC | INH>"
        default_frequency: "<daily | bid | tid | qid | prn | q6h_prn>"
```

`suggest_alternative` は `alternatives` list を順に走査し、各候補を
`check_candidate_against_active` (ペアごとの `check_pair`) で caller の
active 薬と再照合する。最初に conflict の無い entry を採用する。

## `hyperkalemia_response.yaml`

入院中の K 高値への対応 (Issue #2981)。
`clinosim.modules.drug_safety.hyperkalemia` が読み、
`HyperkalemiaResponseFile` で検証する:

- `treat_threshold_mmol_l` — 休薬とオーダーセットを発動する K 値
  (mmol/L、6.0)。
- `hold_classes` — 結果時刻から退院まで休薬するカタログ class
  (`acei`、`arb`、`diuretic.k_sparing`)。
- `treatment.<US|JP>` — 単回オーダー: `drug_id` (カタログ)、`dose`
  (解析可能なオーダー用量、例 `1 g IV`)、`dose_text.{en,ja}`
  (各言語の用法指示)、`ongoing: true` (K 吸着薬) は閾値以上が続く日に
  繰り返す。

## rule の追加手順

1. rule の対象薬剤に `codes/data/drugs.yaml` で class を付与する。
2. 出典ガイドラインを明記して `contraindications.yaml` に rule を追加
   する。自然な indication tag があれば `substitution_hint` を設定する。
3. substitution_hint が新規なら `drug_substitution.yaml` に追加する
   (疾患スコープに該当する疾患 YAML の `alternative_*` block があれば
   そこに `_indication_tag` marker を付けてもよい)。
4. `check_pair(drug_a, drug_b).severity == <expected>` を検証する
   unit test を追加する。
5. コホート検証: p=1000 の sim で `verify_medical_stats.py` を実行し、
   `contraindicated_pair_count` が 0 のままであることを確認する。

英語版: [`README.md`](README.md)。
