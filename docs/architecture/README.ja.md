# `docs/architecture/`

clinosim のアーキテクチャリファレンス。モジュール境界や cross-cutting
不変条件に影響する事項をここに置く; per-module deep dive は各
モジュールの `README.md` 参照。

## 内容

**過去のルート `DESIGN.md` から分割** (Issue #568 PR B、2026-08-09):

- [`design-principles.md`](design-principles.md) — realism-above-all、
  モジュラアーキテクチャ、LLM integration、シミュレーションモード、
  フォルダ構造、モジュール間 interface 規約、命名規則。歴史的基盤;
  ほぼ安定。
- [`architecture-notes.md`](architecture-notes.md) — モジュール別
  アーキテクチャノート: code system、FHIR bulk data (AD-31)、snapshot
  semantics (AD-32)、hospital config レイアウト (AD-34)、vital sign
  パターン、NEWS2、resident identifier (AD-54)、EHR enrichment 分割
  (AD-55)、extensibility (AD-56)。FHIR DocumentReference 経由の臨床
  文書。LLM service アーキテクチャ。
- [`adr-history.md`](adr-history.md) — clean `### AD-NN:` セクション:
  日本語 localization (AD-42、AD-43)、FHIR standards 準拠 + 労災
  (AD-44 〜 AD-48、AD-61 〜 AD-70)。

**ルート `README.md` から抽出** (Issue #568 PR A):

- [`module-architecture.md`](module-architecture.md) — 高レベル
  モジュール階層化、依存方向、simulator / output サブシステムの
  相互参照。
- [`data-flow.md`](data-flow.md) — 集団、シミュレーション、FHIR
  export のエンドツーエンドデータフロー。
- [`module-dependency-graph.md`](module-dependency-graph.md) — トップ
  レベルパッケージ import グラフ。

## 関連

- Design guides: [`../design-guides/`](../design-guides/README.md)。
- ルートポインタ: [`../../DESIGN.md`](../../DESIGN.md) は上記 3
  ファイルを指すランディングページに変更済。
- Per-module アーキテクチャ: `clinosim/modules/<X>/README.md`。
