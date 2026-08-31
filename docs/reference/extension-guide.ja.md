<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# 拡張ガイド

### 新規疾患追加

1. `clinosim/modules/disease/reference_data/<disease_id>.yaml` を
   作成 (既存疾患をテンプレートに)。
2. `clinosim/locale/<country>/demographics.yaml` の incidence リスト
   に追加。
3. **`icd_codes` 全値 (primary + variants) をコードデータに登録** —
   US billable leaves は `clinosim/codes/data/icd-10-cm.yaml`、JP WHO
   コードは `clinosim/codes/data/icd-10.yaml`、CM 粒度を WHO 親コード
   に折り畳む場合等は `clinosim/codes/data/code_mapping_diagnosis/<country>.yaml`
   に mapping エントリを追加。未登録だと FHIR Condition display が
   prefix 近似 fallback に落ちる。`AGENTS.md` 「Diagnosis code
   coverage」参照。
4. テスト: `clinosim test-disease <disease_id>` および
   `pytest tests/unit/test_diagnosis_code_coverage.py`。

詳細: `clinosim/modules/disease/README.ja.md`

### 新規 encounter 型追加 (ED/外来)

1. `clinosim/modules/encounter/reference_data/<condition_id>.yaml`
   を作成。
2. `icd10_code` と `icd10_display` を含める。
3. `icd10_code` を「新規疾患追加」ステップ 3 に従って登録。
4. テスト: `clinosim test-encounter <condition_id>` および
   `pytest tests/unit/test_diagnosis_code_coverage.py`。

### 新規国追加

1. `clinosim/locale/<country_code>/` フォルダを作成
2. `names.yaml`、`addresses.yaml`、`demographics.yaml`、
   `reference_range_lab.yaml`、`formatting.yaml` を追加
3. `clinosim/locale/shared/naming_rules.yaml` にエントリ追加
4. (オプション) 国固有コードシステムを `codes/data/` に追加

### 新規言語追加

`clinosim/codes/data/*.yaml` の各エントリに新言語キーを追加:

```yaml
N10:
  en: "Acute tubulo-interstitial nephritis"
  ja: "急性腎盂腎炎"
  de: "Akute tubulointerstitielle Nephritis"   # 新言語
```

詳細: `clinosim/codes/README.ja.md`

---
