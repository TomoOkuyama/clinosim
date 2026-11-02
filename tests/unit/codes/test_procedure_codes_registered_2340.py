"""Every emitted procedure code is registered, and every JP code is the
支払基金 診療行為マスター code its display names (Issue #2340)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import clinosim
from clinosim.codes.procedures import bedside_procedures
from clinosim.datafiles import load_data_yaml
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_KCODES = load_data_yaml(_ROOT / "codes/data/k-codes.yaml")["codes"]
_CPT = load_data_yaml(_ROOT / "codes/data/cpt.yaml")["codes"]
_MASTER = json.loads((_ROOT / "codes/authoritative/shinryo_koui_ssk_20261013_ja.json").read_text(encoding="utf-8"))[
    "codes"
]


def _yaml(rel: str) -> dict:
    return load_data_yaml(_ROOT / rel)


# 区分 headings of the 点数表 that no master row starts with (the rows name
# the individual items).
_KUBUN_HEADINGS = {"K920": "輸血", "E001": "写真診断", "E200": "コンピューター断層撮影（ＣＴ撮影）"}


@pytest.mark.parametrize("code", sorted(_KCODES))
def test_jp_display_is_the_master_name(code: str) -> None:
    """The ``ja`` display is a master name for the code, or (a 区分-level code)
    the name its master rows start with."""
    ja = _KCODES[code]["ja"]
    if _KUBUN_HEADINGS.get(code) == ja:
        return
    names = _MASTER.get(code)
    assert names, f"{code} is not a code in the 支払基金 master"
    assert any(n == ja or n.startswith(ja) for n in names), (code, ja, names)


def _emitted_codes() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for e in bedside_procedures():
        out |= {("US", str(e.get("cpt") or "")), ("JP", str(e.get("k_code") or ""))}
    for country in ("us", "jp"):
        for code in _yaml(f"locale/{country}/code_mapping_procedure.yaml").values():
            out.add((country.upper(), str(code)))
    peri = _yaml("locale/shared/perinatal.yaml")
    for proc in (peri["procedure"], peri["cesarean"]["procedure"], peri["abortion"]["procedure"]):
        out |= {("US", str(proc.get("us_code") or "")), ("JP", str(proc.get("jp_code") or ""))}
    chemo = _yaml("locale/shared/chemo_regimens.yaml")["procedure"]
    out |= {("US", str(chemo["us_code"])), ("JP", str(chemo["jp_code"]))}
    for path in (_ROOT / "modules/disease/reference_data").glob("*.yaml"):

        def walk(x: object) -> None:
            if isinstance(x, dict):
                for key, country in (("procedure_code_us", "US"), ("procedure_code_jp", "JP")):
                    if isinstance(x.get(key), str):
                        out.add((country, x[key]))
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(load_data_yaml(path))
    # Imaging and chronic follow-up (Issue #2390).
    sites = _yaml("modules/imaging/reference_data/body_sites.yaml")

    def walk_sites(x: object) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("cpt"), str):
                out.add(("US", x["cpt"]))
            if isinstance(x.get("jp_k_code"), str):
                out.add(("JP", x["jp_k_code"]))
            for v in x.values():
                walk_sites(v)

    walk_sites(sites)
    followup = _yaml("locale/shared/chronic_followup.yaml")

    def walk_followup(x: object) -> None:
        if isinstance(x, dict):
            for key, country in (("code", "US"), ("us_code", "US"), ("jp_code", "JP")):
                if isinstance(x.get(key), str) and x.get(key):
                    out.add((country, x[key]))
            for v in x.values():
                walk_followup(v)
        elif isinstance(x, list):
            for v in x:
                walk_followup(v)

    walk_followup(followup)
    return {(c, code) for c, code in out if code}


def test_every_emitted_procedure_code_is_registered() -> None:
    missing = sorted(
        (country, code) for country, code in _emitted_codes() if code not in (_KCODES if country == "JP" else _CPT)
    )
    assert not missing, missing


@pytest.mark.parametrize(
    ("proc_type", "jp", "us"),
    [
        ("urinary_catheter", "J063", "51702"),  # D002 is urine sediment
        ("lumbar_puncture", "D403", "62270"),
        ("thoracentesis", "J008", "32555"),
        ("paracentesis", "J010", "49083"),
        ("chest_tube", "J019", "32551"),
        ("arterial_line", "D225", "36620"),
        ("nasogastric_tube", "J034-2", "43752"),  # J034 is the ileus long tube
        ("ileus_tube_placement", "J034", "44500"),
        ("cardioversion", "J047", "92960"),  # K599 is ICD implantation
        ("ecg_12lead", "D208", "93000"),
        ("short_arm_splint", "J122", "29125"),  # 29075 is a cast
        ("craniotomy_hematoma_evacuation", "K1643", "61313"),
        ("iv_line", "", "36000"),
        ("oxygen_therapy", "J024", ""),
    ],
)
def test_catalog_codes(proc_type: str, jp: str, us: str) -> None:
    entry = next(e for e in bedside_procedures() if e["type"] == proc_type)
    assert (str(entry.get("k_code") or ""), str(entry.get("cpt") or "")) == (jp, us)


def test_uncoded_jp_delivery_has_no_empty_coding() -> None:
    """正常分娩 has no K-code: the JP Procedure carries the CPT coding and a
    Japanese text, never ``code: ""``."""
    proc = {
        "procedure_type": "delivery",
        "procedure_id": "p1",
        "encounter_id": "e1",
        "procedure_code": "",
        "procedure_code_jp": "",
        "procedure_code_us": "59400",
    }
    res = _build_procedure(proc, "pt1", 0, "JP")
    codings = res["code"]["coding"]
    assert all(c["code"] for c in codings)
    assert [c["code"] for c in codings if c["system"] == "http://www.ama-assn.org/go/cpt"] == ["59400"]
    assert res["code"]["text"] == _CPT["59400"]["ja"]


def test_jp_procedure_without_a_k_code_is_recorded_and_emitted_without_an_empty_code() -> None:
    """A JP peripheral IV has no fee code; it is still a ProcedureRecord, and
    its Procedure carries the catalog name and the CPT coding only."""
    from datetime import datetime

    import numpy as np

    from clinosim.modules.procedure.engine import generate_bedside_procedures

    found = []
    for seed in range(40):
        procs = generate_bedside_procedures(
            "P1", "E1", "chest_pain", datetime(2025, 3, 1, 10), "severe", np.random.default_rng(seed), country="JP"
        )
        found += [p for p in procs if p.procedure_type == "iv_line"]
    assert found
    rec = found[0]
    assert (rec.procedure_code, rec.procedure_code_jp, rec.procedure_code_us) == ("", "", "36000")
    res = _build_procedure(
        {
            "procedure_type": "iv_line",
            "procedure_id": "p1",
            "encounter_id": "e1",
            "procedure_code": rec.procedure_code,
            "procedure_code_jp": rec.procedure_code_jp,
            "procedure_code_us": rec.procedure_code_us,
        },
        "pt1",
        0,
        "JP",
    )
    assert res["code"]["text"] == "末梢静脈路確保"
    assert [c["code"] for c in res["code"]["coding"]] == ["36000"]
