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
   に折り畳む場合等は `clinosim/locale/<country>/code_mapping_diagnosis.yaml`
   に mapping エントリを追加。未登録だと FHIR Condition display が
   prefix 近似 fallback に落ちる。`AGENTS.md` 「Diagnosis code
   coverage」参照。
4. 疾患 YAML が重症度ごとに `target_los.japan` と `target_los.us` の両方を持つ
   場合、`clinosim/modules/clinical_course/reference_data/course_time_scale.yaml`
   に疾患の行を追加 (重症度ごとの日本平均 / 米国平均の比を上下限で丸めた値)。
   表がその比と異なると `tests/unit/test_course_time_scale_3931.py` が失敗する
   (行の無い疾患は設計時の速度、倍率 1.0 で進む)。
5. [`AGENTS.md`](../../AGENTS.md) 「Disease protocol YAML files」の Python
   disease-id 集合を確認: 救急入院扱い、1〜2 時間ごとのバイタル、連続 SpO2、
   画像検査が必要な疾患は core ファイルの編集が必要なので、「データのみ」で
   済むのは他の疾患だけ。
6. テスト: `clinosim test-disease <disease_id>` および
   `pytest tests/unit/test_diagnosis_code_coverage.py tests/unit/test_course_time_scale_3931.py`。

詳細: `clinosim/modules/disease/README.ja.md`

### 新規 encounter 型追加 (ED/外来)

1. `clinosim/modules/encounter/reference_data/<condition_id>.yaml`
   を作成。
2. `icd10_code` と `icd10_display` を含める (`emergency` の condition で対象年齢を制限する場合は `min_age` / `max_age` を設定 — ED の抽選は受診年の年齢で gate する)。
3. `icd10_code` を「新規疾患追加」ステップ 3 に従って登録。
4. テスト: `clinosim test-encounter <condition_id>` および
   `pytest tests/unit/test_diagnosis_code_coverage.py`。

### 新規国追加

1. `clinosim/locale/<country_code>/` フォルダを `country.yaml` (国プロファイル)
   付きで作成。このファイルがあることで国が存在する (国 → ディレクトリの
   対応表は無い)
2. `names.yaml`、`addresses.yaml`、`demographics.yaml`、
   `reference_range_lab.yaml`、`formatting.yaml`、`care_practice.yaml`、
   `population_genetics.yaml` と `code_mapping_*.yaml` を追加
3. `country.yaml` の `healthcare_system` が指すヘルスケアシステム設定
   `clinosim/config/<stem>.yaml` を作成
4. 国フォルダの外のエントリを追加: `clinosim/locale/shared/naming_rules.yaml`、
   `clinosim/modules/population/reference_data/anthropometric_reference.yaml`
   の `pediatric_growth` ブロック、`clinosim/modules/encounter/reference_data/minor_burn.yaml`
   と `minor_laceration.yaml` の `diagnosis_variants` の `codes` (欠けるといずれも
   ロード時に失敗する)
5. (オプション) どの国にも無いアルゴリズムの名前付き実装
   (`clinosim/country_profile.py` の `IMPLEMENTATION_MODULES` に載るモジュールで
   登録) または clinosim が知らない FHIR プロファイル (`FHIR_PROFILES` と
   ビルダー側の gate): いずれも core ファイルの編集になる
6. (オプション) 国固有コードシステムを `codes/data/` に追加

完全なチェックリスト: [`../add-your-country.ja.md`](../add-your-country.ja.md)。

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
