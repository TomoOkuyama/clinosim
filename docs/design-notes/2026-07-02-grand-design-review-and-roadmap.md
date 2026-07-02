# Grand Design Review & Roadmap 再構成(2026-07-02)

**Status:** Active(session 31)
**先行文書:** [`2026-06-30-tier1-document-and-event-density-master-plan.md`](2026-06-30-tier1-document-and-event-density-master-plan.md)(7 phase master plan、引き続き有効)
**本文書の役割:** 4 観点モジュール横断レビュー(loader / code-mapping+i18n / generation+narrative IF / docs)の結果を踏まえ、グランドデザインへの適合度を評価し、残る構造課題を chain 単位で優先度整理する。master plan を置き換えるものではなく、**master plan に「基盤整備 chain」を挿入する位置を定める**文書。

---

## 1. グランドデザイン(要求の再確認)

ユーザー要求として確認されたゴール(2026-07-02 時点):

1. **高品質な EHR/EMR データセット生成**がゴール。データ品質・臨床的整合性・リアリティが最重要。
2. 出力は多フォーマット構想、**まず FHIR R4**(将来 SS-MIX2 / CSV / HL7 v2 等)。
3. **人口動態 → 外来/疾患シナリオ → 病院訪問イベント発火 → 検査/問診/処置 → コンディション変化**という event-driven な生成構造。
4. **メインパイプライン + モジュール**構成。モジュール責任分解を明確に。モジュール追加だけで新データ種を生成可能に。
5. CIF は **構造化 CIF + ナラティブ CIF の 2 層**。両者から FHIR を生成。
6. **ナラティブは差し替え可能**:template ベース → Bedrock / local LLM で再生成 → FHIR 再作成、が独立に回せること。
7. ナラティブは **情報タイプ別 prompt** を用意し、患者 profile / シナリオ / 構造化 CIF を入力とする**統一インターフェース**経由で生成。
8. **データドリブン**:静的なバイタル値・コード等を Python 内に定義しない。
9. **多国対応**:US default + JP、国固有情報は YAML/JSON 定義。他国追加可能な構造。

## 2. 現状評価 — 適合している部分

| 要求 | 現状 | 評価 |
|---|---|---|
| 2 層 CIF + file 分離 | AD-65 で `cif/structural/` + `cif/narratives/<version>/` 分離、`CIFReader(narrative_version=...)` merge | ✅ 設計どおり(session 28 で drift 復元済) |
| ナラティブ version 差し替え | `narrate --version-id X --set-current` → `export-fhir --narrative-version X` | ✅ CLI 3-stage(AD-37)で独立再生成可能 |
| モジュール拡張性 | AD-56 3 registry(bundle_builder / output_adapter / enricher)+ `extensions[<module>]` | ✅ 26 module で実証済 |
| データドリブン | disease/encounter YAML、reference_data YAML、codes/locale YAML | ✅ おおむね(例外は §3.4) |
| 多国対応 | `codes/`(国際標準)と `locale/<country>/`(文化依存)の分離、AD-30 code-only CIF | ✅ 構造は健全(例外は §3) |
| 検証基盤 | AD-60 audit 4 軸 + byte-diff + golden e2e + AD-66 patient-profile regression | ✅ 業界水準以上 |
| 決定性 | AD-16/59 sub-seed 階層、per-order RNG isolation | ⚠️ RNG は clean、wall-clock 残存(§3.3) |
| ナラティブ統一 IF | `NarrativePass` ABC + `NarrativeContext` + `DocumentTypeSpec` YAML | ⚠️ 骨格は正しいが二重抽象が残存(§3.1) |

**総評:** グランドデザインとアーキテクチャの骨格は一致している。乖離は「設計の誤り」ではなく「α-min 高速進行で残った未統合の継ぎ目」に集中しており、β-JP-1(LLM ナラティブ)着手前に継ぎ目を閉じるのが最も費用対効果が高い。

## 3. 構造課題と提案 chain(優先度順)

### 3.1 ★★★ N-chain: Narrative interface 統一(β-JP-1 の前提)

レビューで確認された現状(file:line は 2026-07-02 時点):

- **二重抽象**: 正規の swap 継ぎ目は `NarrativePass` ABC(`document/narrative/passes.py`、`_generate`/`_generator_name` hook、(doc_type, language) walk order = prompt-cache 最適化済)。一方で α-min-1 Task 7 由来の `LLMNarrativeGenerator` + `apply_replacement_strategy` + `NarrativeCache`(`llm_generator.py` / `replacement_strategy.py` / `cache.py`)が **どこからも呼ばれず孤立**。`DocumentTypeSpec.stage2_strategy` / `llm_enabled_sections` も定義のみで unreachable(aspirational scaffold = PR-90 型リスク)。
- **同名不整合 protocol**: `narrative/replacement_strategy.py:28 LLMProvider.generate(prompt)->str` vs `llm_service/providers/base.py:24 LLMProvider.complete(...)->ProviderResponse`。同じクラス名で非互換 signature。
- **generator 契約が未型化**: `TemplateNarrativeGenerator.generate(ctx, spec)->NarrativeOutput` の契約に ABC/Protocol がない。
- **template が Python hardcode**: `template_generator.py` 1446 行に文字列組立て。YAML なのは findings/instructions データのみ。一方 `llm_service/prompts/{en,ja}/*.yaml` に per-(doc_type, language) prompt 資産が既にあるが未消費。
- **enum 二重管理**: `DocumentType`(9 種)と `LLMTaskType` narrative 系が非同期(operative_note 等の片側欠落)。
- **`llm_service/__init__.py` が空**: public API surface 規約違反(module 規約「__init__ で export したものだけが公開面」)。

**提案(N-chain、3-4 PR 規模):**
1. **N-1 契約統一**: `NarrativeGenerator` Protocol を `clinosim/types/document.py` に定義(`generate(ctx, spec) -> NarrativeOutput`)。`TemplateNarrativePass` は generator を constructor 注入に変更(現在は hardcode)。孤立している `LLMNarrativeGenerator`/`replacement_strategy`/`NarrativeCache` は **β-JP-1 で使う設計(master plan §3 の D+E+B 戦略)に合わせて `NarrativePass` 配下に接続するか、接続しないなら削除**(コード遺産として残すのが最悪)。`llm_service/__init__.py` に public API export 追加。
2. **N-2 provider 統一**: narrative 側 `LLMProvider` を廃し、`llm_service` の `LLMProvider.complete()` に一本化(thin adapter)。AD-11(LLM 呼出は llm_service 経由のみ)を narrative 層でも構造的に保証。
3. **N-3 prompt 所有権統一**: prompt は `llm_service/prompts/`(per-language YAML、AD-40)を唯一の置き場とし、`PromptRegistry` を (doc_type, language) キーで narrative 層から消費。`_build_seed_prompt` の inline 組立てを registry 経由に。**ユーザー要求 7(情報タイプ別 prompt + 統一 IF)はこの PR で完成**。
4. **N-4(任意、段階的)template のデータ駆動化**: `template_generator.py` の section template を段階的に YAML 化(doc_type 追加が Python 編集なしで済む状態へ)。β-JP-1 と並行可。

### 3.2 ★★ AD-30 chain: display-in-CIF 除去

- `types/allergy.py:18,28`(`manifestation_display` / `allergen_display`、`allergy/engine.py:132,140` で英語 display を格納)— builder は `code_lookup` で再解決しており **dead + AD-30 違反**。
- `types/imaging.py:27`(`body_site_display`、`imaging/engine.py:277` で `display_en` 格納)。
- CIF schema 変更 = golden 再生成を伴うため独立 chain(1 PR + golden regen)。

### 3.3 ★★ Determinism chain: wall-clock 除去(既 TODO の拡張)

今回の byte-diff 実測で差分フィールドを完全列挙:`discharge_prescription.issue_date` + `physiological_states[].timestamp`(+ metadata の generation_timestamp)。加えてレビューで新規確認:
- `modules/diagnosis/engine.py:173` — `diff.timestamp = datetime.now()`(inpatient 生成経路で live)
- `modules/immunization/enricher.py:30` — `date.today()` fallback
- `types/clinical.py` / `types/encounter.py` / `types/procedure.py` の `default_factory=datetime.now` 群(発火箇所の shadow)
- **JP blood_type 重み合計 0.9999999999999999**(`locale/jp/demographics.yaml`)— これを 1.0 に修正しないと `normalize_probabilities` を blood_type に適用すると byte が動く(R6 で意図的 skip した唯一のサイト)
完了すると **CIF まで含む full byte-diff** が可能になり、refactor 検証コストが恒久的に下がる。

### 3.4 ★ Display-dict → codes YAML 移行 chain

`_fhir_reference_data.py`(`_CONDITION_SHORT_NAME` / `_ENCOUNTER_TYPE_SNOMED_JA`)、`_fhir_patient.py`(marital/lang)、`_fhir_microbiology.py`(S/I/R)、`_fhir_allergy_intolerance.py`(status displays)、`_fhir_care_team.py` 等の Python 内臨床 display 辞書を `codes/data/*.yaml`(en+ja)へ移行し `code_lookup` 経由に。**ユーザー要求 8(コード内静的定義禁止)の残債**。機械的だが件数が多いので 1-2 PR。

### 3.5 ★ Dual-access sweep chain

- 読み側の残存 `isinstance(x, dict)` 分岐(`_fhir_observations.py:431` / `csv_adapter.py:290` / `_fhir_conditions.py` ほか)→ `_o()` 統一。
- **書き側 helper 不在**: enricher の `if isinstance(rec, dict): rec["x"]=... else: rec.x=...` が 7+ module に散在。`set_attr_or_key()` を `_shared.py` に追加して統一(PR-90 型リスクの sibling gap)。

### 3.6 その他(単発、適宜同乗)

- `DiagnosisCandidate` / `DifferentialDiagnosis` を `clinosim/types/` へ移設(types 規約違反)。
- `inpatient.py:1826` unknown-condition 経路が `scenario_flags_from_protocol(None)` を呼ばずコメントで代替(J5 型リスク)→ helper 呼出しに正規化。
- locale loader の unsupported-country 挙動不統一(care_level=`{}` vs immunization/code_status/family_history=US fallback)→ 契約を「`{}` 返し」に統一(多国追加=要求 9 の前提)。
- Endpoint/CareTeam 等の hardcoded display("DICOM WADO-RS" 等)の code_lookup 化(3.4 に同乗)。
- root `spec.md`(2026-06-05)の stale 明示(header に「歴史文書、現行は DESIGN.md + modules/output/SPEC.md」注記)。
- DESIGN.md ADR 欠番(AD-1/2/12/14/15/27)に "reserved/withdrawn" 注記 + compact table の番号順整列。

## 4. ロードマップ再構成(master plan への挿入)

master plan 7 phase(α-min-1 ✅ / α-min-2 ✅ / β-JP-1 / β-2 / γ / δ / ε)は有効。基盤 chain の挿入位置と根拠(判断 4 軸:データ品質 / 臨床整合性 / メンテ性 / コンセプト適切性):

| 順 | 項目 | 根拠 |
|---|---|---|
| 0 | **PR #132 merge**(α-min-2c fixture library、adv-1 5-lens or 直接) | β-JP-1 regression 基盤。open のまま放置が最大リスク |
| 1 | **本 refactor branch merge**(common-logic unification + guide refine) | 以降の全 chain の前提となる canonical helper 群 |
| 2 | **α-min-3: outpatient/ED POST_ENCOUNTER 配線** | 実装済 spec が production 0 件のまま = データ品質の最大 gap(US p=10k で ~154k resource 増)。小 PR で最大リターン |
| 3 | **N-chain(3.1)N-1〜N-3** | β-JP-1 の直接前提。孤立 scaffold の解消は PR-90 型リスク低減 |
| 4 | **β-JP-1 LLMNarrativePass**(master plan どおり) | fixture library(#132)+ N-chain 完了で最短経路。JP 4 帳票 + LLM narrative |
| 5 | **Determinism chain(3.3)** | β-JP-1 の LLM 出力比較(semantic diff)整備と同時期に、structural 側の full byte-diff を確立すると検証系が完成する |
| 6 | **AD-30 chain(3.2)+ display-dict 移行(3.4)** | golden regen を伴うため、β-JP-1 の golden 拡張(llm-<model>.golden)と衝突しない切れ目で |
| 7 | **β-2 以降**(master plan §2 どおり)+ dual-access sweep(3.5)は適宜同乗 | |

SS-MIX2 は従来どおり event-density 完了後(TODO.md 記載のまま)。

## 5. 本セッション(2026-07-02)で実施済み

- **R1-R7 共通化リファクタ**(commit `1816db3591`、59 files):`is_jp`/`resolve_lang`、`system_key_for`、URI 定数 3 追加+7 literal 置換、重複 loader 4 組統合、`@lru_cache` 4 loader 追加、`normalize_probabilities` 4 サイト追加、path 定数正規化、`load_all_disease_protocols` の disease module 帰属化。
- **検証**: unit 865 / integration 257 / e2e golden 35 全 PASS。byte-diff(US p=500 + JP p=300、3-stage full pipeline):FHIR NDJSON + narratives 100% 一致、CIF 差分は wall-clock 2 フィールドのみ(§3.3 で列挙)。
- **ガイド refine**: CONTRIBUTING-modules.md へ新 helper 群 + ADR 読書リスト + cross-link、fhir-data-generation-logic.md 更新、design-guides/README.md(新規、読了パス)、staleness 修正(TODO header / AD-63 stage 記述 / module 数統一)。

## 6. 未実施・明示 TODO 化(scope discipline)

§3.2-3.6 の全 chain は TODO.md に formal entry 化(挙動変更 or schema 変更を伴うため本 refactor branch には含めない)。
