<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# 拡張ガイド

### 新規疾患追加

1. `clinosim/modules/disease/reference_data/<disease_id>.yaml` を
   作成 (既存疾患をテンプレートに)
2. `clinosim/locale/<country>/demographics.yaml` の incidence リスト
   に追加
3. 必要な ICD コードを `clinosim/codes/data/icd-10-cm.yaml` に追加
   (未登録の場合)
4. テスト: `clinosim test-disease <disease_id>`

詳細: `clinosim/modules/disease/README.md`

### 新規 encounter 型追加 (ED/外来)

1. `clinosim/modules/encounter/reference_data/<condition_id>.yaml`
   を作成
2. `icd10_code` と `icd10_display` を含める
3. テスト: `clinosim test-encounter <condition_id>`

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
