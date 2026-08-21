# clinosim 設計ガイドライン — Landing Pointer

本ファイルは元々 2819 行 / 154 KB あり、初見の読者には documentation
cliff だった。Issue #568 PR B で `docs/architecture/` 配下の 3 file
にテーマ別 split 済み。

## 3 分割

- **[Design principles](docs/architecture/design-principles.md)** (英語)
  — realism-above-all、モジュラーアーキテクチャ、LLM 統合、
  simulation mode、フォルダ構造、inter-module インターフェイス規約、
  命名規約。歴史的な基盤で largely stable。
- **[Architecture notes](docs/architecture/architecture-notes.md)** (英語)
  — per-module 設計注記 (code system、FHIR bulk data、snapshot
  semantics、hospital config layout、vital sign pattern、identifier、
  EHR enrichment、拡張性 foundation)、臨床文書 module (FHIR
  DocumentReference)、LLM service architecture (pluggable provider
  + YAML prompt)。
- **[ADR history](docs/architecture/adr-history.md)** (英語) —
  per-ADR section (`### AD-NN:`)。日本語 localisation (AD-42、
  AD-43)、FHIR 標準準拠 + 労災 (AD-44 〜 AD-48、AD-61 〜 AD-70)。

## 関連ドキュメント

- **[docs/README.md](docs/README.md)** — top-level docs landing page。
- **[docs/architecture/README.md](docs/architecture/README.md)** —
  architecture 専用ナビゲーション。
- **[MODULES.md](MODULES.md) / [MODULES.ja.md](MODULES.ja.md)** —
  モジュール単位 API 索引。

## 歴史的コンテキスト

pre-split の巨大 `DESIGN.md` は git history に保存されている
(Issue #568 PR B 前)。code と他 doc 内の個別 ADR 参照は split 後の
新 file を直接指すよう更新済み — in-tree の references で古い
top-level `DESIGN.md` を指すものは残っていない。

55+ per-ADR file への split (元 proposal) ではなく 3 file への
split を選んだ理由は Issue #568 PR B の description を参照。

英語版: [`DESIGN.md`](DESIGN.md)。
