# `clinosim.audit.axes` — 軸ごとのチェック実行体

## 目的

`clinosim.audit.axes` は [`ModuleAuditSpec`](../README.ja.md) が宣言
する各 audit 軸の具体的な check 実行体を保持します。親パッケージ
([`clinosim.audit`](../README.ja.md)) が registry / cohort reader /
CLI dispatcher を所有し、本サブパッケージは実際にコホートを走査して
[`AxisResult`](../types.py) を返すロジックを所有します。

軸ロジックをここに分離することで (`audit/engine.py` に inline せず)、
各軸が独立進化でき、engine 層を transport-only に保てます。

## スコープ

- **In scope**: 軸実行関数。各ファイルは spec + cohort を受け取り
  `AxisResult` を返す callable (と必要な定数) を公開します。
- **Out of scope**: registry 管理、cohort I/O、CLI、severity ladder
  定義 — これらは [`clinosim.audit`](../README.ja.md) 側。

## 軸一覧

| ファイル | 軸 | 責務 |
| --- | --- | --- |
| `structural.py` | Structural | FHIR resource 整合性 — `referenceRange` + `interpretation` 100% カバレッジ、NDJSON 毎の id ユニーク性、全 coding で `display != code`。 |
| `clinical.py` | Clinical | `spec.clinical_acceptance` 駆動。HAI 型エントリ (`icd10_code` を持つ dict) ごとに observation を cohort (ICD-10 診断経由) と baseline に分割し、WBC / CRP の `cohort_p50 − baseline_p50` delta を spec 閾値と比較。メタデータキーで追加 gate を有効化: `basedon_coverage` (検査 Observation の `basedOn`)、`imaging_basedon_coverage`、`care_team_per_encounter`、HAI 耐性 / 空感受性 / narrow-rate バンド。 |
| `jp_language.py` | JP-language | コホートレベルのローカライズ整合性 — Issue #473 準拠。JP 側違反 = Latin word (`[A-Za-z]{2,}`) を含み日本語文字ゼロ、US 側漏出 = 日本語文字を含む。`meta`/`identifier`/`extension`/URL slot、JP-CLINS 定義の coding display はスキップ。 |
| `silent_no_op.py` | silent-no-op | PR-90 クラスのバグを止める gate — 独立に有効化できる 2 チェックを実行: canonical constants クロスチェック (`yaml_keys_to_validate` vs `canonical_constants`) と lift-firing proof (`lift_firing_proof`)。3 つ目 (fired counter) はモジュール docstring に記載があるが未実装。ドリフト検出時は FAIL。 |

## 新しい軸を追加する

1. `clinosim/audit/axes/` に新ファイルを追加し `AxisResult` を返す。
   既存パターンに従い `(spec, cohort)` を受け取り、親の `Cohort`
   reader で NDJSON を走査、適切な `Severity` の `AuditFinding` を
   構築する。
2. [`ModuleAuditSpec`](../registry.py) を拡張し、軸が必要とする spec
   フィールドを追加する。
3. `audit/engine.py` に軸を配線する: 名前を `_BUILTIN_AXES` に、
   runner を `_PER_MODULE_RUNNERS` (module ごとに spec 付きで呼び出し)
   または `_COHORT_RUNNERS` (cohort 1 回、`spec=None` で呼び出し) に
   追加。
4. 本表と親 [`README.ja.md`](../README.ja.md) を更新する。

## 相互参照

- フレームワーク概要: [`clinosim.audit`](../README.ja.md)
- 下流研究者向けの公開 per-module gate:
  [`clinosim.eval`](../../eval/README.ja.md) — コホートスコアリング
  の対応物。`audit` は内部 PR gating、`eval` は外部コホート採点。
- ランナー: `clinosim audit run` (repo-root docs 参照)。
