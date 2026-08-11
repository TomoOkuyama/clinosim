# `clinosim.modules.identity` — patient identifiers and insurance records

## Purpose

Generates deterministic, country-appropriate patient identifiers
(MRN, insurance card / member ID, national ID where modelled) and
insurance-coverage records that downstream FHIR builders emit as
`Patient.identifier`, `Coverage`, and (for JP) マイナンバー-related
resources.

## Scope

- **In scope**: MRN generation with per-country format, insurance
  member-ID generation, JP マイナンバー / マイナ保険証 status flags,
  insurance-enrollment date arithmetic, `PatientProfile.identifiers`
  population.
- **Out of scope**: address / name / date-of-birth generation (in
  [`clinosim/modules/population/`](../population/README.md)),
  practitioner IDs (in [`clinosim/modules/staff/`](../staff/README.md)),
  FHIR serialisation (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.identity import (
    build_identifiers,           # (patient, country, rng) -> IdentityBundle
    ResidentLike,                # structural Protocol (see below)
)
from clinosim.modules.identity.providers import get_provider
```

Providers are chosen by country. Each provider implements
`build_identifiers`; new countries add a new provider file under
`providers/`.

> **Note:** `providers/` intentionally has no dedicated README. The
> country-plugin dispatch pattern and the `build_identifiers`
> contract are documented in the paragraph above; a per-directory
> README would duplicate that content.

## Structural typing

`ResidentLike` is a `typing.Protocol` in `base.py` that describes the
minimal patient shape the identity providers need — kept as a Protocol
so this module does not have to import from `clinosim.modules.population`.

## Dependencies

- `clinosim.types.identity` — `NationalIdentity`, `InsuranceCoverage`,
  identity-record dataclasses.
- `clinosim.types.patient` — `PatientProfile.identifiers`.
- `clinosim.simulator.helpers` — sub-seed derivation.
- No dependency on `clinosim.modules.population`
  (structurally typed via `ResidentLike`).

## Constants and configuration

- JP-specific flags in `types/identity.py`:
  - `has_id_card` — JP マイナンバーカード possession.
  - `id_card_linked_to_insurance` — JP マイナ保険証 registration.
- Provider-specific format constants live inside each provider
  (`providers/us.py`, `providers/jp.py`).

## Directory contents

```
clinosim/modules/identity/
  __init__.py               public API
  base.py                   ResidentLike Protocol + shared helpers
  audit.py                  per-module audit spec
  providers/
    __init__.py             registry
    us.py                   US MRN + insurance-member-ID
    jp.py                   JP MRN + マイナ保険証 + insurance-card fields
```

## Testing

```bash
pytest tests/unit -k identity -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
