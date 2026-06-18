# Output-format adapter registry — design

**Date:** 2026-06-17
**Status:** Approved (brainstorming) — pending implementation plan
**Scope:** Foundational extensibility seam for output formats (Approach 2: Protocol/registry).
Future realism/event extensibility is documented as strategy only (not implemented here).

## Problem

`clinosim` currently emits FHIR R4 (and CSV) from CIF, but the output path is not
extensible:

- The CLI hard-codes formats: `if "csv" in args.format: ...`, `if "fhir" in args.format: ...`
  with direct imports of `convert_cif_to_csv` / `convert_cif_to_fhir`.
- Adding a future format (SS-MIX, FHIR R3/STU3, HL7 v2, …) means editing `cli.py` and the
  `export-fhir` path, with no shared interface or discovery.
- There is no single place that answers "what output formats exist and what does each need?"

The architecture already has the right foundation: **CIF is the only simulation output
(AD-17)** and adapters read CIF, never simulation internals. We formalize the adapter layer
into a registry so new formats plug in without touching core code.

## Goals / non-goals

**Goals**
- A self-describing `OutputAdapter` interface + registry. Adding a format = register one
  adapter; no edits to CLI dispatch or other adapters.
- CLI `--format` is driven by the registry (dynamic choices + validation).
- Existing CIF/CSV/FHIR R4 output is **byte-for-byte unchanged** (wrap, don't rewrite).
- Adapters depend only on CIF + `clinosim.codes` + `clinosim.locale` (enforces AD-17/AD-25).
- A contract test proves a new adapter can be added and run end-to-end (without building SS-MIX).

**Non-goals (this round) — tracked as future work**
- Decomposing the 3,245-line `fhir_r4_adapter.py` monolith (independent of the seam; golden risk).
- Implementing a real second format (SS-MIX / FHIR R3).
- `setuptools` entry-point discovery for third-party plugin packages (documented as the next
  evolution once an external plugin actually exists).
- A clinical-event plugin mechanism (separate realism concern; see Strategy section).

## Architecture

```
CIFDataset ──(write_cif)──▶ CIF dir  ◀── canonical store (AD-17), always written
                              │
                              ├─▶ OutputAdapter("csv").convert()      ─▶ out/csv/
                              ├─▶ OutputAdapter("fhir-r4").convert()  ─▶ out/fhir_r4/
                              └─▶ OutputAdapter("ss-mix").convert()   ─▶ out/ss_mix/   (future)
```

CIF stays the source of truth and is always produced first. The registry governs the
**CIF-consuming export adapters**. `"cif"` remains a valid `--format` value meaning
"CIF only, no extra export" (handled specially in the CLI; it is not a registered adapter).

### New module: `clinosim/modules/output/adapter.py`

```python
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

@dataclass
class OutputContext:
    """Shared, format-agnostic context passed to every adapter."""
    country: str = "US"
    narrative_version: str = ""          # optional narrative dir to fold in (FHIR DocumentReference)
    options: dict = field(default_factory=dict)   # format-specific extras (forward-compatible)

@runtime_checkable
class OutputAdapter(Protocol):
    format_id: str        # registry key + CLI value, e.g. "fhir-r4"
    description: str       # shown in CLI help / `available_formats()`
    subdir: str           # output subdirectory name, e.g. "fhir_r4"
    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None: ...

_ADAPTERS: dict[str, OutputAdapter] = {}

def register_output_adapter(adapter: OutputAdapter) -> None:
    """Register (or replace) an adapter by format_id. Idempotent."""
    _ADAPTERS[adapter.format_id] = adapter

def get_adapter(format_id: str) -> OutputAdapter: ...      # raises KeyError → CLI turns into a clear error
def available_formats() -> list[tuple[str, str]]: ...      # [(format_id, description), ...] sorted

def register_builtin_adapters() -> None:
    """Register the in-repo adapters. Called once at module import (mirrors AD-56 enrichers)."""
```

Mirrors the AD-56 patterns (`register_bundle_builder`, `register_builtin_enrichers`):
explicit registry, builtins registered at import, third parties can `register_output_adapter`
from their own import side-effect today and via entry points later.

### Built-in adapters (thin wrappers — zero behavior change)

In `clinosim/modules/output/adapters_builtin.py` (or inline in `adapter.py`):

```python
class CsvAdapter:
    format_id, description, subdir = "csv", "CSV tables (one file per resource type)", "csv"
    def convert(self, cif_dir, out_dir, ctx):
        from clinosim.modules.output.csv_adapter import convert_cif_to_csv
        convert_cif_to_csv(cif_dir, out_dir)

class FhirR4Adapter:
    format_id, description, subdir = "fhir-r4", "HL7 FHIR R4 Bulk Data NDJSON", "fhir_r4"
    def convert(self, cif_dir, out_dir, ctx):
        from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
        convert_cif_to_fhir(cif_dir, out_dir, country=ctx.country,
                            narrative_version=ctx.narrative_version)
```

`fhir_r4_adapter.py` / `csv_adapter.py` internals are untouched → golden/e2e unchanged.

**Back-compat for `--format fhir`:** the legacy value `"fhir"` is accepted as an alias of
`"fhir-r4"` (alias map in the CLI) so existing invocations keep working.

### CLI integration (`simulator/cli.py`)

- `--format` help text and validation come from `available_formats()` (plus `"cif"`).
  Unknown format → error message listing available formats.
- Dispatch (replacing the hard-coded `if`s):
  ```python
  write_cif(dataset, cif_dir)                      # always
  ctx = OutputContext(country=country, narrative_version=narrative_version)
  for fmt in requested_formats:
      fmt = _ALIAS.get(fmt, fmt)                   # "fhir" → "fhir-r4"
      if fmt == "cif": continue
      adapter = get_adapter(fmt)
      adapter.convert(cif_dir, os.path.join(args.output, adapter.subdir), ctx)
  ```
- `export-fhir` subcommand keeps its CLI surface but its body routes through the registry
  (`get_adapter("fhir-r4").convert(...)`), so there is one code path.
- Output subdirectories preserved exactly (`fhir_r4`, `csv`).

## Data flow & ownership

- CIF remains the only contract between simulation and output (AD-17). Adapters MUST NOT
  import simulation internals; they read the CIF directory + `clinosim.codes` + `clinosim.locale`.
- `OutputContext` carries cross-cutting concerns (country, narrative version, future locale
  overrides) so adapters share one localization entry point (AD-25).

## Error handling

- `get_adapter(unknown)` → `KeyError`; the CLI catches it and prints
  `Unknown format 'x'. Available: cif, csv, fhir-r4` and exits non-zero.
- An adapter that raises during `convert()` aborts that format with a clear message; CIF and
  already-completed formats are preserved (no partial-state rollback needed — each format
  writes its own subdir).

## Testing

- **Unit** (`tests/unit/test_output_adapter.py`):
  - `register_output_adapter` / `get_adapter` / `available_formats` behavior; idempotent re-register.
  - Built-in adapters are registered after import and expose the expected `format_id`/`subdir`.
  - CLI format validation: unknown format errors; `"fhir"` alias resolves to `"fhir-r4"`.
  - **Contract test:** define a dummy `MemoAdapter` (writes a sentinel file), register it,
    run the dispatch, assert the file appears — proves a new format plugs in with no core edits.
- **Integration / e2e:** unchanged. The wrappers are pass-throughs, so the existing FHIR/CSV
  integration + e2e golden tests prove no regression.

## Documentation

- **New ADR `AD-58` in DESIGN.md** — "Output-format adapter registry":
  CIF→format adapters self-register; CLI is registry-driven; adding a format = add an adapter
  (no core edits); adapters depend only on CIF + codes + locale; evolution path to
  `setuptools` entry-point discovery for external plugin packages.
- `clinosim/modules/output/README.md` — document the interface + "how to add a format".
- CLAUDE.md "Add a FHIR resource via register_bundle_builder" section gains a sibling note:
  "Add an output format via register_output_adapter (AD-58) — do NOT edit CLI dispatch."

## Strategy note: realism & event extensibility (design-only, not built here)

Per the broader directive (make adding realism data/events easy, and adding output formats
easy), the realism side is **already** largely extensible and is reaffirmed as the policy:

- **Add data → `CIFPatientRecord.extensions[<module>]`** (modules never edit core CIF types; AD-55/56).
- **Add a post-pass → register an `Enricher`** (`simulator/enrichers.py`; AD-56).
- **Add a FHIR resource → `register_bundle_builder`** (AD-56) — and now, by symmetry,
  **add a format → `register_output_adapter`** (AD-58).
- **Gap (future work):** there is no first-class *clinical-event* plugin (e.g. registering new
  intra-encounter events / life events that perturb physiology). Today events live in the
  simulator/disease layer. A future ADR should introduce a clinical-event registry analogous
  to the enricher/bundle-builder registries, so realism events are added without core edits.
  Out of scope for this round; tracked in TODO.

## Risks

- **Determinism / golden:** none expected — wrappers call the existing functions unchanged.
  Verified by the unchanged integration + e2e suites.
- **CLI back-compat:** preserved via the `"fhir"`→`"fhir-r4"` alias and identical output subdirs.
