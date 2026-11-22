"""The one reading of an administered drug from a medication row (Issue #3560).

A supportive order is stored as ``"<type>: <detail>"``. When ``<type>`` is a
category label (``antipyretic``, ``IV_fluid``) the drug is in ``<detail>`` and
the label is dropped; when ``<type>`` is itself a catalog drug
(``lactulose: 30mL PO TID if encephalopathy``) it is the drug name and is kept.
Every narrative that names a drug from a row (MAR administration, discharge
prescription) goes through here rather than stripping the prefix itself
(see ``docs/design-guides/code-mapping-and-localization-spec.md``, section
"Administered drug label").
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from clinosim.codes.drugs import drug_display, drug_key, drug_ref
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.free_text import localize_drug_name
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix

_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "administered_drug_name.yaml"


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_detail_cuts: list[str]

    @model_validator(mode="after")
    def _compiles(self) -> _Config:
        for p in self.order_detail_cuts:
            re.compile(p)
        return self


@lru_cache(maxsize=1)
def _cuts() -> tuple[re.Pattern[str], ...]:
    data = load_validated_yaml(_YAML, _Config)
    return tuple(re.compile(p, re.IGNORECASE) for p in data["order_detail_cuts"])


def order_drug_text(raw: str) -> str:
    """The drug-and-dose text of an order string: a category prefix dropped, a
    drug prefix kept as the drug name, a monitoring target cut."""
    text = (raw or "").strip()
    if ":" in text:
        prefix = text.split(":", 1)[0]
        rest = strip_protocol_prefix(text)[0]
        # The prefix is the drug only when the detail names none ("lactulose:
        # 30mL PO TID"); "IV_insulin: Regular insulin 0.1 U/kg/h" is a label.
        text = text.replace(":", " ", 1) if drug_ref(prefix.replace("_", " ").strip()) and not drug_ref(rest) else rest
    for cut in _cuts():
        text = cut.sub("", text)
    return " ".join(text.split())


def _raw(row: Any) -> str:
    return str(_o(row, "drug_name", None) or _o(row, "medication", None) or "")


def administered_drug_key(row: Any) -> str:
    """Identity of the drug of ``row``: its ``drug_id``, else the catalog id of
    its order text, else the folded text (``""`` for a row with no name)."""
    ref = str(_o(row, "drug_id", "") or "")
    text = order_drug_text(_raw(row))
    return drug_key(ref or text) if (ref or text) else ""


def administered_drug_label(row: Any, lang: str) -> str:
    """The drug of ``row`` with its dose, in ``lang``. Falls back to the catalog
    name of ``drug_id`` when the order text does not name the drug itself."""
    text = order_drug_text(_raw(row))
    ref = str(_o(row, "drug_id", "") or "")
    if ref and (not text or drug_ref(text) != ref):
        named = drug_display(ref, lang)
        if named:
            return named
    return localize_drug_name(text, lang) if text else ""


def administered_drug_name(row: Any, lang: str) -> str:
    """The bare drug name of ``row`` in ``lang`` (no dose): the catalog name
    when the drug is catalogued, else the label."""
    key = administered_drug_key(row)
    return (drug_display(key, lang) if key else None) or administered_drug_label(row, lang)
