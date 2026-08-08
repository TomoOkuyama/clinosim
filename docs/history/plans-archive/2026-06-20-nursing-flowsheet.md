# 看護フローシート (Nursing Flowsheet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NEWS2 / GCS / Braden / 転倒リスクを physiology から決定論的に算出して CIF に追加し、既存 I/O・ADL を含む看護データを FHIR `Observation` + CSV に出力する (AD-55 Base)。

**Architecture:** 計算は新規 `clinosim/modules/observation/nursing.py` の純粋関数 + `reference_data/nursing_scores.yaml` (閾値データ駆動)。実行は AD-56 の Enricher (`stage=POST_RECORDS`, always-on) として `simulator/enrichers.py` に登録し、専用サブシードで主乱数列を乱さない。FHIR は `register_bundle_builder` で nursing Observation ビルダーを登録。

**Tech Stack:** Python 3.11+, PyYAML, numpy Generator (sub-seed), pytest。FHIR R4 NDJSON, LOINC (NLM 照合)。

## Global Constraints

- 決定論 (AD-16): 看護 rng は `ctx.master_seed` から **専用サブシード** を導出 (microbiology `_encounter_seed` と同型 hashlib、独自 OFFSET)。主シミュレーションループ・主乱数列を一切変更しない。NEWS2/GCS は rng 不要 (純粋計算)。
- **既存 golden 不変**: labs / vitals 数値 / 診断 / I/O / ADL は byte 不変。新規 `news2_score`/`gcs_score` フィールドと `nursing_risk_assessments`、新規 FHIR/CSV 出力のみ追加。
- AD-55 Base: コア型 (`VitalSignRecord` / `CIFPatientRecord`) に typed field を追加してよい (extensions ではない)。always-on (`enabled=lambda c: True`)。
- AD-30: CIF はコードのみ。display は `codes.lookup` で出力時解決。
- AD-56: FHIR リソース追加は `register_bundle_builder` 経由。`_build_bundle` は編集しない。
- コード値は捏造禁止: 全 LOINC を NLM Clinical Tables (`https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms=<code>&df=LOINC_NUM,LONG_COMMON_NAME`) で照合。照合できたコードのみ採用。新規 LOINC は `codes/data/loinc.yaml` に `en` (必須) + `ja` で追加。
- ハードコード禁止: スコア閾値/重みは `nursing_scores.yaml`。FHIR system URI は `get_system_uri()`。
- 型は `clinosim/types/` のみで定義。`observation` モジュールは `types`/`codes`/`locale` のみに依存。
- コメント/docstring 英語、行長 100、ruff フォーマット、mypy strict 方針。
- US 出力は 100% 英語、JP は日本語 (`country` 分岐)。
- git: master から branch。commit 末尾に下記トレーラ (空行の後)。push/PR/merge はユーザー指示時のみ。`git add` は特定パスのみ (`git add -A` 禁止、`output/` を巻き込む)。

```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PAVRbWqciawmAyKriJFsL1
```

- venv: 各コマンド前に `source .venv/bin/activate`。

---

### Task 1: CIF 型の追加 (VitalSignRecord フィールド + NursingRiskAssessment)

**Files:**
- Modify: `clinosim/types/encounter.py` (VitalSignRecord に 2 フィールド追加; 新 dataclass NursingRiskAssessment 追加)
- Modify: `clinosim/types/output.py` (CIFPatientRecord に `nursing_risk_assessments` 追加)
- Test: `tests/unit/test_nursing.py` (新規、Task 1 では型のスモークのみ)

**Interfaces:**
- Produces: `VitalSignRecord.news2_score: int | None`, `VitalSignRecord.gcs_score: int | None`;
  `NursingRiskAssessment` dataclass (フィールドは下記); `CIFPatientRecord.nursing_risk_assessments: list`。

- [ ] **Step 1: VitalSignRecord にフィールド追加**

`clinosim/types/encounter.py` の `VitalSignRecord` (consciousness_level / pain_score が定義された dataclass) に、既存フィールド群の末尾 (デフォルト値付き) に追加:

```python
    news2_score: int | None = None  # NEWS2 aggregate (0-20), derived from this vital set
    gcs_score: int | None = None    # Glasgow Coma Scale total (3-15)
```

- [ ] **Step 2: NursingRiskAssessment dataclass を追加**

`clinosim/types/encounter.py` の `ADLAssessment` / `IntakeOutputRecord` の近くに追加 (`from datetime import date` は既存を利用、無ければ import 確認):

```python
@dataclass
class NursingRiskAssessment:
    """Daily nursing risk assessment: Braden (pressure ulcer) + Morse (fall) scales."""
    date: date = field(default_factory=date.today)
    braden_total: int = 23          # 6-23; lower = higher pressure-ulcer risk
    braden_sensory: int = 4         # 1-4
    braden_moisture: int = 4        # 1-4
    braden_activity: int = 4        # 1-4
    braden_mobility: int = 4        # 1-4
    braden_nutrition: int = 4       # 1-4
    braden_friction: int = 3        # 1-3
    morse_total: int = 0            # 0-125
    fall_risk_level: str = "low"    # "low" | "moderate" | "high"
```

- [ ] **Step 3: CIFPatientRecord に格納フィールド追加**

`clinosim/types/output.py` の `CIFPatientRecord`、`adl_assessments` の直後に:

```python
    nursing_risk_assessments: list = field(default_factory=list)  # NursingRiskAssessment
```

- [ ] **Step 4: 型のスモークテスト**

`tests/unit/test_nursing.py` を新規作成:

```python
"""Unit tests for nursing flowsheet scores."""

import pytest

pytestmark = pytest.mark.unit


def test_types_importable():
    from clinosim.types.encounter import NursingRiskAssessment, VitalSignRecord
    v = VitalSignRecord()
    assert v.news2_score is None and v.gcs_score is None
    n = NursingRiskAssessment()
    assert 6 <= n.braden_total <= 23
    assert n.fall_risk_level == "low"
```

- [ ] **Step 5: 実行 + lint**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_nursing.py -q && ruff check clinosim/types/encounter.py clinosim/types/output.py`
Expected: PASS、lint クリーン。

- [ ] **Step 6: コミット**

```bash
git add clinosim/types/encounter.py clinosim/types/output.py tests/unit/test_nursing.py
git commit  # 本文 + トレーラ
```
メッセージ: `feat(types): add NEWS2/GCS vital fields + NursingRiskAssessment (AD-55 nursing)`

---

### Task 2: スコア計算モジュール nursing.py + nursing_scores.yaml (TDD)

**Files:**
- Create: `clinosim/modules/observation/reference_data/nursing_scores.yaml`
- Create: `clinosim/modules/observation/nursing.py`
- Test: `tests/unit/test_nursing.py` (拡張)

**Interfaces:**
- Consumes: `VitalSignRecord` (Task 1)、`ADLAssessment`/`IntakeOutputRecord` (既存)、numpy Generator。
- Produces:
  - `compute_news2(vs: dict) -> int` — RR/SpO2/on_supplemental_oxygen/temp/SBP/HR/consciousness から NEWS2 (0-20)。
  - `compute_gcs(consciousness_level: str, perfusion_status: float, rng) -> int` — AVPU 基点 + 補正 (3-15)。
  - `compute_braden(adl: dict, consciousness_level: str, volume_status: float, rng) -> NursingRiskAssessment 用サブスケール辞書 + braden_total`。
  - `compute_morse_fall_risk(age: int, adl: dict, consciousness_level: str, has_iv: bool, rng) -> tuple[int, str]` — (morse_total, level)。
  関数は純粋 (rng は引数注入、グローバル状態なし)。

- [ ] **Step 1: nursing_scores.yaml を作成 (RCP NEWS2 公式集計表)**

`clinosim/modules/observation/reference_data/nursing_scores.yaml`:

```yaml
# Nursing score thresholds. Sources (authoritative, published instruments):
#   NEWS2: Royal College of Physicians, National Early Warning Score 2 (2017).
#   GCS: Teasdale & Jennett 1974. Braden: Bergstrom et al. 1987. Morse: Morse 1989.
# Aggregation tables are the published scoring rules; not fabricated.
news2:
  # Each band: [low_inclusive, high_inclusive, points]. Use null for open bounds.
  respiratory_rate:
    - [null, 8, 3]
    - [9, 11, 1]
    - [12, 20, 0]
    - [21, 24, 2]
    - [25, null, 3]
  spo2_scale1:
    - [null, 91, 3]
    - [92, 93, 2]
    - [94, 95, 1]
    - [96, null, 0]
  on_supplemental_oxygen: 2   # +2 if on supplemental O2
  temperature_celsius:
    - [null, 35.0, 3]
    - [35.1, 36.0, 1]
    - [36.1, 38.0, 0]
    - [38.1, 39.0, 1]
    - [39.1, null, 2]
  systolic_bp:
    - [null, 90, 3]
    - [91, 100, 2]
    - [101, 110, 1]
    - [111, 219, 0]
    - [220, null, 3]
  heart_rate:
    - [null, 40, 3]
    - [41, 50, 1]
    - [51, 90, 0]
    - [91, 110, 1]
    - [111, 130, 2]
    - [131, null, 3]
  consciousness:        # AVPU: A=0; V/P/U=3 (new confusion or below)
    A: 0
    V: 3
    P: 3
    U: 3
gcs:
  # AVPU → GCS total base band; perfusion/encephalopathy applies a small decrement.
  avpu_base:
    A: 15
    V: 13
    P: 9
    U: 5
  min: 3
  max: 15
braden:
  # Subscale ranges 1-4 (friction 1-3). Mapped from ADL/consciousness/volume.
  # Barthel (0-100) → activity/mobility subscale via thresholds.
  barthel_to_subscale:   # [barthel_low_inclusive, subscale_value]
    - [0, 1]
    - [25, 2]
    - [60, 3]
    - [90, 4]
morse:
  # Morse Fall Scale item weights (published).
  history_of_falling: 25
  secondary_diagnosis: 15
  ambulatory_aid: 15
  iv_access: 20
  gait_impaired: 20
  gait_weak: 10
  mental_status_forgets_limits: 15
  risk_levels:           # [score_low_inclusive, level]
    - [0, "low"]
    - [25, "moderate"]
    - [45, "high"]
```

- [ ] **Step 2: NEWS2 の失敗テストを書く (RCP 既知症例)**

`tests/unit/test_nursing.py` に追加:

```python
def test_news2_normal_is_zero():
    from clinosim.modules.observation.nursing import compute_news2
    vs = {"respiratory_rate": 16, "spo2": 98, "on_supplemental_oxygen": False,
          "temperature_celsius": 36.8, "systolic_bp": 120, "heart_rate": 70,
          "consciousness_level": "A"}
    assert compute_news2(vs) == 0


def test_news2_aggregates_known_case():
    from clinosim.modules.observation.nursing import compute_news2
    # RR 26 (+3), SpO2 92 (+2), on O2 (+2), Temp 39.2 (+2), SBP 95 (+2),
    # HR 115 (+2), AVPU A (0) = 13
    vs = {"respiratory_rate": 26, "spo2": 92, "on_supplemental_oxygen": True,
          "temperature_celsius": 39.2, "systolic_bp": 95, "heart_rate": 115,
          "consciousness_level": "A"}
    assert compute_news2(vs) == 13
```

- [ ] **Step 3: 失敗を確認**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_nursing.py -q`
Expected: FAIL (`compute_news2` 未定義 / ImportError)。

- [ ] **Step 4: nursing.py を実装**

`clinosim/modules/observation/nursing.py` を作成。YAML をロード (microbiology の `_load()` パターン参照 = モジュール相対 `reference_data/nursing_scores.yaml`、`functools.lru_cache` 等で 1 回ロード)。各関数:

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

_DATA = Path(__file__).parent / "reference_data" / "nursing_scores.yaml"


@lru_cache(maxsize=1)
def _scores() -> dict:
    with open(_DATA) as f:
        return yaml.safe_load(f) or {}


def _band_points(value, bands) -> int:
    """bands: list of [low|null, high|null, points]; inclusive bounds."""
    if value is None:
        return 0
    for low, high, pts in bands:
        if (low is None or value >= low) and (high is None or value <= high):
            return int(pts)
    return 0


def compute_news2(vs: dict) -> int:
    cfg = _scores()["news2"]
    total = 0
    total += _band_points(vs.get("respiratory_rate"), cfg["respiratory_rate"])
    total += _band_points(vs.get("spo2"), cfg["spo2_scale1"])
    if vs.get("on_supplemental_oxygen"):
        total += int(cfg["on_supplemental_oxygen"])
    total += _band_points(vs.get("temperature_celsius"), cfg["temperature_celsius"])
    total += _band_points(vs.get("systolic_bp"), cfg["systolic_bp"])
    total += _band_points(vs.get("heart_rate"), cfg["heart_rate"])
    total += int(cfg["consciousness"].get(vs.get("consciousness_level", "A"), 0))
    return min(20, total)


def compute_gcs(consciousness_level: str, perfusion_status: float,
                rng: np.random.Generator) -> int:
    cfg = _scores()["gcs"]
    base = int(cfg["avpu_base"].get(consciousness_level, 15))
    # Poor perfusion (shock/encephalopathy) nudges GCS down slightly, deterministic + small noise.
    decrement = int(round((1.0 - perfusion_status) * 2))
    jitter = int(rng.integers(0, 1, endpoint=True))  # 0 or 1, deterministic per sub-seed
    score = base - decrement - jitter
    return max(cfg["min"], min(cfg["max"], score))


def _barthel_to_subscale(barthel: int) -> int:
    table = _scores()["braden"]["barthel_to_subscale"]
    sub = 1
    for low, val in table:
        if barthel >= low:
            sub = int(val)
    return sub


def compute_braden(adl: dict, consciousness_level: str, volume_status: float,
                   rng: np.random.Generator) -> dict:
    barthel = adl.get("barthel_score", 100) if adl else 100
    activity = _barthel_to_subscale(barthel)
    mobility = _barthel_to_subscale(barthel)
    sensory = 4 if consciousness_level == "A" else 2
    # Higher volume (edema/incontinence proxy) → more moisture risk (lower subscale).
    moisture = 3 if volume_status > 0.3 else 4
    nutrition = max(1, min(4, activity + int(rng.integers(-1, 1, endpoint=True))))
    friction = 2 if barthel < 60 else 3
    total = sensory + moisture + activity + mobility + nutrition + friction
    return {
        "braden_sensory": sensory, "braden_moisture": moisture,
        "braden_activity": activity, "braden_mobility": mobility,
        "braden_nutrition": nutrition, "braden_friction": friction,
        "braden_total": max(6, min(23, total)),
    }


def compute_morse_fall_risk(age: int, adl: dict, consciousness_level: str,
                            has_iv: bool, rng: np.random.Generator) -> tuple[int, str]:
    cfg = _scores()["morse"]
    barthel = adl.get("barthel_score", 100) if adl else 100
    score = 0
    if age >= 75:
        score += cfg["history_of_falling"]
    if has_iv:
        score += cfg["iv_access"]
    if barthel < 60:
        score += cfg["gait_impaired"]
    elif barthel < 90:
        score += cfg["gait_weak"]
    if consciousness_level != "A":
        score += cfg["mental_status_forgets_limits"]
    # small deterministic jitter
    score = max(0, min(125, score + int(rng.integers(-5, 5, endpoint=True))))
    level = "low"
    for low, lvl in cfg["risk_levels"]:
        if score >= low:
            level = lvl
    return score, level
```

- [ ] **Step 5: Braden/GCS/Morse の境界テストを追加**

`tests/unit/test_nursing.py` に追加:

```python
def _rng():
    import numpy as np
    return np.random.default_rng(42)


def test_gcs_avpu_bands_in_range():
    from clinosim.modules.observation.nursing import compute_gcs
    for loc in ("A", "V", "P", "U"):
        g = compute_gcs(loc, perfusion_status=1.0, rng=_rng())
        assert 3 <= g <= 15
    assert compute_gcs("A", 1.0, _rng()) >= compute_gcs("U", 1.0, _rng())


def test_braden_total_in_range_and_monotone():
    from clinosim.modules.observation.nursing import compute_braden
    healthy = compute_braden({"barthel_score": 100}, "A", 0.0, _rng())
    frail = compute_braden({"barthel_score": 10}, "P", 0.5, _rng())
    assert 6 <= frail["braden_total"] <= healthy["braden_total"] <= 23


def test_morse_levels():
    from clinosim.modules.observation.nursing import compute_morse_fall_risk
    score, level = compute_morse_fall_risk(85, {"barthel_score": 20}, "P", True, _rng())
    assert 0 <= score <= 125 and level in ("low", "moderate", "high")


def test_deterministic_same_seed():
    import numpy as np
    from clinosim.modules.observation.nursing import compute_braden
    a = compute_braden({"barthel_score": 50}, "A", 0.0, np.random.default_rng(7))
    b = compute_braden({"barthel_score": 50}, "A", 0.0, np.random.default_rng(7))
    assert a == b
```

- [ ] **Step 6: 実行 (全緑) + lint**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_nursing.py -q && ruff check clinosim/modules/observation/nursing.py`
Expected: 全 PASS、lint クリーン。

- [ ] **Step 7: コミット**

```bash
git add clinosim/modules/observation/nursing.py clinosim/modules/observation/reference_data/nursing_scores.yaml tests/unit/test_nursing.py
git commit
```
メッセージ: `feat(observation): nursing score functions (NEWS2/GCS/Braden/Morse), data-driven`

---

### Task 3: LOINC コードの権威照合・登録

**Files:**
- Modify: `clinosim/codes/data/loinc.yaml` (照合できた看護スコア LOINC を追加)

**Interfaces:**
- Produces: `loinc.yaml` の新規キー (Task 5 の FHIR ビルダーが参照)。

- [ ] **Step 1: 候補 LOINC を NLM で照合**

各候補を NLM Clinical Tables で確認 (WebFetch 可):
`https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms=<CODE>&df=LOINC_NUM,LONG_COMMON_NAME`

確認する候補 (LONG_COMMON_NAME が一致するか検証):
- GCS total: `9269-2` (Glasgow coma scale total)
- Braden total: `38228-4` (Braden scale total score)
- Morse fall risk: NLM で "Morse fall" を検索し正式コードを特定
- Barthel index total: NLM で "Barthel" を検索 (例 `42526-6` を検証)
- NEWS / NEWS2: NLM で "NEWS" を検索 (単一集計コードが存在すれば採用、無ければ NEWS2 は
  `valueInteger` の survey Observation として LOINC を付さず `code.text="NEWS2"` で出力可 —
  ただし可能なら公式パネル/スコア LOINC を優先)
- Fluid intake total / output total: NLM で "fluid intake 24 hour" / "urine output" を検索
  (例 intake `9192-6`, output 系) し検証

**捏造禁止**: LONG_COMMON_NAME が看護スコアと明確に一致するコードのみ採用。一致しない/
見つからないものは採用せず、その旨を report に記録 (FHIR 側で LOINC 無し survey として扱う)。

- [ ] **Step 2: 照合できたコードを loinc.yaml に追加**

`clinosim/codes/data/loinc.yaml` の `codes:` 配下に、確認できた各コードを追加 (`en` 必須、
`ja` 任意)。例 (実際の照合結果に置換):

```yaml
  9269-2:
    en: "Glasgow coma score total"
    ja: "GCS 合計"
  38228-4:
    en: "Braden scale total score"
    ja: "ブレーデンスケール合計"
```

- [ ] **Step 3: codes 整合性テスト**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_codes_integrity.py -q`
Expected: PASS (重複キー無し)。

- [ ] **Step 4: コミット**

```bash
git add clinosim/codes/data/loinc.yaml
git commit
```
メッセージ: `feat(codes): add NLM-verified nursing-score LOINC codes`
(本文に各コードの LONG_COMMON_NAME 照合結果を記載)

---

### Task 4: Enricher 配線 (看護データ生成)

**Files:**
- Create: `clinosim/modules/observation/nursing_enricher.py` (enricher 本体 + サブシード)
- Modify: `clinosim/simulator/enrichers.py` (`register_builtin_enrichers` に 1 行追加)
- Test: `tests/integration/test_nursing_enricher.py` (新規)

**Interfaces:**
- Consumes: `EnricherContext` (`.records`, `.master_seed`)、Task 2 の計算関数、Task 1 の型。
- Produces: `enrich_nursing(ctx: EnricherContext) -> None` — 各 CIFPatientRecord の
  `vital_signs[*].news2_score/gcs_score` を埋め、`nursing_risk_assessments` を生成。

- [ ] **Step 1: enricher 本体を実装**

`clinosim/modules/observation/nursing_enricher.py`:

```python
"""Nursing flowsheet enricher (AD-55 Base, AD-56 post_records).

Fills NEWS2/GCS on each vital record and generates daily Braden/Morse risk
assessments. Uses a dedicated sub-seed so the main random stream is untouched.
"""

from __future__ import annotations

import hashlib

import numpy as np

from clinosim.modules.observation.nursing import (
    compute_braden, compute_gcs, compute_morse_fall_risk, compute_news2,
)
from clinosim.types.encounter import NursingRiskAssessment

_NURSING_SEED_OFFSET = 0x4E55  # "NU"


def _sub_seed(master_seed: int, key: str) -> int:
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:6], "big")
    return (int(master_seed) + _NURSING_SEED_OFFSET + h) % (2**32)


def _get(obj, name, default=None):
    """Read attr or dict key (records may be dataclasses)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enrich_nursing(ctx) -> None:
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 70) or 70)
        rng = np.random.default_rng(_sub_seed(ctx.master_seed, pid or "x"))

        # 1) NEWS2 + GCS on each vital record (NEWS2 deterministic; GCS small jitter)
        for vs in _get(rec, "vital_signs", []) or []:
            vsd = vs if isinstance(vs, dict) else vs.__dict__
            news2 = compute_news2(vsd)
            gcs = compute_gcs(vsd.get("consciousness_level", "A"),
                              perfusion_status=1.0, rng=rng)
            if isinstance(vs, dict):
                vs["news2_score"], vs["gcs_score"] = news2, gcs
            else:
                vs.news2_score, vs.gcs_score = news2, gcs

        # 2) Daily Braden + Morse from ADL (align by date) + I/O (IV present)
        adls = _get(rec, "adl_assessments", []) or []
        ios = _get(rec, "intake_output_records", []) or []
        iv_dates = {str(_get(io, "date")) for io in ios if (_get(io, "intake_iv_ml", 0) or 0) > 0}
        out = []
        for adl in adls:
            adld = adl if isinstance(adl, dict) else adl.__dict__
            d = adld.get("date")
            loc = "A"  # consciousness proxy; could be refined from same-day vitals
            braden = compute_braden(adld, loc, volume_status=0.0, rng=rng)
            morse, level = compute_morse_fall_risk(
                age, adld, loc, has_iv=str(d) in iv_dates, rng=rng)
            out.append(NursingRiskAssessment(
                date=d, morse_total=morse, fall_risk_level=level, **braden))
        if isinstance(rec, dict):
            rec["nursing_risk_assessments"] = out
        else:
            rec.nursing_risk_assessments = out
```

- [ ] **Step 2: register_builtin_enrichers に登録**

`clinosim/simulator/enrichers.py` の `register_builtin_enrichers()` 内、identity 登録の後に:

```python
    # Nursing flowsheet (AD-55 Base): NEWS2/GCS + Braden/Morse. Always-on.
    from clinosim.modules.observation.nursing_enricher import enrich_nursing

    register_enricher(
        Enricher(
            name="nursing",
            stage=POST_RECORDS,
            order=20,
            enabled=lambda c: True,
            run=enrich_nursing,
        )
    )
```

- [ ] **Step 3: integration テストを書く**

`tests/integration/test_nursing_enricher.py`:

```python
import pytest

pytestmark = pytest.mark.integration


def test_enricher_fills_nursing_data():
    import numpy as np  # noqa: F401
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.types.encounter import VitalSignRecord, ADLAssessment, IntakeOutputRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    from datetime import date

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p1", age=80),
        vital_signs=[VitalSignRecord(respiratory_rate=26, spo2=92,
                     on_supplemental_oxygen=True, temperature_celsius=39.2,
                     systolic_bp=95, heart_rate=115, consciousness_level="A")],
        adl_assessments=[ADLAssessment(date=date(2026, 1, 1), barthel_score=20)],
        intake_output_records=[IntakeOutputRecord(date=date(2026, 1, 1), intake_iv_ml=1500)],
    )
    ctx = EnricherContext(config=None, master_seed=123, records=[rec])
    enrich_nursing(ctx)

    assert rec.vital_signs[0].news2_score == 13
    assert 3 <= rec.vital_signs[0].gcs_score <= 15
    assert len(rec.nursing_risk_assessments) == 1
    nra = rec.nursing_risk_assessments[0]
    assert 6 <= nra.braden_total <= 23
    assert nra.fall_risk_level in ("low", "moderate", "high")


def test_enricher_deterministic():
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.types.encounter import VitalSignRecord, ADLAssessment
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    from datetime import date

    def build():
        return CIFPatientRecord(
            patient=PatientProfile(patient_id="p1", age=80),
            vital_signs=[VitalSignRecord(consciousness_level="A")],
            adl_assessments=[ADLAssessment(date=date(2026, 1, 1), barthel_score=50)],
        )
    r1, r2 = build(), build()
    enrich_nursing(EnricherContext(config=None, master_seed=99, records=[r1]))
    enrich_nursing(EnricherContext(config=None, master_seed=99, records=[r2]))
    assert r1.nursing_risk_assessments[0] == r2.nursing_risk_assessments[0]
```

(注: `PatientProfile` の実フィールド名 `patient_id`/`age` を実装前に `clinosim/types/patient.py`
で確認し、相違あれば合わせる。)

- [ ] **Step 4: 実行**

Run: `source .venv/bin/activate && python -m pytest tests/integration/test_nursing_enricher.py -q && ruff check clinosim/modules/observation/nursing_enricher.py clinosim/simulator/enrichers.py`
Expected: PASS、lint クリーン。

- [ ] **Step 5: コミット**

```bash
git add clinosim/modules/observation/nursing_enricher.py clinosim/simulator/enrichers.py tests/integration/test_nursing_enricher.py
git commit
```
メッセージ: `feat(simulator): register nursing flowsheet enricher (AD-56 post_records)`

---

### Task 5: FHIR nursing Observation ビルダー

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py` (`_build_nursing_observations` 追加 + `register_bundle_builder` 登録 + `_BUNDLE_BUILDERS` への組み込み)
- Test: `tests/integration/test_fhir_nursing.py` (新規)

**Interfaces:**
- Consumes: `BundleContext` (`.record` dict, `.patient_id`, `.country`, `.primary_enc_id`)、
  Task 3 の LOINC、`get_system_uri`/`lookup`。
- Produces: `_build_nursing_observations(ctx: BundleContext) -> list[dict]` — FHIR `Observation`
  (category=survey) のリスト。

- [ ] **Step 1: ビルダーを実装**

`fhir_r4_adapter.py` の `_BUNDLE_BUILDERS` 定義の近く (既存ビルダーのスタイルに合わせる) に
`_build_nursing_observations(ctx)` を追加。要件:
- `ctx.record.get("vital_signs")` を index 付き反復し、`news2_score`/`gcs_score` が非 None の
  ものを `Observation` 化 (id: `news2-{ctx.primary_enc_id}-{i}` / `gcs-{...}-{i}`、
  `category=survey`、`subject` = Patient 参照、`encounter` = `ctx.primary_enc_id` があれば付与、
  `valueInteger`、GCS は LOINC `9269-2` 等 Task 3 で確認できたコードで `code.coding` + `code.text`、
  NEWS2 は LOINC があれば付与・無ければ `code.text="NEWS2"`)。
- `ctx.record.get("nursing_risk_assessments")` を反復し、Braden (`valueInteger`=braden_total,
  LOINC `38228-4` 等) と Morse (valueInteger=morse_total, interpretation=fall_risk_level) を
  Observation 化 (id: `braden-{enc}-{i}` / `morse-{enc}-{i}`、`effectiveDateTime`=date)。
- `ctx.record.get("adl_assessments")` を反復し Barthel total を Observation 化 (LOINC 確認時)。
- `ctx.record.get("intake_output_records")` を反復し fluid intake/output total を Observation 化
  (LOINC 確認時、`valueQuantity` mL)。
- display は `lookup("loinc", code, lang)`、`lang = "ja" if ctx.country=="JP" else "en"`。
  US 出力に日本語が混入しないこと。system URI は `get_system_uri("loinc")`。
- 全 Observation の `id` はタイプ内で一意 (encounter-scoped + index)。`subject`/`encounter`
  参照は export 内で解決可能なものを使う (既存ビルダーと同じ参照形式)。

実装は既存 `_build_vital_observations` / microbiology FHIR ビルダーの構造を踏襲する
(同じ resource dict 形、同じ参照キー)。

- [ ] **Step 2: ビルダーを登録**

`_BUNDLE_BUILDERS` リスト (fhir_r4_adapter.py:846 付近) に `_build_nursing_observations` を
追加する (AD-56: `_build_bundle` は編集しない。リスト追記 or `register_bundle_builder` 呼び出し)。
既存ビルダーがリストリテラルに並んでいる形に合わせて 1 エントリ追加。

- [ ] **Step 3: integration テストを書く**

`tests/integration/test_fhir_nursing.py` — 看護データ入り CIF record (dict 形) を
`_build_nursing_observations` に渡し、検証:
- NEWS2/GCS/Braden/Morse の Observation が生成される。
- 各 `resourceType == "Observation"`、`category` に survey、`id` 一意、
  `subject.reference` が Patient を指す。
- `country="US"` で日本語文字が出力に含まれない (`assert not re.search(r'[぀-ヿ一-鿿]', json.dumps(obs))`)。
- LOINC を付したものは `code.coding[0].system == get_system_uri("loinc")` かつ
  `display != code` (display==code 禁止)。

```python
import json
import re
import pytest

pytestmark = pytest.mark.integration


def _record():
    return {
        "patient_id": "p1",
        "vital_signs": [{"consciousness_level": "A", "news2_score": 13, "gcs_score": 15,
                         "timestamp": "2026-01-01T08:00:00"}],
        "nursing_risk_assessments": [{"date": "2026-01-01", "braden_total": 14,
                                      "morse_total": 55, "fall_risk_level": "high"}],
        "adl_assessments": [{"date": "2026-01-01", "barthel_score": 40}],
        "intake_output_records": [{"date": "2026-01-01", "intake_iv_ml": 1500,
                                   "output_urine_ml": 1200}],
    }


def test_nursing_observations_us_no_japanese():
    from clinosim.modules.output.fhir_r4_adapter import (
        _build_nursing_observations, BundleContext,
    )
    # Construct BundleContext per its actual constructor (inspect fields first).
    ctx = BundleContext(record=_record(), patient_id="p1", country="US",
                        primary_enc_id="enc1")  # adjust kwargs to real signature
    obs = _build_nursing_observations(ctx)
    assert obs, "no nursing observations built"
    assert all(o["resourceType"] == "Observation" for o in obs)
    ids = [o["id"] for o in obs]
    assert len(ids) == len(set(ids)), "duplicate observation ids"
    assert not re.search(r"[぀-ヿ一-鿿]", json.dumps(obs)), "Japanese in US output"
```

(注: `BundleContext` の実コンストラクタ引数を `fhir_r4_adapter.py:594` で確認し、テストの
生成を合わせる。必要フィールドが多い場合は最小限のダミーで構築。)

- [ ] **Step 4: 実行**

Run: `source .venv/bin/activate && python -m pytest tests/integration/test_fhir_nursing.py -q && ruff check clinosim/modules/output/fhir_r4_adapter.py`
Expected: PASS、lint クリーン。

- [ ] **Step 5: コミット**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py tests/integration/test_fhir_nursing.py
git commit
```
メッセージ: `feat(output): FHIR nursing Observations (NEWS2/GCS/Braden/Morse/ADL/IO)`

---

### Task 6: CSV 出力 (nursing_risk.csv + vitals に news2/gcs 列)

**Files:**
- Modify: `clinosim/modules/output/csv_adapter.py`
- Test: `tests/integration/test_fhir_nursing.py` (CSV 観点を追記、または既存 CSV テストに追記)

**Interfaces:**
- Consumes: `nursing_risk_assessments` / `vital_signs.news2_score,gcs_score`。
- Produces: `nursing_risk.csv`、`vital_signs.csv` に 2 列追加。

- [ ] **Step 1: vitals 行に news2/gcs 列を追加**

`csv_adapter.py` の vitals 行構築箇所 (`vitals_rows.append({...})`) に
`"news2_score": vs.get("news2_score")`, `"gcs_score": vs.get("gcs_score")` を追加。

- [ ] **Step 2: nursing_risk.csv を追加**

ADL ループ (`record.get("adl_assessments")`) の近くに nursing_risk ループを追加:

```python
        for nra in record.get("nursing_risk_assessments", []):
            nursing_rows.append({
                "patient_id": patient_id,
                "date": nra.get("date"),
                "braden_total": nra.get("braden_total"),
                "morse_total": nra.get("morse_total"),
                "fall_risk_level": nra.get("fall_risk_level"),
            })
```

関数冒頭の rows リスト初期化群に `nursing_rows = []` を追加し、「Write CSVs」節に
`_write_csv(os.path.join(output_dir, "nursing_risk.csv"), nursing_rows)` を追加。

- [ ] **Step 3: スモーク確認**

Run:
```bash
source .venv/bin/activate && python -c "
from clinosim.modules.output import csv_adapter
import inspect
src = inspect.getsource(csv_adapter)
assert 'nursing_risk.csv' in src and 'news2_score' in src and 'gcs_score' in src
print('OK: csv adapter wired')
" && ruff check clinosim/modules/output/csv_adapter.py
```
Expected: `OK: csv adapter wired`、lint クリーン。

- [ ] **Step 4: コミット**

```bash
git add clinosim/modules/output/csv_adapter.py
git commit
```
メッセージ: `feat(output): CSV nursing_risk + NEWS2/GCS columns in vitals`

---

### Task 7: ドキュメント + フル回帰検証

**Files:**
- Modify: `clinosim/modules/observation/README.md` (看護フローシート節を追加)
- Modify: `TODO.md` (line 429 の nursing flowsheets を完了に、line 441 進捗反映)

- [ ] **Step 1: observation/README.md を更新**

看護フローシート機能の節を追加: 提供スコア (NEWS2/GCS/Braden/Morse)、データ駆動
(`nursing_scores.yaml`)、enricher 実行 (AD-56 post_records, 専用サブシード)、CIF 表現
(VitalSignRecord フィールド + NursingRiskAssessment)、FHIR/CSV 出力、権威出典
(RCP NEWS2 / GCS / Braden / Morse、LOINC=NLM)。

- [ ] **Step 2: TODO.md を更新**

line 429 `Nursing flowsheets` 項目を `[x]` 完了 (実装内容を 1-2 行で記述、LOINC 照合状況を
明記)。推奨順序 (line 441) の進捗を反映。

- [ ] **Step 3: コミット**

```bash
git add clinosim/modules/observation/README.md TODO.md
git commit
```
メッセージ: `docs: record nursing flowsheet feature (NEWS2/GCS/Braden/Morse)`

- [ ] **Step 4: unit + integration 全体**

Run: `source .venv/bin/activate && python -m pytest -m "unit or integration" -q`
Expected: 全 PASS (既存 259 + 新規 nursing テスト分)。

- [ ] **Step 5: e2e golden 回帰 (既存値 byte 不変 + 新データ)**

Run: `source .venv/bin/activate && python -m pytest -m e2e -q`
Expected: 全 PASS。golden に新フィールド/リソース (NEWS2/GCS/nursing_risk/nursing
Observations) が追加され、**既存の labs/vitals 数値/診断/I/O/ADL は byte 不変**。
golden ファイルの更新が必要な場合は、差分が新規看護データのみであることを確認してから
golden を再生成する (既存値の変化はバグ — 決定論サブシードの実装を見直す)。CPU 競合で稀に
途中 exit (FAILED なし) → 再実行で確認 ([[feedback_clinosim_workflow]])。

- [ ] **Step 6: 生成物の確認とユーザー報告**

ブランチに 7 コミット。全テスト緑・golden 差分が新規看護データのみであることを報告し、
push / PR 作成の可否をユーザーに確認する。

---

## Self-Review

**Spec coverage:**
- スコア計算 nursing.py + YAML (spec §設計/スコア) → Task 2。
- CIF 表現 VitalSignRecord/NursingRiskAssessment (spec §CIF 表現) → Task 1。
- Enricher 実行 + 専用サブシード決定論 (spec §アーキ/決定論) → Task 4。
- LOINC 権威照合 (spec §FHIR/受け入れ基準3) → Task 3。
- FHIR Observation (spec §FHIR 出力) → Task 5。
- CSV (spec §CSV; **訂正**: I/O CSV は既存、よって nursing_risk.csv + vitals 列のみ) → Task 6。
- ドキュメント (spec §受け入れ基準6) → Task 7。
- 既存 golden 不変 (spec §決定論/受け入れ基準4) → Task 7 Step 5。

**Placeholder scan:** TBD/TODO 無し。LOINC は「NLM 照合し一致コードのみ採用」= 具体的手順。
FHIR ビルダー (Task 5 Step 1) は要件箇条 + 既存ビルダー踏襲の指示で具体化 (巨大関数のため
逐語コードは置かず、入出力契約とスタイル参照で規定)。

**Type consistency:** `compute_news2(vs: dict) -> int`、`compute_gcs(loc, perfusion, rng) -> int`、
`compute_braden(...) -> dict`、`compute_morse_fall_risk(...) -> tuple[int,str]`、
`enrich_nursing(ctx) -> None`、`_build_nursing_observations(ctx) -> list[dict]`、
`NursingRiskAssessment` フィールド — Task 1/2/4/5 で一貫。`compute_braden` の返す辞書キーが
`NursingRiskAssessment(**braden)` の braden_* フィールドと一致 (Task 2 Step 4 ↔ Task 1 Step 2)。
```
