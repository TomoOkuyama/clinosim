# Changelog (日本語)

**clinosim** の全変更履歴は英語版 [`CHANGELOG.md (English)`](CHANGELOG.md)
に記載されています。

書式は [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) に基づき、
本プロジェクトは
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) に従います。

- **MAJOR** — API / CIF / FHIR schema の非互換変更。
- **MINOR** — 後方互換な機能追加 (新モジュール、新 resource 型、
  追加 locale サポート)。
- **PATCH** — 後方互換なバグ修正、CIF / FHIR schema を変えない
  データ品質修正。

**決定論保証**: `(seed, hospital_config, country, start, end,
population)` タプル固定で、同一 MINOR 系列内の PATCH-only リリース
間で NDJSON 出力は byte-identical であること。MINOR リリースは
byte 出力を変更してよいが、変更内容は英語版 CHANGELOG に記録される
こと。

## 翻訳ポリシー

Changelog は release note の速さを重視する性質上、本 file は
英語版へのポインタとして最小に保っています。個別 release で
日本語圏開発者に load-bearing な変更 (JP-Core / JP-CLINS profile 変更、
JP 表示テキスト方針変更、JP 保険番号 opt-in 挙動変更等) が発生した
場合は本 file に該当 entry のみ日本語で追記する運用です。

英語版: [`CHANGELOG.md (English)`](CHANGELOG.md)。

## [Unreleased] (JP load-bearing 追記)

- **外来 follow-up 診療科 resolver 化**: 従来 `outpatient.py` が
  post-discharge / chronic / screening / pediatric すべての外来 follow-up
  encounter で `department_id="internal_medicine"` を hardcode し、
  外傷 (外科入院) 後のフォローが内科、AFib/HF chronic フォローが内科、
  colonoscopy screening が内科、well-child / mammography / 予防接種が
  内科 に落ちていた。新規 resolver
  `simulator/outpatient_dept.py::resolve_outpatient_department` が
  (visit_type × 疾患/screening code) → 専門科 mapping と既存
  `hospital_ops.resolve_department` (yaml の `department_rollup` 経由で
  available_departments に collapse) を合成し、post-discharge は
  入院時 `department_id` を継承 (継続診療の臨床整合)、chronic 心疾患
  (I25/I48/I50/I20/I21/I26) → 循環器内科、chronic GI → 消化器内科、
  M81 骨粗鬆症 → 整形外科、colonoscopy screening → 消化器内科、
  well-child / mammography / 健診 / 予防接種 → 総合診療科 (primary_care)、
  それ以外 (I10 HTN / E11 DM / E78 dyslipidemia / N18 CKD / J44 COPD /
  E03 hypothyroid 等 = 日本の外来実務で 内科 fallback) → internal_medicine
  へ振り分け。JP p=10000 s500 sample で **post_discharge 265 件 (34.2%) と
  chronic + screening 15,316 件 が正しい診療科へ再配置**。
  `hospital_operations.yaml` / `hospital_small.yaml` の rollup に
  `pediatrics: primary_care` / `obgyn: primary_care` / `dermatology:
  primary_care` を追加 (この 50-bed 病院に無い OPD 専門科の fallback
  先を明示化)。RNG 影響: `assign_staff("rounds", dept)` の pool が
  変わることで各 outpatient encounter 内の RNG stream が shift する
  が、per-encounter phase RNG なので他 encounter に伝播しない
  (inpatient / ED / narrative pipeline は byte-identical 保持)。

## [0.3.0] - 2026-08-22 (JP load-bearing 追記)

- **JP-CLINS MedicationRequest `timing.code` を MHLW `MedicationUsage_ePrescription` 実 code 化**: 従来 100% dummy `0X0XXXXXXXXX0000` だったが、薬剤クラス + freq + route heuristic により **85.86% の dosage に実 MHLW code** を付与 (statin→就寝前、PPI→朝食前、biguanide→朝夕食後、抗生剤→毎食後 等)。route filter (`_NON_ORAL_ROUTE_MARKERS`) により **oral code は `route=経口` の record のみに emit**、意味的に正しくない oral code emit を排除。残 14.14% dummy は MHLW oral CS 未収載 route (吸入/静注/皮下注/筋注/舌下/直腸 等)、spec-legit の JP-CLINS uncoded fallback。
- **narrative text 内の JP 生 token localization**: `staff_id` (`DR-CA-002` → `加瀬 幸男 医師`)、`severity` (`mild` → `軽度`)、`oxygen_device` (`nasal_cannula` → `経鼻カニューレ`)、`fall_risk_level` (`high` → `高リスク`) をすべて template 層で source-fix (LLM が verbatim preserve するので template で resolve すれば FHIR emit にも反映)。従前の Composition post-hoc walker (`_localize_practitioner_ids_in_text`) は defence-in-depth として維持。
