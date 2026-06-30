# document モジュール

## 役割

Tier 1 #3 α-min-1 の Always-on Module (AD-55 near-essential cascade)。
入院・外来・救急 encounter ごとに臨床 narrative (入院時記録 / 経過記録 / 退院サマリ) を生成し、
FHIR `DocumentReference` / `Composition` として emit する。

α-min-1 段階では骨格 (DocumentTypeSpec registry + NarrativeContext factory) を提供。
Task 6+ で template generator、Task 8 で POST_ENCOUNTER enricher、Task 9 で FHIR builder を追加する。

## Dependencies

- `clinosim/types/document.py` — `DocumentType` / `FormatType` / `NarrativeContext` / `NarrativeOutput`
- `clinosim/types/allergy.py` — `Allergy` (NarrativeContext.allergies)
- `clinosim/modules/_shared.py` — `get_attr_or_key` (dual-access helper for dict / dataclass)

## Reference data

| ファイル | 説明 |
|---|---|
| `reference_data/document_type_specs.yaml` | 3 文書種別の LOINC コード・表示名・セクション構成・生成戦略 |

α-min-1 scope = `ADMISSION_HP` / `PROGRESS_NOTE` / `DISCHARGE_SUMMARY` の 3 種。本 chain では追加禁止 (scope discipline)。

## Canonical ID-prefix constants

| 定数 | 値 | 対応 FHIR resource |
|---|---|---|
| `DOC_REFERENCE_ID_PREFIX` | `"doc-"` | `DocumentReference.id` |
| `COMPOSITION_ID_PREFIX` | `"comp-"` | `Composition.id` |
| `ALLERGY_ID_PREFIX` | `"allergy-"` | 参照先 `AllergyIntolerance.id` |
| `CLINICAL_IMPRESSION_ID_PREFIX` | `"ci-"` | `ClinicalImpression.id` |

FHIR builder (Task 9) はこれらをインポートして使用する。

## Consumers

- Task 6 narrative generator: `build_narrative_context()` で `NarrativeContext` を受け取り `NarrativeOutput` を返す
- Task 8 enricher: `load_document_type_specs()` + `specs_for_country()` で生成対象文書を決定
- Task 9 FHIR builder: ID-prefix 定数でリソース ID を構築

## 関連

- 仕様: `docs/spec/tier1-document-density-alpha-min-1-spec.md`
- マスタープラン: `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
- 設計: `DESIGN.md` (AD-55, AD-62)
