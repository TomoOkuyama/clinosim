# β-JP-1 chain 1b: LLM Golden + Semantic Check + Remote Execution Support — Design Spec

**Date:** 2026-07-03(session 32)
**Status:** Approved for implementation
**Branch:** `feature/beta-jp1-1b-llm-golden-semantic-diff`
**先行:** chain 1a(PR #136、context wiring)。実 LLM smoke は Ollama gpt-oss:20b で
end-to-end 成功済(session 32)。

## 0. 運用前提(user 決定、2026-07-03)

**ナラティブの実 LLM 生成は別サーバで実行する。** 本 chain はローカルで完結する
コード + テスト(mock provider)だけを ship し、実 provider 実行・LLM golden の実生成・
prompt 品質チューニングは LLM サーバ上で後日行う。従って:
- 検証は MockProvider(deterministic)で行い、実 LLM 依存の検証項目は設けない
- リモート実行のための CLI・手順書を成果物に含める

## 1. Scope

### T1: LLM parallel goldens — `regenerate-goldens` の provider 拡張

- `clinosim regenerate-goldens --profile <name>|--all` に `--provider
  {template,mock,bedrock,ollama}`(default template = 既存挙動不変)+ `--llm-config PATH`
  を追加。narrate 段を該当 provider で実行し、golden を
  `tests/fixtures/patient_profiles/<name>.llm-<tag>.golden.json` に書出す。
  `<tag>` は `--model-tag` 明示 or provider 名から導出(mock → `mock`)。
  template provider は従来どおり `<name>.golden.json`(命名不変)。
- **regression suite 拡張**: `pytest -m regression` に LLM-mock leg を追加 —
  `<name>.llm-mock.golden.json` が存在する profile は mock provider で再生成し byte-diff
  (MockProvider は deterministic かつ per-run reset なので byte 安定。walk order 決定的)。
  初期 commit で 6 profiles の llm-mock golden を生成して同梱(サイズ確認の上、
  過大なら代表 2-3 profiles に絞り spec 逸脱として report)。
- 実 LLM golden(`llm-<real model tag>`)の生成はリモートで実行される前提。
  byte-diff は実 LLM に不適用 → T2 の semantic check が gate。

### T2: Semantic check(実 LLM 出力の検証機構)

- 新 module `clinosim/modules/document/narrative/semantic_check.py`:
  `check_narratives(cif_dir, version_id, expectations) -> SemanticCheckReport`。
  検証軸(byte-diff の代替、fail-loud list を返す):
  1. **構造**: 期待 doc 数 / section keys が spec と一致、空 section なし、
     generator metadata(llm/template_fallback 比率)
  2. **facts 整合**: `facts_used` が非空で structural CIF 由来 tag のみ
  3. **禁止 pattern**(hallucination / meta 応答検知): 既定 regex 集
     (`As an AI` / `I cannot` / `[Mock` / 未解決 `{placeholder}` / TEMPLATE SEED 指示文の
     漏洩)+ locale 違反(US 出力の日本語文字。既知 ja-only fallback section は除外)
  4. **期待 phrase**: per-profile expectations YAML の required/forbidden phrases
     (doc_type × section 単位、`any_of` / `all_of`)
  5. **数値整合**: expectations に列挙した数値 fact(例 los_days、主要 lab 値)が
     text 中に出現するか(tolerance 付き optional)
- **expectations YAML**: `tests/fixtures/patient_profiles/<name>.llm-expectations.yaml`
  (schema: `document_type → section → {all_of: [], any_of: [], forbidden: []}` +
  `global: {forbidden_patterns: [...]}`)。6 profiles 分の初期版を臨床妥当な
  最小内容で同梱(過剰な brittle 化は避ける — disease 名 / 主要薬剤 / 転帰程度)。
- **CLI**: `clinosim check-narratives --cif-dir X --version <id> --profile <name>
  [--expectations PATH] [--report PATH]` — リモートサーバで narrate 後に回す想定。
  exit code 非 0 = fail(CI 組込み可能)。
- unit tests は合成 narrative + 小 expectations で各軸の PASS/FAIL を pin。
  mock provider での integration 1 本(profile pipeline → check green)。

### T3: `narrate --patient-filter <regex>`(リモートでの反復チューニング支援)

- `NarrativePass.run()` の patient walk に filter(patient JSON filename / patient_id に
  対する regex)を追加、CLI から `--patient-filter`。既定 None = 全患者(挙動不変)。
- 部分実行した version の manifest に `patient_filter` を記録(部分 golden 化の事故防止:
  `regenerate-goldens` は filter 指定を拒否)。

### T4: chain 1a deferred (d) — {sbp}/{hr}/{temp} 系 placeholder の実値導出

- encounter template の数値系 placeholder(sbp/dbp/hr/temp/spo2/rr 等、実 inventory は
  実装時に確認)を `ctx.vitals`(chain 1a で配線済)から day 対応の実測値で解決。
  値が無い場合は現行の section 全体 fallback を維持。
- `_KNOWN_PLACEHOLDERS` の拡張として実装(I-2 の section fallback 機構はそのまま)。
- goldens 再生成(inpatient 6 profiles は encounter template 不使用なら diff 無しの
  可能性 — 実測して report)。

### T5: Prompt 改良(構造のみ)+ リモート実行手順書

- `prompts/{en,ja}/narrative_seed.yaml`: 指示の明確化(構造: 事実の追加禁止 /
  seed 中の数値・薬剤名の保持 / 出力は section 本文のみ / ja は敬体・書式規約)。
  品質チューニング(モデル別調整)はリモートで行うため、ここでは
  contract 部分の強化に留める。
- **手順書** `docs/design-notes/2026-07-03-remote-llm-narrative-workflow.md`:
  別サーバでの実行手順(CIF 転送 or 生成 → `narrate --provider ollama|bedrock
  --llm-config ... [--patient-filter ...]` → `check-narratives` → 合格後
  `--set-current` / `export-fhir` → LLM golden 更新は `regenerate-goldens --provider`)
  + 必要環境(Ollama model pull / AWS IAM)+ cost 概算(session 30 メモ:
  6 profiles ~158 docs × sections)。

## 2. Out of scope(TODO)

- 実 provider での品質チューニング・実 LLM golden の生成(リモート、次 session 以降)
- 厚労省 4 帳票(chain 2)/ Bug A en-authoring chain / N-4 template YAML 化
- semantic check の embedding/LLM-judge 化(将来。まず規則ベースで運用)

## 3. Verification gates

1. unit / integration / e2e / regression 全 green(template goldens 不変が原則。
   T4 で goldens が変わる場合は AD-66 Rule 2 categorize)
2. 新規: llm-mock goldens byte-diff leg green、semantic check の PASS/FAIL 両方向 pin、
   check-narratives CLI exit code、patient-filter 決定性(filter 有無で対象患者の
   narrative byte 一致)
3. mock end-to-end: profile pipeline → `regenerate-goldens --provider mock` →
   `pytest -m regression`(llm leg 含む)→ `check-narratives` green
4. ruff / mypy 新規違反 0
