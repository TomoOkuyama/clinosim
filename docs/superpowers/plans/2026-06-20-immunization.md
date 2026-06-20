# 予防接種 (Immunization) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 成人ワクチン (インフル/肺炎球菌/COVID-19/Tdap/帯状疱疹) の接種歴を人口統計 + 国別スケジュール (接種開始時期・年齢×性別別接種率) から決定論的に生成し、FHIR `Immunization` + CSV に出力する (AD-55 Base, US+JP)。

**Architecture:** CVX コード (国際, CDC 照合) を `codes/data/cvx.yaml` に、接種スケジュール (locale 文化データ) を `locale/<country>/immunization_schedule.yaml` に置く。生成は `modules/immunization/engine.py` の純粋関数。実行は AD-56 Base Enricher (post_records, always-on) で専用サブシードを使い主乱数列を乱さない。FHIR は `register_bundle_builder`。

**Tech Stack:** Python 3.11+, PyYAML, numpy Generator (sub-seed), pytest, FHIR R4, CVX (CDC).

## Global Constraints

- 決定論 (AD-16): 接種生成 rng は `ctx.master_seed` から専用サブシード (hashlib, per-patient; microbiology `_encounter_seed` / nursing `_sub_seed` と同型、独自 OFFSET)。主シミュレーションループ・主乱数列を変更しない。
- **既存 golden 不変**: labs/vitals/診断/看護データ等は byte 不変。新規 `immunizations` フィールド + 新規 FHIR `Immunization` + 新 CSV のみ追加。
- AD-55 Base: コア型 (`CIFPatientRecord`) に typed field を追加してよい。always-on (`enabled=lambda c: True`)。
- AD-56: FHIR は `register_bundle_builder`。`_build_bundle` は編集しない。Enricher は `register_enricher`。
- AD-30: CIF はコードのみ (`vaccine_cvx`)。display は `lookup("cvx", code, lang)` で出力時解決。
- AD-32 (snapshot): 全 `occurrence_date ≤ as_of`。as_of = `ctx.config.snapshot_date` (あれば) else 患者の主 encounter `admission_datetime.date()`。
- **コード値は捏造禁止**: 全 CVX を CDC で照合 (`https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx` または `https://www2.cdc.gov/vaccines/iis/iisstandards/downloads/cvx.txt`)。照合できたコードのみ採用。`cvx.yaml` は `en` 必須 + `ja`。接種率 (`coverage_by_age_sex`) と `available_from` はモデリングパラメータ (疾病罹患率と同様の推定値、出典コメント付き) — コードではない。
- ハードコード禁止: スケジュール/コードは YAML。FHIR system URI は `get_system_uri("cvx")`。
- 型は `clinosim/types/` のみ。`modules/immunization` は `types`/`codes`/`locale` のみに依存。
- コメント/docstring 英語、行長 100、ruff、mypy strict 方針。US 出力 100% 英語、JP 日本語。
- git: master から branch。commit 末尾に下記トレーラ (空行の後)。push/PR/merge はユーザー指示時のみ。`git add` は特定パスのみ (`-A` 禁止、`output/` を巻き込む)。venv: 各コマンド前 `source .venv/bin/activate`。

```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PAVRbWqciawmAyKriJFsL1
```

---

### Task 1: CVX コード体系 (CDC 照合 + 登録)

**Files:**
- Create: `clinosim/codes/data/cvx.yaml`
- Modify: `clinosim/codes/loader.py` (`_BUILTIN_URIS` に `cvx` を追加)

**Interfaces:**
- Produces: `cvx.yaml` (`system.uri` + `codes:` の CVX 群)、`get_system_uri("cvx")` → CVX URI。

- [ ] **Step 1: 候補 CVX を CDC で照合**

CDC CVX マスター (`https://www2.cdc.gov/vaccines/iis/iisstandards/downloads/cvx.txt` を WebFetch、
または `...vaccines.asp?rpt=cvx`) で各候補の "CVX Code" と "Vaccine Name/Short Description" を確認:
- インフル不活化 (季節性, 成人): 候補 `150` / `158` / `171` / `186` / `185` — "influenza, injectable"
  系で成人季節性に適うものを 1 つ確認採用。
- 肺炎球菌: PPSV23 `33`、PCV13 `133`、PCV15 `215`、PCV20 `216`。
- COVID-19: mRNA 系 `208` / `207` / `221` / `229` / `300` 等から確認して 1-2 採用。
- Tdap `115`、Td `113` または `138`。
- 帯状疱疹: 組換え RZV (Shingrix) `187`、生 ZVL `121`。

照合できた CVX のみ採用。Short Description が一致しないものは不採用 (report に記録)。

- [ ] **Step 2: cvx.yaml を作成**

```yaml
# CVX (Vaccine Administered) — CDC-maintained vaccine code set.
# Source: CDC IIS CVX (https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx)
# Verified <DATE>. en = CDC short description; ja = clinical Japanese term.
system:
  key: cvx
  uri: http://hl7.org/fhir/sid/cvx
codes:
  "150":
    en: "Influenza, injectable, quadrivalent"
    ja: "インフルエンザ（不活化・4価）"
  "33":
    en: "Pneumococcal polysaccharide PPSV23"
    ja: "肺炎球菌（23価多糖体, PPSV23）"
  # ... verified entries only ...
```
(注: `system:` ブロックの形は他の `codes/data/*.yaml` (例 `snomed-ct.yaml` 冒頭) に合わせる。
`_load_system` がこの形を読めることを確認する。)

- [ ] **Step 3: loader に URI フォールバックを追加**

`clinosim/codes/loader.py` の `_BUILTIN_URIS` に 1 行追加 (cvx.yaml が `uri` を持つので冗長だが
他系統と同様に明示):
```python
    "cvx": "http://hl7.org/fhir/sid/cvx",
```

- [ ] **Step 4: 照合 + 整合性確認**

Run:
```bash
source .venv/bin/activate && python -c "
from clinosim.codes import lookup, get_system_uri
print('uri:', get_system_uri('cvx'))
print('150:', lookup('cvx','150','en'), '/', lookup('cvx','150','ja'))
" && python -m pytest tests/unit/test_codes_integrity.py -q
```
Expected: uri が `http://hl7.org/fhir/sid/cvx`、display が code と異なる、integrity PASS (重複キー無し)。

- [ ] **Step 5: コミット**

```bash
git add clinosim/codes/data/cvx.yaml clinosim/codes/loader.py
git commit
```
メッセージ: `feat(codes): add CDC-verified CVX vaccine code system` (本文に採用 CVX と短い説明を列挙)。

---

### Task 2: CIF 型 (ImmunizationRecord + CIFPatientRecord.immunizations)

**Files:**
- Modify: `clinosim/types/encounter.py` (新 dataclass)
- Modify: `clinosim/types/output.py` (CIFPatientRecord に list 追加)
- Test: `tests/unit/test_immunization.py` (新規、型スモーク)

**Interfaces:**
- Produces: `ImmunizationRecord` dataclass; `CIFPatientRecord.immunizations: list`。

- [ ] **Step 1: ImmunizationRecord を追加**

`clinosim/types/encounter.py` の `IntakeOutputRecord` / `NursingRiskAssessment` 近くに
(`from datetime import date` は既存利用):
```python
@dataclass
class ImmunizationRecord:
    """A completed immunization (vaccine history). FHIR Immunization (AD-55 Base).

    CIF stores the CVX code only; display resolved at output via clinosim.codes (AD-30).
    """
    vaccine_cvx: str = ""
    occurrence_date: date = field(default_factory=date.today)
    status: str = "completed"
    primary_source: bool = True
    dose_number: int | None = None
```

- [ ] **Step 2: CIFPatientRecord に格納フィールドを追加**

`clinosim/types/output.py` の `CIFPatientRecord`、`nursing_risk_assessments` の直後に:
```python
    immunizations: list = field(default_factory=list)  # ImmunizationRecord
```

- [ ] **Step 3: 型スモークテスト**

`tests/unit/test_immunization.py` を新規作成:
```python
"""Unit tests for immunization generation."""

import pytest

pytestmark = pytest.mark.unit


def test_types_importable():
    from clinosim.types.encounter import ImmunizationRecord
    r = ImmunizationRecord(vaccine_cvx="150")
    assert r.status == "completed" and r.primary_source is True
```

- [ ] **Step 4: 実行 + lint**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_immunization.py -q && ruff check clinosim/types/encounter.py clinosim/types/output.py`
Expected: PASS、新規行 lint クリーン。

- [ ] **Step 5: コミット**

```bash
git add clinosim/types/encounter.py clinosim/types/output.py tests/unit/test_immunization.py
git commit
```
メッセージ: `feat(types): add ImmunizationRecord (AD-55 immunization)`

---

### Task 3: 接種スケジュール YAML (US + JP)

**Files:**
- Create: `clinosim/locale/us/immunization_schedule.yaml`
- Create: `clinosim/locale/jp/immunization_schedule.yaml`

**Interfaces:**
- Produces: `vaccines:` マップ (Task 4 の engine が読む)。各ワクチン: `cvx` / `min_age` /
  `frequency` (`annual`|`once`|`every_n_years`) / 任意 `interval_years` / 任意 `season_month` /
  `available_from` (YYYY-MM-DD) / `coverage_by_age_sex` (`"lo-hi": {M: p, F: p}`)。

- [ ] **Step 1: US スケジュールを作成**

`clinosim/locale/us/immunization_schedule.yaml` (cvx は Task 1 で採用したコードに合わせる。
coverage は CDC FluVaxView / MMWR の概数。年齢帯は `"18-49"/"50-64"/"65-99"`):
```yaml
# US adult immunization schedule.
# Sources: CDC ACIP adult immunization schedule; coverage = CDC FluVaxView / MMWR
# approximate population estimates (modeling parameters, not codes). Verified <DATE>.
vaccines:
  influenza:
    cvx: "150"
    min_age: 18
    frequency: annual
    season_month: 10
    available_from: "2000-01-01"
    coverage_by_age_sex:
      "18-49": {M: 0.32, F: 0.38}
      "50-64": {M: 0.45, F: 0.50}
      "65-99": {M: 0.68, F: 0.70}
  covid19:
    cvx: "208"
    min_age: 18
    frequency: once
    available_from: "2020-12-14"
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
  tdap:
    cvx: "115"
    min_age: 18
    frequency: every_n_years
    interval_years: 10
    available_from: "2005-06-01"
    coverage_by_age_sex:
      "18-49": {M: 0.30, F: 0.34}
      "50-64": {M: 0.28, F: 0.32}
      "65-99": {M: 0.24, F: 0.26}
  zoster_rzv:
    cvx: "187"
    min_age: 50
    frequency: once
    available_from: "2017-10-20"
    coverage_by_age_sex:
      "50-64": {M: 0.30, F: 0.35}
      "65-99": {M: 0.45, F: 0.50}
```

- [ ] **Step 2: JP スケジュールを作成**

`clinosim/locale/jp/immunization_schedule.yaml` (JP 固有: COVID `available_from: 2021-02-17`、
PPSV23 は 65 歳定期、coverage は MHLW 概数。cvx は同 CVX を流用):
```yaml
# JP adult immunization schedule.
# Sources: MHLW 定期接種 schedule; coverage = MHLW 接種率統計 approximate estimates.
# Verified <DATE>.
vaccines:
  influenza:
    cvx: "150"
    min_age: 18
    frequency: annual
    season_month: 11
    available_from: "2000-01-01"
    coverage_by_age_sex:
      "18-49": {M: 0.25, F: 0.30}
      "50-64": {M: 0.40, F: 0.44}
      "65-99": {M: 0.55, F: 0.58}
  covid19:
    cvx: "208"
    min_age: 18
    frequency: once
    available_from: "2021-02-17"
    coverage_by_age_sex:
      "18-49": {M: 0.70, F: 0.74}
      "50-64": {M: 0.82, F: 0.84}
      "65-99": {M: 0.90, F: 0.92}
  pneumococcal_ppsv23:
    cvx: "33"
    min_age: 65
    frequency: once
    available_from: "2014-10-01"
    coverage_by_age_sex:
      "65-99": {M: 0.40, F: 0.42}
```
(JP は Tdap/zoster の成人定期が US と異なるため当面 3 種。スコープは「JP で妥当な成人セット」。)

- [ ] **Step 3: ロード確認**

Run:
```bash
source .venv/bin/activate && python -c "
import yaml
for c in ('us','jp'):
    d = yaml.safe_load(open(f'clinosim/locale/{c}/immunization_schedule.yaml'))
    vs = d['vaccines']
    print(c, 'vaccines:', list(vs))
    for name, v in vs.items():
        assert 'cvx' in v and 'min_age' in v and 'frequency' in v and 'available_from' in v and 'coverage_by_age_sex' in v, (c, name)
print('OK: schedules well-formed')
"
```
Expected: `OK: schedules well-formed`。

- [ ] **Step 4: コミット**

```bash
git add clinosim/locale/us/immunization_schedule.yaml clinosim/locale/jp/immunization_schedule.yaml
git commit
```
メッセージ: `feat(locale): US/JP adult immunization schedules (availability + age/sex coverage)`

---

### Task 4: 生成エンジン `modules/immunization/engine.py` (TDD)

**Files:**
- Create: `clinosim/modules/immunization/__init__.py`
- Create: `clinosim/modules/immunization/engine.py`
- Test: `tests/unit/test_immunization.py` (拡張)

**Interfaces:**
- Consumes: `PatientProfile` (age/sex/date_of_birth)、スケジュール dict、`as_of: date`、numpy Generator。
- Produces:
  - `load_schedule(country: str) -> dict` — locale の immunization_schedule.yaml をロード (US 既定)。
  - `generate_immunizations(patient, schedule, as_of, rng) -> list[ImmunizationRecord]` — 純粋関数。

- [ ] **Step 1: 失敗テストを書く**

`tests/unit/test_immunization.py` に追加:
```python
from datetime import date

import numpy as np


def _patient(age, sex="M", dob_year=None):
    from clinosim.types.patient import PatientProfile
    dob = date((dob_year or (2026 - age)), 1, 1)
    return PatientProfile(patient_id="p1", age=age, sex=sex, date_of_birth=dob, country="US")


def _sched():
    from clinosim.modules.immunization.engine import load_schedule
    return load_schedule("US")


def test_min_age_excludes_pneumococcal_for_young():
    from clinosim.modules.immunization.engine import generate_immunizations
    recs = generate_immunizations(_patient(40), _sched(), date(2026, 1, 1), np.random.default_rng(1))
    assert all(r.vaccine_cvx != "33" for r in recs)  # PPSV23 min_age 65


def test_all_dates_within_window():
    from clinosim.modules.immunization.engine import generate_immunizations
    as_of = date(2026, 1, 1)
    recs = generate_immunizations(_patient(80), _sched(), as_of, np.random.default_rng(2))
    assert all(r.occurrence_date <= as_of for r in recs)
    # COVID-19 (cvx 208) never before its availability date
    covid = [r for r in recs if r.vaccine_cvx == "208"]
    assert all(r.occurrence_date >= date(2020, 12, 14) for r in covid)


def test_high_coverage_more_than_low_band():
    from clinosim.modules.immunization.engine import generate_immunizations
    # elderly flu coverage (0.68-0.70) >> younger; count flu records across many seeds
    def flu_count(age):
        n = 0
        for s in range(60):
            recs = generate_immunizations(_patient(age), _sched(), date(2026, 1, 1),
                                          np.random.default_rng(s))
            n += sum(1 for r in recs if r.vaccine_cvx == "150")
        return n
    assert flu_count(80) > flu_count(30)


def test_deterministic_same_seed():
    from clinosim.modules.immunization.engine import generate_immunizations
    a = generate_immunizations(_patient(70), _sched(), date(2026, 1, 1), np.random.default_rng(7))
    b = generate_immunizations(_patient(70), _sched(), date(2026, 1, 1), np.random.default_rng(7))
    assert [(r.vaccine_cvx, r.occurrence_date) for r in a] == [(r.vaccine_cvx, r.occurrence_date) for r in b]
```

- [ ] **Step 2: 失敗を確認**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_immunization.py -q`
Expected: FAIL (engine 未実装)。

- [ ] **Step 3: engine.py を実装**

`clinosim/modules/immunization/__init__.py` (空) と `clinosim/modules/immunization/engine.py`:
```python
"""Immunization history generation (AD-55 Base).

Pure functions deriving a patient's adult vaccine history from demographics and a
locale schedule (eligibility age, availability date, season, age/sex coverage).
Codes (CVX) live in clinosim.codes; schedules in clinosim/locale/<country>/.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

_LOCALE = Path(__file__).resolve().parents[2] / "locale"


@lru_cache(maxsize=4)
def load_schedule(country: str) -> dict:
    key = "jp" if str(country).upper() == "JP" else "us"
    with open(_LOCALE / key / "immunization_schedule.yaml") as f:
        return (yaml.safe_load(f) or {}).get("vaccines", {})


def _age_on(dob: date | None, on: date, fallback_age: int) -> int:
    if dob is None:
        return fallback_age
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _coverage(cov: dict, age: int, sex: str) -> float:
    for band, ms in cov.items():
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return float(ms.get(sex, next(iter(ms.values()))))
    return 0.0


def _parse(d: str) -> date:
    y, m, day = (int(x) for x in d.split("-"))
    return date(y, m, day)


def generate_immunizations(patient, schedule: dict, as_of: date,
                           rng: np.random.Generator) -> list:
    from clinosim.types.encounter import ImmunizationRecord

    dob = getattr(patient, "date_of_birth", None)
    base_age = int(getattr(patient, "age", 0) or 0)
    sex = getattr(patient, "sex", "M") or "M"
    out: list = []

    for _name, v in schedule.items():
        cvx = str(v["cvx"])
        min_age = int(v["min_age"])
        avail = _parse(v["available_from"])
        freq = v["frequency"]
        cov = v["coverage_by_age_sex"]

        # earliest eligible date = max(availability, date patient reached min_age)
        if dob is not None:
            reached = date(dob.year + min_age, dob.month, dob.day)
        else:
            reached = date(as_of.year - (base_age - min_age), 1, 1) if base_age >= min_age else None
        if reached is None:
            continue
        start = max(avail, reached)
        if start > as_of:
            continue

        if freq == "annual":
            month = int(v.get("season_month", 10))
            for yr in range(start.year, as_of.year + 1):
                occ = date(yr, month, 1)
                if occ < start or occ > as_of:
                    continue
                age_at = _age_on(dob, occ, base_age)
                if rng.random() < _coverage(cov, age_at, sex):
                    out.append(ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=occ))
        elif freq == "every_n_years":
            interval = int(v.get("interval_years", 10))
            yr = start.year
            while date(yr, start.month, start.day) <= as_of:
                occ = date(yr, start.month, start.day)
                age_at = _age_on(dob, occ, base_age)
                if rng.random() < _coverage(cov, age_at, sex):
                    out.append(ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=occ))
                yr += interval
        else:  # once
            age_at = _age_on(dob, as_of, base_age)
            if rng.random() < _coverage(cov, age_at, sex):
                # place once at a deterministic point within [start, as_of]
                span = (as_of - start).days
                offset = int(rng.integers(0, span + 1)) if span > 0 else 0
                occ = date.fromordinal(start.toordinal() + offset)
                out.append(ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=occ))

    out.sort(key=lambda r: r.occurrence_date)
    return out
```
(注: 実装中に `PatientProfile` のフィールド名を `clinosim/types/patient.py` で再確認し、相違あれば
合わせる。`coverage_by_age_sex` のバンドは整数 `lo-hi`。)

- [ ] **Step 4: 全テスト緑 + lint**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_immunization.py -q && ruff check clinosim/modules/immunization/engine.py`
Expected: 全 PASS、lint クリーン。

- [ ] **Step 5: コミット**

```bash
git add clinosim/modules/immunization/__init__.py clinosim/modules/immunization/engine.py tests/unit/test_immunization.py
git commit
```
メッセージ: `feat(immunization): schedule-driven immunization history generator`

---

### Task 5: Base Enricher 配線

**Files:**
- Create: `clinosim/modules/immunization/enricher.py`
- Modify: `clinosim/simulator/enrichers.py` (`register_builtin_enrichers` に登録)
- Test: `tests/integration/test_immunization_enricher.py` (新規)

**Interfaces:**
- Consumes: `EnricherContext` (`.records`, `.master_seed`, `.config`)、Task 4 の `load_schedule`/
  `generate_immunizations`、Task 2 の型。
- Produces: `enrich_immunizations(ctx) -> None` — 各 CIFPatientRecord の `immunizations` を生成。

- [ ] **Step 1: enricher を実装**

`clinosim/modules/immunization/enricher.py`:
```python
"""Immunization enricher (AD-55 Base, AD-56 post_records).

Generates each patient's vaccine history with a dedicated sub-seed so the main
simulation random stream is untouched (AD-16). occurrence dates <= snapshot (AD-32).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

import numpy as np

from clinosim.modules.immunization.engine import generate_immunizations, load_schedule

_IMM_SEED_OFFSET = 0x494D  # "IM"


def _sub_seed(master_seed: int, key: str) -> int:
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:6], "big")
    return (int(master_seed) + _IMM_SEED_OFFSET + h) % (2**32)


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_of(ctx, rec) -> date:
    snap = _get(_get(ctx, "config"), "snapshot_date", None) if _get(ctx, "config") else None
    if snap:
        y, m, d = (int(x) for x in str(snap).split("-"))
        return date(y, m, d)
    # else: latest encounter admission date, else today
    encs = _get(rec, "encounters", []) or []
    dates = []
    for e in encs:
        adm = _get(e, "admission_datetime")
        if isinstance(adm, datetime):
            dates.append(adm.date())
    return max(dates) if dates else date.today()


def enrich_immunizations(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    schedule = load_schedule(country)
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        rng = np.random.default_rng(_sub_seed(ctx.master_seed, pid or "x"))
        recs = generate_immunizations(patient, schedule, _as_of(ctx, rec), rng)
        if isinstance(rec, dict):
            rec["immunizations"] = recs
        else:
            rec.immunizations = recs
```

- [ ] **Step 2: register_builtin_enrichers に登録**

`clinosim/simulator/enrichers.py` の `register_builtin_enrichers()` 内、nursing 登録の後に:
```python
    # Immunization history (AD-55 Base): adult vaccine history. Always-on.
    from clinosim.modules.immunization.enricher import enrich_immunizations

    register_enricher(
        Enricher(
            name="immunization",
            stage=POST_RECORDS,
            order=30,
            enabled=lambda c: True,
            run=enrich_immunizations,
        )
    )
```

- [ ] **Step 3: integration テスト**

`tests/integration/test_immunization_enricher.py`:
```python
import pytest

pytestmark = pytest.mark.integration


def _ctx(records, country="US", snapshot=None, seed=123):
    from clinosim.simulator.enrichers import EnricherContext

    class _Cfg:
        def __init__(self, country, snapshot_date):
            self.country = country
            self.snapshot_date = snapshot_date
    return EnricherContext(config=_Cfg(country, snapshot), master_seed=seed, records=records)


def _record(age=80, sex="F"):
    from datetime import date, datetime
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    from clinosim.types.encounter import Encounter
    p = PatientProfile(patient_id="p1", age=age, sex=sex,
                       date_of_birth=date(2026 - age, 3, 1), country="US")
    enc = Encounter(admission_datetime=datetime(2026, 1, 10, 9, 0))
    return CIFPatientRecord(patient=p, encounters=[enc])


def test_enricher_fills_immunizations():
    from clinosim.modules.immunization.enricher import enrich_immunizations
    rec = _record()
    enrich_immunizations(_ctx([rec], snapshot="2026-01-15"))
    assert rec.immunizations, "no immunizations generated for an 80yo"
    from datetime import date
    assert all(r.occurrence_date <= date(2026, 1, 15) for r in rec.immunizations)


def test_enricher_deterministic():
    from clinosim.modules.immunization.enricher import enrich_immunizations
    r1, r2 = _record(), _record()
    enrich_immunizations(_ctx([r1], seed=99))
    enrich_immunizations(_ctx([r2], seed=99))
    k = lambda recs: [(x.vaccine_cvx, x.occurrence_date) for x in recs]
    assert k(r1.immunizations) == k(r2.immunizations)
```
(注: `Encounter` / `PatientProfile` の実コンストラクタを確認し、必要最小限の引数で構築。)

- [ ] **Step 4: 実行**

Run: `source .venv/bin/activate && python -m pytest tests/integration/test_immunization_enricher.py -q && ruff check clinosim/modules/immunization/enricher.py clinosim/simulator/enrichers.py`
Expected: PASS、lint クリーン。

- [ ] **Step 5: コミット**

```bash
git add clinosim/modules/immunization/enricher.py clinosim/simulator/enrichers.py tests/integration/test_immunization_enricher.py
git commit
```
メッセージ: `feat(simulator): register immunization enricher (AD-56 post_records)`

---

### Task 6: FHIR Immunization ビルダー

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py` (`_build_immunizations` 追加 + `_BUNDLE_BUILDERS` 登録)
- Test: `tests/integration/test_fhir_immunization.py` (新規)

**Interfaces:**
- Consumes: `BundleContext` (`.record`, `.country`, `.patient_id`)、`get_system_uri("cvx")`、`lookup`。
- Produces: `_build_immunizations(ctx) -> list[dict]` — FHIR `Immunization` のリスト。

- [ ] **Step 1: ビルダーを実装**

`fhir_r4_adapter.py` に `_build_immunizations(ctx)` を追加 (既存 `_bb_*` ビルダー / nursing ビルダー
のスタイルに合わせる)。要件:
- `ctx.record.get("immunizations")` を index 付き反復。各 `ImmunizationRecord` を FHIR
  `Immunization` 化:
  - `resourceType="Immunization"`、`id=f"imm-{ctx.patient_id}-{i}"` (タイプ内一意)、
    `status` = record.status (`"completed"`)、
    `vaccineCode = {"coding": [{"system": get_system_uri("cvx"), "code": cvx,
      "display": lookup("cvx", cvx, lang)}], "text": lookup("cvx", cvx, lang)}`
      (display == code の場合は display を省く)、
    `patient = {"reference": f"Patient/{ctx.patient_id}"}`、
    `occurrenceDateTime` = ISO 日付、`primarySource` = record.primary_source。
  - `lang = "ja" if ctx.country == "JP" else "en"`。US 出力に日本語ゼロ。
- `_BUNDLE_BUILDERS` リストに `_build_immunizations` を追記 (AD-56)。

- [ ] **Step 2: integration テスト**

`tests/integration/test_fhir_immunization.py` — 看護 FHIR テスト (`test_fhir_nursing.py`) の
`BundleContext` 構築方法を踏襲し、immunizations 入り record を渡して検証:
- 各 `resourceType == "Immunization"`、`status == "completed"`、`id` 一意、
  `patient.reference == "Patient/{id}"`。
- `vaccineCode.coding[0].system == get_system_uri("cvx")`、`display != code`。
- `country="US"` で日本語文字ゼロ (`assert not re.search(r"[぀-ヿ一-鿿]", json.dumps(obs))`)。

- [ ] **Step 3: 実行**

Run: `source .venv/bin/activate && python -m pytest tests/integration/test_fhir_immunization.py -q && ruff check clinosim/modules/output/fhir_r4_adapter.py`
Expected: PASS、lint クリーン。

- [ ] **Step 4: コミット**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py tests/integration/test_fhir_immunization.py
git commit
```
メッセージ: `feat(output): FHIR Immunization resources (CVX, AD-56)`

---

### Task 7: CSV 出力 (immunizations.csv)

**Files:**
- Modify: `clinosim/modules/output/csv_adapter.py`

**Interfaces:**
- Consumes: `record.get("immunizations")`。
- Produces: `immunizations.csv`。

- [ ] **Step 1: rows 初期化 + ループ + write を追加**

`csv_adapter.py`:
- 行リスト初期化群 (line 29-34 付近) に `imm_rows: list[dict] = []` を追加。
- microbiology ループ近くに immunization ループを追加:
```python
        for imm in record.get("immunizations", []):
            imm_rows.append({
                "patient_id": patient_id,
                "vaccine_cvx": imm.get("vaccine_cvx"),
                "occurrence_date": imm.get("occurrence_date"),
                "status": imm.get("status"),
                "dose_number": imm.get("dose_number"),
            })
```
- 「Write CSVs」節に `_write_csv(os.path.join(output_dir, "immunizations.csv"), imm_rows)` を追加。

- [ ] **Step 2: スモーク確認**

Run:
```bash
source .venv/bin/activate && python -c "
import inspect
from clinosim.modules.output import csv_adapter
s = inspect.getsource(csv_adapter)
assert 'immunizations.csv' in s and 'vaccine_cvx' in s
print('OK: csv immunization wired')
" && ruff check clinosim/modules/output/csv_adapter.py
```
Expected: `OK: csv immunization wired`、lint クリーン。

- [ ] **Step 3: コミット**

```bash
git add clinosim/modules/output/csv_adapter.py
git commit
```
メッセージ: `feat(output): CSV immunizations.csv`

---

### Task 8: ドキュメント + フル回帰

**Files:**
- Create: `clinosim/modules/immunization/README.md`
- Modify: `TODO.md`

- [ ] **Step 1: モジュール README を作成**

`clinosim/modules/immunization/README.md` (日本語 + 英語技術用語): 目的、提供ワクチン、
データ駆動 (CVX = codes, schedule = locale, `available_from` + `coverage_by_age_sex`)、
enricher 実行 (AD-56 post_records, 専用サブシード)、CIF 表現、FHIR/CSV 出力、決定論/snapshot、
権威出典 (CVX=CDC、接種率=CDC/MHLW 概数)、依存関係 (`types`/`codes`/`locale`)。

- [ ] **Step 2: TODO.md を更新**

AD-55 Base クラスタの immunization を完了 (`[x]`)、推奨順序 (line 441 付近) の進捗を反映。
採用 CVX と JP/US スケジュール概要、coverage の出典を 1-2 行で記述。

- [ ] **Step 3: コミット**

```bash
git add clinosim/modules/immunization/README.md TODO.md
git commit
```
メッセージ: `docs: record immunization feature (CVX, US/JP adult schedules)`

- [ ] **Step 4: unit + integration 全体**

Run: `source .venv/bin/activate && python -m pytest -m "unit or integration" -q`
Expected: 全 PASS (既存 287 + 新規 immunization テスト)。

- [ ] **Step 5: e2e 回帰 (既存 byte 不変 + 新データ)**

Run: `source .venv/bin/activate && python -m pytest -m e2e -q`
Expected: 全 PASS (37)。e2e はプロパティ/決定論ベース (保存 golden ファイルではない)。専用
サブシードのため既存 labs/vitals/診断/看護データは byte 不変、新規 Immunization のみ追加。
CPU 競合で稀に途中 exit → 再実行で確認 ([[feedback_clinosim_workflow]])。

- [ ] **Step 6: 報告とユーザー確認**

ブランチのコミット一覧と全テスト結果を報告し、push / PR 作成の可否をユーザーに確認する。

---

## Self-Review

**Spec coverage:**
- CVX コード (spec §CVX) → Task 1。
- 型 (spec §CIF 表現) → Task 2。
- スケジュール US+JP + available_from + coverage_by_age_sex (spec §スケジュール) → Task 3。
- 生成ロジック (spec §生成) → Task 4。
- Enricher + 専用サブシード + snapshot as-of (spec §決定論/スナップショット) → Task 5。
- FHIR Immunization (spec §FHIR) → Task 6。
- CSV (spec §CSV) → Task 7。
- ドキュメント + 既存 byte 不変 (spec §受け入れ基準5/6) → Task 8。

**Placeholder scan:** TBD/TODO 無し。CVX は「CDC 照合し採用」= 具体的手順。FHIR ビルダー (Task 6)
は contract + 既存スタイル参照で規定 (巨大ファイルのため逐語コードは置かない)。coverage 値は
出典付きモデリングパラメータ。

**Type consistency:** `load_schedule(country)->dict`、`generate_immunizations(patient,schedule,as_of,rng)->list[ImmunizationRecord]`、
`enrich_immunizations(ctx)->None`、`_build_immunizations(ctx)->list[dict]`、`ImmunizationRecord`
フィールド (`vaccine_cvx`/`occurrence_date`/`status`/`primary_source`/`dose_number`) — Task 2/4/5/6/7 で一貫。
スケジュールキー (`cvx`/`min_age`/`frequency`/`interval_years`/`season_month`/`available_from`/
`coverage_by_age_sex`) は Task 3 (定義) ↔ Task 4 (消費) で一致。
