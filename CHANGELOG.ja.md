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

## [0.3.0] - 2026-08-22 (JP load-bearing 追記)

- **JP-CLINS MedicationRequest `timing.code` を MHLW `MedicationUsage_ePrescription` 実 code 化**: 従来 100% dummy `0X0XXXXXXXXX0000` だったが、薬剤クラス + freq + route heuristic により **85.86% の dosage に実 MHLW code** を付与 (statin→就寝前、PPI→朝食前、biguanide→朝夕食後、抗生剤→毎食後 等)。route filter (`_NON_ORAL_ROUTE_MARKERS`) により **oral code は `route=経口` の record のみに emit**、意味的に正しくない oral code emit を排除。残 14.14% dummy は MHLW oral CS 未収載 route (吸入/静注/皮下注/筋注/舌下/直腸 等)、spec-legit の JP-CLINS uncoded fallback。
- **narrative text 内の JP 生 token localization**: `staff_id` (`DR-CA-002` → `加瀬 幸男 医師`)、`severity` (`mild` → `軽度`)、`oxygen_device` (`nasal_cannula` → `経鼻カニューレ`)、`fall_risk_level` (`high` → `高リスク`) をすべて template 層で source-fix (LLM が verbatim preserve するので template で resolve すれば FHIR emit にも反映)。従前の Composition post-hoc walker (`_localize_practitioner_ids_in_text`) は defence-in-depth として維持。
