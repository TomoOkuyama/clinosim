# コード display の権威ソース同期 (JA 概要)

> **本ファイルは日本語話者向けの概要 + セクションガイド** です。
> 元のドキュメント (英語、161 行) の canonical は
> [`code-display-authoritative-sync.md`](code-display-authoritative-sync.md)。

**Status**: Framework は session 58 Phase 1 (YJ code テンプレート)
で導入。残る code system の移行は follow-up PR で追跡。

## なぜ

`clinosim/codes/data/*.yaml` はシミュレータが emit する各コードに
対して curated な `(code, en, ja, …)` マッピングを同梱。このフレーム
ワーク以前は、curated `display` 文字列と権威ソース (SNOMED CT
International、WHO ICD-10、MHLW YJ / MEDIS terminology、HL7 / IETF
言語タグ) 間の drift は、fhir-jp-validator が特定リソースをフラグ
したときにのみ発見される reactive な whack-a-mole workflow だった。
v4 fullset run (2026-07-18) が 6 code system にわたって ~13,000 の
display 関連エラーを表面化し、体系的検証フレームワークの動機となった。

## 原則

1. **Curated データが clinosim emit の権威**。`clinosim/codes/data/`
   の YAML は同梱される正確な display 文字列の source of truth。
   小さな臨床 override — 例: ICD-10 `F32` で WHO preferred
   `Depressive episode` の代わりに `MDD` を emit — はドキュメント化
   された allowlist 経由で可能。
2. **権威ソースは machine-verifiable**。全 ship-time display は
   権威 preferred term / 登録 synonym と一致するか、または臨床根拠
   付きで override allowlist に出現しなければならない。
3. **Fragment ship は norm を保つ**。clinosim は emit するコードのみ
   同梱 (system あたり典型的に << 200)。権威 snapshot もこの scope
   を mirror し ship サイズを小さく保つ。
4. **Silent drift は CI fail**。cross-check テストが hard defense
   layer。
5. **Refresh は maintainer workflow、runtime 関心事ではない**。
   シミュレータは生成時に terminology server に到達しない。

## 構造

```
clinosim/codes/
  data/*.yaml                           # curated source of truth
  authoritative/
    README.md                           # index + fetch provenance
    <system>_tx.json                    # 権威 snapshot (fragment)
```

各 code system は
`clinosim/codes/authoritative/<system>_tx.json` に権威 snapshot
fragment を持ち、CI cross-check が curated display と snapshot を
diff する。

## ワークフロー

- **通常開発**: curated YAML を編集、CI が snapshot 一致検証 →
  mismatch は fail (silent drift 防御)。
- **Refresh (maintainer)**: 権威ソースから最新 snapshot を fetch し
  `authoritative/` に反映、curated との diff が clinical override か
  drift かを判定。
- **新規 override**: `override_allowlist:` エントリに臨床根拠 (short
  rationale) を追加。

## 現状進捗

- **YJ code** (session 58 Phase 1): テンプレート導入済み。
- **他の code system** (SNOMED CT / WHO ICD-10 / MHLW etc.):
  follow-up PR で順次移行中。

## 詳細な英語版

具体的な snapshot ファイル形式、CI cross-check テストの実装、
override allowlist スキーマ、fetch script の使い方は
[`code-display-authoritative-sync.md`](code-display-authoritative-sync.md)
参照。**JA 版と英語版に不整合を発見した場合は、英語版が canonical**。
