"""Procedure codes and names (Issue #2263).

The catalog (``codes/data/clinosim-procedure-catalog.yaml``) holds, per
procedure type, the CPT code (US), the 診療行為 K-code (JP) and the en/ja
name. Displays of a coded procedure come from the CPT / K-code registries.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes.loader import display, system_key_for
from clinosim.datafiles import load_data_yaml

_DATA_FILE = Path(__file__).parent / "data" / "clinosim-procedure-catalog.yaml"

# Catalog field holding the code of each procedure code system (Issue #3144).
_CATALOG_FIELD = {"cpt": "cpt", "k-codes": "k_code"}


@cache
def _catalog() -> dict[str, Any]:
    return load_data_yaml(_DATA_FILE)


def bedside_procedures() -> tuple[dict[str, Any], ...]:
    """Bedside / routine inpatient procedures in dispatch order."""
    return tuple(_catalog().get("bedside") or ())


@cache
def _entries() -> dict[str, dict[str, Any]]:
    named = tuple(_catalog().get("named") or ())
    return {str(e["type"]): e for e in (*bedside_procedures(), *named)}


def catalog_procedure_types() -> frozenset[str]:
    """Every procedure type the catalog names: the bedside procedures and the
    ``named`` types recorded elsewhere (Issue #3081)."""
    return frozenset(_entries())


def procedure_code(proc_type: str, country: str) -> str:
    """CPT (US) or K-code (JP) of a procedure type — the catalog field of the
    country's procedure code system; ``""`` when the catalog has no verified
    code for it."""
    entry = _entries().get(proc_type) or {}
    field = _CATALOG_FIELD[system_key_for("procedure", country)]
    return str(entry.get(field) or "")


def country_procedure_code(country: str, codes: dict[str, Any]) -> Any:
    """The code, from ``codes`` keyed by procedure code-system key (``"cpt"``,
    ``"k-codes"``), of the system the country profile names for procedures
    (Issue #3144). The value is returned as given."""
    return codes[system_key_for("procedure", country)]


def procedure_anesthesia(proc_type: str) -> str:
    """Anesthesia under which the catalog says a procedure type is done
    (``none`` / ``local`` / ``sedation`` / ``general``); ``""`` (not recorded)
    when the catalog does not say (Issue #3257)."""
    return str((_entries().get(proc_type) or {}).get("anesthesia") or "")


def procedure_is_emergent(proc_type: str) -> bool:
    """True when the catalog marks a procedure type as an emergency by nature
    (``emergent: true``; Issue #3550), so its consent is emergency / implied."""
    return bool((_entries().get(proc_type) or {}).get("emergent"))


@dataclass(frozen=True)
class DurationSpec:
    """Duration distribution of a procedure type, in minutes: a normal draw
    (``mean``, ``sd``) clipped to [``min``, ``max``]; ``max`` is None when
    unbounded."""

    mean: float
    sd: float
    min: int
    max: int | None = None


def procedure_duration(proc_type: str) -> DurationSpec | None:
    """The catalog's ``duration_minutes`` of a procedure type (Issue #3550);
    None when the catalog gives none, so the caller uses its default."""
    raw = (_entries().get(proc_type) or {}).get("duration_minutes")
    if not raw:
        return None
    mx = raw.get("max")
    return DurationSpec(float(raw["mean"]), float(raw["sd"]), int(raw["min"]), int(mx) if mx is not None else None)


def procedure_default_body_site(proc_type: str) -> str:
    """The SNOMED body-site code the procedure metadata gives a procedure type
    (``procedure-snomed-metadata.yaml``): the organ or system the type works on,
    which is not a recorded insertion site (Issue #3550); ``""`` when none."""
    from clinosim.codes import data_table

    row = (data_table("procedure-snomed-metadata").get("procedures") or {}).get(proc_type) or {}
    return str(row.get("body_site") or "") if isinstance(row, dict) else ""


def procedure_aftercare(proc_type: str) -> str:
    """Aftercare category of a procedure type (``urinary_catheter``,
    ``vascular_access``, ``surgical_wound`` ...), which selects the plan the
    operative / procedure note writes after it; ``""`` when the catalog does
    not say (Issue #3257). The text of each category is the
    ``procedure_aftercare.<category>`` phrase."""
    return str((_entries().get(proc_type) or {}).get("aftercare") or "")


def procedure_type_display(proc_type: str, lang: str) -> str:
    """Name of a procedure type in ``lang`` (then English) from the catalog;
    an unknown type is humanised (underscores → spaces), never a raw slug."""
    if not proc_type:
        return ""
    from clinosim.locale.localized import localized

    entry = _entries().get(proc_type) or _entries().get(str(proc_type).strip().lower()) or {}
    return localized(entry.get("name") or {}, lang, fallback=str(proc_type).replace("_", " "))


def procedure_code_display(codes: Iterable[str], lang: str) -> str | None:
    """Display of the first code that resolves, trying the K-code registry and
    then CPT for each code in turn; ``None`` when none resolves. The one copy
    of the "K-codes, then CPT" display loop."""
    for code in codes:
        if not code:
            continue
        for system_key in ("k-codes", "cpt"):
            hit = display(system_key, code, lang)
            if hit:
                return hit
    return None


def procedure_specimens(proc_type: str) -> tuple[str, ...]:
    """Specimens a procedure type removes and sends to histopathology, as
    ``specimen_type`` keys of ``snomed-maps.yaml`` (the catalog's
    ``specimens`` table, Issue #3284); empty for a procedure that sends none."""
    return tuple(str(s) for s in (_catalog().get("specimens") or {}).get(proc_type) or ())


def procedure_implants(proc_type: str) -> tuple[str, ...]:
    """Devices a procedure type leaves in the patient, as keys of
    ``narrative_op_implants.yaml`` (the catalog's ``implants`` table, Issue
    #3406); empty for a procedure that leaves none."""
    return tuple(str(i) for i in (_catalog().get("implants") or {}).get(proc_type) or ())


def specimen_code(slug: str) -> str:
    """SNOMED CT specimen concept of a ``specimens_sent`` entry; ``""`` when
    the key is not mapped (Issue #3284)."""
    from clinosim.codes.snomed import snomed_for

    return snomed_for("specimen_type", slug) or "" if slug else ""


def specimen_label(slug: str, lang: str) -> str:
    """Clinical label of a ``specimens_sent`` entry in ``lang`` (then English):
    the ``surgical_specimen`` narrative label ("Appendix" / 虫垂), else the
    SNOMED CT display of its specimen concept. The operative note's specimen
    line and FHIR ``Specimen.type.text`` (Issue #3284)."""
    from clinosim.locale.loader import narrative_label

    code = specimen_code(slug)
    fallback = (display("snomed-ct", code, lang) if code else None) or slug.replace("_", " ")
    return narrative_label("surgical_specimen", slug, lang, fallback=fallback)
