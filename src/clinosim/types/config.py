"""Configuration types. Loaded from YAML, validated by Pydantic (AD-18)."""

from __future__ import annotations

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


class SimulatorConfig(BaseModel):
    """Top-level simulation configuration (AD-19: preset + override)."""

    mode: str = "patient_record"
    country: str = "JP"
    hospital_scale: str = "medium"
    disease_modules: list[str] = ["bacterial_pneumonia"]
    catchment_population: int = 50_000
    random_seed: int = 42
    time_range: tuple[str, str] = ("2024-04-01", "2025-03-31")
    cif_format: str = "json"  # "json" | "msgpack" | "parquet"

    llm: LLMServiceConfig = LLMServiceConfig()

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
