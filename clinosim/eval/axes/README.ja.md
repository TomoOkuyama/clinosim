# `clinosim.eval.axes` — 軸ごとの eval check 実行体

## 目的

`clinosim.eval.axes` は [`clinosim.eval`](../README.ja.md) が評価する
4 軸それぞれの具体的な check 実行体を保持します。親パッケージが
`EvalCheck` dataclass / `Cohort` reader / スコアリング engine /
`clinosim eval` CLI を所有し、本サブパッケージは engine が集約する
`list[EvalCheck]` を生成する軸単位ロジックを所有します。

軸ロジックをここに分離することで engine 層を transport-only に保ち、
新チェック追加時に各軸を独立進化させられます。

## スコープ

- **In scope**: 軸ランナー関数。各ファイルは
  `run(cohort, country) -> list[EvalCheck]` を公開する — engine が
  スコアリング時に呼び出す契約。
- **Out of scope**: `EvalCheck` dataclass、スコア集約、CLI、
  Markdown/JSON 出力フォーマッタ — これらは
  [`clinosim.eval`](../README.ja.md) 側。

## 軸一覧

| ファイル | 軸 | チェック数 | 備考 |
| --- | --- | :-: | --- |
| `structural.py` | Structural | 5 (MVP) | FHIR 適合性 — id ユニーク性、参照整合性、必須フィールド、`meta.profile` 宣言、`resourceType` 一貫性。 |
| `clinical.py` | Clinical | 7 (5 MVP + 2 P1-9) | 一貫性チェック — 生理学-lab 整合性、medication-lab コヒーレンス (warfarin)、矛盾検出。 |
| `locale.py` | Locale | 5 (MVP) | 言語 + code system 適合性 — JP lab は JLAC10 / LOINC、medication systems、name/address locale。 |
| `jp_clins_lab_compliance.py` | JP-CLINS | 3 ratio | JP-CLINS `JP_Observation_LabResult_eCS` の自己測定 — CS 使用率 / display 一致率 / dual-slot 充足率。eCS が Open slicing (未知 coding は silently 受容) を使うため、validator 非依存で意図的に自前計測している。 |

## 新しい軸を追加する

1. `clinosim/eval/axes/` に新ファイルを追加し
   `run(cohort, country) -> list[EvalCheck]` を公開する。既存パターン
   に従い、[`clinosim.audit.types.Cohort`](../../audit/types.py) 経由
   でコホートの NDJSON を走査し、`(id, axis, description, outcome,
   severity, evidence)` で 1 チェック 1 `EvalCheck` を構築。
2. `eval/engine.py::score_cohort` に配線し、集約時にランナーが呼ばれる
   ようにする。
3. 親 [`README.ja.md`](../README.ja.md) の軸一覧と本表を更新する。

## なぜ `jp_clins_lab_compliance` を自前計測するのか

外部 FHIR validator は JP-CLINS 品質指標として機能しません。
`JP_Observation_LabResult_eCS` は `Observation.code.coding` に対して
`discriminator = system + display` の **Open slicing** を使うため、
fixed slice の display に一致しない coding は「未知の追加 coding」
として silently 受容されてしまう (surface するのは `information`
OperationOutcome issue のみ)。coding drift のクラス全体が pass/fail
gating では不可視です。本軸は NDJSON を直接走査し、per-resource な
3 ratio (denominator は必ず Observations であって codings ではない
— 多数 coding を持つ resource が不利になるため) を計算します。
根拠の全体はモジュール docstring 参照。

## 相互参照

- フレームワーク概要: [`clinosim.eval`](../README.ja.md)
- 内部 per-module PR gate:
  [`clinosim.audit`](../../audit/README.ja.md) とその
  [axes/](../../audit/axes/README.ja.md)
- ランナー: `clinosim eval` (repo-root docs 参照)。
