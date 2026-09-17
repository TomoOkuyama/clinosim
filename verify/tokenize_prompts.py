"""Pre-boot tokenizer precount for narrate throughput investigation.

Measures the system: block token count for each Case's prompt yaml using
the Qwen3.8-27B-FP8 tokenizer (same as vLLM inference).

Output: verify/tokens_precount.json

Factor A (JA vs EN system prompt language) is bounded above by the token
difference between v22 JA and Case A' (EN scaffold) system blocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

# Qwen3.8-27B-FP8 uses the same tokenizer as Qwen2.5 base.
# We use AutoTokenizer to load whatever local cache has, falling back to
# a manual estimate if the model weights are not cached locally.
try:
    from transformers import AutoTokenizer

    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False


HERE = Path(__file__).parent
CASES = {
    "v22_ja_current": HERE / "v22_prompt_ja.yaml",
    "v22_en_case_a_prime": HERE / "v22_prompt_en.yaml",
    "v21_ja_case_e": HERE / "v21_prompt_ja.yaml",
    "v22_en_us_original": HERE / "v22_prompt_en_original.yaml",
}

TOKENIZER_CANDIDATES = [
    # Try the exact model first (may not be cached locally on Mac)
    "Qwen/Qwen3-8B",  # closest publicly available shape
    "Qwen/Qwen2.5-7B-Instruct",  # fallback
]


def load_tokenizer():
    if not _HF_AVAILABLE:
        return None
    for name in TOKENIZER_CANDIDATES:
        try:
            tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
            return tok, name
        except Exception as e:
            print(f"  ! tokenizer {name} not available: {type(e).__name__}: {e}")
    return None, None


def count_tokens_naive(text: str) -> int:
    """Fallback: rough char-based estimate.

    Qwen tokenizer for Japanese: ~0.6-0.8 tokens per char.
    For English: ~0.25 tokens per char.
    We use 0.5 as a language-agnostic rough estimate, but this is
    ONLY used if HuggingFace tokenizer is not available.
    """
    return int(len(text) * 0.5)


def analyze(case: str, path: Path, tokenizer=None) -> dict:
    doc = yaml.safe_load(path.read_text())
    system = doc.get("system", "")
    user_template = doc.get("user_template", "")
    description = doc.get("description", "")

    result = {
        "case": case,
        "path": str(path.relative_to(HERE.parent)),
        "version": doc.get("version"),
        "system_chars": len(system),
        "system_lines": system.count("\n") + 1,
        "user_template_chars": len(user_template),
        "description_chars_NOT_SENT": len(description),
    }

    if tokenizer is not None:
        result["system_tokens"] = len(tokenizer.encode(system))
        result["user_template_tokens"] = len(tokenizer.encode(user_template))
        result["tokenizer_source"] = "huggingface"
    else:
        result["system_tokens_estimate"] = count_tokens_naive(system)
        result["user_template_tokens_estimate"] = count_tokens_naive(user_template)
        result["tokenizer_source"] = "char_estimate_fallback"

    return result


def main() -> None:
    tok, tok_name = None, None
    if _HF_AVAILABLE:
        tok, tok_name = load_tokenizer()

    if tok is None:
        print("WARNING: no HuggingFace tokenizer available. Using char-based estimate.")
        print("         Rerun with `pip install transformers` and cached weights for accuracy.")
    else:
        print(f"tokenizer: {tok_name}")

    results = {}
    for case, path in CASES.items():
        if not path.exists():
            print(f"  ! missing: {path}")
            continue
        results[case] = analyze(case, path, tokenizer=tok)
        r = results[case]
        tok_key = "system_tokens" if "system_tokens" in r else "system_tokens_estimate"
        print(
            f"  {case:32s} v{r['version']:3d}  "
            f"system {r['system_chars']:6d} chars / {r[tok_key]:5d} tokens  "
            f"({r['system_lines']} lines)"
        )

    out = {
        "tokenizer": tok_name if tok else "char_estimate_fallback",
        "cases": results,
        "factor_a_bound_tokens": None,
    }
    if "v22_ja_current" in results and "v22_en_case_a_prime" in results:
        ja = results["v22_ja_current"]
        en = results["v22_en_case_a_prime"]
        tk = "system_tokens" if "system_tokens" in ja else "system_tokens_estimate"
        out["factor_a_bound_tokens"] = ja[tk] - en[tk]
        pct = 100.0 * out["factor_a_bound_tokens"] / ja[tk]
        print(
            f"\nFactor A upper bound (JA v22 - EN Case A'): "
            f"{out['factor_a_bound_tokens']} tokens ({pct:+.1f}% of v22 JA system block)"
        )
    if "v22_ja_current" in results and "v21_ja_case_e" in results:
        v22 = results["v22_ja_current"]
        v21 = results["v21_ja_case_e"]
        tk = "system_tokens" if "system_tokens" in v22 else "system_tokens_estimate"
        out["factor_bc_bound_tokens"] = v22[tk] - v21[tk]
        pct = 100.0 * out["factor_bc_bound_tokens"] / v22[tk]
        print(
            f"Factor B/C upper bound (JA v22 - JA v21):   "
            f"{out['factor_bc_bound_tokens']} tokens ({pct:+.1f}% of v22 JA system block)"
        )

    (HERE / "tokens_precount.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nsaved: verify/tokens_precount.json")


if __name__ == "__main__":
    main()
