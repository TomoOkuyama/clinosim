"""F4 snapshot memoize (session 49):前 snapshot output を cache として利用。

大規模 population で daily cron を実現するための最重要 primitive。
前 snapshot で全 encounter が discharge 済の patient は、cursor が
進んでも bit-identical な output になる(snapshot semantics + F1
cross-cursor determinism の帰結)。この patient を simulate skip して
前 CIF から load することで、p=500k advance が数分に短縮される。

state module / cursor.json は不要。cache directory = 前 snapshot output
directory 自体(_cache_manifest.json 1 ファイルだけ併存)。
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
    """
    result: set[str] = set()
    for r in patient_records:
        pid = r.patient.patient_id
        all_completed = True
        for enc in r.encounters:
            dc = enc.discharge_datetime
            if dc is None or dc.date() > prev_cursor_date:
                all_completed = False
                break
        if all_completed:
            result.add(pid)
    return result
