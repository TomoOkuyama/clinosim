"""Catalog of the codes a dataset uses, accumulated while the FHIR export writes.

A consumer that loads a dataset into an EHR or a data platform needs to know,
before loading, every code that appears in the data. The catalog is built by
feeding each resource to :meth:`UsedCodesCatalog.observe` at the moment the
FHIR writer emits it, so it always matches the written data and costs no
second pass over the NDJSON. It is written once, at the end of the export, to
``catalog/codes-used.ndjson`` next to ``fhir_r4/``; nothing is added inside
``fhir_r4/``.

One line per ``(kind, system, code)`` (medications also per route text), in FHIR
terms only. The fields, the kinds and the resource locations they come from are
specified in ``clinosim/modules/output/fhir_r4/README.md`` ("Used-codes
catalog"). The accumulator keeps one entry per distinct key and, per entry, a
set of interned patient ids, so its size follows the number of distinct codes,
not the number of resources.

The accumulator reads only what the emitted resource states. A kind-specific
attribute the resource does not carry (for example an RxNorm term type) is not
derived from reference data and is absent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any

from clinosim.codes.snomed_concepts import NO_GROWTH

CATALOG_DIRNAME = "catalog"
CATALOG_FILENAME = "codes-used.ndjson"
METADATA_KEY = "used_codes_catalog"

# Observation.identifier system of the organism-isolate Observation written by
# the microbiology builder (``mb-organism-observation-key``). Kept as a suffix
# match so the catalog does not import the builder.
_ORGANISM_KEY_SUFFIX = "mb-organism-observation-key"

# Observation.category code -> catalog kind. A survey Observation with an
# integer value is an assessment score (GCS, NEWS, Barthel, Braden, Morse).
_CATEGORY_KIND = {"laboratory": "lab", "vital-signs": "vital-sign"}

Key = tuple[str, str, str, str, str, str | None]
Attr = tuple[Any, ...]


class _Entry:
    """Accumulated state of one catalog line."""

    __slots__ = ("attrs", "count", "display", "key", "patients", "text")

    def __init__(self, key: Key, display: str | None, text: str | None) -> None:
        self.key = key
        self.display = display
        self.text = text
        self.count = 0
        self.patients: set[int] = set()
        self.attrs: dict[str, set[Attr]] = {}

    def add(self, name: str, value: Attr) -> None:
        self.attrs.setdefault(name, set()).add(value)


def _codings(concept: Any) -> list[dict]:
    """The codings of a CodeableConcept that carry a code (text-only concepts have none)."""
    if not isinstance(concept, dict):
        return []
    return [c for c in concept.get("coding") or [] if isinstance(c, dict) and c.get("code")]


def _ref_id(ref: Any) -> str:
    return str(ref.get("reference", "")) if isinstance(ref, dict) else ""


def _tidy(mapping: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if v not in (None, "", [])}


def _quantity_unit(q: Any) -> str | None:
    if isinstance(q, dict):
        return q.get("code") or q.get("unit")
    return None


class UsedCodesCatalog:
    """Accumulates the codes of the emitted resources and writes the catalog."""

    def __init__(self) -> None:
        self._entries: dict[Key, _Entry] = {}
        self._patient_ids: dict[str, int] = {}
        # Specimen type by id, and Observations seen before their Specimen, for
        # the bundle being written (cleared by end_bundle, so they stay small).
        self._specimens: dict[str, tuple[str, str, str | None]] = {}
        self._pending: list[tuple[list[_Entry], str]] = []
        self._handlers: dict[str, Callable[[dict], None]] = {
            "MedicationRequest": self._medication_request,
            "Observation": self._observation,
            "ImagingStudy": self._imaging_study,
            "Condition": self._condition,
            "Procedure": self._procedure,
            "DocumentReference": self._document_reference,
            "Immunization": self._immunization,
            "AllergyIntolerance": self._allergy_intolerance,
            "Specimen": self._specimen,
        }

    # ---- feeding -------------------------------------------------------

    def observe(self, resource: dict) -> None:
        """Account for one resource exactly as the writer emits it."""
        handler = self._handlers.get(resource.get("resourceType", ""))
        if handler is not None:
            handler(resource)

    def end_bundle(self) -> None:
        """Resolve per-bundle references (Observation -> Specimen) and clear them."""
        for entries, spec_id in self._pending:
            spec = self._specimens.get(spec_id)
            if spec is not None:
                for entry in entries:
                    entry.add("specimens", spec)
        self._pending.clear()
        self._specimens.clear()

    # ---- accumulation --------------------------------------------------

    def _patient(self, resource: dict) -> int | None:
        ref = _ref_id(resource.get("subject")) or _ref_id(resource.get("patient"))
        if not ref:
            return None
        return self._patient_ids.setdefault(ref, len(self._patient_ids))

    def _count(
        self,
        kind: str,
        resource: dict,
        element: str,
        concept: Any,
        *,
        route: str | None = None,
    ) -> list[_Entry]:
        """Count every coded coding of ``concept`` once for this resource."""
        rtype = resource["resourceType"]
        pid = self._patient(resource)
        text = concept.get("text") if isinstance(concept, dict) else None
        seen: dict[Key, _Entry] = {}
        for coding in _codings(concept):
            key: Key = (kind, rtype, element, str(coding.get("system") or ""), str(coding["code"]), route)
            if key in seen:
                continue
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = _Entry(key, coding.get("display") or None, text or None)
            entry.count += 1
            if pid is not None:
                entry.patients.add(pid)
            seen[key] = entry
        return list(seen.values())

    def _medication_request(self, res: dict) -> None:
        concept = res.get("medicationCodeableConcept")
        dosage = (res.get("dosageInstruction") or [None])[0]
        dosage = dosage if isinstance(dosage, dict) else {}
        route: dict[str, Any] = dosage["route"] if isinstance(dosage.get("route"), dict) else {}
        entries = self._count("medication", res, "medicationCodeableConcept", concept, route=route.get("text") or None)
        route_coding = (_codings(route) or [{}])[0]
        dose = (dosage.get("doseAndRate") or [{}])[0]
        dose_unit = _quantity_unit(dose.get("doseQuantity")) if isinstance(dose, dict) else None
        codings = _codings(concept)
        for entry in entries:
            if route_coding:
                entry.add(
                    "route_coding",
                    (route_coding.get("system"), route_coding.get("code"), route_coding.get("display")),
                )
            if dose_unit:
                entry.add("dose_units", (dose_unit,))
            # The other codings of the same concept: a product and its ingredient
            # are carried together, in the order the resource states them.
            for other in codings:
                if (other.get("system"), other["code"]) != (entry.key[3], entry.key[4]):
                    entry.add("co_coded", (other.get("system"), other["code"], other.get("display")))

    def _observation_kind(self, res: dict) -> str:
        cats = {
            c.get("code")
            for cat in res.get("category") or []
            if isinstance(cat, dict)
            for c in cat.get("coding") or []
            if isinstance(c, dict)
        }
        for cat_code, kind in _CATEGORY_KIND.items():
            if cat_code in cats:
                return kind
        if "survey" in cats and "valueInteger" in res:
            return "nursing-score"
        return "observation"

    def _observation(self, res: dict) -> None:
        kind = self._observation_kind(res)
        entries = self._count(kind, res, "code", res.get("code"))
        value_types = tuple(sorted(k[5:] for k in res if k.startswith("value") and k != "value"))
        unit = _quantity_unit(res.get("valueQuantity"))
        ranges = [self._range(r) for r in res.get("referenceRange") or [] if isinstance(r, dict)]
        components = [
            (c.get("system"), c["code"], c.get("display"), _quantity_unit(comp.get("valueQuantity")))
            for comp in res.get("component") or []
            if isinstance(comp, dict)
            for c in _codings(comp.get("code"))
        ]
        spec_id = _ref_id(res.get("specimen")).removeprefix("Specimen/")
        for entry in entries:
            for vt in value_types:
                entry.add("value_types", (vt,))
            if unit:
                entry.add("units", (unit,))
            for rng in ranges:
                entry.add("reference_ranges", rng)
            for comp in components:
                entry.add("components", comp)
        if spec_id and entries:
            self._pending.append((entries, spec_id))
        # The isolate of a culture: the coded value of the organism Observation.
        if any(
            str(i.get("system", "")).endswith(_ORGANISM_KEY_SUFFIX)
            for i in res.get("identifier") or []
            if isinstance(i, dict)
        ):
            concept = res.get("valueCodeableConcept")
            if not any(c["code"] == NO_GROWTH for c in _codings(concept)):
                self._count("organism", res, "valueCodeableConcept", concept)

    @staticmethod
    def _range(rng: dict) -> Attr:
        low, high = rng.get("low"), rng.get("high")
        types = _codings(rng.get("type"))
        applies = tuple(sorted(str(c["code"]) for a in rng.get("appliesTo") or [] for c in _codings(a)))
        return (
            low.get("value") if isinstance(low, dict) else None,
            high.get("value") if isinstance(high, dict) else None,
            _quantity_unit(low) or _quantity_unit(high),
            rng.get("text"),
            types[0]["code"] if types else None,
            applies,
        )

    def _specimen(self, res: dict) -> None:
        codings = _codings(res.get("type"))
        if codings and res.get("id"):
            coding = codings[0]
            self._specimens[str(res["id"])] = (
                str(coding.get("system") or ""),
                str(coding["code"]),
                coding.get("display") or None,
            )

    def _imaging_study(self, res: dict) -> None:
        series = [s for s in res.get("series") or [] if isinstance(s, dict)]
        modalities: dict[tuple, Attr] = {}
        for m in [*(res.get("modality") or []), *(s.get("modality") for s in series)]:
            if isinstance(m, dict) and m.get("code"):
                modalities.setdefault((m.get("system"), m["code"]), (m.get("system"), m["code"], m.get("display")))
        body_sites = {
            (b.get("system"), b["code"], b.get("display"))
            for b in (s.get("bodySite") for s in series)
            if isinstance(b, dict) and b.get("code")
        }
        for concept in res.get("procedureCode") or []:
            for entry in self._count("imaging", res, "procedureCode", concept):
                for m in modalities.values():
                    entry.add("modalities", m)
                for b in body_sites:
                    entry.add("body_sites", b)

    def _condition(self, res: dict) -> None:
        self._count("diagnosis", res, "code", res.get("code"))

    def _procedure(self, res: dict) -> None:
        self._count("procedure", res, "code", res.get("code"))

    def _document_reference(self, res: dict) -> None:
        self._count("document-type", res, "type", res.get("type"))

    def _immunization(self, res: dict) -> None:
        self._count("vaccine", res, "vaccineCode", res.get("vaccineCode"))

    def _allergy_intolerance(self, res: dict) -> None:
        self._count("allergen", res, "code", res.get("code"))

    # ---- output --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def _attr_value(name: str, value: Attr) -> Any:
        if name in ("value_types", "dose_units", "units"):
            return value[0]
        if name == "reference_ranges":
            low, high, unit, text, rtype, applies = value
            return _tidy(
                {"low": low, "high": high, "unit": unit, "text": text, "type": rtype, "applies_to": list(applies)}
            )
        if name == "components":
            return _tidy({"system": value[0], "code": value[1], "display": value[2], "unit": value[3]})
        if name == "route_coding":
            return _tidy({"system": value[0], "code": value[1], "display": value[2]})
        # specimens, co_coded, modalities, body_sites: (system, code, display)
        return _tidy({"system": value[0], "code": value[1], "display": value[2]})

    def lines(self) -> Iterator[dict[str, Any]]:
        """The catalog lines in a stable order (kind, system, code, route)."""
        for key in sorted(self._entries, key=lambda k: (k[0], k[3], k[4], k[5] or "", k[1], k[2])):
            entry = self._entries[key]
            kind, rtype, element, system, code, route = key
            line: dict[str, Any] = {
                "kind": kind,
                "resource": rtype,
                "element": element,
                "system": system,
                "code": code,
                "display": entry.display,
            }
            if entry.text and entry.text != entry.display:
                line["text"] = entry.text
            if kind == "medication":
                line["route"] = route
            line["count"] = entry.count
            line["patients"] = len(entry.patients)
            for name in sorted(entry.attrs):
                values = [self._attr_value(name, v) for v in entry.attrs[name]]
                line[name] = sorted(values, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
            yield line

    def write(self, path: str) -> int:
        """Write the catalog as NDJSON (one line per code) and return the line count."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        n = 0
        with open(path, "w", encoding="utf-8") as f:
            for line in self.lines():
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                n += 1
        return n


def catalog_path_for(fhir_output_dir: str) -> str:
    """``catalog/codes-used.ndjson`` next to the ``fhir_r4/`` directory."""
    parent = os.path.dirname(os.path.abspath(fhir_output_dir))
    return os.path.join(parent, CATALOG_DIRNAME, CATALOG_FILENAME)


def register_in_cif_metadata(cif_dir: str, catalog_path: str) -> None:
    """Record the catalog path (relative to the dataset root) in ``cif/metadata.json``.

    Soft-failure: a missing or unreadable metadata file is left alone, as for
    the other optional metadata readers of the export.
    """
    meta_path = os.path.join(cif_dir, "metadata.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            return
        root = os.path.dirname(os.path.abspath(cif_dir))
        meta[METADATA_KEY] = os.path.relpath(os.path.abspath(catalog_path), root).replace(os.sep, "/")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except (OSError, json.JSONDecodeError):
        return
