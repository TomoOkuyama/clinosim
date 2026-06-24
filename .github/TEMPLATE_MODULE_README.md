# [モジュールタイトル] — [JP one-line description]

> このファイルは新規モジュール README のテンプレートです。
> `<placeholders>` を埋め、不要なセクションは削除してください。
> 既存の参考例: `clinosim/modules/observation/README.md`,
> `clinosim/modules/identity/README.md`, `clinosim/modules/sdoh/README.md`

## 概要 / 役割

[2-3 sentences: what does this module do, why does it exist]

## 設計原則 (該当時のみ)

| Principle | Source |
|---|---|
| 例: AD-16 deterministic (sub-seed) | DESIGN.md AD-16 |
| 例: BNP-pattern surgical (state-unchanged) | DESIGN.md AD-57 |
| 例: per-order sub-rng isolation | DESIGN.md AD-59 |
| 例: data-only module variant | docs/CONTRIBUTING-modules.md |

## ディレクトリ構造

```
clinosim/modules/<name>/
  __init__.py            # public API export
  engine.py              # core logic / loaders
  enricher.py            # (該当時) AD-56 post_records enricher
  reference_data/*.yaml  # data-driven definitions
  README.md              # this file
```

## API Reference

[Public functions exported via __init__.py. Show signature + 1-line description for each.]

```python
def public_function(arg: type) -> ReturnType:
    """One-line description.

    Optional longer explanation (when behavior is subtle).
    """
```

## データ構造 (該当時)

主要型 (`clinosim/types/<name>.py` 推奨; 既存負債で `engine.py` 内残置の場合もあり、CLAUDE.md "All types defined in clinosim/types/" を将来統一予定):

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `MyType` | `clinosim/types/<name>.py` (`@dataclass`) | `field_a`, `field_b` | このモジュールの公開データ型 |

## Dependencies

| Dependency | Why |
|---|---|
| `clinosim/types/<name>` | data types |
| `clinosim/codes/` | code system display lookups via `code_lookup()` |
| `clinosim/locale/<country>/` | locale-specific data (該当時のみ) |
| (他モジュール) | (理由 — DESIGN.md ADR 参照) |

> 各モジュールは README の Dependencies に明記したもののみに依存可 (CLAUDE.md「Module independence」)。

## Consumers

このモジュールに依存するもの (grep で発見、`from clinosim.modules.<name>` を import している箇所):

| Caller | How it uses this module | Impact when changing |
|---|---|---|
| `simulator/inpatient.py:NNN` | calls `public_function()` at line NNN | core (main simulation loop) |
| `modules/output/_fhir_<X>.py` | reads `<data type>` for FHIR builder | medium (FHIR builder for X resource) |
| `tests/unit/test_<name>.py` | 各種 unit tests | guard |

**Impact tier**:
- `core` — main simulation loop or all encounters
- `medium` — specific feature (FHIR builder, lab path, etc.)
- `guard` — test only (no runtime impact)

> 新しい module 追加 / 既存 module の signature 変更時、影響範囲を素早く知るため
> `grep -rln "from clinosim.modules.<name>\b\|import clinosim.modules.<name>\b" clinosim/ tests/`
> を実行して結果を本表に反映してください。

## 拡張ガイド (Extensibility) (該当時)

[How to add a new <thing> to this module — e.g., new analyte, new scenario flag, new SDOH attribute]

詳細は [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 参照。

## 関連

- [DESIGN.md](../../../DESIGN.md) ADxx (該当 ADR)
- [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 該当セクション
- [MODULES.md](../../../MODULES.md) — 全 module 俯瞰
- [SCENARIO_FLAGS.md](../../../SCENARIO_FLAGS.md) (scenario / medication flag を扱う場合)
- 関連モジュール: [リスト]
- 関連 spec / plan: `docs/superpowers/specs/...` (該当時)
