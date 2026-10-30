# `clinosim.modules.drug_safety`

クラスベースの禁忌併用ゲート + 代替薬 substitution。

## 1. 目的

実 EHR の CPOE (Computerized Physician Order Entry) が処方時点で禁忌
併用を防ぐのと同様に、生成される CIF/FHIR 記録に禁忌併用が現れないよう
にする。 修正前は US p=10,000 コホートで ~150 件の禁忌ペア
(warfarin+aspirin、warfarin+NSAID、β遮断薬+非DHP CCB、ACEi/ARB+K 補充)
が発生していたが、simulator の処方経路 (入院時 / daily loop / ED /
退院処方 / 予防投与) と `patient` activator から呼び出される class ベースの
rule engine によって 0 件に低減する。薬剤 × 疾患状態
(`check_candidate_against_disease_state`) と薬剤 × 年齢/性別
(`check_demographic_gate`) の禁忌 gate も併せて提供する。

## 2. スコープ

**含まれる**:
- Rule engine: class × class 禁忌 lookup と severity 判定
  (allowed / minor / moderate / major / contraindicated)。
- 薬剤 class × 慢性疾患状態 rule (`disease_contraindications.yaml`、
  Issue #1392 / #1350、stage 条件 `stage_in` は Issue #1769)。
- 年齢 / 性別 gate (`demographic_gates.yaml`、Issue #1316 / #1328)、
  ICD prefix の `exception_indications` で bypass。
- 代替薬 substitution: Issue #437 の dead-data `alternative_*` block
  を revive + 新規 `locale/shared/drug_substitution.yaml`。
- CIF trace (`PatientProfile.safety_skip_log`)。
- Narrative 統合 (4 layer 全て)。
- MedicationRequest.note[] passthrough (moderate DDI caution)。
- AD-60 スタイルの audit 関数 (stand-alone、audit registry には未登録)。

**含まれない (post-MVP)**:
- `DetectedIssue` FHIR リソースの emit (実 CPOE は skip した order の
  痕跡を残さない; DetectedIssue は薬剤師 review workflow の産物)。
- `allow_if_indication` whitelist (post-PCI+AF、機械弁例外)。
- `antibiotic` モジュール統合。
- 慢性薬の substitution (activator は skip-only)。
- LLM production 評価 (H100 clinician-eye review)。

## 3. 公開 API

`README.md` の Section 3 を参照。

## 4. Determinism

- 判定は pure YAML lookup、RNG 非消費。
- Substitution は YAML 順で最初の conflict-free 候補を選ぶ。
- RNG shape shift はコホート規模の変化として MINOR bump 対象。
- Cross-platform bit-reproducibility 保証 (`_DeterministicRngProxy`
  regime 下で安全)。

## 5-11

`README.md` (英語版) を参照。日本語ミラーは 1-4 のみ独立記述、以降の
セクションは README.md と 1 対 1 対応。

## Ownership

- session 99 (2026-09-03) — 初期実装。
- Spec: `docs/superpowers/specs/2026-09-03-drug-safety-module-design.md`
- Plan: `docs/superpowers/plans/2026-09-03-drug-safety-module.md`
- Issue: #1066
