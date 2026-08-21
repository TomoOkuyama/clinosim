# コード display の権威ソース同期

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
    yj_tx_fragment.json                 # ← framework の最初の住民
    <system>_<source>.json              # snapshot は PR ごとにここへ
  loader.py                             # lookup() は不変
tests/unit/codes/
  test_display_matches_authoritative.py # silent-no-op 防御の 5 層目
  authoritative_override_allowlist.yaml # 臨床略記 override
scripts/
  refresh_authoritative_yj.py           # 抽出スクリプト (system ごと)
```

## Snapshot 形式

各 snapshot は `metadata` ブロックと `concept` リストを持つ JSON
ドキュメント。concept リストは clinosim が現在 emit するコードのみ
を含み、ソート順 (安定した diff のため):

```json
{
  "metadata": {
    "source_package": "jpfhir-terminology 2.2606.0",
    "source_url": "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code",
    "source_file": "CodeSystem-jp-medicationcodeyj-cs.json",
    "source_content_mode": "fragment",
    "fetched_from": "https://github.com/iryohjoho/fhir-jp-validator tx-server-build/",
    "extracted_at": "2026-07-19",
    "clinosim_codes_total": 165,
    "clinosim_codes_in_fragment": 9,
    "clinosim_codes_missing_from_fragment": ["…"]
  },
  "concept": [{"code": "1149037F1020", "display": "セレコックス錠１００ｍｇ"}]
}
```

`metadata.clinosim_codes_missing_from_fragment` 配列は抽出時に
tx-server の loaded fragment 外にあった clinosim コードを記録 —
検証不能 (テストは SKIP) だが、この記録により将来の refresh で
fetch を広げるかギャップを許容するかを判断可能。

## Cross-check セマンティクス

curated YAML の各 `(system, code)` ペアについて:

1. コードが snapshot エントリを持たない → **SKIP** (fragment 欠落、
   検証失敗ではない)。
2. curated display が snapshot の `display` または `designation[].value`
   synonym のいずれかと一致 → **PASS**。
3. curated display が allowlist エントリの `clinosim_display` に一致し、
   その allowlist エントリがドキュメント化された `rationale` +
   `registered_at` を持つ → **PASS (allowlisted)**。
4. それ以外 → **FAIL**、drift したコードと権威 display を列挙する
   diagnostic 付き。

テストは system ごとの count (`verified` / `allowlisted` /
`unverifiable`) を情報出力として emit、maintainer が snapshot
refresh を跨いでカバレッジの成長を追える。

## Override allowlist

各 allowlist エントリは以下を必須:

- `lang`: override が適用される display 言語フィールド (`en` / `ja`)。
- `clinosim_display`: `clinosim/codes/data/<system>.yaml` が emit
  する内容そのまま。
- `authoritative_display`: snapshot にある内容 (reviewer 用 context)。
- `rationale`: 臨床 / 学芸的理由の自由形式。ガイドライン、専門学会
  スタイルガイド、または具体的な臨床慣習を引用。
- `registered_at`: override がレビューされた日付 (ISO YYYY-MM-DD)。

Framework 起動時 allowlist は空。1 次充填が期待されるのは、SNOMED CT
の preferred term が JP 臨床略記と衝突する場合 (例: 心筋梗塞 vs.
Myocardial infarction (disorder))。

## Refresh workflow (maintainer)

1. 最新の `../fhir-jp-validator/` を `git pull` (または抽出スクリプト
   が指す上流 terminology パッケージを refresh)。
2. 上流が refresh された code system について
   `python scripts/refresh_authoritative_<system>.py` を実行。
3. `git diff clinosim/codes/authoritative/` — 変更エントリを検査。
4. コード単位トリアージ:
   - **新権威 display が curated と一致するようになった** → アクション
     なし; display は反対方向から収束。cross-check テストが以前 drift
     していたコードをカバーするようになる。
   - **Curated を更新する必要** → `clinosim/codes/data/<system>.yaml`
     を編集し display を更新; テストを再実行。
   - **意図的な divergence** (JP 臨床略記 vs 上流 preferred term) →
     臨床根拠付きの allowlist エントリを追加。
5. snapshot diff + curated データ / allowlist 編集を含む 1 つの PR を
   開く。

## Migration plan

| System        | Source                                          | Migration PR   |
|---------------|-------------------------------------------------|-----------------|
| YJ            | `jpfhir-terminology 2.2606.0` YJ-code CS         | Phase 1 (本 PR) |
| SNOMED CT     | tx-server SNOMED International fragment           | Phase 2         |
| ICD-10 (WHO)  | `codes/data/icd-10.yaml` vs WHO ICD-10 browser    | Phase 2         |
| ICD-10-CM     | `codes/data/icd-10-cm.yaml` vs NLM CM master       | Phase 3         |
| MEDIS keyNo   | `medis-codesystem-diseasekanricodes`              | Phase 3         |
| BCP-47        | HL7 terminology `urn:ietf:bcp:47`                  | Phase 2         |
| LOINC         | Regenstrief LOINC master                          | Phase 3         |
| RxNorm        | NLM RxNorm                                        | Phase 4         |
| MHLW / JLAC10 | JCCLS + MHLW masters                              | Phase 4         |

Phase 順は v4 で観測された drift を持つ code system を優先 (Phase 2
は SNOMED、ICD-10、MEDIS、BCP-47)。system 追加ごとに必要となるもの:
1 つの `authoritative/<system>_<source>.json`、
`_SYSTEMS_UNDER_CROSS_CHECK` へのエントリ、および (スキーマが異なる
場合) `_build_authoritative_display_map` への小さな拡張。

## このフレームワークが **しない** こと

- **Runtime term resolution**。clinosim は生成時に terminology
  server にクエリしない。検証はテスト時に走る。
- **新コードの追加**。必要言語で `display` を持たないコードの追加は
  別のカバレッジ関心事 (`tests/unit/test_diagnosis_code_coverage.py`
  および兄弟)。cross-check は存在する display を検証するのみ。
- **翻訳品質保証**。`en`-only 権威ソース (ICD-10 WHO は日本語を
  ship しない) の `ja` 翻訳は clinosim curated フィールド。翻訳品質
  は下流 reviewer が評価; cross-check は関与しない。

---

**Note**: JA 版と英語版に不整合を発見した場合は、[英語版](code-display-authoritative-sync.md) を canonical とし JA 側を修正すること。
