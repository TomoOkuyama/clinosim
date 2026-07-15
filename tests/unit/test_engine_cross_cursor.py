"""F1 core invariant: cursor A と cursor B の共有区間 record が bytewise 一致。

現行(F1 未実装)では master RNG 消費量が snapshot_date で変わるため、
同 patient X の同 event でも cursor A と B で違う結果が出る。F1 実装後は
一致する。この test は F1 実装完了時に PASS するように書き、実装前は FAIL。

Note (実装 + stress-test 中に判明した補正、brief 原案からの deviation。
p=200/1-month-gap という brief の既定 config ではどれも顕在化しないが、より大きい
population / cursor 差分だと再現する。20+ seed × 3 population regime(US/JP 含む)
で確認済み。note 4 は本 test の記述ではなく production code 側の fix だが、
この test で発見したので合わせて記録する):

1. **encounter_id を join key に使う**: 1 patient が複数 record(post-discharge /
   chronic_followup 等)を持ちうるため、``{patient_id: record}`` で dict 化すると
   cursor ごとに件数が異なる場合「両者の最後の record」が別々の論理訪問を指してしまい
   偽陽性の drift になる。encounter_id は F1 実装で hash 由来の決定論的値になった
   (``clinosim/modules/encounter/engine.py:_encounter_id_suffix``)ので、これを
   join key にすることで同一 encounter 同士を正しく対応付ける。
2. **``immunizations`` field は比較から除外**: ``modules/immunization/enricher.py``
   の POST_RECORDS enricher は ``ctx.config.snapshot_date`` を「as of」参照日として
   直接使い、ワクチン接種歴をその日付基準で逆算生成する(RNG stream 自体は per-patient
   sub-seed で cursor 非依存だが、生成ロジックの入力そのものが snapshot_date)。これは
   AD-32 と同種の by-design な cursor 依存であり、Task 2 の brief が明記する
   "POST_POPULATION / POST_RECORDS の enricher 呼び出しは変更しない" のスコープ外。
   F1 が保証するのは run_beta 内 4 phase(life event / hospital main loop /
   readmission / outpatient calendar + ED)の RNG 由来コンテンツの cross-cursor
   安定性であり、POST_RECORDS enricher の意図的な snapshot 依存出力ではない。
3. **patient snapshot が cursor 間で異なる患者は比較から除外**: ``population``
   モジュールの ``PersonRecord``(``chronic_conditions`` 等)は P1(月次 life event)
   〜 P3(readmission)の間、mutable state として直接書き換えられる
   (``_deactivate_to_layer1``)。cursor B が cursor A より長い window を持つ場合、
   B だけに存在する「A の cutoff より後の」admission が、その discharge 診断を
   person.chronic_conditions に確定的に(F1 sub-seed 由来で)追加する。この
   mutation は ``_activate_cached`` の patient snapshot 生成、および
   ``generate_healthcare_calendar`` の慢性疾患判定の両方が読む「現在の」
   person state に反映されるため、**A の cutoff より前の日付の record**
   (encounter 自体は完全に共有区間内)であっても、その patient の
   snapshot や慢性疾患カレンダー scheduling が cursor 間で変わりうる
   (実際に大 population stress test で観測: ある patient の
   Jan-Aug の 8 件の chronic_followup 訪問が、B にのみ存在する Oct
   admission の影響で B 側で 0 件になるケースを確認)。
   これは F1 の phase-RNG sub-seed 化とは独立した、person state が
   「時点 X の状態」でなく「シミュレーション完了後の最終状態」を反映して
   しまうという、より深い pre-existing の設計課題(population/patient
   モジュールの mutable-state モデル全体に関わる)であり、Task 2 の
   スコープ(4 phase の RNG 派生方法)を大きく超える。挙動そのものは
   確認済みだが、修正は別 chain の backlog とする — 本 test では、
   その patient の *どの* record が影響を受けるか個別に特定するのではなく、
   「A/B 間で patient snapshot が異なる患者」を丸ごと比較対象から除外する
   ことで、F1 が実際に保証する RNG-stream 由来のコンテンツ安定性だけを
   検証する。
4. **production fix (test 対象外)**: 上記 stress-test 中に 2 件の実害バグを
   発見し、この Task 2 の中で修正済み(いずれも「shared/sequential な状態が
   無関係な entity 間に漏れる」という F1 と同じ defect class):
   (a) ``clinosim/modules/population/engine.py:generate_healthcare_calendar``
   が全 population を単一の ``rng`` で順次消費していたため、ある 1 patient
   の chronic_conditions 差分(note 3)が population 内の**別の**patient の
   カレンダー scheduling まで巻き込んで変えてしまっていた(大 population
   stress test で発見)。``rng.spawn(n)`` で patient ごとに独立した
   sub-stream を割り当てる方式に変更。
   (b) ``clinosim/modules/encounter/engine.py:_encounter_id_suffix`` の
   6-digit hash suffix が同一 patient 内で真の衝突を起こしうることを
   p=500 の stress test で実際に確認(2 つの chronic_visit が異なる日でも
   6-digit の空間内で衝突)。12-digit に拡張。合わせて、
   ``generate_healthcare_calendar`` が発行する
   annual/colonoscopy/mammography の 3 種の screening が全部
   ``event_type="health_screening"`` を共有し、かつ engine.py の P4
   dispatch が visit_reason を screening 種別によらず
   "Annual health screening" に固定していたため、同日に 2 screening が
   重なると (patient, time, complaint) が完全一致する真の重複 encounter
   になっていた(hash 空間の確率的衝突ではなく、5 つの hash 入力全てが
   本当に同一値になるケース)。ev_key に disease_id を追加 + screening
   種別ごとの visit_reason に修正。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.mark.unit
def test_cross_cursor_shared_window_byte_identical():
    """F1 core: cursor A の全 record が cursor B の共有区間と bit-identical。"""
    config_a = SimulatorConfig(
        random_seed=42,
        catchment_population=200,
        country="US",
        time_range=("2025-01", "2026-01"),
        snapshot_date="2025-06-30",
    )
    # SimulatorConfig is a Pydantic BaseModel, not a stdlib dataclass — use
    # model_copy (dataclasses.replace raises TypeError on Pydantic models).
    config_b = config_a.model_copy(update={"snapshot_date": "2025-07-31"})

    ds_a = run_beta(config_a)
    ds_b = run_beta(config_b)

    # A に居た全 patient は B にも同一 patient_id で存在
    a_by_pid = {r.patient.patient_id: r for r in ds_a.patients}
    b_by_pid = {r.patient.patient_id: r for r in ds_b.patients}
    assert set(a_by_pid.keys()) <= set(b_by_pid.keys()), "cursor B is missing patients present in cursor A"

    # 「patient snapshot が A/B で異なる患者」を丸ごと除外(note 3 参照)。
    # `_activate_cached` は patient ごとに 1 回だけ snapshot するので、同一
    # cursor 内であればどの record の `.patient` を見ても同じ値になる —
    # よって各患者の最初の record だけを比較すれば十分。
    accretion_affected_pids = {pid for pid, a_rec in a_by_pid.items() if a_rec.patient != b_by_pid[pid].patient}

    # cursor A の各 encounter(record)を encounter_id で cursor B と対応付けて比較
    # (patient_id だけで対応付けると複数 record を持つ患者で誤対応する — note 1 参照)
    b_by_enc = {r.encounters[0].encounter_id: r for r in ds_b.patients if r.encounters}

    checked = 0
    for a_rec in ds_a.patients:
        if not a_rec.encounters:
            continue
        if a_rec.patient.patient_id in accretion_affected_pids:
            continue
        enc = a_rec.encounters[0]
        # A の encounter が discharge_datetime <= 2025-06-30 で完了している場合だけ
        # 厳格 assert(cursor 越えの in-progress は F1 単独では保証しない)
        if enc.discharge_datetime is None or enc.discharge_datetime.date() > date(2025, 6, 30):
            continue
        enc_id = enc.encounter_id
        assert enc_id in b_by_enc, (
            f"encounter {enc_id} (patient {a_rec.patient.patient_id}) present in cursor A but missing in cursor B"
        )
        b_rec = b_by_enc[enc_id]
        # immunizations は POST_RECORDS enricher が snapshot_date を as-of 参照日と
        # して直接使うため意図的に cursor 依存(note 2 参照)— 比較から除外
        a_cmp = replace(a_rec, immunizations=[])
        b_cmp = replace(b_rec, immunizations=[])
        assert a_cmp == b_cmp, f"cross-cursor drift for encounter {enc_id}"
        checked += 1

    assert checked > 0, "no completed shared-window encounters were compared — test is vacuous"
