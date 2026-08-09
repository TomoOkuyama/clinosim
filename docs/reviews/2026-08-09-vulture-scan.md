# vulture semantic dead-code scan — 2026-08-09

**Tool**: [`vulture`](https://github.com/jendrikseipp/vulture) 2.16.

**Scope**: `clinosim/` (production Python code). `tests/` is intentionally
excluded — test files exercise many private symbols through indirection
and produce a large false-positive population that would drown the
signal.

**Threshold**: `--min-confidence 60`. At `--min-confidence 80` the tree
yields only a single finding (`benchmarks/sepsis.py:43 hours`) because
`ruff` F401 (enabled since Issue #635) already sweeps the
unused-imports class that dominates the 80–99 % band.

**Baseline commit**: initial scan on `master` `628326b6e2b`.

**Policy reference**:
[`docs/design-guides/documentation-and-code-quality-policy.md`](../design-guides/documentation-and-code-quality-policy.md)
§6 (dead-code hygiene).

## Summary

| Bucket | Count |
|---|---:|
| Total vulture findings | 310 |
| Kept by design (whitelisted, categorised A–E) | 261 |
| Delete candidates (Category F, temporarily whitelisted; queued for follow-up PR) | 49 |
| Follow-up Issues filed | 0 |

Every finding is now either categorised as a whitelist entry with an
explicit reason, or queued for deletion in a follow-up PR. From now on
the `vulture dead-code` CI job (added by this PR) fails any PR that
introduces a new finding not already covered by the whitelist.

## Whitelist categories

The by-design whitelist at `.vulture-whitelist.py` groups its ~261
"kept" entries under five categories. Each entry carries an inline
comment naming its file / line and the concrete reason it is retained.

| Category | Description | ~count |
|---|---|---:|
| A | dataclass / Pydantic model fields (vulture reports every class-body assignment as "unused variable" because it does not model attribute reads through the instance) | ~205 |
| B | Protocol / ABC method signatures dispatched by duck-typing (e.g. LLM `health_check` / `list_models`; FHIR labs `specimen_material_*`) | ~15 |
| C | Test-only public API (used by files under `tests/`, which vulture does not scan) | ~6 |
| D | Test-referenced module constants (imported by tests for symbolic use in assertions) | ~4 |
| E | Attributes set by simulator, read by output / eval layer through cross-module attribute access | ~19 |

Total roughly 249; a handful of entries span multiple categories (e.g.
Pydantic field that is also written by the simulator), and the exact
per-category count fluctuates by ±5.

## Delete candidates (Category F — pending follow-up PR)

The 49 findings below appear to be genuinely unused after grep
verification across both `clinosim/` and `tests/`: no callers, no test
coverage, no re-exports through `__init__.py`, no `__all__` inclusion.
Where a README mentions the symbol, the mention is the only reference —
API-doc drift, not live coupling.

**A follow-up PR will delete these symbols AND their whitelist entries.**
Byte-diff verification of a golden cohort is required before merge, to
confirm no runtime output changes (dead code should be truly dead).

### Dead classes (3 — 262 LOC)

| Symbol | File:line | LOC | Notes |
|---|---|---:|---|
| `DESEngine` | `simulator/des_engine.py:87` | 245 | Discrete-event simulator engine class. No external references anywhere. |
| `DailyTrajectoryEntry` | `modules/disease/protocol.py:446` | 7 | Pydantic model class. Referenced only in a code comment in `template_generator.py`. |
| `ResidentLike` | `modules/identity/base.py:21` | 10 | Structural `Protocol` never annotated on any function parameter. |

### Dead functions (8 — 175 LOC)

| Symbol | File:line | LOC | Notes |
|---|---|---:|---|
| `generate_encounter_timeline` | `modules/encounter/engine.py:177` | 58 | Only README mentions; no callers. |
| `calculate_imaging_result_time` | `modules/order/engine.py:555` | 49 | Only README mentions; superseded by state-machine variant. |
| `run_consistency_checks` | `modules/validator/consistency.py:55` | 28 | Only README mentions. |
| `format_lab_trends` | `modules/output/hospital_course_extractor.py:561` | 21 | Only README mentions. |
| `load_terminology` | `locale/loader.py:188` | 7 | Only README mentions. |
| `load_formatting` | `locale/loader.py:206` | 4 | Only README mentions. |
| `_generate_name` | `modules/staff/engine.py:324` | 5 | Shadowed by `_generate_name_pair` at the callsites. |
| `get_default_cache` | `modules/document/narrative/cache.py:133` | 3 | No callers. |

### Dead methods on live classes (3)

| Symbol | File:line | Notes |
|---|---|---|
| `LLMService.from_config_file` | `modules/llm_service/engine.py:256` | Superseded by `factory.build_from_config_file`. |
| `_resolve_daily_trajectory` | `modules/document/narrative/template_generator.py:2545` | Attached to `DailyTrajectoryEntry`; deleted with that class. |
| `SimulatorConfig.override` | `types/config.py:245` | No callers. |
| `IdentityRecord.enrollment_on` | `types/identity.py:53` | No callers. |

### Dead attributes / variables (35)

Locals and class attributes never read anywhere. Predominantly clustered
inside `simulator/des_engine.py` (deleted with the class), `simulator/
enumerate.py`, `llm_service/engine.py`, `modules/output/fhir_r4/labs/
coding_package.py`, and `modules/validator/{benchmarks,consistency}.py`.
Full list is in the "Category F" section of `.vulture-whitelist.py`
alongside file:line references.

## Follow-up Issues filed

None. All 49 delete candidates will be handled by the immediate
follow-up PR. If any candidate turns out to be less clear-cut than the
grep suggested (e.g. reflected access discovered during byte-diff
verification), a per-symbol follow-up Issue can be filed at that point.

## Reproduce

```bash
pip install "vulture==2.16"
vulture clinosim/ .vulture-whitelist.py --min-confidence 60
# Expected: exit 0, no output.

# Without the whitelist (raw findings):
vulture clinosim/ --min-confidence 60 --sort-by-size > /tmp/raw.txt
wc -l /tmp/raw.txt
# Expected: 310 lines.
```

## Change history

- **2026-08-09** — Baseline established. Whitelist and CI guard added in
  the PR closing [Issue #636](https://github.com/TomoOkuyama/clinosim/issues/636).
