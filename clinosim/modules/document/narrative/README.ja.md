# `clinosim.modules.document.narrative` — ナラティブテキスト生成

## 目的

[`clinosim.modules.document`](../README.ja.md) のナラティブ生成
サブパッケージ。`NarrativeContext` を各 document type の
`NarrativeOutput` に変換します。決定的テンプレート (デフォルト) または
LLM プロバイダー (CLI フラグで opt-in) の 2 経路。

AD-65 Stage 2 アーキテクチャ準拠: `NarrativePass` が構造化 CIF を
`(doc_type, language)` グループ順に walk し、実際のコンテンツ生成は
コンストラクタ注入された `NarrativeGenerator` (Protocol は
[`clinosim/types/document.py`](../../../types/README.ja.md) 定義) に
委譲。

## スコープ

- **In scope**: テンプレートベース決定的ナラティブ生成、LLM 支援
  ナラティブ生成 (section 単位 opt-in)、section-level 置換戦略、
  layer-1 メモリ内ナラティブキャッシュ、生成結果のセマンティック
  post-check、CIF からのナラティブ入力用ファクト抽出。
- **Out of scope**: document type レジストリ (親パッケージ
  [`clinosim/modules/document/`](../README.ja.md))、FHIR emission
  ([`clinosim/modules/output/` (English)](../../output/README.md))、
  LLM サービス本体 ([`clinosim/modules/llm_service/` (English)](../../llm_service/README.md)、
  日本語版は Issue #646 で作成予定)。

## 公開 API

```python
from clinosim.modules.document.narrative import (
    TemplateNarrativeGenerator,   # Stage 1 決定的ジェネレータ
    LLMNarrativeGenerator,        # template ベース + section 単位 LLM 置換
    NarrativeCache,               # layer-1 メモリ内キャッシュ
    apply_replacement_strategy,   # section 置換 dispatcher
)
```

2 種の `NarrativePass` (`TemplateNarrativePass` /
`LLMNarrativePass`) が enricher レジストリに配線され、上記
ジェネレータを消費します。

## ジェネレータ

- **`TemplateNarrativeGenerator`** — `NarrativeContext` から抽出した
  値でセクションテンプレートを埋める決定的レンダラー。デフォルト
  ジェネレータ。`TemplateNarrativePass` および LLM 経路のベース層
  として使用。
- **`LLMNarrativeGenerator`** — `TemplateNarrativeGenerator` を
  ラップし、`DocumentTypeSpec.llm_enabled_sections` にリストされた
  section を `apply_replacement_strategy` →
  `LLMService.complete_prompt` (AD-11 opt-in) で置換。プロバイダー
  失敗時は document 単位でテンプレート出力にフォールバック (section
  単位ではない) — silent partial generation を作らない。

Opt-in は CLI での明示選択
`narrate --provider bedrock|ollama|mock` (`LLMNarrativePass`)。
環境変数 gate なし。

## キャッシュ

- **Layer 1** — `NarrativeCache` (メモリ内、本サブパッケージ)。key:
  clinical-context hash + template-seed hash。基礎コンテキストが
  等価なら患者横断で section 再利用を可能にする。
- **Layer 2** — `LLMService` 内の `PromptCache` (永続、ディスク)。
  本サブパッケージは所有せず、`LLMService` 経由でのみ参照。

## 依存

- `clinosim.types.document` — `NarrativeGenerator` Protocol、
  `NarrativeContext`、`NarrativeOutput`、`DocumentTypeSpec`。
- `clinosim.modules.document` (上流) — factory / registry。
- `clinosim.modules.llm_service` — `LLMService` (opt-in、
  `LLMNarrativeGenerator` のみ使用)。

## 定数と設定

- Section テンプレートは本サブパッケージ内にデータとして配置
  (下記ディレクトリ構成参照)。
- プロバイダー選択は CLI のみ。実行時環境変数なし。
- `apply_replacement_strategy` は section 単位で LLM 呼び出しか
  テンプレートフォールバックかを判定。ロジックは
  `replacement_strategy.py`。

## ディレクトリ構成

```
clinosim/modules/document/narrative/
  __init__.py               公開 API
  passes.py                 TemplateNarrativePass / LLMNarrativePass
  template_generator.py     TemplateNarrativeGenerator (Stage 1 レンダラー)
  llm_generator.py          LLMNarrativeGenerator (Stage 2、LLM 経路)
  cache.py                  NarrativeCache (layer-1、メモリ内)
  registry.py               loader + 後方互換再エクスポート
  context.py                NarrativeContext factory
  scenario_spine.py         section 順を駆動する疾患シナリオ spine
  fact_extractor.py         CIF レコードからナラティブファクト抽出
  section_extractor.py      section 単位のファクト抽出
  replacement_strategy.py   template vs LLM の per-section 判定
  semantic_check.py         生成後のセマンティック sanity check
```

## 新規 document type / template の追加

1. `DocumentTypeSpec` を [`clinosim/modules/document/`](../README.ja.md)
   engine に登録。
2. 各 section 用テンプレート文字列を `template_generator.py` (あるいは
   そこから読み込む section-scoped file) に追加。
3. LLM 置換を希望するなら該当 section ID を
   `DocumentTypeSpec.llm_enabled_sections` に列挙。
4. 新規コンテキストデータが必要なら `fact_extractor.py` にファクト
   抽出器を追加。
5. `tests/unit/modules/document/narrative/` に unit test 追加。

## テスト

```bash
pytest tests/unit/modules/document/narrative/ -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
