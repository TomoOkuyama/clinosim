# clinosim Development Guidelines

## Project overview

clinosim is a population-driven, physiology-based synthetic EHR data simulator.
See `DESIGN.md` for full architecture, `TODO.md` for roadmap, `modules/INTERFACES.md` for data type contracts.

## Language

- Code: Python 3.11+
- Code comments and docstrings: English
- README.md: Japanese (top sections) + English
- All other documentation (SPEC.md, DESIGN.md, TODO.md, INTERFACES.md): English
- Communication with user: Japanese

## Code standards

- Formatter: ruff
- Type checking: mypy (strict mode)
- Line length: 100
- Types: Pydantic BaseModel for YAML-loaded configs (AD-18). @dataclass for runtime types.
- All types defined in `clinosim/types/` — never define data types inside module code.

## Architecture rules

- **INTERFACES.md is the contract** — all inter-module data types must be defined there (design phase) or in `clinosim/types/` (implementation).
- **Module independence** — each module under `clinosim/modules/` can only depend on types and other modules listed in its SPEC.md Dependencies section.
- **LLM calls only via llm_service** (AD-11) — no other module may call any LLM API directly.
- **CIF is the only simulation output** (AD-17) — format adapters (FHIR, CSV) read CIF, never simulation internals.
- **Deterministic with seed** (AD-16) — each module creates its own `numpy.random.Generator` from its sub-seed. Never use `random.random()` or shared global state.

## Testing

- `make test-unit` — per-module unit tests (<30s)
- `make test-integration` — module chain tests (<5min)
- `make test-e2e` — golden file comparison (<30min)
- Always run `make test-unit` before committing.

## When modifying a module

1. Read the module's SPEC.md first
2. Make changes
3. Check README.md dependency matrix — verify affected modules
4. Update affected modules' SPEC.md if needed
5. Update INTERFACES.md (or types/*.py) if data types changed
6. Run tests

## Current implementation phase

**v0.1-alpha** — see TODO.md for the 12-task plan. Goal: 1 pneumonia patient, 14-day inpatient, CIF JSON output.

## Key directories

```
clinosim/
  types/          <- All data type definitions
  modules/        <- Module implementations (one package per module)
  config/         <- Default YAML configurations
tests/            <- Test code
```

## LLM setup

Default: local Ollama (no API key or cloud account needed).

```bash
# Install Ollama
brew install ollama    # macOS
# or: curl -fsSL https://ollama.com/install.sh | sh   # Linux

# Pull the default model
ollama pull llama3.1:8b

# (Optional) Higher quality model for narratives (requires ~40GB VRAM)
ollama pull llama3.1:70b
```

Config files:
- `clinosim/config/llm_service.yaml` — default (local Ollama)
- `clinosim/config/llm_service.cloud.yaml` — cloud (Anthropic API, needs ANTHROPIC_API_KEY)

JUDGMENT and NARRATIVE can use different providers (AD-24). See `modules/llm_service/SPEC.md` for details.

## Disease protocol YAML files

Located at `modules/disease/reference_data/`. Validated by Pydantic models at load time.
Adding a new disease = adding a new YAML file. No code changes to the engine.
