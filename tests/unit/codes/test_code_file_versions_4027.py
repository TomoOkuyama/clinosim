"""Issue #4027: a code file's ``metadata.version`` names the edition of the
snapshot it is verified against, and the attribution files ship.

The version of a code file is not emitted (``clinosim.codes.loader`` stores
it on the ``CodeSystem`` and nothing reads it); it tells a reader which
edition the curated codes and displays were checked against. Each row below
pairs a code file with the snapshot in ``codes/authoritative/`` that the
display cross-check (``test_display_matches_authoritative.py``) or the
code-file test uses, and with the edition as that snapshot records it.
Code files without a snapshot (``cpt.yaml``, ``hot7.yaml``, ...) and
``icd-10.yaml`` (checked against a terminology package, ``fhir.tx.support.r4
0.37.0``, that names no ICD-10 edition) are not listed.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from clinosim.datafiles import data_metadata

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_DATA = _REPO / "clinosim" / "codes" / "data"
_SNAPSHOTS = _REPO / "clinosim" / "codes" / "authoritative"

# code file -> (snapshot file, edition written in the code file, the text of the
# snapshot metadata that records that edition)
_VERSIONED_BY_SNAPSHOT: dict[str, tuple[str, str, str]] = {
    "loinc.yaml": ("loinc_2_83_tx.json", "2.83", "LOINC 2.83"),
    "snomed-ct.yaml": ("snomed_ct_tx.json", "2025-02-01", "SNOMED CT International Edition 2025-02-01"),
    "icd-10-cm.yaml": ("icd10cm_2027_cms.json", "FY2027", "CMS ICD-10-CM FY2027"),
    "rxnorm.yaml": ("rxnorm_rxnav_snapshot.json", "RxNav 2026-10-28", "2026-10-28"),
    "yj.yaml": ("yj_medis_hot_20261031.json", "2026-10-31", "医薬品HOTコードマスター (2026-10-31)"),
    "k-codes.yaml": ("shinryo_koui_ssk_20261013_ja.json", "2026-10-13", "s_ALL20261013.csv"),
    "jlac10.yaml": ("jlac10_jslm_137.json", "137", "version 137"),
}


@pytest.mark.parametrize("code_file", sorted(_VERSIONED_BY_SNAPSHOT))
def test_code_file_version_is_the_snapshot_edition(code_file: str) -> None:
    snapshot, version, recorded = _VERSIONED_BY_SNAPSHOT[code_file]
    meta = json.loads((_SNAPSHOTS / snapshot).read_text(encoding="utf-8"))["metadata"]
    assert recorded in json.dumps(meta, ensure_ascii=False), f"{snapshot} metadata does not record {recorded!r}"
    assert str(data_metadata(_DATA / code_file).get("version")) == version, (
        f"{code_file} metadata.version must be {version!r}, the edition of {snapshot}"
    )


def test_notice_and_inventory_ship_in_the_sdist() -> None:
    include = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"]["build"][
        "targets"
    ]["sdist"]["include"]
    for name in ("NOTICE", "THIRD_PARTY_TERMINOLOGIES.md", "THIRD_PARTY_TERMINOLOGIES.ja.md"):
        assert (_REPO / name).is_file(), name
        assert name in include, f"{name} is not in the sdist include list"
