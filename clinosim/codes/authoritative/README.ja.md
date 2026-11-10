# 権威コードシステム snapshot

権威コードシステム display の機械可読 snapshot。
`clinosim/codes/data/*.yaml` を元の terminology ソースに対して検証
するために使用。これらは **検証リファレンス** であり、source of
truth ではない — clinosim が emit する内容の source of truth は
`clinosim/codes/data/*.yaml` に留まり、これは小さな意図的な臨床
override を許容する (下の allowlist に登録)。

同伴ドキュメント: [`docs/design-guides/code-display-authoritative-sync.ja.md`](../../../docs/design-guides/code-display-authoritative-sync.ja.md)。

## ファイル

| File | Source | Fetched | Notes |
| --- | --- | --- | --- |
| `yj_tx_fragment.json` | `jpfhir-terminology 2.2606.0` / `CodeSystem-jp-medicationcodeyj-cs.json` (`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code`) | 2026-07-19 | Fragment (tx-server 上 2000 concept)、clinosim が現在 emit する 9 コードにフィルタ。 |
| `loinc_2_82_tx.json` | LOINC 2.82 公式マスター (`Loinc_2.82/LoincTable/Loinc.csv`) を `tx-server-build/loinc-src/` 経由で | 2026-07-19 | clinosim が emit する LOINC コード; `display` (LONG_COMMON_NAME) + `short_display` (SHORTNAME) + `status` を含む。フル display cross-check は Issue #270 (Phase 3-b) で有効化 — 75 の正当略記 + 17 の追跡セマンティック mismatch override を allowlist に登録。 |
| `icd10_who_tx.json` | `fhir.tx.support.r4 0.37.0` / `CodeSystem-icd-10.json` (`http://hl7.org/fhir/sid/icd-10`、content `complete`) | 2026-07-19 | clinosim が emit する WHO ICD-10 コード (`metadata.clinosim_codes_missing_from_source` に upstream 不在の参照コード数を記録)。 |
| `icd10_mhlw_2013_ja.json` | 厚労省 基本分類表 (ICD-10 2013年版準拠)、`https://www.mhlw.go.jp/toukei/sippei/xls/kihon2013.xlsx` (シート 基本分類表データ) | 2026-11-01 | `icd-10.yaml` の ICD-10 コードの公式日本語名。`ja` はこれと完全一致する (Issue #2360)。 |
| `shinryo_koui_ssk_20261013_ja.json` | 社会保険診療報酬支払基金 基本マスター 医科診療行為マスター (`s_ALL20261013.csv`)、`https://www.ssk.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html` | 2026-11-01 | `k-codes.yaml` 登録コードのマスター名称 (点数表区分番号または区分番号-枝番で引く)。`ja` はそのいずれか、または名称が始まる区分名と一致する (Issue #2340)。 |
| `rxnorm_rxnav_snapshot.json` | RxNav (NLM) `/REST/rxcui/{code}/historystatus` | 2026-10-28 | clinosim 同梱の全 RxCUI (`rxnorm.yaml` / `drugs.yaml` / US 薬剤マッピング) の status / name / term type。`tests/unit/codes/test_rxnorm_codes_name_their_drug.py` がオフラインで読む。 |
| `yj_mhlw_snapshot.json` | 厚労省 薬価基準収載品目リスト及び後発医薬品に関する情報 (令和8年6月12日適用)、`https://www.mhlw.go.jp/topics/2026/04/xls/tp20260612-01_05.xlsx` | 2026-10-31 | 薬剤カタログ (`drugs.yaml` の `codes.yj`) の YJ コードに対する厚労省の成分名・品名。JP 薬剤コードテスト (例: `tests/unit/codes/test_jp_yj_class_codes_name_their_drug.py`) がオフラインで読む (Issue #2347)。統一名収載の品目は MEDIS の製品コードをキーにし、リスト上のコードを `mhlw_code` に記録 (Issue #3013)。 |
| `JP_MedicationCodeYJ_CS_full.json` | YJ-code CodeSystem 全体 (`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code`、version `2026.8.31`、content `complete`) | — | 23,923 concept。YJ full-CS テスト (例: `tests/unit/output/test_fhir_yj_full_cs_gate_1220.py`) が使用。 |
| `snomed_allergy_tx.json` | tx.fhir.org R4 `CodeSystem/$lookup`、SNOMED CT International Edition 2025-02-01 | 2026-11-10 | `allergens.yaml` のアレルゲン物質・アレルギー歴なし・反応 manifestation コード (display、FSN、`inactive`)。`tests/unit/modules/allergy/test_allergen_codes_3128.py` がオフラインで参照 (Issue #3128)。 |
| `jfagy_jpfhir_terminology.json` | `jpfhir-terminology 2.2606.0` (`JP_AllergyIntolerance_VS` の JFAGY アレルゲン CodeSystem。医薬品 CodeSystem は fragment) | 2026-11-10 | JP AllergyIntolerance が emit する JFAGY コード (`allergens.yaml` `country_codes.JP`) と、各 `ja` が一致すべき CodeSystem display (Issue #3128)。 |

snapshot の件数は clinosim の emit 範囲に合わせて増えるため上表には
記載しません。件数は `len(json.load(open(path))["concept"])` で数えて
ください。

後続 snapshot (SNOMED / MEDIS / BCP-47 etc.) は
design guide で追跡され、各 Chain がフレームワークに移行するたびに
後続 PR で landing する。

## Content mode: `fragment`

各 snapshot はソース CodeSystem の `content` セマンティクスを継承。
`content == "fragment"` の場合、snapshot に無いコードでもソース
terminology 上では **valid でありうる** — tx-server の partial リス
ティングが単にそれを持たないだけ。cross-check テストは欠落コードを
*検証不能* (SKIP) として扱い、*invalid* (FAIL) とはしない。
`metadata.clinosim_codes_missing_from_fragment` フィールドが fragment
の外にある clinosim コードを正確に記録し、将来の snapshot refresh で
fetch を広げるかを判断できるようにする。

## Cross-check セマンティクス

権威 snapshot にエントリを持つ全 `(system, code)` ペアについて、
cross-check テストは clinosim-curated display が以下のいずれかに一致
することを assert:

- 権威 `display` (preferred term)、または
- 権威 `designation[].value` エントリのいずれか (synonym)、または
- ドキュメント化された臨床根拠を持つ override allowlist のエントリ。

Drift (curated display ≠ 権威 かつ allowlist に無し) は CI fail。
これは silent-no-op 防御の 5 層目。

## Refresh workflow

1. 最新の `../fhir-jp-validator/tx-server-build/` (または上流
   terminology パッケージ) を pull。
2. 抽出スクリプトを再実行 (per-code-system スクリプトを `scripts/`
   に配置、各 system の移行に伴い TBD)。
3. snapshot ファイルの diff を検査。
4. 変更エントリごと:
   - Now 一致 → curated データが既に正しく、clinosim 変更不要。
   - Now 一致、curated が古い → `clinosim/codes/data/*.yaml` を更新。
   - 意図的な divergence (臨床略記 override) → 臨床根拠付きで
     allowlist に追加。
5. PR: snapshot diff + allowlist / YAML 編集 + cross-check テスト
   refresh。

## ここに **属さない** もの

- 完全な CodeSystem 定義 (structure、filter、hierarchy) — これらは
  clinosim ではなく tx-server に存在。
- 権威ソースが持たない locale 翻訳 — これらは
  `clinosim/codes/data/*.yaml` の `ja` / 他言語キー下に存在し、
  clinosim-curated と見なされる (上流に対する検証不可)。
- clinosim が決して emit しないコード — fragment は shipped snapshot
  を小さく保つため clinosim の emit surface に意図的にスコープ限定。
