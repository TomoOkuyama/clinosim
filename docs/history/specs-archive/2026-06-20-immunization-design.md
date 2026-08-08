# 予防接種 (Immunization) — AD-55 Base / US+JP 成人ワクチン

- **Date**: 2026-06-20
- **Scope**: 成人ワクチン (インフル / 肺炎球菌 / COVID-19 / Tdap / 帯状疱疹) × US+JP
- **Type**: AD-55 Base データ拡充 (always-on)。新規データ追加 (既存出力は不変)。
- **Status**: 設計承認済 (接種開始時期 + 年齢×性別別接種率を反映)

## 背景と目的

実 EHR の患者要約には予防接種歴が含まれる。clinosim には現状ない。TODO.md 推奨順序
(line 441) で看護フローシートの次が「immunization / family-history / code-status / SDOH
(Base)」クラスタ。本機能はその先頭の予防接種を実装する。

集団は成人・高齢中心 (community/regional hospital) のため成人ワクチンに絞る。患者の
人口統計 (年齢/性別/生年月日) + 国別接種スケジュールから**決定論的**に接種歴を導出し、
FHIR `Immunization` + CSV に出力する。

**臨床的整合性** (ユーザー要件、横断原則): 接種は単に年齢適格なだけでなく、
(a) **ワクチンの接種開始時期** (`available_from`) 以降にのみ存在し (例: COVID-19 ワクチンは
2020-12 (US) / 2021-02 (JP) 以前には存在しない)、(b) **年齢×性別別の接種率** で uptake を
サンプリングする (例: インフル接種率は高齢者で高い)。

## 設計 (看護フローシートと並行構造)

### アーキテクチャ

- **コード (国際)**: 新規 `clinosim/codes/data/cvx.yaml` (CDC CVX、`uri:
  http://hl7.org/fhir/sid/cvx`、`en` + `ja`)。CVX コードは **CDC で権威照合・捏造禁止**。
- **スケジュール (locale 文化データ)**: `clinosim/locale/us/immunization_schedule.yaml` /
  `clinosim/locale/jp/immunization_schedule.yaml`。ワクチン毎に cvx / 対象年齢 / 頻度 / 季節 /
  `available_from` / `coverage_by_age_sex`。国別に内容が異なる。
- **生成ロジック**: 新規 `clinosim/modules/immunization/engine.py` の純粋関数。
- **実行**: AD-55 Base Enricher (`stage=post_records`, always-on) を `simulator/enrichers.py` に
  登録。専用 hashlib サブシード (per-patient) で主乱数列を乱さない (AD-16)。

### CVX コード (CDC 権威照合・実装時に確認)

成人セット (代表的 CVX、実装時に CDC `https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx`
で各コードと vaccine name を照合):

- インフル (不活化、季節性): 例 `150` / `158` / `186` 等のいずれか確認して採用
- 肺炎球菌多糖 PPSV23: `33`
- 肺炎球菌結合 PCV13: `133` / PCV20: `216` / PCV15: `215`
- COVID-19: 代表 mRNA コード (`208`/`207`/`221`/`229` 等、確認して採用)
- Tdap: `115` / Td: `113` or `138`
- 帯状疱疹 組換え (Shingrix/RZV): `187` / 生 (ZVL): `121`

照合できた CVX のみ採用 (`en` 必須 + `ja`)。確証できないコードは採用しない。

### スケジュール YAML スキーマ

```yaml
# locale/<country>/immunization_schedule.yaml
# Sources: US = CDC ACIP adult schedule + FluVaxView/MMWR coverage.
#          JP = MHLW 定期接種 schedule + 接種率統計. Coverage rates are
#          approximate population estimates (modeling parameters), not codes.
vaccines:
  influenza:
    cvx: "150"
    min_age: 18
    frequency: annual          # annual | once | every_n_years
    season_month: 10           # administered ~October each season
    available_from: "2000-01-01"
    coverage_by_age_sex:       # annual uptake probability
      "18-49": {M: 0.32, F: 0.38}
      "50-64": {M: 0.45, F: 0.50}
      "65-99": {M: 0.68, F: 0.70}
  covid19:
    cvx: "208"
    min_age: 18
    frequency: once            # primary series modeled as one completed record
    available_from: "2020-12-14"   # US EUA; JP file overrides to 2021-02-17
    coverage_by_age_sex:
      "18-49": {M: 0.62, F: 0.66}
      "50-64": {M: 0.78, F: 0.80}
      "65-99": {M: 0.90, F: 0.91}
  pneumococcal_ppsv23:
    cvx: "33"
    min_age: 65
    frequency: once
    available_from: "2000-01-01"
    coverage_by_age_sex:
      "65-99": {M: 0.65, F: 0.68}
  # ... Tdap (every_n_years: 10), zoster (min_age 50, once), PCV (>=65) ...
```

- `frequency: annual` → `available_from` 以降・適格年齢以降の各シーズンに 1 件ずつ
  (`season_month` 月)、`coverage_by_age_sex` の確率で各年独立にサンプリング。
- `frequency: once` → 適格化〜as-of の窓で 1 件、確率でサンプリング。
- `frequency: every_n_years: N` → N 年間隔で配置。
- すべて `available_from ≤ occurrence_date ≤ as_of_date`。

### CIF 表現 (AD-55 Base: コア型に typed field 追加可)

`types/encounter.py` に新 dataclass:
```python
@dataclass
class ImmunizationRecord:
    """A completed immunization (vaccine history). FHIR Immunization (AD-55 Base)."""
    vaccine_cvx: str               # CVX code (display resolved at output, AD-30)
    occurrence_date: date
    status: str = "completed"
    primary_source: bool = True
    dose_number: int | None = None
    lot_number: str | None = None  # optional; omit if not modeled
```
`types/output.py` の `CIFPatientRecord` に `immunizations: list = field(default_factory=list)`
を追加 (`microbiology` / `nursing_risk_assessments` と並置)。

### 生成ロジック (`modules/immunization/engine.py`)

```python
def generate_immunizations(
    patient: PatientProfile,      # age / sex / date_of_birth
    schedule: dict,               # locale immunization_schedule.yaml の vaccines
    as_of_date: date,             # snapshot_date or primary encounter admission date
    rng: np.random.Generator,
) -> list[ImmunizationRecord]:
```
- 各ワクチンについて: 対象年齢・`available_from`・as_of から有効窓を決定し、頻度に応じて
  候補接種日を列挙、`coverage_by_age_sex[age_band][sex]` 確率でサンプリングして
  `ImmunizationRecord` を生成。年齢帯は患者の各接種時点年齢で判定。
- 純粋関数 (rng 注入)。コード値はハードコードせずスケジュール由来。

### 決定論・スナップショット (AD-16 / AD-32)

- enricher は `ctx.master_seed` から専用サブシード (hashlib、per-patient)。主乱数列不変 →
  既存 labs/vitals/診断/看護データは **byte 不変**、新規 `immunizations` のみ追加。
- as-of: `ctx.config.snapshot_date` があればそれ、無ければ患者の主 encounter
  `admission_datetime.date()`。全 `occurrence_date ≤ as_of`。

### FHIR 出力 (AD-56)

- `register_bundle_builder` で `_build_immunization_resources(ctx)` を登録
  (`_build_bundle` 不変)。FHIR `Immunization`:
  - `status="completed"`、`vaccineCode` = CVX coding (`system =
    get_system_uri("cvx")`、display は `lookup("cvx", code, lang)`、`display != code`)、
    `patient = {reference: "Patient/{id}"}`、`occurrenceDateTime`、`primarySource`。
  - id は patient-scoped + index で一意 (`imm-{patient_id}-{i}`)。
  - lang = ja (JP) / en (US)。US 出力に日本語ゼロ。

### CSV 出力

`csv_adapter` に `immunizations.csv` (patient_id, vaccine_cvx, occurrence_date, status,
dose_number) を追加。

## テスト

- **unit** (`tests/unit/test_immunization.py`):
  - 適格性: `min_age` 未満は生成されない、`available_from` 前の接種日は生成されない、
    全 `occurrence_date ≤ as_of`。
  - 接種率: 高 coverage バンドは低バンドより多く生成される (統計的、固定 seed で検証)。
  - 頻度: annual は複数シーズン、once は最大 1 件。
  - COVID-19: `available_from` (2020-12 / JP 2021-02) 前に出現しない。
  - 決定論: 同一 seed → 同一出力。
- **unit** (`test_codes_integrity.py` 既存): `cvx.yaml` 重複キー無し。
- **integration**: enricher 実行後 `immunizations` が CIF に存在し FHIR/CSV に流れる。
  FHIR Immunization が `vaccineCode.system == get_system_uri("cvx")`、`display != code`、
  US 日本語ゼロ、patient 参照解決可能。
- **e2e**: 既存出力 byte 不変 (サブシード) + 新規 Immunization リソース。

## スコープ外

- 小児定期接種シリーズ (MMR/DTaP/Hib/ロタ/B型肝炎等) — 集団が成人中心のため別件。
- JP 独自ワクチンコード体系 (CVX で代替、JP display は `ja`)。将来 JP Core 準拠が要れば follow-up。
- ロット番号・接種部位・製造元の詳細 (任意フィールド、当面 omit)。
- 拒否/未接種の明示記録 (completed のみモデル化)。

## 受け入れ基準

1. 成人ワクチン接種歴が人口統計 + 国別スケジュールから決定論的に生成され CIF に格納。
2. 接種開始時期 (`available_from`) と年齢×性別別接種率が反映される (COVID-19 が 2020-12/
   2021-02 前に出ない等)。全接種日 ≤ snapshot (AD-32)。
3. 全 CVX が CDC 照合済 (捏造ゼロ)、`en` 必須。
4. FHIR `Immunization` + CSV に出力、US 英語 / JP 日本語、参照整合・id 一意・display≠code。
5. 既存 golden の labs/vitals/診断/看護データが byte 不変、新リソースのみ追加。
6. unit/integration/e2e 全緑。observation/README 相当 (immunization モジュール README) +
   TODO.md 更新。
