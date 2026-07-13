"""F4 snapshot memoize (session 49):前 snapshot output を cache として利用。

大規模 population で daily cron を実現するための最重要 primitive。
前 snapshot で全 encounter が discharge 済の patient は、cursor が
進んでも bit-identical な output になる(snapshot semantics + F1
cross-cursor determinism の帰結)。この patient を simulate skip して
前 CIF から load することで、p=500k advance が数分に短縮される。

state module / cursor.json は不要。cache directory = 前 snapshot output
directory 自体(_cache_manifest.json 1 ファイルだけ併存)。

Task 8 実装時に stress test(p=300〜1000、複数 seed)で確認した **既知の限界
2 件**(いずれも ``clinosim/simulator/engine.py`` の cache-hit path 挿入範囲
(admission loop のみ)を超えて ``clinosim/simulator/inpatient.py`` /
``clinosim/modules/order/engine.py`` / ``clinosim/modules/facility/hospital_state.py``
に手を入れないと根治できない — Task 8 の file scope 外のため followup backlog
とする):

1. **``_IMPLIED_CHRONIC_BY_DISEASE`` accretion**(``inpatient.py:493``)—
   `_simulate_patient` は admission の disease_id が implied-chronic table に
   あると、activate 済で patient の全 record に共有される ``PatientProfile``
   object(``engine.py`` の ``patient_cache[pid]``)の ``chronic_conditions``
   に直接 in-place append する(RNG 不使用、disease_id + sex のみに依存する
   純粋な決定論的 mutation)。cache hit は `_simulate_patient` 呼び出し自体を
   skip するため、この mutation が memo run の共有 object に反映されない。
   同一 patient の(cache hit した admission より後に処理される)他の
   record は同じ共有 object を見るため、chronic_conditions が 1 件少ない
   まま推移し、``initialize_state`` 経由で後続 admission の生理状態にまで
   波及しうる。`tests/unit/test_engine_memoize.py::test_memoize_hit_bit_identical`
   はこの class を検出したら該当 patient を丸ごと比較対象から除外する
   (``test_engine_cross_cursor.py`` note 3 と同じ pattern)。
2. **``HospitalState`` resource-queue congestion**(``clinosim/modules/order/engine.py``
   の ``calculate_result_time_from_state`` → ``hospital_state.add_to_queue``)—
   lab/imaging の result turnaround は
   ``hospital_state.lab_queue`` / ``ct_queue`` 等の**累積・共有**な congestion
   state に依存する。cache hit した admission は、その admission が生成した
   はずの lab/imaging order 分の queue 増分を一切発生させないため、
   **同一 run 内でそれ以降に処理される、無関係な(同一 patient である
   必要すらない)admission の result_datetime** が cold run と drift しうる
   (p=300〜1000 の stress test で複数 seed で再現確認済み、値そのものは
   数十分オーダーのシフト、日付/臨床内容は無傷)。1 と異なり「patient 単位
   の除外」では検出しきれない(patient をまたいで波及するため)。Task 8
   の admission-loop-only cache scope では未対応 — 根治には
   ``hospital_state`` の queue を「完全 time-based(累積依存なし)」に
   するか、cache-hit 側で該当 order 分の queue 増分を replay する設計変更が
   必要。次 task で `hospital_state.py` / `order/engine.py` を touch する
   前提の backlog として TODO.md に記載すること。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clinosim.types.config import SimulatorConfig
    from clinosim.types.output import CIFPatientRecord

_MANIFEST_FILENAME = "_cache_manifest.json"
_MANIFEST_SCHEMA_VERSION = 1


@dataclass
class CacheManifest:
    """前 snapshot の cache 情報。output directory に併存 (_cache_manifest.json)."""

    schema_version: int
    master_seed: int
    config_hash: str
    snapshot_date: str
    country: str
    population_size: int


def compute_config_hash(config: SimulatorConfig) -> str:
    """SimulatorConfig の canonical sha256 hash (snapshot_date は除外)。

    snapshot_date だけが違う config は cache 対象なので hash 一致させる。
    seed / country / population / hospital / time_range 等が変わったら
    hash が変わって cache 無効になる。

    NOTE: SimulatorConfig is a Pydantic BaseModel (not a stdlib dataclass),
    so `model_dump()` is used instead of `dataclasses.asdict()` for the
    canonical snapshot. `default=str` in `json.dumps` covers any residual
    non-JSON-native values (e.g. tuples serialize as lists already, but
    this keeps the hash robust to future field types).
    """
    d = config.model_dump()
    d.pop("snapshot_date", None)
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def write_cache_manifest(output_dir: Path, config: SimulatorConfig) -> None:
    """output directory に _cache_manifest.json を書き出す。"""
    manifest = CacheManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        master_seed=config.random_seed,
        config_hash=compute_config_hash(config),
        snapshot_date=config.snapshot_date or "",
        country=config.country,
        population_size=config.catchment_population or 0,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / _MANIFEST_FILENAME).open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)


def read_cache_manifest(cache_dir: Path) -> CacheManifest | None:
    """cache directory の manifest を読む。存在しなければ None。"""
    path = cache_dir / _MANIFEST_FILENAME
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        d = json.load(f)
    return CacheManifest(**d)


def is_cache_valid(cache_dir: Path, config: SimulatorConfig) -> tuple[bool, str]:
    """cache が現 config と互換か判定。返り値 = (valid, reason)。

    snapshot_date 以外の全て(seed / country / population / hospital / ...)
    が cache manifest と一致していれば valid。不一致は fail loud:cache
    を無視して全再走することを caller に告げる。
    """
    manifest = read_cache_manifest(cache_dir)
    if manifest is None:
        return False, f"no cache manifest at {cache_dir / _MANIFEST_FILENAME}"
    if manifest.schema_version != _MANIFEST_SCHEMA_VERSION:
        return False, (
            f"cache schema version {manifest.schema_version} != expected {_MANIFEST_SCHEMA_VERSION}"
        )
    if manifest.master_seed != config.random_seed:
        return False, (f"seed mismatch: cache={manifest.master_seed} config={config.random_seed}")
    if manifest.config_hash != compute_config_hash(config):
        return False, "config_hash mismatch (config changed since cache was written)"
    if manifest.country != config.country:
        return False, f"country mismatch: cache={manifest.country} config={config.country}"
    return True, "ok"


def eligible_patient_ids(
    patient_records: list[CIFPatientRecord],
    prev_cursor_date: date,
) -> set[str]:
    """全 encounter が prev_cursor 以前に完了した patient_id 集合。

    厳格 rule: encounter が 1 件でも in-progress (discharge_datetime = None) or
    discharge_datetime > prev_cursor だった場合は非 eligible。cursor 越えの
    可能性がある patient は full sim させる。

    Task 8 fix: a single patient_id commonly maps to MANY separate
    ``CIFPatientRecord`` entries in ``patient_records`` (one admission +
    several annual chronic-disease follow-up visits, ED visits, etc. — a
    p=300 empirical run showed ~90% of patients have 2+ records). The
    original implementation added ``pid`` to the result set independently
    per-record (``if all_completed: result.add(pid)``), so a patient with
    one *complete* record and one *in-progress* record among their several
    records would still end up in the eligible set (whichever record
    happened to be iterated last didn't matter — ``add`` is monotonic and
    nothing ever removed a pid once added). That would let the F4 cache
    substitute a patient who still has an open encounter. Aggregating
    per-pid first (any incomplete encounter anywhere disqualifies the whole
    patient) fixes this; behavior for the existing single-record-per-patient
    unit tests is unchanged.
    """
    seen: set[str] = set()
    ineligible: set[str] = set()
    for r in patient_records:
        pid = r.patient.patient_id
        seen.add(pid)
        if pid in ineligible:
            continue
        for enc in r.encounters:
            dc = enc.discharge_datetime
            if dc is None or dc.date() > prev_cursor_date:
                ineligible.add(pid)
                break
    return seen - ineligible


def _all_pids_from_cif(cif_dir: Path) -> set[str]:
    """前 CIF に存在する全 patient_id を高速 pre-scan する(dataclass 変換なし)。

    ``clinosim.modules.output.cif_reader.CIFReader`` の ``iter_patients()`` を
    single source of truth として再利用(structural CIF walk ロジックの
    重複を避ける — narrative merge は cache 用途では不要だが、CIFReader は
    narrative dir が無くても warn のみで動作を続けるので害はない)。
    """
    from clinosim.modules.output.cif_reader import CIFReader

    reader = CIFReader(str(cif_dir))
    pids: set[str] = set()
    for raw in reader.iter_patients():
        pid = (raw.get("patient") or {}).get("patient_id", "")
        if pid:
            pids.add(pid)
    return pids


def load_patient_records_from_cif(
    cif_dir: Path,
    eligible_pids: set[str],
) -> dict[str, list[CIFPatientRecord]]:
    """前 CIF から指定 patient_id の record を全件 load し、pid でグルーピングする。

    1 patient は admission / readmission / chronic follow-up (calendar) /
    ED visit 等、複数の独立した ``CIFPatientRecord`` を持ちうる(p=300 実測で
    patient の ~90% が 2 件以上)。よって ``dict[str, CIFPatientRecord]``
    (1 patient 1 record 前提)ではなく ``dict[str, list[CIFPatientRecord]]``
    でグルーピングして返す — ``eligible_patient_ids`` が同一 patient の
    全 record を横断して completeness を判定できるようにするため。

    Deserialization は ``pydantic.TypeAdapter(CIFPatientRecord)`` を使う。
    ``CIFPatientRecord`` は stdlib dataclass だが pydantic v2 は dataclass も
    validate 可能(ネストした dataclass / Enum / date / datetime を含め、
    JSON → 元の型へ正しく復元することを p=200 の実データで検証済 —
    唯一 ``extensions: dict[str, Any]`` フィールドだけは型情報が無いため
    module 側が書いた dataclass(例: ImagingStudyRecord)が生の dict の
    ままになる。これは既存の AD-55/56 dual-access 規約
    (``clinosim/modules/_shared.py:get_attr_or_key`` / ``_o()`` helper)が
    前提とする状態そのもの — CIF を disk から読む経路(FHIR adapter 等)は
    元々 extensions を dict として扱っている)。
    """
    if not eligible_pids:
        return {}

    from pydantic import TypeAdapter

    from clinosim.modules.output.cif_reader import CIFReader
    from clinosim.types.output import CIFPatientRecord

    ta: TypeAdapter[CIFPatientRecord] = TypeAdapter(CIFPatientRecord)
    reader = CIFReader(str(cif_dir))
    result: dict[str, list[CIFPatientRecord]] = {}
    for raw in reader.iter_patients():
        pid = (raw.get("patient") or {}).get("patient_id", "")
        if pid not in eligible_pids:
            continue
        record = ta.validate_python(raw)
        result.setdefault(pid, []).append(record)
    return result
