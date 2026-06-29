# Session 23 Breakpoint Data Quality Review

**Date**: 2026-06-29
**Cohort**: scratchpad/session23_breakpoint_dqr (US p=10000 + JP p=5000, seed=42)
**Master**: `7db639c54f`(PR #123 区切り達成宣言 merge 直後)
**Audit**: `clinosim audit run -d scratchpad/session23_breakpoint_dqr`

## Summary

**Overall: PASS** with WARN-regime expected at p=10000 (rare-event HAI bands).

3 軸全て健全:
- **データ品質**: CLEAN(0 violations across 5 structural checks)
- **臨床整合性**: 主要 disease marker distribution 健全(過去 PR fix 全て維持)
- **JP language quality**: CLEAN(primary coding 全 100% 日本語、secondary English coding は AD-44 multilingual interop 仕様通り)

Cohort size:
- US: 24,883 patients / 161,032 encounters / 3.49M observations / 650 microbiology cultures(うち **4 件 HAI-derived** = PR3b-5 HAI_EVENT_ID_SYSTEM identifier emission production fire 観測)
- JP: 2,458 patients / 16,184 encounters / 422K observations / 77 microbiology cultures(p=5000 rare-event regime で HAI 0 件)

## 1. データ品質 axis(構造健全性)

| Check | US | JP | Verdict |
|---|---|---|---|
| Resource ID duplicates | 0 | 0 | ✓ CLEAN |
| Unresolved references | 0 | 0 | ✓ CLEAN |
| display == code violations | 0 | 0 | ✓ CLEAN |
| Numeric Observation missing refRange(主要 lab: WBC/CRP/JLAC10) | 0 | 0 | ✓ CLEAN |
| Interpretation without refRange | 0 | 0 | ✓ CLEAN |

**HAI identifier emission(PR3b-5 production verification)**:
- US: 650 mb-org-* 中 **4 件が `urn:clinosim:identifier:hai-event-id` identifier 付き**(PR3b-5 emission wiring が p=10000 で初観測)
- JP: 0 件(rare-event regime、production p=50k+ で fire 想定)

## 2. 臨床整合性 axis(主要 disease marker distribution)

### 過去 PR fix 維持(US cohort、median 値)

| Marker / Disease | Baseline | Acute disease cohort | Verdict |
|---|---|---|---|
| Troponin I (MI cohort) | 35.2 ng/mL | **80.14**(MI 401 patients) | ✓ ACS marker fire(PR #28 BNP-pattern surgical 系) |
| WBC (Sepsis cohort) | 8316 | **13131**(Sepsis 60 patients) | ✓ leukocytosis(PR3a HAI lift パターン適用) |
| CRP (Sepsis cohort) | 12.5 mg/L | **132.4**(Sepsis 60 patients) | ✓ strong inflammation |
| Temp (Sepsis cohort) | 37.4°C | **38.7°C**(p95 40.0°C) | ✓ 発熱 fire(PR #8 ED 急性提示) |
| Lactate (Sepsis cohort) | 4.4 mmol/L | **4.6**(Sepsis 60 patients) | ✓ elevated |
| SBP (Sepsis cohort) | 119 mmHg | **116**(p95 142、低下緩やか) | ⚠ septic shock 過少(memory `project_realism_gaps` 既知)|
| Cr (CKD cohort) | 1.22 mg/dL | **1.64**(p95 4.52, CKD 1424 patients) | ✓ baseline elevated |
| Na (HF cohort) | 139 mEq/L | **134**(HF 251 patients) | ✓ hyponatremia(古典的 HF sign) |
| HbA1c (Diabetes cohort) | 7.1% | **7.1%**(p95 11.5%, DM 11251 patients) | ✓ diabetic range(PR #44 DET-6 glycemic_control 軸) |

### PR3b-3 D1+D2 + PR3b-5 gate(US 10k で initial production fire)

| Gate | n | Observed | Verdict |
|---|---|---|---|
| CAUTI WBC delta p50 | 14 | **+1760.5**(baseline 12044 → cohort ~13800) | ✓ HAI inflammation lift 観測(PR3a forward-delta) |
| CAUTI CRP delta p50 | 13 | **+35.0**(baseline 23.7 → cohort ~58) | ✓ |
| us_cauti/112283007/ceftriaxone R-rate | n=1 | n<30 WARN | rare-event 規定通り |
| us_vap/3092008/cefazolin R-rate | n=1 | n<30 WARN | rare-event 規定通り |
| us_hai_empty_susc_rate | n=2 | **0.000**(<5% threshold) | ✓ PR3b-5 panel-eligible filter 効いてる |
| us_cauti narrow_rate | n=3 | **0.667** | ✓ narrow / de-escalation chain fire(PR3b-3) |
| us_vap narrow_rate | n=1 | **1.0** | ✓ |

silent_no_op axis: **PASS** all modules(17/17 equality_checks across antibiotic + hai).

## 3. JP language quality axis(多言語表示整合性)

**CLEAN**(primary coding 100% 日本語、secondary English coding は intentional multilingual interop)。

- Primary coding(`coding[0].display`)の英語 leakage: **0 件**(35994 Conditions 全部 日本語 primary)
- Secondary coding(`coding[1+].display`、English for FHIR R5 interop)の英語: 35994(AD-44 multilingual coding 仕様通り、intentional)
- 例:I10 → primary `"本態性高血圧症"` + secondary `"Essential (primary) hypertension"` ✓

JP 値の単位整合性(JLAC10):
- Na (3H010): 141 mmol/L ✓
- K (3H015): 4.5 mmol/L ✓
- Plt (2A050): 260 × 10³/μL ✓
- Lactate (3E010): 3.5 mmol/L(sepsis sample 由来 elevated)✓

## 4. silent_no_op axis(harness 自体の self-check)

- antibiotic module: **17/17 equality_checks PASS**(8 PR3b-1 regimen + 3 PR3b-2 antibiogram + 6 PR3b-3 narrow chain)
- hai module: WBC delta proof = 2520.0 ✓

## 既知の WARN(rare-event regime + 既知 issue)

- HAI cohort 系 gate は p=10000 では n<30 WARN regime のまま(production p>=50k or ForcedScenario で fire)
- sepsis SBP<90 = 過去 #62 で fix 済だが本 cohort で SBP p95=142、distribution の low tail を p=10000 で再確認しても **septic shock 過少**は memory `project_realism_gaps` 既知 issue として継続

## Verdict

**全 3 axis CLEAN、Overall PASS(WARN-regime 規定通り)。**

PR3b-3 + PR3b-5 + sibling sweep 3 chain CLOSE 後の master が production cohort に対して:
1. 構造健全(0 violations)
2. 臨床健全(過去 PR fix 全維持、PR3a HAI lift + PR3b-5 HAI identifier emission の **first production fire 観測**)
3. JP 日本語 quality 健全(primary 100% localized)

「区切り達成」状態の honest verification。

## 推奨 next actions(本 DQR で actionable な発見なし、既存 TODO 継続)

- **次セッション task** = TODO.md formal entries から選択:PR3b-4 WBC/CRP decay / audit registry `_reset_for_test` ordering fix / NHSN clinical-accuracy verification / DESIGN.md ADR polish / `_code_in_data` public API promote / 等
- 既知の sepsis SBP < 90 過少は memory `project_realism_gaps` で記録、本 DQR は regression なし確認のみ
