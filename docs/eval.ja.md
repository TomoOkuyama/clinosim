# `clinosim eval` — 公開評価フレームワーク

`clinosim eval` は生成コホートを 6 軸 — 普遍 3 軸 (**structural** /
**clinical** / **locale**) + 国 条件 3 軸
(**jp_clins_lab_compliance** / **jp_core_compliance** /
**us_core_compliance**) — でスコア化し、check ごとの outcome、
軸スコア (0–100)、overall score を含む JSON + Markdown レポートを
emit します。国 条件軸はコホートの locale に合致するもののみ有効化
(軸の集合は `clinosim/eval/engine.py::EvalEngine` の `axes` dict、各軸の
実装は `clinosim/eval/axes/`)。

**`clinosim audit run` とは異なります** (詳細は
[`docs/CONTRIBUTING-modules.md`](CONTRIBUTING-modules.ja.md)「PR 検証
ガイド」参照):

|  | `clinosim eval` | `clinosim audit run` |
| --- | --- | --- |
| 想定利用者 | 外部研究者 / ML エンジニア | PR を書くコントリビュータ |
| 入力 | 任意の FHIR NDJSON ディレクトリ | Module PR で生成したコホート |
| 出力 | 数値スコア + 違反リスト | 軸 × Module ごとに PASS / FAIL / WARN |
| Module 登録必須 | いいえ | はい (per-Module `audit.py`) |
| レポート形式 | JSON + Markdown | Markdown |

## Quick start

```bash
# 同梱プリセットの 1 つをビルド (datasets/README.md 参照)。
clinosim dataset build jp-100 --output ./jp-100

# スコア化。
clinosim eval -d ./jp-100
```

オプション:

```
clinosim eval
  -d/--cohort-dir DIR      生成コホートのルート (fhir_r4/ を含む)、または
                           Synthea の fhir/ 出力ディレクトリ (自動検出し、
                           スコア化前に正規化)
  --json PATH              JSON レポートを PATH に書き出し
  --md PATH                Markdown レポートを PATH に書き出し
  --country CODE           対象を国サブディレクトリ
                           (<cohort-dir>/<CODE>/fhir_r4/) に限定 (複数指定は
                           フラグを繰り返す)。デフォルトは検出した全サブ
                           ディレクトリ。locale の判定自体はサブディレクトリ
                           名から行い、フラットな <cohort-dir>/fhir_r4/
                           レイアウトでは先頭 Patient の address.country /
                           JP Core meta.profile から自動検出 (fallback: US)
  --only-axes LIST         実行する軸 id のカンマ区切り (例:
                           clinical,locale)。未知の id は即エラー
  --synthea-normalize DIR  Synthea 正規化レイアウトの書き出し先
                           (デフォルト: <cohort-dir>/../synthea-normalized/)
  --strict                 いずれかの軸で FAIL check があれば exit 1
```

## 軸

structural + locale は 5 check ずつ、clinical は 7 (MVP 5 + coherence
2、P1-9 で追加)。追加 check は GitHub の `good first issue` タグ経由
で入ります。国 条件軸は locale ごとに有効化 — `jp_clins_lab_compliance`
(3 check) と `jp_core_compliance` (7 check: Patient / Encounter /
MedicationRequest) は JP コホート、`us_core_compliance` (7 check:
Patient / Encounter / Condition) は US コホートで発火し、いずれも
master で 100 % 成立している invariant を gate にします。check 一覧は
[eval-rules.md](eval-rules.ja.md)、完全な軸リストは
[`clinosim.eval`](../clinosim/eval/README.ja.md) 参照。

### Structural (FHIR 準拠)

| Check | Severity | 主張内容 |
| --- | --- | --- |
| `resource_id_uniqueness` | critical | 同一 resourceType 内で `id` 重複なし |
| `reference_integrity` | critical | 全 `reference` フィールドが emit 済リソースに解決 |
| `required_fields_present` | major | Patient.identifier / Encounter.status / Condition.subject が非空 |
| `meta_profile_declared` | major (JP のみ) | 全 JP Core primary resourceType が `meta.profile` を宣言 |
| `resource_type_consistency` | minor | 全 NDJSON 行の `resourceType` がファイル名と一致 |

### Clinical (整合性)

| Check | Severity | 主張内容 |
| --- | --- | --- |
| `lab_values_physiological_range` | major | LOINC コード付き検査値が生理範囲内 (WBC / Hb / Cr / Glucose / K / Na / T-bili / PT-INR) |
| `age_condition_consistency` | major | 小児患者に adult-only 疾患なし |
| `medication_date_sanity` | major | MedicationRequest.authoredOn ≥ Patient.birthDate |
| `encounter_temporal_ordering` | major | Encounter.period.start ≤ .end |
| `condition_encounter_link` | minor | Condition.encounter が設定されている場合、emit 済 Encounter に解決 |
| `condition_lab_coherence` | major | 敗血症で lactate 上昇、DKA で HCO₃ 低下、MI で troponin 上昇 … (8 ペアリング — [eval-rules.md](eval-rules.ja.md#condition_lab_coherence-major) 参照) |
| `medication_lab_coherence_warfarin` | major | ワルファリン患者の PT-INR が治療域 2.0–3.5 内 |

### Locale (言語 + コードシステム)

コホート country により dispatch: `<root>/<country>/fhir_r4/` レイアウト
では国サブディレクトリ名、それ以外は先頭 Patient の `address.country`
または JP Core `meta.profile` 存在から自動検出 (fallback: US)。

**JP checks:**

| Check | Severity |
| --- | --- |
| `japanese_displays_on_condition` | major |
| `jlac10_or_loinc_on_lab` | major |
| `yj_code_on_medications` | major |
| `jp_core_profile_declared` | major |
| `jp_name_order` | minor |

**US checks:**

| Check | Severity |
| --- | --- |
| `ascii_only_displays` | major |
| `rxnorm_present_on_medications` | major |
| `loinc_present_on_lab_observations` | major |
| `no_japanese_leakage` | critical |
| `us_practitioner_name_order` | minor |

## スコアリング

軸スコア = 100 × Σ(pass-weight) / Σ(total-weight)。ここで:

- Severity 重み: **CRITICAL = 3、MAJOR = 2、MINOR = 1**
- Outcome 重み: **PASS = 1.0、WARN = 0.5、FAIL / N/A = 0.0**

Overall score = レポート中の全軸結果 (軸 × 国サブディレクトリごとに
1 件) のスコアの算術平均。コホートの locale に該当しない国 条件軸も
`checks` が空・score 0.0 の結果としてレポートに現れ、この平均に含まれ
ます。Overall status はいずれかの軸のいずれかの check が
FAIL なら `FAIL`、いずれか WARN なら `WARN`、それ以外は `PASS`。

## JSON 出力形状

```json
{
  "eval_version": "1",
  "cohort_dir": "./jp-100",
  "generated_at": "2026-07-12T04:55:08.910006+00:00",
  "resource_counts": {"_flat": {"Patient": 41, "Encounter": 109, ...}},
  "overall_score": 83.3,
  "overall_status": "FAIL",
  "axes": [
    {
      "axis": "structural",
      "country": "_flat",
      "score": 100.0,
      "status": "PASS",
      "checks": [
        {
          "name": "resource_id_uniqueness",
          "outcome": "PASS",
          "severity": "critical",
          "weight": 3,
          "message": "All resource ids are unique within their resourceType.",
          "detail": {}
        },
        ...
      ]
    },
    ...
  ]
}
```

## プログラマチック利用

```python
from clinosim.eval import EvalEngine

engine = EvalEngine(cohort_dir="./jp-100")
report = engine.run()

print(report.overall_score, report.overall_status)
for axis in report.axes:
    print(axis.axis, axis.score, axis.status)
    for check in axis.checks:
        if check.outcome.value == "FAIL":
            print("  FAIL:", check.name, check.message)
```

## Extending

check 追加手順:

1. `clinosim/eval/axes/` 配下の該当ファイルを開く。
2. `_check_<name>(cohort, country) -> EvalCheck` ヘルパーを追加。
3. 軸の `run()` 戻り値リストに append。
4. `tests/unit/test_eval_axes.py` に、FAIL outcome を発火する最小
   ミニコホートを組む単体テストを追加。
5. `docs/eval.md` と `CHANGELOG.md` を更新。

5 check の MVP は意図的 — フレームワークは個別 check よりも価値が
あります。小さくスコープの明確な追加は、一発 30-check リライトより
レビューが容易。
