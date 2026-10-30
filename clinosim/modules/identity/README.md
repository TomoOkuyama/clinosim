# `clinosim.modules.identity` — resident identifier and insurance numbering

## Purpose

Runs a POST_POPULATION numbering pass that attaches an
`IdentityTimeline` (national identity + insurance enrollment) to every
resident produced by
[`clinosim.modules.population`](../population/README.md). Country-
specific numbering rules live behind an `IdentityProvider` Protocol
so adding a new country is a provider file + one locale YAML — no
engine changes (AD-54).

## Scope

- **In scope**: household-scoped insurance numbering (shared 記号 /
  member id + per-member 枝番) and per-individual national identity
  (JP マイナンバー-style personal ID + マイナ保険証 holding), plus
  the shared per-household latent draw used to give マイナ保険証
  holding a realistic intra-household correlation.
- **Active providers**: JP and US. The US provider (Issue #1107)
  samples one age-banded `InsuranceEnrollment` per member from
  `locale/us/identity.yaml` `sampling.insurance_distribution` (age 65+
  forced to a Medicare category, synthetic 11-digit member id, no
  group symbol / branch number); `assign_personal` returns a bare
  `NationalIdentity(country="US")` — no SSN is generated. The legacy
  `insurance_type` string is still sampled separately in
  [`clinosim.modules.patient.activator`](../patient/README.md). The
  enricher is `enabled=lambda c: c.jp_insurance_numbers if
  is_jp(c.country) else True`, so JP honours the `--no-jp-insurance`
  opt-out and US always runs.
- **Mid-sim newborns** (Issue #1581): `assign_identity_for_person`
  gives a single person the same identity timeline, reusing the
  household latent persisted on `Household.identity_latent`; called
  from `clinosim/modules/population/person_init.py` when a newborn is
  registered.
- **Out of scope**: name / address / date-of-birth generation
  ([`clinosim.modules.population`](../population/README.md) +
  [`clinosim/locale/<country>/`](../../locale/)), practitioner IDs
  ([`clinosim.modules.staff`](../staff/README.md)), FHIR serialisation
  ([`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.identity import (
    assign_identities,           # (registry, country, master_seed) -> None (mutates)
    get_provider,                # (country) -> IdentityProvider (JP or US)
)
from clinosim.modules.identity.assign import (
    assign_identity_for_person,  # (registry, person, country, master_seed) -> None (mutates; newborns)
)
```

Two internal Protocol types are the extension seam:

- `ResidentLike` (in `base.py`) — structural minimum a provider
  needs (`person_id`, `household_id`, `age`, `sex`, `date_of_birth`,
  `occupation`). Used specifically so this module never imports
  from `clinosim.modules.population`.
- `IdentityProvider` (in `base.py`) — country-specific numbering
  contract: `assign_household(members, rng, config)` returns a
  `{person_id: InsuranceEnrollment}` map, and
  `assign_personal(member, household_latent, rng, config)` returns
  a per-member `NationalIdentity`.

`providers/` intentionally has no dedicated README — the country-
plugin dispatch pattern and the `IdentityProvider` contract are
documented above; a per-directory README would only duplicate that
content.

## Determinism

- Sub-seed offset `540_054` (decimal, grandfathered — the identity
  seed pre-dates the hex-ASCII convention and stays as-is to preserve
  cross-cursor byte-identity). Registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["identity"]`.
- One RNG per run: `master_seed + ENRICHER_SEED_OFFSETS["identity"]`
  (simple addition, not `derive_sub_seed`), consumed sequentially
  household by household. The main patient RNG stream is not
  disturbed (AD-16).
- `assign_identity_for_person` uses its own per-person RNG
  (`int(sha256(f"{master_seed}|identity_person|{person_id}|v1")[:4]) +
  master_seed + ENRICHER_SEED_OFFSETS["identity"]`), so it never
  consumes from the batch stream.
- Per household, a single `rng.standard_normal()` draw
  (`household_latent`, persisted on `Household.identity_latent`) is
  passed to every member; JP's Gaussian-copula
  card-holding model uses it to preserve marginal age-banded rates
  exactly while giving intra-household correlation.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `is_us` (canonical country
  predicates).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`.
- `clinosim.types` — `IdentityTimeline`, `NationalIdentity`,
  `InsuranceEnrollment` (imported from `clinosim.types`).
- `clinosim.locale.loader` — `load_identity_config(country)` (loads
  `clinosim/locale/<country>/identity.yaml`).
- `numpy` — `np.random.Generator`, `standard_normal`.
- **Not depended on**: `clinosim.modules.population`, which is
  structurally typed via `ResidentLike`.

## Constants and configuration

- Registry (in `registry.py`): `_SUPPORTED = {"JP", "US"}`. Any other
  country → `ValueError` in `get_provider`. `is_jp` / `is_us` are the
  canonical case-insensitive predicates; a raw `country == "JP"`
  comparison is a FP-UNIFY-4 anti-pattern.
- Locale YAML: [`clinosim/locale/jp/identity.yaml`](../../locale/jp/identity.yaml)
  — age-banded rates for マイナンバー card holding + マイナ保険証
  registration, insurer scheme distributions, `household_icc` for
  the Gaussian-copula intra-household correlation.
  [`clinosim/locale/us/identity.yaml`](../../locale/us/identity.yaml)
  — age-banded `sampling.insurance_distribution` + `payers`. A
  country without an `identity.yaml` makes `assign_identities` return
  early.
- Number generators (in `generators.py`):
  - `my_number(rng)` — 12-digit 個人番号 with valid check digit
    computed by `my_number_check_digit(base11)` (formula:
    `11 - ((Σ P_n·Q_n) mod 11)`, `0` when remainder ≤ 1).
  - `insurer_number(houbetsu, prefecture, serial, *, national=False)`
    — 8-digit 保険者番号 (employee / late-elderly) or 6-digit
    (国保); trailing mod-10 check digit via `mod10_check_digit`.
  - `mod10_check_digit(body)` — modulus-10 (weights 2, 1, 2, 1 from
    the right; product digits summed). Marked `# TODO: verify`
    against official spec.
  - `numeric_id(rng, width)` — zero-padded random numeric ID.
  - `branch_number(index)` — 2-digit 枝番 (individual within a
    被保険者 record).

## Directory contents

```
clinosim/modules/identity/
  __init__.py                     public API (get_provider + assign_identities)
  assign.py                       assign_identities POST_POPULATION pass + assign_identity_for_person (newborns)
  base.py                         ResidentLike + IdentityProvider Protocols
  generators.py                   my_number / mod10 / insurer_number / …
  registry.py                     country → provider dispatch (JP / US)
  providers/
    __init__.py                   re-exports JPIdentityProvider + USIdentityProvider
    jp.py                         JP numbering rules + card-holding copula
    us.py                         US age-banded insurance enrollment (Issue #1107); no national ID
```

The module has **no `enricher.py`, no `audit.py`, no `reference_data/`**
— reference data lives in `clinosim/locale/{jp,us}/identity.yaml`, and the
enricher entry point is `assign_identities` in `assign.py`.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) under
`register_builtin_enrichers`:

- `name="identity"`, `stage=POST_POPULATION`, `order=10`,
  `enabled=lambda c: c.jp_insurance_numbers if is_jp(c.country) else True`.
- Runs early in the population pass; it ties with `allergy` at
  order 10 (sorted by name, so `allergy` runs first) and precedes the
  later POST_POPULATION enrichers.
- The `run` lambda passes `ctx.population`, `ctx.config.country`, and
  `ctx.master_seed` — the enricher is stateless.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:144-152`](../../simulator/enrichers.py) | POST_POPULATION order=10 registration. |
| `PersonRecord.identity` field | [`clinosim/types/population.py:98`](../../types/population.py) | Downstream code reads `person.identity.national` and `person.identity.enrollments` after the pass runs. |
| FHIR `Patient` / `Coverage` builders | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | Emit マイナンバー-style identifiers on `Patient` and insurance-card data (JP) / payer enrollment (US) on `Coverage`. |
| Newborn registration | [`clinosim/modules/population/person_init.py`](../population/person_init.py) | Calls `assign_identity_for_person` for mid-sim newborns (Issue #1581). |

## Testing

```bash
pytest tests/unit -k identity -q         # provider + generators + assign_identities
pytest tests/e2e -k identity_jp -q       # JP-locale end-to-end
```

Individual files:

- [`tests/unit/test_identity.py`](../../../tests/unit/test_identity.py)
  — provider dispatch, `assign_identities` idempotency + determinism,
  number-generator check-digit verification.
- [`tests/e2e/test_identity_jp.py`](../../../tests/e2e/test_identity_jp.py)
  — JP cohort end-to-end (household sharing, card-holding rates,
  insurer distribution).
- [`tests/unit/test_fhir_coverage.py`](../../../tests/unit/test_fhir_coverage.py)
  — Coverage emit from enrollments.
- [`tests/unit/modules/population/test_newborn_registration_1564.py`](../../../tests/unit/modules/population/test_newborn_registration_1564.py)
  — newborn identity via `assign_identity_for_person`.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
