# β-JP-1 chain 1a: Narrative Context CIF Wiring — Design Spec

**Date:** 2026-07-03(session 32)
**Status:** Approved for implementation
**Branch:** `feature/beta-jp1-1a-narrative-context-wiring`
**先行:** N-chain(PR #135)。spec §6 + adv-1 M-4 で deferred とした `_build_context`
degenerate fields の解消 = LLM seed 品質(β-JP-1 chain 1b)の前提。

## 1. Problem(実測、2026-07-03)

`NarrativePass._build_context`(`passes.py:158-193`)は Stage 2 の全 narrative 生成
(template + LLM seed)への入力 `NarrativeContext` を組み立てるが、structural CIF の
実 schema と乖離しており大半が空/固定値:

| ctx field | 現在の読み元 | 実態 |
|---|---|---|
| `vitals` | `patient_dict.get("vitals")` | **key 不存在**(実 = `vital_signs`)→ 常に `[]` |
| `medications` | `.get("medications")` | **key 不存在**(実 = `medication_administrations` / `orders` / `discharge_prescription`)→ `[]` |
| `diagnoses` | `.get("diagnoses")` | **key 不存在**(実 = `clinical_diagnosis`)→ `[]` |
| `allergies` | `.get("allergies")` | **key 不存在**(実 = `patient.allergies`)→ `[]` |
| `clinical_course_archetype` | `.get("clinical_course_archetype")` | **CIF に未永続化** → `""` |
| `severity` | `.get("severity")` | top-level に無し。`encounter.severity` は field 存在するが空 |
| `disease_protocol` | 固定 `None` | `condition_event.ground_truth_diseases[0]` から解決可能 |
| `day_index` / `los_days` | 固定 `0` | 全 daily note が「入院 1 日目」になる実害。stub の `period_start`/`authored_datetime` + encounter の admission/discharge から導出可能 |
| `narrative_spine` | `build_narrative_spine(None, None, "")` | 上記により degenerate |

結果: hpi「Patient presented with  symptoms.」等の退化 seed、進行 note の日付不変、
severity/archetype 非依存の均質 narrative。N-chain adv-1 C-1 の cache 退化を偶然マスク
していた根本原因でもある。

## 2. Scope

### 2a. Stage 1: archetype + severity の structural CIF 永続化(schema 変更)

- `EncounterRecord.clinical_course_archetype: str = ""` を新設(`types/encounter.py`、
  default 付き = 旧 CIF JSON 後方互換)。inpatient.py で archetype 決定箇所から書込み
  (unknown-condition 経路は `""` のまま)。
- `EncounterRecord.severity` を inpatient 経路で実書込み(現在空。ED は triage 経路で
  書込み済みか実装確認の上、欠けている venue のみ追加)。
- AD-30 確認: archetype/severity は code/enum 的内部値で display text ではない → 適法。

### 2b. Stage 2: `_build_context` の実 schema 配線

- 上表の全 field を実 key に修正。medications は「Stage 2 の consumer(template
  generator / fact extractors)が何を期待するか」を読み、admission~discharge の
  medication_administrations + discharge_prescription を適切に渡す(consumer の期待が
  別 shape ならそちらに合わせ、決定を spec 逸脱として report)。
- `disease_protocol`: `condition_event.condition_type == "known_disease"` のとき
  `load_disease_protocol(ground_truth_diseases[0])`(#133 で lru_cache 済 = 低 cost)。
  ED/outpatient の `encounter_protocol` は protocol key が CIF から復元可能な場合のみ
  配線、不可なら None 維持 + TODO(scope discipline)。
- `narrative_spine = build_narrative_spine(disease_protocol, condition_event, archetype)`
  (実 signature を読んで正しい引数で)。
- **per-stub `day_index` / `los_days`**: ctx は per-patient 構築のまま、stub loop 内で
  `ctx.shift` と同様に `ctx.day_index` を stub から設定(`period_start` or
  `authored_datetime` − `admission_datetime` の日数)。`los_days` は
  admission/discharge から(in-progress は engine と同じ los proxy 規則)。

### 2c. 消費側の最小追随

- template generator / fact extractors は「ctx が正しく埋まった」ことで自然に品質向上
  するのが原則。読み替え修正は required なもののみ(大改修は scope 外)。
- 期待される可視改善(verification で確認): progress note の日付が日毎に進む /
  hpi に chief_complaint + 実 symptom が入る / severity・archetype が trajectory 文言に
  反映される。

## 3. Out of scope(TODO)

- N-4 template YAML 化 / LLM golden + semantic diff(chain 1b)/ 厚労省 4 帳票(chain 2)
- encounter_protocol 復元(不可だった場合)
- fact extractor の全面リライト

## 4. Verification gates

1. unit / integration / e2e green。**goldens は変わる**(改善方向)→
   `regenerate-goldens --all` + AD-66 Rule 2 diff 精査(変化が context 配線起因のみか、
   全 6 profile の diff を categorize して report)+ `pytest -m regression` 6 PASS。
2. 新 unit: 各 mapping(vital_signs/medications/diagnoses/allergies/severity/archetype/
   disease_protocol/day_index per stub/los_days)の pin + 旧 CIF JSON(新 field 無し)
   読込の後方互換。
3. Pipeline sanity(US p=100 + JP p=100): progress note day 数列が 1..N で進行、
   hpi 非空、encounter.severity 非空率、archetype 永続化率を report。
4. audit run PASS(document_chain ほか)。
5. mock LLM seam 再確認: seed が非退化になったことで NarrativeCache の患者間 hit 率が
   下がる(= C-1 fix の実効性が上がる)ことを 1 例で確認。
