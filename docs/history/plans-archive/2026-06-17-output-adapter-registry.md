# Output-format Adapter Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `OutputAdapter` Protocol + registry so new output formats (SS-MIX, FHIR R3, …) plug in by registering one adapter — with zero edits to CLI dispatch or other adapters — while existing CIF/CSV/FHIR R4 output stays byte-for-byte unchanged.

**Architecture:** CIF remains the only simulation output (AD-17) and is always written first. A new `clinosim/modules/output/adapter.py` defines the `OutputAdapter` Protocol, an `OutputContext`, and a registry (`register_output_adapter` / `get_adapter` / `available_formats`). Built-in CSV and FHIR-R4 adapters in `adapters_builtin.py` are thin wrappers over the existing `convert_cif_to_csv` / `convert_cif_to_fhir` functions (internals untouched). `simulator/cli.py` dispatch becomes registry-driven with a `fhir`→`fhir-r4` back-compat alias.

**Tech Stack:** Python 3.11+, `typing.Protocol`, pytest. Formatter ruff, mypy strict, line length 100.

---

### Task 1: OutputAdapter interface + registry

**Files:**
- Create: `clinosim/modules/output/adapter.py`
- Test: `tests/unit/test_output_adapter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_output_adapter.py`:

```python
"""Unit tests for the output-format adapter registry (AD-58)."""

import pytest

from clinosim.modules.output.adapter import (
    OutputAdapter,
    OutputContext,
    available_formats,
    get_adapter,
    register_output_adapter,
)


class _DummyAdapter:
    format_id = "dummy"
    description = "Dummy test adapter"
    subdir = "dummy"

    def __init__(self):
        self.calls = []

    def convert(self, cif_dir, out_dir, ctx):
        self.calls.append((cif_dir, out_dir, ctx))


@pytest.mark.unit
class TestAdapterRegistry:
    def test_register_and_get(self):
        a = _DummyAdapter()
        register_output_adapter(a)
        assert get_adapter("dummy") is a

    def test_register_is_idempotent_replace(self):
        a1, a2 = _DummyAdapter(), _DummyAdapter()
        register_output_adapter(a1)
        register_output_adapter(a2)
        assert get_adapter("dummy") is a2  # last registration wins

    def test_unknown_format_raises_keyerror(self):
        with pytest.raises(KeyError):
            get_adapter("does-not-exist")

    def test_available_formats_includes_registered(self):
        register_output_adapter(_DummyAdapter())
        ids = [fid for fid, _desc in available_formats()]
        assert "dummy" in ids

    def test_dummy_satisfies_protocol(self):
        assert isinstance(_DummyAdapter(), OutputAdapter)

    def test_output_context_defaults(self):
        ctx = OutputContext()
        assert ctx.country == "US"
        assert ctx.narrative_version == ""
        assert ctx.options == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_output_adapter.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clinosim.modules.output.adapter'`

- [ ] **Step 3: Write minimal implementation**

Create `clinosim/modules/output/adapter.py`:

```python
"""Output-format adapter registry (AD-58).

CIF is the only simulation output (AD-17). Format adapters read the CIF directory and
emit a concrete export format. New formats (SS-MIX, FHIR R3, ...) register one adapter
here instead of editing CLI dispatch. Adapters depend only on CIF + clinosim.codes +
clinosim.locale (AD-17 / AD-25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OutputContext:
    """Shared, format-agnostic context passed to every adapter."""

    country: str = "US"
    narrative_version: str = ""  # optional narrative dir folded into output (e.g. FHIR DocumentReference)
    options: dict = field(default_factory=dict)  # format-specific extras (forward-compatible)


@runtime_checkable
class OutputAdapter(Protocol):
    """A CIF-consuming export adapter. Implementations are plain classes (duck-typed)."""

    format_id: str  # registry key + CLI value, e.g. "fhir-r4"
    description: str  # shown in CLI help / available_formats()
    subdir: str  # output subdirectory name, e.g. "fhir_r4"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None: ...


_ADAPTERS: dict[str, OutputAdapter] = {}
_builtins_loaded = False


def register_output_adapter(adapter: OutputAdapter) -> None:
    """Register (or replace) an adapter by its format_id. Idempotent."""
    _ADAPTERS[adapter.format_id] = adapter


def _ensure_builtins() -> None:
    """Import the built-in adapters module once so it self-registers."""
    global _builtins_loaded
    if not _builtins_loaded:
        _builtins_loaded = True
        import clinosim.modules.output.adapters_builtin  # noqa: F401  (registers on import)


def get_adapter(format_id: str) -> OutputAdapter:
    """Return the adapter for format_id, or raise KeyError with the available list."""
    _ensure_builtins()
    if format_id not in _ADAPTERS:
        raise KeyError(
            f"Unknown output format {format_id!r}. "
            f"Available: {', '.join(sorted(_ADAPTERS))}"
        )
    return _ADAPTERS[format_id]


def available_formats() -> list[tuple[str, str]]:
    """Return [(format_id, description), ...] sorted by format_id."""
    _ensure_builtins()
    return sorted((a.format_id, a.description) for a in _ADAPTERS.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_output_adapter.py -q`
Expected: PASS (6 passed). Note: `test_available_formats_includes_registered` triggers
`_ensure_builtins()`, which imports `adapters_builtin` — that module does not exist yet, so
this specific test will error until Task 2. Run only the non-builtin tests to confirm green now:
Run: `python -m pytest tests/unit/test_output_adapter.py -q -k "not available_formats"`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/adapter.py tests/unit/test_output_adapter.py
git commit -m "feat(output): OutputAdapter protocol + registry (AD-58)"
```

---

### Task 2: Built-in CSV + FHIR-R4 adapters

**Files:**
- Create: `clinosim/modules/output/adapters_builtin.py`
- Test: `tests/unit/test_output_adapter.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_output_adapter.py`:

```python
@pytest.mark.unit
class TestBuiltinAdapters:
    def test_builtins_registered(self):
        ids = {fid for fid, _ in available_formats()}
        assert {"csv", "fhir-r4"} <= ids

    def test_fhir_adapter_metadata(self):
        a = get_adapter("fhir-r4")
        assert a.subdir == "fhir_r4"
        assert "FHIR" in a.description

    def test_csv_adapter_metadata(self):
        a = get_adapter("csv")
        assert a.subdir == "csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_output_adapter.py::TestBuiltinAdapters -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clinosim.modules.output.adapters_builtin'`

- [ ] **Step 3: Write minimal implementation**

Create `clinosim/modules/output/adapters_builtin.py`:

```python
"""Built-in output adapters (CSV, FHIR R4) — thin wrappers over the existing converters.

Heavy converter modules are lazy-imported inside convert() so importing this module just
defines + registers the adapters (no import cycle, no heavy import cost).
"""

from __future__ import annotations

from clinosim.modules.output.adapter import OutputContext, register_output_adapter


class CsvAdapter:
    format_id = "csv"
    description = "CSV tables (one file per resource type)"
    subdir = "csv"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        from clinosim.modules.output.csv_adapter import convert_cif_to_csv

        convert_cif_to_csv(cif_dir, out_dir)


class FhirR4Adapter:
    format_id = "fhir-r4"
    description = "HL7 FHIR R4 Bulk Data NDJSON"
    subdir = "fhir_r4"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

        convert_cif_to_fhir(
            cif_dir, out_dir, country=ctx.country, narrative_version=ctx.narrative_version
        )


register_output_adapter(CsvAdapter())
register_output_adapter(FhirR4Adapter())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_output_adapter.py -q`
Expected: PASS (9 passed — all tests including `test_available_formats_includes_registered`).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/adapters_builtin.py tests/unit/test_output_adapter.py
git commit -m "feat(output): built-in CSV + FHIR-R4 adapters wrapping existing converters"
```

---

### Task 3: Registry-driven CLI dispatch (generate)

**Files:**
- Modify: `clinosim/simulator/cli.py:40` (the `--format` help text) and `:214-255`
  (the output dispatch block in the generate path).
- Test: `tests/unit/test_output_adapter.py` (extend with a dispatch helper test)

- [ ] **Step 1: Write the failing test**

First we extract the dispatch into a testable helper. Append to `tests/unit/test_output_adapter.py`:

```python
@pytest.mark.unit
class TestRunExports:
    def test_runs_requested_adapters_and_skips_cif(self, tmp_path):
        from clinosim.simulator.cli import _run_exports

        calls = []

        class RecordingAdapter:
            format_id = "rec"
            description = "recording"
            subdir = "rec"

            def convert(self, cif_dir, out_dir, ctx):
                calls.append((cif_dir, out_dir, ctx.country))

        register_output_adapter(RecordingAdapter())
        _run_exports(
            formats=["cif", "rec"],
            cif_dir=str(tmp_path / "cif"),
            output_root=str(tmp_path),
            country="JP",
            narrative_version="v1",
        )
        # "cif" is skipped (no adapter call); "rec" ran once into <root>/rec
        assert len(calls) == 1
        assert calls[0][1].endswith("/rec")
        assert calls[0][2] == "JP"

    def test_fhir_alias_resolves(self, tmp_path):
        from clinosim.simulator.cli import _run_exports

        seen = []

        class FhirSpy:
            format_id = "fhir-r4"
            description = "spy"
            subdir = "fhir_r4"

            def convert(self, cif_dir, out_dir, ctx):
                seen.append(out_dir)

        register_output_adapter(FhirSpy())  # replaces builtin for this test
        _run_exports(["fhir"], str(tmp_path / "cif"), str(tmp_path), "US", "")
        assert seen and seen[0].endswith("/fhir_r4")

    def test_unknown_format_raises_valueerror(self, tmp_path):
        from clinosim.simulator.cli import _run_exports

        with pytest.raises(ValueError, match="Unknown output format"):
            _run_exports(["nope"], str(tmp_path / "cif"), str(tmp_path), "US", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_output_adapter.py::TestRunExports -q`
Expected: FAIL with `ImportError: cannot import name '_run_exports' from 'clinosim.simulator.cli'`

- [ ] **Step 3: Write minimal implementation**

In `clinosim/simulator/cli.py`, add the helper near the other module-level helpers (e.g.
just above `_print_summary`):

```python
# Back-compat alias: legacy "--format fhir" means FHIR R4.
_FORMAT_ALIASES = {"fhir": "fhir-r4"}


def _run_exports(
    formats: list[str],
    cif_dir: str,
    output_root: str,
    country: str,
    narrative_version: str,
) -> None:
    """Run each requested export format through the adapter registry (AD-58).

    CIF is assumed already written. "cif" is a no-op (CIF-only). Unknown formats raise
    ValueError. Output goes to <output_root>/<adapter.subdir>.
    """
    import os

    from clinosim.modules.output.adapter import OutputContext, get_adapter

    ctx = OutputContext(country=country, narrative_version=narrative_version or "")
    for fmt in formats:
        fmt = _FORMAT_ALIASES.get(fmt, fmt)
        if fmt == "cif":
            continue
        try:
            adapter = get_adapter(fmt)
        except KeyError as e:
            raise ValueError(str(e)) from e
        adapter.convert(cif_dir, os.path.join(output_root, adapter.subdir), ctx)
```

Then replace the generate-path dispatch. Change lines `214-216` (the CSV block) by
**removing** it (CSV now runs via the registry after narrative), and replace the FHIR block
at `247-255` with the registry call. The resulting region (from after `write_cif`) reads:

```python
    # Output — CIF is the canonical store (AD-17), always written.
    from clinosim.modules.output.cif_writer import write_cif
    cif_dir = os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    # Narrative layer (Stage 2, optional) — runs BEFORE format export so DocumentReference
    # can reference the freshly generated version.
    narrative_version = getattr(args, "narrative_version", None)
    if getattr(args, "narrative", False):
        from clinosim.modules.llm_service.engine import LLMService
        from clinosim.modules.llm_service.factory import build_from_config_file
        from clinosim.modules.output.document_generator import generate_documents

        lang = "ja" if getattr(args, "country", "US") == "JP" else "en"
        llm_config = getattr(args, "llm_config", None)
        if llm_config:
            llm = build_from_config_file(llm_config)
            print(f"  Using LLM config: {llm_config}")
        else:
            from clinosim.modules.llm_service.providers.ollama import OllamaProvider
            model = getattr(args, "narrative_model", "qwen:7b")
            print(f"  Generating narratives with local Ollama model={model}")
            llm = LLMService(
                mode="llm",
                narrative_provider=OllamaProvider({"model": model}),
                narrative_model_map={"small": model, "medium": model},
                provider_name_narrative="ollama",
            )
        narrative_version = generate_documents(
            cif_dir, llm, version_id=narrative_version, language=lang
        )
        print(f"  Narrative version: {narrative_version}")
        print(f"  LLM cost report: {llm.cost_report()}")

    # Format exports via the adapter registry (AD-58). Add a format = register an adapter.
    _run_exports(
        args.format,
        cif_dir,
        args.output,
        getattr(args, "country", "US"),
        narrative_version or "",
    )

    # Summary
    _print_summary(dataset, args.output)
```

Also update the `--format` help text at line 40:

```python
    gen.add_argument(
        "--format", nargs="+", default=["cif"],
        help="Output formats: cif, csv, fhir-r4 (alias: fhir). "
             "Add more by registering an OutputAdapter (AD-58).",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_output_adapter.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/cli.py tests/unit/test_output_adapter.py
git commit -m "feat(cli): registry-driven output dispatch with fhir alias (AD-58)"
```

---

### Task 4: Route export-fhir subcommand through the registry

**Files:**
- Modify: `clinosim/simulator/cli.py` — the `_run_export_fhir` handler (around `:150-180`).

- [ ] **Step 1: Read the current handler**

Run: `grep -n "_run_export_fhir\|convert_cif_to_fhir" clinosim/simulator/cli.py`
Then open the `_run_export_fhir` function to see its exact body and argument names
(it currently calls `convert_cif_to_fhir(...)` directly).

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_output_adapter.py`:

```python
@pytest.mark.unit
class TestExportFhirRoutesThroughRegistry:
    def test_export_fhir_uses_adapter(self, tmp_path, monkeypatch):
        import clinosim.simulator.cli as cli

        seen = {}

        class FhirSpy:
            format_id = "fhir-r4"
            description = "spy"
            subdir = "fhir_r4"

            def convert(self, cif_dir, out_dir, ctx):
                seen["out_dir"] = out_dir
                seen["country"] = ctx.country
                seen["nv"] = ctx.narrative_version

        register_output_adapter(FhirSpy())

        cif_dir = tmp_path / "cif"
        cif_dir.mkdir()
        args = cli.argparse.Namespace(
            cif_dir=str(cif_dir),
            output=str(tmp_path / "out"),
            country="JP",
            narrative_version="v2",
        )
        cli._run_export_fhir(args)
        assert seen["country"] == "JP"
        assert seen["nv"] == "v2"
        assert seen["out_dir"].endswith("/fhir_r4")
```

(If `_run_export_fhir`'s real Namespace fields differ — e.g. `cif_dir`/`output` —
adjust the Namespace in this test to match the actual attribute names found in Step 1.)

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_output_adapter.py::TestExportFhirRoutesThroughRegistry -q`
Expected: FAIL (the handler still calls `convert_cif_to_fhir` directly, so the spy's
`convert` is never invoked → KeyError on `seen["country"]`).

- [ ] **Step 4: Write minimal implementation**

In `_run_export_fhir`, replace the direct `convert_cif_to_fhir(...)` call with:

```python
    from clinosim.modules.output.adapter import OutputContext, get_adapter

    out_dir = os.path.join(args.output, "fhir_r4")
    get_adapter("fhir-r4").convert(
        args.cif_dir,
        out_dir,
        OutputContext(
            country=getattr(args, "country", "US"),
            narrative_version=getattr(args, "narrative_version", None) or "",
        ),
    )
```

Keep the surrounding output-path / print statements as they were. Match `args.cif_dir`
/ `args.output` to the real attribute names confirmed in Step 1.

- [ ] **Step 5: Run test + commit**

Run: `python -m pytest tests/unit/test_output_adapter.py -q`
Expected: PASS.

```bash
git add clinosim/simulator/cli.py tests/unit/test_output_adapter.py
git commit -m "refactor(cli): export-fhir routes through adapter registry (AD-58)"
```

---

### Task 5: End-to-end contract test (new format plugs in)

**Files:**
- Test: `tests/integration/test_output_adapter_contract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_output_adapter_contract.py`:

```python
"""Contract test: a brand-new output format plugs in via the registry with no core edits."""

import json
from pathlib import Path

import pytest

from clinosim.modules.output.adapter import (
    OutputContext,
    get_adapter,
    register_output_adapter,
)


class _MemoAdapter:
    """A minimal third-party-style adapter that writes one sentinel file from CIF."""

    format_id = "memo"
    description = "Sentinel memo (contract test)"
    subdir = "memo"

    def convert(self, cif_dir, out_dir, ctx: OutputContext) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "memo.json").write_text(
            json.dumps({"cif_dir": cif_dir, "country": ctx.country}), encoding="utf-8"
        )


@pytest.mark.integration
def test_new_format_plugs_in(tmp_path):
    register_output_adapter(_MemoAdapter())
    adapter = get_adapter("memo")
    out_dir = tmp_path / "memo"
    adapter.convert(str(tmp_path / "cif"), str(out_dir), OutputContext(country="JP"))
    data = json.loads((out_dir / "memo.json").read_text())
    assert data["country"] == "JP"
    assert (out_dir / "memo.json").exists()
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python -m pytest tests/integration/test_output_adapter_contract.py -q`
Expected: PASS (the seam already supports this — the test documents/locks the contract).
If it errors on import, fix the import path; the test needs no new production code.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_output_adapter_contract.py
git commit -m "test(output): contract test — new format plugs in via registry"
```

---

### Task 6: Documentation — ADR AD-58 + module README + CLAUDE.md

**Files:**
- Modify: `DESIGN.md` (ADR table + a short §section)
- Modify: `clinosim/modules/output/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add ADR row to DESIGN.md**

Find the ADR table (search `| AD-57 |` or the last `| AD-` row) and add:

```markdown
| AD-58 | 2026-06-17 | **Output-format adapter registry.** CIF→format adapters self-register via `register_output_adapter` (`clinosim/modules/output/adapter.py`); the CLI is registry-driven (`available_formats()` / `get_adapter()`). Adding a format (SS-MIX, FHIR R3, HL7 v2) = add one `OutputAdapter` (`format_id`/`description`/`subdir`/`convert`) — no CLI or core edits. Adapters depend only on CIF + `clinosim.codes` + `clinosim.locale` (AD-17/AD-25). Built-in CSV/FHIR-R4 are thin wrappers (output unchanged). Evolution path: `setuptools` entry-point discovery for external plugin packages. |
```

- [ ] **Step 2: Document "how to add a format" in the output README**

Add a section to `clinosim/modules/output/README.md`:

```markdown
## 出力フォーマットの追加 (AD-58)

新しい出力形式は `OutputAdapter` を1つ登録するだけで追加できる（CLI もコアも無改修）。

```python
from clinosim.modules.output.adapter import OutputContext, register_output_adapter

class SsMixAdapter:
    format_id = "ss-mix"
    description = "SS-MIX2 標準化ストレージ"
    subdir = "ss_mix"
    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        ...  # CIF を読んで out_dir に書き出す（CIF + clinosim.codes + locale のみ依存）

register_output_adapter(SsMixAdapter())
```

`--format ss-mix` で利用可能になる。`OutputContext` は country / narrative_version 等の
共通文脈を渡す。組み込み（csv / fhir-r4）は `adapters_builtin.py`。
```

- [ ] **Step 3: Add the sibling note to CLAUDE.md**

In CLAUDE.md, next to the AD-56 "Add a FHIR resource via register_bundle_builder" bullet,
add:

```markdown
- **Add an output format** by registering an `OutputAdapter` via `register_output_adapter()` (AD-58) — do NOT edit the CLI `--format` dispatch. Adapters read CIF + `clinosim.codes` + `clinosim.locale` only.
```

- [ ] **Step 4: Commit**

```bash
git add DESIGN.md clinosim/modules/output/README.md CLAUDE.md
git commit -m "docs: AD-58 output-format adapter registry"
```

---

### Task 7: Full verification (no regression)

**Files:** none (verification only)

- [ ] **Step 1: Lint + type-check changed files**

Run: `ruff check clinosim/modules/output/adapter.py clinosim/modules/output/adapters_builtin.py clinosim/simulator/cli.py tests/unit/test_output_adapter.py tests/integration/test_output_adapter_contract.py`
Expected: all checks pass (no NEW errors vs master; pre-existing cli.py/adapter errors, if any, unchanged).
Run: `mypy clinosim/modules/output/adapter.py clinosim/modules/output/adapters_builtin.py`
Expected: no new errors.

- [ ] **Step 2: Unit + integration**

Run: `python -m pytest -m unit -q`
Expected: PASS (prior count + the new `test_output_adapter` cases).
Run: `python -m pytest -m integration -q`
Expected: PASS (prior count + the contract test).

- [ ] **Step 3: e2e (no-regression proof — output unchanged)**

Run: `python -m pytest -m e2e -q -p no:cacheprovider`
Expected: PASS (37). If it dies mid-run with exit 1 and no FAILED lines, that is the known
disk/CPU-contention flake — re-run once to confirm green. The wrappers are pass-throughs, so
FHIR/CSV golden output is unchanged.

- [ ] **Step 4: Manual smoke (registry-driven CLI emits identical layout)**

Run: `python -m clinosim.simulator.cli generate -o output/smoke_adapter -p 3000 -s 1 --country US --format cif csv fhir`
Expected: creates `output/smoke_adapter/{cif,csv,fhir_r4}/` (note `fhir` alias → `fhir_r4`).
Run: `python -m clinosim.simulator.cli generate -o /tmp/x -p 100 -s 1 --format bogus 2>&1 | tail -3`
Expected: a clear "Unknown output format 'bogus'. Available: csv, fhir-r4" style error.
Then: `rm -rf output/smoke_adapter` (clean up; do NOT commit output/).

---

## Self-review notes

- **Spec coverage:** interface+registry (Task 1), built-ins/wrappers (Task 2), CLI registry
  dispatch + alias + error (Task 3), export-fhir one-path (Task 4), contract test (Task 5),
  ADR AD-58 + READMEs (Task 6), no-regression incl. e2e (Task 7). Realism/event strategy is
  documentation-only per the spec (covered by the AD-58 text + existing AD-55/56; the event
  registry remains future work and is NOT in this plan by design).
- **Determinism/golden:** unchanged — adapters wrap existing converters; verified by Task 7.
- **Back-compat:** `--format fhir` preserved via alias; output subdirs identical.
