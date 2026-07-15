"""Configuration types. Loaded from YAML, validated by Pydantic (AD-18)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class HealthcareSystemConfig(BaseModel):
    """Country-specific configuration. Loaded from healthcare_system/configs/{country}.yaml."""

    country: str  # "JP" | "US"

    # Clinical practice
    lab_frequency_multiplier: float = 1.0
    discharge_criteria: str = "lab_normalization"
    target_los_multiplier: float = 1.0

    # Coding systems
    diagnosis_code_system: str = "ICD-10"
    drug_code_system: str = "YJ"
    lab_code_system: str = "JLAC10"
    procedure_code_system: str = "K-code"


class LLMProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    provider: str = "none"  # "bedrock_gateway" | "anthropic_direct" | "openai_compatible" | "local" | "none"
    mode: str = "none"  # "llm" | "template" | "none"

    # Model tier mapping (clinosim tier → actual model ID)
    model_map: dict[str, str] = {
        "small": "",
        "medium": "",
        "large": "",
    }

    # Provider-specific settings (keyed by provider name)
    bedrock_gateway: dict = {}  # url, api_key_env, timeout_seconds, ...
    anthropic_direct: dict = {}  # api_key_env, ...
    openai_compatible: dict = {}  # base_url, api_key_env, model, ...
    local: dict = {}  # endpoint, model, ...

    # Resilience
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_backoff_seconds: float = 2.0

    # Budget
    max_tokens_per_run: int | None = None
    fallback_on_budget_exceeded: str = "template"


class LLMServiceConfig(BaseModel):
    """LLM configuration with separate JUDGMENT and NARRATIVE providers."""

    judgment: LLMProviderConfig = LLMProviderConfig()
    narrative: LLMProviderConfig = LLMProviderConfig()

    # Shared cache settings
    cache_enabled: bool = True
    cache_max_entries: int = 5000
    cache_persist_to_disk: bool = True


class ForcedScenario(BaseModel):
    """Force generation of a specific clinical scenario."""

    disease_id: str
    count: int = 1
    severity: str | None = None  # "mild" | "moderate" | "severe" — None = random
    archetype: str | None = None  # force specific archetype — None = random selection
    complications: list[str] = []  # force specific complications to occur
    patient_overrides: dict = {}  # override patient attributes: {"age": 82, "sex": "M", ...}

    # PR3b-1 Task 7b: deterministically force one HAI event per matching device.
    # Shape: {"hai_type": "cauti", "onset_offset_days": 3,
    #         "organism_snomed": "112283007"}. None = use stochastic Poisson sampling.
    # hai_type must be in HAI_TYPES (validated by enrich_hai at consume time).
    force_hai_event: dict | None = None


# --- AD-66 α-min-2c: Canonical Patient Profile fixture library ---

_PATIENT_PROFILE_DIR: Path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "patient_profiles"


class PatientProfile(BaseModel):
    """Canonical patient scenario fixture for narrative regression testing (α-min-2c, AD-66).

    Loaded from tests/fixtures/patient_profiles/<name>.yaml. Transformed to
    ForcedScenario at CLI dispatch via .to_forced_scenario(). β-JP-1 extends
    with LLM-specific fields (llm_seed, expected_sections, ...).
    """

    model_config = {"extra": "forbid"}

    # Identity
    profile_id: str

    # Simulation inputs
    disease_id: str
    country: Literal["US", "JP"] = "US"
    severity: Literal["mild", "moderate", "severe"] | None = None
    archetype: str | None = None
    count: int = 1
    random_seed: int = 42
    hospital_scale: Literal["small", "medium", "large"] = "medium"

    # Optional overrides
    patient_overrides: dict = {}
    force_hai_event: dict | None = None
    # NOTE (adv-1 F-1): `chronic_medications` and `time_range` were removed as
    # unwired fields — nothing consumed them (to_forced_scenario() omitted both,
    # CLI built SimulatorConfig without time_range), so declaring them defeated
    # the extra=forbid typo defense: a profile author setting them got a silent
    # no-op (PR-90 class). extra=forbid now rejects them loudly at load time.
    # β-JP-1 should re-add them together WITH actual consumption.

    # Documentation
    description: str = ""
    clinical_notes: str = ""

    def to_forced_scenario(self) -> ForcedScenario:
        return ForcedScenario(
            disease_id=self.disease_id,
            count=self.count,
            severity=self.severity,
            archetype=self.archetype,
            patient_overrides=self.patient_overrides,
            force_hai_event=self.force_hai_event,
        )


def load_patient_profile(name_or_path: str) -> PatientProfile:
    """Resolve a patient profile by name or absolute path.

    - If ``name_or_path`` exists as a file → load directly.
    - Otherwise → resolve as ``tests/fixtures/patient_profiles/<name>.yaml``.

    Raises:
        FileNotFoundError: unresolvable name / missing file
        pydantic.ValidationError: schema mismatch (extra keys, wrong types, etc.)
        ValueError: profile_id does not match filename stem
    """
    import yaml

    p = Path(name_or_path)
    if not p.is_file():
        p = _PATIENT_PROFILE_DIR / f"{name_or_path}.yaml"
        if not p.is_file():
            raise FileNotFoundError(
                f"patient profile not found: {name_or_path!r} (looked in {_PATIENT_PROFILE_DIR} and as literal path)"
            )

    data = yaml.safe_load(p.read_text())
    profile = PatientProfile(**data)

    expected_stem = p.stem
    if profile.profile_id != expected_stem:
        raise ValueError(
            f"profile_id {profile.profile_id!r} does not match filename stem "
            f"{expected_stem!r} in {p} (silent-no-op defense)"
        )

    return profile


class SimulatorConfig(BaseModel):
    """Top-level simulation configuration (AD-19: preset + override)."""

    mode: str = "patient_record"
    country: str = "US"  # default: US (English). Use "JP" for Japanese.
    hospital_scale: str = "medium"
    disease_modules: list[str] = ["bacterial_pneumonia"]
    # None = use hospital's recommended_population (see hospital_operations.yaml).
    # Explicit int = honored as-is (Bug D fix: previously a `== 10_000` sentinel
    # silently replaced any explicit CLI value that happened to equal the old
    # argparse default, dropping user-requested population sizes).
    catchment_population: int | None = None
    random_seed: int = 42
    time_range: tuple[str, str] = ("2024-04-01", "2025-03-31")
    snapshot_date: str | None = None  # YYYY-MM-DD; ongoing inpatients have no discharge_datetime as of this date
    cif_format: str = "json"  # "json" | "msgpack" | "parquet"
    # (JP only, AD-54) Include Japanese insurance enrollment / 被保険者番号 (FHIR Coverage).
    # No effect for non-JP countries.
    jp_insurance_numbers: bool = True

    # (AD-56) Opt-in module enablement, e.g. {"billing": True, "device": False}.
    # Scales without adding one boolean per module. Query via module_enabled().
    modules: dict[str, bool] = {}

    llm: LLMServiceConfig = LLMServiceConfig()

    # Force specific scenarios (in addition to population-generated ones)
    forced_scenarios: list[ForcedScenario] = []

    @classmethod
    def preset(cls, name: str) -> SimulatorConfig:
        presets: dict[str, dict] = {
            "japan_medium": {
                "country": "JP",
                "hospital_scale": "medium",
                "catchment_population": 100_000,
            },
            "japan_small": {
                "country": "JP",
                "hospital_scale": "small",
                "catchment_population": 20_000,
            },
            "japan_large": {
                "country": "JP",
                "hospital_scale": "large",
                "catchment_population": 300_000,
            },
            "us_medium": {
                "country": "US",
                "hospital_scale": "medium",
                "catchment_population": 100_000,
            },
        }
        return cls(**presets[name])

    def module_enabled(self, name: str, default: bool = False) -> bool:
        """Whether an opt-in module is enabled (AD-56). See `modules`."""
        return self.modules.get(name, default)

    def override(self, overrides: dict) -> SimulatorConfig:
        data = self.model_dump()
        for key, value in overrides.items():
            # Support dot notation: "llm.judgment.mode" → nested update
            parts = key.split(".")
            target = data
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        return SimulatorConfig(**data)
