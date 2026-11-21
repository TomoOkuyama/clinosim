"""The recipient of a 診療情報提供書, chosen once for the narrative and FHIR (Issue #3460).

The letter's 紹介先 (910) section names an institution of the country's
external-organization catalog. The narrative section and the FHIR Composition
both read it from :func:`pick_external_hospital`, so a letter names the same
institution in both. The pick is a sha256 modulo (RNG-neutral): the same
``(patient_id, encounter_id)`` resolves to the same catalog row everywhere.
The addressee physician is not in the CIF, so the letter is addressed to the
institution's 御担当医 rather than to an invented name.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.determinism import sha_index
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_external_organizations

_REF_FILE = Path(__file__).resolve().parent / "reference_data" / "referral_recipients.yaml"

# Sampling salt: distinct from any other per-encounter derived value.
_REFERRAL_SAMPLING_SALT = "referral-external-hospital"


class ReferralRecipientsConfig(BaseModel):
    """Shape of referral_recipients.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: dict[str, Any] = Field(default_factory=dict)
    transfer_dispositions: tuple[str, ...]
    recipient_types: tuple[str, ...]


@lru_cache(maxsize=1)
def referral_recipients_config() -> ReferralRecipientsConfig:
    """The validated ``referral_recipients.yaml`` (shared, read-only)."""
    return ReferralRecipientsConfig.model_validate(load_data_yaml(_REF_FILE))


def is_transfer_disposition(disposition: Any) -> bool:
    """Whether a discharge with this ``discharge_disposition`` moves the
    patient's care to another provider."""
    return str(getattr(disposition, "value", disposition) or "") in referral_recipients_config().transfer_dispositions


@lru_cache(maxsize=8)
def _catalog(country: str) -> list[dict[str, Any]]:
    """The country's external hospital catalog (cached)."""
    return load_external_organizations(country)


def pick_external_hospital(patient_id: str, encounter_id: str, country: str) -> dict[str, Any] | None:
    """The institution a referral letter is addressed to, deterministic on
    ``(patient_id, encounter_id)``.

    ``None`` when the country has no catalog (US today) or no entry of an
    allowed ``recipient_types``; callers state no recipient then.
    """
    allowed = referral_recipients_config().recipient_types
    catalog = [e for e in _catalog(country) if e.get("type") in allowed]
    if not catalog:
        return None
    return catalog[sha_index(f"{patient_id}::{encounter_id}::{_REFERRAL_SAMPLING_SALT}", len(catalog))]


def format_referral_destination_text(entry: dict[str, Any], lang: str) -> str:
    """The 910 (紹介先) section sentence: the institution and its 御担当医."""
    return t("referral_fhir.destination_sentence", lang, name=entry.get("name") or entry["id"])
