# healthcare_system

Country-specific configuration provider. All other modules depend on this for country-specific parameters.

## Public API

```python
from clinosim.modules.healthcare_system.loader import load_healthcare_config

config = load_healthcare_config("JP")  # returns HealthcareSystemConfig
```

### `load_healthcare_config(country: str) -> HealthcareSystemConfig`
Loads the YAML config for the specified country (`"JP"` or `"US"`).

## Dependencies
- None (leaf module — no imports from other clinosim modules except types)

## Config files
- `src/clinosim/config/japan.yaml` — Japan configuration
- `src/clinosim/config/us.yaml` — US configuration (not yet implemented)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_healthcare_system.py -v
```

## Implementation status
- [x] Japan config YAML (essential params for v0.1-alpha)
- [ ] US config YAML
- [ ] Full parameter set (screening programs, calendar, care transitions)
- [ ] Pydantic validation of all fields
