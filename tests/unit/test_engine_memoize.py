"""F4 memoize test: cache manifest / eligibility / hit / miss / staleness。

Task 8 で追加した ``test_memoize_hit_bit_identical`` / ``test_memoize_hit_ratio_realistic``
は ``run_beta`` を複数回(p=100/p=500)呼ぶため ``@pytest.mark.integration`` を付与する。
pytest はマーカーを加算するだけで module-level ``pytestmark`` を個別 test だけ打ち消す
ことができないため、この module は module-level ``pytestmark`` を使わず、全 test に
``@pytest.mark.unit`` / ``@pytest.mark.integration`` を個別 decorator で付与する
(brief 原案は module-level `pytestmark = pytest.mark.unit` のままだったが、それだと
`pytest -m unit` にも重い 2 test が混入し unit suite <30s の budget を壊すための
adaptation)。
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path

import pytest

from clinosim.simulator.memoize import (
    CacheManifest,
    compute_config_hash,
    eligible_patient_ids,
    is_cache_valid,
    read_cache_manifest,
    write_cache_manifest,
)
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFDataset, CIFPatientRecord
from clinosim.types.patient import PatientProfile


@pytest.mark.unit
def test_config_hash_stable():
    """同 config → 同 hash。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    assert compute_config_hash(c1) == compute_config_hash(c2)


@pytest.mark.unit
def test_config_hash_ignores_snapshot_date():
    """snapshot_date が変わっても hash は同一(cache は cursor 越えで使うため)。"""
    c1 = SimulatorConfig(
        random_seed=42, catchment_population=200, country="US", snapshot_date="2026-05-31"
    )
    c2 = c1.model_copy(update={"snapshot_date": "2026-06-01"})
    assert compute_config_hash(c1) == compute_config_hash(c2)


@pytest.mark.unit
def test_config_hash_detects_seed_change():
    """seed が違えば hash 変わる。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = c1.model_copy(update={"random_seed": 43})
    assert compute_config_hash(c1) != compute_config_hash(c2)


@pytest.mark.unit
def test_config_hash_detects_country_change():
    """country が違えば hash 変わる。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = c1.model_copy(update={"country": "JP"})
    assert compute_config_hash(c1) != compute_config_hash(c2)


@pytest.mark.unit
def test_write_and_read_manifest(tmp_path):
    config = SimulatorConfig(
        random_seed=42, catchment_population=200, country="US", snapshot_date="2026-05-31"
    )
    write_cache_manifest(tmp_path, config)
    manifest = read_cache_manifest(tmp_path)
    assert manifest is not None
    assert isinstance(manifest, CacheManifest)
    assert manifest.master_seed == 42
    assert manifest.country == "US"
    assert manifest.snapshot_date == "2026-05-31"


@pytest.mark.unit
def test_read_manifest_absent_returns_none(tmp_path):
    assert read_cache_manifest(tmp_path) is None


@pytest.mark.unit
def test_is_cache_valid_happy_path(tmp_path):
    config = SimulatorConfig(
        random_seed=42, catchment_population=200, country="US", snapshot_date="2026-05-31"
    )
    write_cache_manifest(tmp_path, config)
    # cursor だけ進めた
    new_config = config.model_copy(update={"snapshot_date": "2026-06-01"})
    valid, reason = is_cache_valid(tmp_path, new_config)
    assert valid, reason


@pytest.mark.unit
def test_is_cache_valid_seed_mismatch(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    write_cache_manifest(tmp_path, config)
    new_config = config.model_copy(update={"random_seed": 99})
    valid, reason = is_cache_valid(tmp_path, new_config)
    assert not valid
    assert "seed" in reason.lower()


@pytest.mark.unit
def test_is_cache_valid_missing_manifest(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    valid, reason = is_cache_valid(tmp_path, config)
    assert not valid
    assert "manifest" in reason.lower() or "no cache" in reason.lower()


@pytest.mark.unit
def test_eligible_patient_ids_all_completed():
    """全 encounter が prev_cursor 以前に discharge 済 → eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 5, 1),
        discharge_datetime=datetime(2025, 5, 10),
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == {"p1"}


@pytest.mark.unit
def test_eligible_patient_ids_in_progress_excluded():
    """discharge_datetime = None (in-progress) → not eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 6, 25),
        discharge_datetime=None,  # in-progress
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == set()


@pytest.mark.unit
def test_eligible_patient_ids_discharge_past_cursor_excluded():
    """discharge_datetime > prev_cursor → not eligible(cursor 越え)。"""
    patient = PatientProfile(patient_id="p1")
    enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 6, 25),
        discharge_datetime=datetime(2025, 7, 5),  # > cursor 2025-06-30
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == set()


@pytest.mark.unit
def test_eligible_patient_ids_multiple_records_any_incomplete_excludes():
    """Task 8 regression: 1 patient が複数 record を持つ場合、そのうち 1 件でも
    in-progress なら patient 全体が non-eligible(元実装は record 単位で
    ``result.add(pid)`` していたため、この patient が誤って eligible に
    なるバグがあった — production では patient の ~90% が 2 件以上の record
    を持つ(admission + 複数の chronic_visit / ED visit 等)ため必須の fix)。
    """
    patient = PatientProfile(patient_id="p1")
    completed_enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 5, 1),
        discharge_datetime=datetime(2025, 5, 10),
    )
    in_progress_enc = Encounter(
        encounter_id="e2",
        patient_id="p1",
        encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=datetime(2025, 6, 28),
        discharge_datetime=None,  # in-progress
    )
    r1 = CIFPatientRecord(patient=patient, encounters=[completed_enc])
    r2 = CIFPatientRecord(patient=patient, encounters=[in_progress_enc])
    # 順序に依らないことも確認(bug は "最後に処理された record" 次第で結果が
    # 変わっていたわけではなく、恒常的に混入していた)
    assert eligible_patient_ids([r1, r2], date(2025, 6, 30)) == set()
    assert eligible_patient_ids([r2, r1], date(2025, 6, 30)) == set()


@pytest.mark.unit
def test_eligible_patient_ids_multiple_records_all_completed_includes():
    """1 patient の複数 record が全て completed なら eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc1 = Encounter(
        encounter_id="e1", patient_id="p1", encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 5, 1), discharge_datetime=datetime(2025, 5, 10),
    )
    enc2 = Encounter(
        encounter_id="e2", patient_id="p1", encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=datetime(2025, 6, 1), discharge_datetime=datetime(2025, 6, 1),
    )
    r1 = CIFPatientRecord(patient=patient, encounters=[enc1])
    r2 = CIFPatientRecord(patient=patient, encounters=[enc2])
    assert eligible_patient_ids([r1, r2], date(2025, 6, 30)) == {"p1"}


def _save_ds_as_cache(ds: CIFDataset, cache_dir: Path, config: SimulatorConfig) -> None:
    """CIF + _cache_manifest.json を cache_dir に書き出す helper (F4 test 用)。"""
    from clinosim.modules.output.cif_writer import write_cif

    cif_dir = cache_dir / "cif"
    write_cif(ds, str(cif_dir))
    write_cache_manifest(cache_dir, config)


def _canonical_cmp(rec: CIFPatientRecord) -> object:
    """CIFPatientRecord → canonical JSON-native dict for content-equality comparison.

    Mirrors ``tests/unit/test_engine_cross_cursor.py``'s F1 invariant test
    adaptations:

    1. ``immunizations`` is excluded (``dataclasses.replace(rec,
       immunizations=[])``) — the POST_RECORDS immunization enricher derives
       content directly from ``config.snapshot_date`` as an as-of reference
       date (AD-32-style, by-design), not purely from a per-patient RNG
       sub-seed, so it is out of scope for a cache/RNG-determinism invariant.
    2. The whole record is then round-tripped through the exact JSON
       encoding ``cif_writer.write_cif`` uses (``_CIFEncoder``) and reloaded,
       instead of comparing raw dataclass instances with ``==``. A cache-hit
       record has been loaded back from JSON via
       ``pydantic.TypeAdapter(CIFPatientRecord)`` (Task 8's
       ``load_patient_records_from_cif``), which faithfully reconstructs
       every *typed* field but leaves ``extensions: dict[str, Any]`` as
       plain dicts (no static type to validate module-written dataclasses
       like ``ImagingStudyRecord`` against — confirmed empirically against a
       p=200 production run: the ONLY field that differs after a JSON
       round-trip is ``extensions``). A freshly-simulated record's
       ``extensions`` still holds the original dataclass instances. Raw
       ``==`` would therefore report a false-positive "drift" purely from
       this representation difference (dict vs. dataclass), which is
       expected and by-design per the existing AD-55/56 dual-access
       convention (``clinosim/modules/_shared.py:get_attr_or_key`` / the
       ``_o()`` helper) — CIF read from disk always presents extensions as
       dicts. Normalizing both sides to the same canonical JSON form isolates
       genuine content drift from this expected representation gap.
    """
    from clinosim.modules.output.cif_writer import _CIFEncoder

    normalized = replace(rec, immunizations=[])
    return json.loads(json.dumps(asdict(normalized), cls=_CIFEncoder, sort_keys=True))


@pytest.mark.integration
def test_memoize_hit_bit_identical(tmp_path):
    """F4 core: eligible (cursor A で全 encounter 完了済) patient の record が、
    cursor B を cache 経由で生成した場合と cold(cache_dir=None)で生成した場合とで
    content-identical になる。

    F1 の cross-cursor determinism (per-event sub-seed) が正しく働いていれば、
    cache から load した record も、同じ event を再度 simulate した record も
    同一内容になるはず — 比較方法は ``_canonical_cmp`` の docstring 参照。

    Note (stress-test 中に判明した real finding — p=100/seed=42/1 か月 advance
    という本 test の既定 config では顕在化しないが、より大きい population/cursor
    差分(p=600/seed=123/2 か月 advance で確認)だと再現する。
    ``test_engine_cross_cursor.py`` note 3 と同じ defect class の、cache-hit 版:

    ``clinosim/simulator/inpatient.py:493`` (``_simulate_patient`` 内)は、
    admission の ``disease_id`` が ``_IMPLIED_CHRONIC_BY_DISEASE`` にあると
    (acute_mi → I25 等)、**activate 済で全 record に共有される** ``patient``
    object(``engine.py`` の ``patient_cache[pid]``、Layer 2 ``PatientProfile``)
    の ``chronic_conditions`` list に直接 in-place append する(RNG 不使用、
    disease_id + sex のみに依存する純粋な決定論的 mutation)。cache hit は
    ``_simulate_patient`` 呼び出し自体をまるごと skip するため、この mutation
    が memo run の ``patient_cache[pid]`` には一切反映されない。同一 patient の
    「cache hit した admission より後に処理される」他の record(chronic_followup
    calendar 訪問、後続 admission 等)は同じ共有 ``patient`` object を参照する
    ため、memo run 側だけ chronic_conditions が 1 件少ないまま推移し、
    ``initialize_state(patient.physiological_profile, patient.chronic_conditions, ...)``
    経由で後続 admission の生理状態にまで波及しうる。

    Task 8 の file scope(``engine.py`` / ``memoize.py`` / ``cli.py`` / test の
    み)では ``inpatient.py`` を触れないため、正しい fix(``_IMPLIED_CHRONIC_BY_DISEASE``
    + 適用ロジックを ``_simulate_patient`` と cache-hit path の両方から呼べる
    純関数として抽出)は別 task の backlog とする。ここでは
    ``test_engine_cross_cursor.py`` の "accretion_affected_pids" と全く同じ
    パターン(該当 patient を丸ごと比較対象から除外)を踏襲し、F4 が実際に
    保証する「cache-hit した admission 自体の record 内容」と「その他大多数の
    patient の全 record」の content stability だけを検証する。

    ★ もう 1 件、stress test で確認した別 class の既知の限界がある
    (``clinosim/simulator/memoize.py`` module docstring 参照): cache hit した
    admission は自身が発生させたはずの lab/imaging queue 増分
    (``clinosim/modules/order/engine.py:calculate_result_time_from_state`` →
    ``hospital_state.add_to_queue``)を発生させないため、**同一 run 内で
    それ以降に処理される、無関係な admission の result_datetime** が drift
    しうる(patient 単位の除外では検出できない、cross-patient に波及する
    class)。この test の既定 config(p=100/seed=42/1 か月 advance、cache hit
    わずか 2 件)では顕在化しないため追加の除外ロジックは入れていないが、
    より大きい population/cache-hit 数だと再現しうる(p=800/seed=55 で確認)。
    根治は ``order/engine.py`` / ``hospital_state.py`` を touch する別 task。
    """
    from clinosim.simulator.engine import run_beta

    config = SimulatorConfig(
        random_seed=42, catchment_population=100, country="US",
        time_range=("2025-01", "2026-01"), snapshot_date="2025-06-30",
    )
    ds_a = run_beta(config)

    cache_dir = tmp_path / "snap_a"
    _save_ds_as_cache(ds_a, cache_dir, config)

    config_b = config.model_copy(update={"snapshot_date": "2025-07-31"})
    ds_b_cold = run_beta(config_b, cache_dir=None)
    ds_b_memo = run_beta(config_b, cache_dir=cache_dir)

    eligible = eligible_patient_ids(ds_a.patients, date(2025, 6, 30))
    assert eligible, "no eligible patients at cursor A — test is vacuous"

    # encounter_id で join する(patient_id だけで dict 化すると、1 patient が複数
    # record を持つ場合に「たまたま最後に処理された record」同士を比較してしまい
    # 偽陽性/偽陰性になる — test_engine_cross_cursor.py note 1 と同じ理由)。
    cold_by_enc = {r.encounters[0].encounter_id: r for r in ds_b_cold.patients if r.encounters}
    memo_by_enc = {r.encounters[0].encounter_id: r for r in ds_b_memo.patients if r.encounters}

    # "_IMPLIED_CHRONIC_BY_DISEASE" accretion(上記 docstring 参照)で patient
    # snapshot が食い違う患者を丸ごと除外(test_engine_cross_cursor.py note 3
    # と同じパターン)。detection は「memo run 内で同一 patient_id の
    # ``.patient.chronic_conditions`` fingerprint が複数種類存在するか」で行う
    # ——単純に cold/memo それぞれの「最初に見つかった 1 件」を比較する方式は
    # 誤検出する: cache-hit した admission 自体の ``.patient`` は cursor A から
    # そのまま複製された値(5 codes)で cold 側の同 admission とも一致してしまう
    # ため、"最初の record" 同士は一致していても、memo run の**他の**
    # record(``patient_cache[pid]`` を参照する、cache-hit していない record)は
    # 別 object(4 codes)を指しており、そちらは cold と食い違う。1 run が
    # 正しく機能していれば同一 patient の全 record は同一 ``.patient`` object
    # を共有するはずなので、fingerprint が 2 種類以上ある時点で「この patient は
    # memo run 内で内部不整合(=accretion 発生)」と確定できる。
    def _chronic_fingerprints_by_pid(ds: CIFDataset) -> dict[str, set[tuple[str, ...]]]:
        result: dict[str, set[tuple[str, ...]]] = {}
        for r in ds.patients:
            pid = r.patient.patient_id
            fp = tuple(sorted(c.code for c in r.patient.chronic_conditions))
            result.setdefault(pid, set()).add(fp)
        return result

    memo_fingerprints = _chronic_fingerprints_by_pid(ds_b_memo)
    accretion_affected_pids = {
        pid for pid in eligible
        if pid in memo_fingerprints and len(memo_fingerprints[pid]) > 1
    }

    checked = 0
    for enc_id, memo_rec in memo_by_enc.items():
        pid = memo_rec.patient.patient_id
        if pid not in eligible or pid in accretion_affected_pids:
            continue
        assert enc_id in cold_by_enc, (
            f"encounter {enc_id} (eligible patient {pid}) present in memo run "
            f"but missing from cold run"
        )
        cold_rec = cold_by_enc[enc_id]
        assert _canonical_cmp(cold_rec) == _canonical_cmp(memo_rec), (
            f"F4 memoize drift for encounter {enc_id}"
        )
        checked += 1

    assert checked > 0, "no eligible-patient encounters were compared — test is vacuous"


@pytest.mark.unit
def test_memoize_config_change_invalidates(tmp_path):
    """F4 safety: seed 変化で cache 無効化 → fail loud で用途 caller に伝える。"""
    from clinosim.simulator.engine import run_beta

    config = SimulatorConfig(random_seed=42, catchment_population=30, country="US")
    ds = run_beta(config)
    cache_dir = tmp_path / "snap"
    _save_ds_as_cache(ds, cache_dir, config)

    # seed が変わったら cache は無効 → 全再走(warning message は stdout に出る)
    config_new = config.model_copy(update={"random_seed": 99, "snapshot_date": "2025-07-31"})
    ds_new = run_beta(config_new, cache_dir=cache_dir)
    # 全再走なので ds は seed=99 の結果で、とにかく走ればよい(dropout せず)
    assert ds_new is not None
    assert ds_new.metadata.random_seed == 99


@pytest.mark.integration
def test_memoize_hit_ratio_realistic(tmp_path):
    """F4 performance: cursor 1 か月 advance で過半数の patient が hit。"""
    from clinosim.simulator.engine import run_beta

    config = SimulatorConfig(
        random_seed=42, catchment_population=500, country="US",
        time_range=("2025-01", "2026-01"), snapshot_date="2025-06-30",
    )
    ds_a = run_beta(config)
    cache_dir = tmp_path / "snap_a"
    _save_ds_as_cache(ds_a, cache_dir, config)

    eligible = eligible_patient_ids(ds_a.patients, date(2025, 6, 30))
    distinct_patients = {r.patient.patient_id for r in ds_a.patients}
    hit_ratio = len(eligible) / max(1, len(distinct_patients))
    # cursor がまだ 6 か月分しかない小 population だが、少なくとも過半数は
    # 完了しているはず
    assert hit_ratio >= 0.5, f"hit_ratio too low: {hit_ratio:.2%}"
