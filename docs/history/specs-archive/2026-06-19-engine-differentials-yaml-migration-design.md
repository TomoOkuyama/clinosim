# engine.py 診断テーブルの YAML 駆動化 (follow-up #2)

- **Date**: 2026-06-19
- **Module**: `clinosim/modules/diagnosis/`
- **Type**: 出力ロジック隣接のリファクタ (YAML 駆動原則 AD への準拠)
- **Status**: 設計承認済

## 背景と目的

`clinosim/modules/diagnosis/engine.py` は 3 つの module-level 定数を Python に
ハードコードしている。これは clinosim の YAML 駆動原則 (コードはハードコードせず
reference_data / コードマップ駆動) に反する既知の負債。

- `DIFFERENTIALS` (L35〜): `disease_id -> list[{disease, icd, name, prior}]`
- `DIAGNOSIS_PROGRESSION` (L244〜): `disease_id -> list[(threshold, code, name)]`
- `LR_TABLE` (L376〜): `finding -> {disease_code -> {pos, neg}}`

加えて各エントリの表示 `name` がハードコードされており、AD-30
(「コードが真実、display は出力時に `clinosim.codes` で解決」) に反する。

本リファクタはこれらを `reference_data` YAML へ移し、表示名を `codes.lookup` 解決に
切り替える。

## 調査で確定した事実 (リスク評価の根拠)

1. **`name` / `display_name` は出力に一切到達しない**。
   - `get_current_diagnosis_code` の返り値 `dx_name` は `simulator/inpatient.py:292`
     でアンパックされるが破棄され、`ClinicalDiagnosis` には `dx_code` のみ格納される。
   - CIF `ClinicalDiagnosis` は AD-30 によりコードのみ保持 (型 docstring に明記)。
   - コードベースの `.display_name` 参照は全て `Order.display_name` 由来であり、
     `DiagnosisCandidate.display_name` とは無関係。`.evidence` も engine 外で未使用。
2. ⇒ **priors / LR 値 / progression の `(threshold, code)` が byte-identical なら、
   golden / e2e 出力は不変**。本リファクタは RNG を一切触らないため、決定論 (AD-16) は
   自明に保たれる。
3. disease YAML 側 (`modules/disease/reference_data/<id>.yaml` の `diagnostic` セクション)
   に既に同一スキーマ (`differential` / `likelihood_ratios` / `diagnosis_progression`)
   の override 経路があり、これは現状維持。
4. `tests/unit/test_diagnosis_code_coverage.py` の `_engine_differential_codes()` は
   engine.py を**正規表現でソース走査**して第 3 emittable 源の ICD コードを収集している。
   YAML 移行に伴い YAML パースへ書き換える (より堅牢になる)。

## 設計

### 1. データファイル

新規: `clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml`
(単一ファイル、3 トップレベルキー)。

```yaml
differentials:
  bacterial_pneumonia:
    - {disease: bacterial_pneumonia, icd: J18.9, prior: 0.45}   # name は廃止
    - {disease: viral_pneumonia, icd: J12.9, prior: 0.15}
    ...
diagnosis_progression:
  bacterial_pneumonia:
    - [0.0, J18.9]    # (threshold, code) の 2 要素。name は廃止
    - [0.7, J18.1]
    - [0.9, J13]
    ...
lr_table:
  chest_xray_consolidation:
    bacterial_pneumonia: {pos: 8.0, neg: 0.3}
    viral_pneumonia: {pos: 2.0, neg: 0.7}
    ...
```

- 現 Python 定数と**完全に同順・同値**。値の同一性は移行スクリプト
  (現定数から機械生成) で保証する。
- float は YAML でそのまま round-trip。リスト順序は dict / list の挿入順を保存し、
  正規化後ソートのタイブレーク (Python の stable sort) を現状と一致させる。

### 2. ローダ (engine.py 内)

`_load_reference_data()` を engine.py に追加。import 時に 1 度だけ YAML を読み込み、
module-level の以下を populate する:

- `DIFFERENTIALS: dict[str, list[dict]]` — `{disease, icd, prior}` (name なし)
- `DIAGNOSIS_PROGRESSION: dict[str, list[tuple[float, str]]]` — **2 要素タプル**
- `LR_TABLE: dict[str, dict[str, dict[str, float]]]`
- `DEFAULT_PNEUMONIA_DIFFERENTIAL = DIFFERENTIALS["bacterial_pneumonia"]` (後方互換維持)

公開関数 (`initialize_differential` / `update_differential` /
`get_current_diagnosis_code`) のシグネチャは不変。

**AD-18 (YAML config は Pydantic) の扱い**: これらは内部リファレンス表であり、
protocol override 経路 (`protocol_diagnostic`) も plain dict で消費している。整合性の
ため **plain dict ロード + ローダ内の最小限の構造サニティチェック**とする
(protocol 経路と一貫、ユーザー承認済)。

### 3. `name` の lookup 解決 (AD-30 準拠)

- `DiagnosisCandidate.display_name` は構築時に
  `codes.lookup("icd-10-cm", icd, "en")` で解決する。built-in / protocol 両経路とも
  `name` を読まず一律 lookup (protocol differential の `name` フィールドは無視される)。
- `get_current_diagnosis_code` は `(code, lookup("icd-10-cm", code, "en"))` を返す。
  progression タプルは `(threshold, code)` の 2 要素を反復し、name は lookup で解決。
- **新規モジュール依存**: `diagnosis -> codes` (アーキ規則で許可)。README の
  Dependencies に追記。
- display は出力で破棄されるため**出力は不変**。内部 debug / `evidence` 文字列のみ
  権威 en テキストへ変わる (より正確になる、許容)。
- 内部表示は英語固定 (engine は country コンテキストを持たない)。`lookup` は
  exact → base → child → code のフォールバックを持つため、map 経由でしか解決しない
  コードでも妥当な文字列を返す (best-effort、出力非影響)。

### 4. カバレッジテスト更新

`tests/unit/test_diagnosis_code_coverage.py` の `_engine_differential_codes()` を、
engine.py の正規表現ソース走査から **`builtin_differentials.yaml` の YAML パース**へ
書き換える:

- `differentials[*][*].icd`
- `diagnosis_progression[*][*][1]` (タプルの 2 番目 = code)
- (`lr_table` のキーは disease_code であり ICD コードではないので対象外)

第 3 emittable 源の不変条件 (US→ICD-10-CM、JP→WHO で exact 解決) は維持される。

### 5. ドキュメント

- `clinosim/modules/diagnosis/README.md`: `DIFFERENTIALS` / `DIAGNOSIS_PROGRESSION` /
  `LR_TABLE` の各セクションを YAML 駆動 + lookup 解決に更新。「既知の負債」注記を
  「解消済」に更新。Dependencies に `codes` を追加。
- ルート `CLAUDE.md`「Diagnosis code coverage」: 第 3 源を "engine.py にハードコード" →
  "`diagnosis/reference_data/builtin_differentials.yaml`" に更新。

### 6. 検証計画

- **値同一性**: 移行スクリプトで旧 Python 値 (`DIFFERENTIALS` から name 除去 /
  `DIAGNOSIS_PROGRESSION` から name 除去 / `LR_TABLE`) == 新 YAML ロード値 を assert。
- **unit**: `test_diagnosis.py` + `test_diagnosis_code_coverage.py` +
  `test_codes_integrity.py` (全緑)。
- **e2e フル**: golden 不変を無回帰確認 (CPU 競合で稀にフレーキー → 再実行で確認)。
  出力監査の生成物は `/tmp` に作り監査後削除 (`output/` は触らない)。

## スコープ外

- disease YAML (`modules/disease/reference_data/*.yaml`) の `diagnostic` セクション
  (16 ファイルの override) は変更しない。`name` フィールドが vestigial になるが
  engine が無視するだけで害はなく、編集は別件。
- LR 値・prior 値・progression コードの臨床的見直しはしない (値は現状を完全保存)。

## 受け入れ基準

1. engine.py に 3 定数のハードコードが無く、`builtin_differentials.yaml` から
   ロードされる。
2. `name` がデータから消え、display は `codes.lookup` で解決される。
3. 移行スクリプトの値同一性 assert が通る。
4. unit / integration / e2e が全緑、golden 出力が不変。
5. README / CLAUDE.md が更新されている。
