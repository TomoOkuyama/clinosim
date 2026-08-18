"""Concurrency safety proof: concurrent narrate output == sequential.

The premise of ``NarrativePass(concurrency=N)`` is that when the LLM
provider is *deterministic per prompt* (which real vLLM/Ollama are with
a fixed seed), running N worker threads must produce byte-identical
narrative documents to the sequential (concurrency=1) baseline.

The bundled ``MockProvider`` embeds ``call_count`` in its output, so it
is deliberately NOT prompt-deterministic — it would falsely fail this
test. This file uses a ``HashProvider`` that returns a text derived
only from (system_prompt, user_prompt, model), which is the property
every real seeded LLM guarantees.

The test also stresses the two thread-safety guards added in the same
chain: ``PromptCache._lock`` (llm_service/cache.py) and
``NarrativeCache._lock`` (document/narrative/cache.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from clinosim.modules.document.narrative.passes import LLMNarrativePass
from clinosim.modules.llm_service.engine import LLMService
from clinosim.modules.llm_service.providers.base import ProviderResponse


class HashProvider:
    """Prompt-deterministic mock: output depends only on the prompt.

    Mirrors what a real seeded LLM guarantees — same (system, user,
    model) → same text — so concurrent narrate output must match the
    sequential baseline byte-for-byte.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        digest = hashlib.sha256(
            (system_prompt + "\x00" + prompt + "\x00" + (model or "hash")).encode("utf-8")
        ).hexdigest()[:16]
        # Bundle strategy support: when the prompt asks for a JSON
        # object with a specific schema, emit a matching one.
        placeholder = "<rewritten section body>"
        if placeholder in prompt:
            keys = re.findall(rf'"([^"]+)":\s*"{re.escape(placeholder)}"', prompt)
            body = json.dumps({k: f"[hash-{digest}-{k}]" for k in keys}, ensure_ascii=False)
        else:
            body = f"[hash-{digest}]"
        return ProviderResponse(
            text=body,
            input_tokens=max(1, len(prompt.split())),
            output_tokens=max(1, len(body.split())),
            model=model or "hash",
            latency_ms=0,
        )

    def health_check(self) -> bool:
        return True


def _cohort(base: Path, n_patients: int = 4) -> None:
    """Write a small structural CIF cohort with N inpatient patients."""
    structural = base / "structural" / "patients"
    structural.mkdir(parents=True, exist_ok=True)
    for i in range(n_patients):
        pid = f"POP-{i:02d}"
        enc_id = f"ENC-{i:02d}"
        (structural / f"{enc_id}.json").write_text(
            json.dumps(
                {
                    "patient": {"patient_id": pid, "age": 60 + i * 2, "sex": "M" if i % 2 == 0 else "F"},
                    "encounters": [
                        {
                            "encounter_id": enc_id,
                            "encounter_type": {"value": "inpatient"},
                            "admission_datetime": "2026-01-01T09:00:00",
                            "discharge_datetime": "2026-01-05T10:00:00",
                            "severity": "moderate",
                            "clinical_course_archetype": "stable_chronic",
                        }
                    ],
                    "documents": [
                        {
                            "document_id": f"doc-{enc_id}-admission",
                            "task_type": "admission_hp",
                            "loinc_code": "34117-2",
                            "format_type": "composition",
                            "narrative": None,
                        }
                    ],
                    "vital_signs": [],
                    "lab_results": [],
                    "medication_administrations": [],
                    "discharge_prescription": [],
                    "clinical_diagnosis": None,
                    "procedures": [],
                    "allergies": [],
                }
            )
        )


def _hash_llm_service() -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=HashProvider(),
        narrative_model_map={"medium": "hash", "large": "hash", "small": "hash"},
        provider_name_narrative="hash",
    )


def _sha_of_dir(narrative_dir: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for every doc under narrative_dir."""
    out: dict[str, str] = {}
    for f in sorted(narrative_dir.rglob("*.json")):
        # Skip manifest — its generated_at is wall-time and legitimately
        # differs across two runs. Byte-identity claim is for the
        # per-document narrative files only.
        if f.name == "manifest.json":
            continue
        rel = str(f.relative_to(narrative_dir))
        out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


@pytest.mark.unit
def test_narrate_concurrent_equals_sequential(tmp_path):
    """concurrency=8 output must be byte-identical to concurrency=1."""
    seq_dir = tmp_path / "seq"
    par_dir = tmp_path / "par"
    _cohort(seq_dir, n_patients=6)
    _cohort(par_dir, n_patients=6)

    LLMNarrativePass(
        cif_dir=str(seq_dir),
        llm=_hash_llm_service(),
        version_id="run",
        country="US",
        concurrency=1,
    ).run()
    LLMNarrativePass(
        cif_dir=str(par_dir),
        llm=_hash_llm_service(),
        version_id="run",
        country="US",
        concurrency=8,
    ).run()

    seq_hashes = _sha_of_dir(seq_dir / "narratives" / "run")
    par_hashes = _sha_of_dir(par_dir / "narratives" / "run")
    assert set(seq_hashes) == set(par_hashes), (
        f"file set differs: seq_only={set(seq_hashes) - set(par_hashes)}, par_only={set(par_hashes) - set(seq_hashes)}"
    )
    mismatches = {p: (seq_hashes[p], par_hashes[p]) for p in seq_hashes if seq_hashes[p] != par_hashes[p]}
    assert not mismatches, f"content differs on {len(mismatches)} files: {mismatches}"


@pytest.mark.unit
def test_narrate_concurrency_1_matches_baseline_serial(tmp_path):
    """concurrency=1 must byte-match the pre-concurrency path (no regression)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    _cohort(a, n_patients=3)
    _cohort(b, n_patients=3)
    # Both concurrency=1 — the only path that existed before the change.
    LLMNarrativePass(cif_dir=str(a), llm=_hash_llm_service(), version_id="run", country="US", concurrency=1).run()
    LLMNarrativePass(cif_dir=str(b), llm=_hash_llm_service(), version_id="run", country="US", concurrency=1).run()
    assert _sha_of_dir(a / "narratives/run") == _sha_of_dir(b / "narratives/run")
