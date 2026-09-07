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

## [0.6.0] - 2026-09-07 (JP load-bearing 追記)

- **session 104 実測 defect fix 3 件** (2026-09-06 → 2026-09-07):
  - **JP 抗癌剤 canonical katakana** (PR #1170、Issue #1168 Cat A/B):
    `chronic_medications.yaml` 側で `drug_ja` 定義済だが
    `drug_names_ja.yaml` 側に未登録だった 14 薬 (Osimertinib →
    オシメルチニブ / Sorafenib → ソラフェニブ / Lenvatinib →
    レンバチニブ / 他 11 薬) を追加。localize 抜けが解消され JP
    narrative の EN 混入が消える。
  - **Rule 5 Section A に stage/persistence 語彙追加** (PR #1170):
    従来は mild/moderate/severe しか対象化されていなかったが、
    Stage / Level / Grade / persistent / intermittent を追加。
    prompt v15 → v16。case-insensitive 明示、「Mild persistent」
    → 「軽度持続」の複合形も enumerate。
  - **admission_hp EN 出力 Kanji 見出し混入 fix** (PR #1169、
    Issue #1167): 【評価】/【薬物療法】等 5 見出しの locale 分岐を
    prompt に明記。target_language=en 時は "Assessment /
    Medications / Diagnostics / Patient Education / Planned Length
    of Stay" に切り替わる。US p=100 で 4/859 doc が Kanji 混入 → 0 化。
- **calendar-day filter fix (progress-note vitals grounding)** (PR
  #1171、Issue #1166): `_filter_vitals_for_day` + 3 sibling
  helper が `timedelta.days` を使っており、20:23 admission だと
  day_index=1 が 2026-03-20 evening + 2026-03-21 daytime の 2 暦日
  にまたがっていた → LLM が Objective (day-1 evening) と別日 (day-2)
  の T=38.5°C spike を "today's" として引用する Rule 1 GROUNDING
  drift。calendar-day 化 (`(ts.date() - adm_dt.date()).days`) で解決。
- **疾患別 nursing content pilot (5 疾患)** (PR #1165): 従来 nursing
  content は chronic ICD-10 の 6 prefix のみ由来だったので、
  COPD 増悪 / DKA / HF 増悪 / 細菌性肺炎 / 脳梗塞 全て同一な内容が
  emit されていた。`nursing_content.yaml` に急性疾患軸を追加、NANDA-I
  / NIC / AHA-ADA-ATS-ASA 患者向け教育資材ベースで疾患別 nursing
  diagnosis / care plan / patient education を格納。
- **JP 完全生命表 (MHLW 2020 第23回) 導入 + natural_death lifecycle 完成** (PR #1147/#1150/#1152/#1153、session 103 C11g-1〜5):
  `clinosim/locale/shared/actuarial_life_table.yaml` に JP MHLW 生命表 (男/女、
  0-110 歳 5 年帯 qₓ) を追加、`clinosim.modules.natural_death.NaturalDeathEnricher`
  が per-person Bernoulli で自然死日をサンプリング、`is_alive_at(t)` を 4
  イベント dispatcher に配線、`Patient.deceasedDateTime` + `Patient.active=false`
  を deceased record に emit。JP p=10000 s326 1yr で 204/5,529 = 3.69% が
  deceased 化、死亡日以降の encounter は完全に 0 (jp-core-patient 準拠)。
- **JP 肺炎 (J18) hospital-cohort target band を (4, 14) に拡張** (PR #1145、
  Issue #1115): 高齢者向け急性期病院の入院来院 cohort では J18 有病率が
  一般人口ベンチマーク (~2%) より高いのが実運用通例なので、
  `scripts/verify_medical_stats.py::HOSPITAL_COHORT_TARGET.JP` に該当バンド
  を明示化し `OK-HC` verdict とした。JP demographics YAML は変更なし。
- **JP がん有病率を benchmark band 内へ -30%** (PR #1124、Issue #1112):
  MHLW cancer registry ベース。JP demographics YAML `chronic_prevalence.C**`
  の band を再校正。
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
