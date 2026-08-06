"""Shared utilities for AD-55 enricher modules.

Helpers used across multiple modules under ``clinosim/modules/<name>/enricher.py``
that would otherwise be duplicated. Add new cross-module helpers here when
DRY violations appear (and only then — premature centralization is worse than
local duplication).
"""

from __future__ import annotations

from typing import Any

import numpy as np

# ────────────────────────────────────────────────────────────────────
# Cross-writer/reader id markers.

# STOP (discontinuation) order id marker used by daily-loop simulators
# when a treatment-modification archetype discontinues an active
# medication (see ``clinosim/simulator/inpatient.py:1147`` and
# ``sanitize_id_token``'s docstring). FHIR emitters (currently
# ``clinosim/modules/output/_fhir_medications.py``) key on this marker
# to override MedicationRequest.status → ``"stopped"`` (Issue #436;
# session 79 investigation ruled out F1 because reassigning
# ``OrderStatus.STOPPED`` at Order creation shifts ``_generate_mar``'s
# per-order rng cursor and violates AD-16 determinism). Marker
# constant is shared so writer and reader stay in lockstep — the same
# convention as ``ABX_ORDER_ID_PREFIX`` in ``modules/antibiotic/engine.py``.
MED_STOP_ORDER_ID_MARKER: str = "-STOP-"


def is_jp(country: str) -> bool:
    """True when the country code refers to Japan (case-insensitive).

    Canonical JP-gating predicate (common-logic unification, 2026-07-02).
    Replaces the divergent inline idioms (``country == "JP"`` /
    ``country.lower() == "jp"`` / ``str(country).upper() == "JP"``) so every
    module gates on the same normalization.
    """
    return str(country).strip().lower() == "jp"


def is_us(country: str) -> bool:
    """True when the country code refers to the United States (case-insensitive).

    Sibling to ``is_jp``. Locale loaders with only US/JP data files use
    ``is_us(country) or is_jp(country)`` to gate on "supported country" and
    return ``{}`` otherwise, rather than silently falling back to US data
    for an unrecognized country (locale-loader unsupported-country contract,
    2026-07-02 grand design review; ``care_level.load_rates`` is the
    original compliant precedent this generalizes).
    """
    return str(country).strip().lower() == "us"


def resolve_lang(country: str) -> str:
    """Display language for a country: ``"ja"`` for JP, ``"en"`` otherwise.

    Single edit point for the ``lang = "ja" if <country is JP> else "en"``
    selection previously inlined at each FHIR builder / enricher call site.
    """
    return "ja" if is_jp(country) else "en"


def strip_protocol_prefix(name: str) -> tuple[str, str]:
    """Strip protocol/category prefix from drug order text (AD-50).

    "DVT_prophylaxis: Enoxaparin 2000IU SC daily"
        → ("Enoxaparin 2000IU SC daily", "DVT prophylaxis")
    "antipyretic: Acetaminophen 500mg PO q6h PRN temp >= 38.5"
        → ("Acetaminophen 500mg PO q6h PRN temp >= 38.5", "antipyretic")
    "Ceftriaxone 1g IV q8h" → ("Ceftriaxone 1g IV q8h", "")

    Returns (cleaned_name, protocol_category).

    Promoted from ``modules/output/_fhir_common.py`` (β-JP-1 chain 1a adv-1
    I-1): narrative rendering (``modules/document``) needs the same
    normalization as the FHIR medication builders — single edit point per the
    data-logic unification rule. ``_fhir_common._strip_protocol_prefix`` is an
    alias of this function.
    """
    if ":" in name:
        prefix, rest = name.split(":", 1)
        rest = rest.strip()
        if rest:
            return rest, prefix.replace("_", " ").strip()
    return name, ""


_ID_ALLOWED_XLATE = str.maketrans(
    {
        "_": "-",
        " ": "-",
        "/": "-",
        "\\": "-",
        ",": "",
        "(": "",
        ")": "",
        "[": "",
        "]": "",
        ":": "-",
        ";": "",
        "'": "",
        '"': "",
        "&": "and",
        "+": "-",
        "*": "",
        "?": "",
        "!": "",
    }
)


def sanitize_id_token(token: str, max_len: int = 40) -> str:
    """Normalize a free-text fragment into a FHIR R4 ``id``-safe token.

    FHIR R4 ``id`` type restricts to ``[A-Za-z0-9\\-\\.]{1,64}`` — anything
    else in a resource id fails HAPI validator with a hard error. Free-text
    fragments like ``drug_name[:8]`` / ``proc[:8]`` (used to build
    ``ORD-{enc}-STOP-D{day}-...`` order ids in the daily-loop simulators)
    leak underscores, spaces, punctuation, and non-ASCII into id strings.
    This helper is the single source of truth for producing the fragment
    that ends up inside a resource id.

    Session 52 fix (iris4h-ai HAPI FB): 24 Procedure / 3 MedicationRequest /
    2 ServiceRequest ids carried ``NIV_BiPA`` / ``Broad sp`` / ``DIC_p``
    substrings from raw ``drug[:8]`` slices. Route those slices through
    ``sanitize_id_token(name)[:max_len]`` — never truncate first.

    ``max_len`` is a defensive upper bound on the *emitted* fragment (the
    caller still owns the overall id length, which must stay under 64
    characters after joining prefixes / suffixes).
    """
    if not token:
        return ""
    # translate first (may produce empty runs), then drop stray non-ASCII
    t = token.translate(_ID_ALLOWED_XLATE)
    # collapse runs of dashes / dots into single dashes; strip leading/trailing
    out_chars: list[str] = []
    prev_dash = False
    for c in t:
        if c == "-":
            if not prev_dash:
                out_chars.append(c)
                prev_dash = True
            continue
        # any leftover non-safe char → drop (defensive; xlate covers common ones)
        if c.isalnum() or c == ".":
            out_chars.append(c)
            prev_dash = False
    out = "".join(out_chars).strip("-.")
    return out[:max_len]


def select_with_exclusive_classes(
    drug_specs: list[dict],
    exclusive_classes: set[str] | frozenset[str],
    rng: np.random.Generator,
    *,
    independent_mode: str = "bernoulli",
    context: str = "",
) -> list[dict]:
    """Partition drug_specs by ``drug_class`` + ``exclusive_classes``, return
    the drug_specs actually selected for prescription.

    Two selection modes coexist within one call (Issue #432 single-mechanism):

    - **Exclusive class draw**: drugs whose ``drug_class`` is in
      ``exclusive_classes`` are grouped by class, and each class does an
      independent categorical draw across its members' ``probability``
      values. At most one drug per exclusive class is selected. The
      residual mass (``1 - sum(probs)``) becomes a "no drug from this
      class" branch. Sum > 1.0 in an exclusive class is a YAML author
      error and raises ``ValueError`` (fail-loud).

    - **Non-exclusive drugs** (drugs with no ``drug_class`` or whose class
      is not in the exclusive set) are selected per ``independent_mode``:

      * ``"bernoulli"`` (default): independent Bernoulli per drug using its
        ``probability`` field (drugs with probability >= 1.0 always selected).
        Used by population-time activator where per-drug independent draws
        model "some drugs are optional".
      * ``"always"``: include unconditionally, ignoring ``probability``.
        Used by ``_build_discharge_rx`` where the pre-existing legacy
        semantics are "every drug listed for this discharge_oral block is
        prescribed" (byte-compat with disease protocols that predate
        Issue #432 and rely on unconditional emit).

    This helper deliberately does NOT do renal-hold checks, drug-name
    localization (``drug_ja``), item construction, or ``seen`` dedup — those
    differ between callers (activator vs discharge_rx builder) and stay in
    the call sites so the helper stays testable and semantically small.

    Args:
        drug_specs: list of drug spec dicts, each optionally carrying
            ``drug_class: str`` and/or ``probability: float`` fields.
        exclusive_classes: set/frozenset of drug_class labels that must be
            selected mutually exclusively. Empty set = no exclusive draw
            (all drugs go through the independent path).
        rng: seeded numpy Generator (AD-16 determinism).
        independent_mode: ``"bernoulli"`` (default) or ``"always"``.
        context: optional human-readable label included in the fail-loud
            ``ValueError`` message when an exclusive class has probability
            sum > 1.0 (e.g. ``"ICD I48"`` or ``"disease pulmonary_embolism
            discharge_oral"``).

    Returns:
        list of drug_spec dicts (subset of the input, preserving input dict
        identity — no copies). Order: exclusive-class picks first (in the
        order classes were first seen), then non-exclusive picks (in input
        order).

    Raises:
        ValueError: if any exclusive class has ``sum(probabilities) > 1.0``.
    """
    by_exclusive_class: dict[str, list[dict]] = {}
    independent: list[dict] = []
    for spec in drug_specs:
        if not isinstance(spec, dict):
            continue
        cls = spec.get("drug_class")
        if cls and cls in exclusive_classes:
            by_exclusive_class.setdefault(cls, []).append(spec)
        else:
            independent.append(spec)

    selected: list[dict] = []

    # Exclusive-class categorical draws.
    for cls, drugs in by_exclusive_class.items():
        probs = [float(d.get("probability", 1.0)) for d in drugs]
        total = sum(probs)
        if total > 1.0 + 1e-9:
            label = f" ({context})" if context else ""
            raise ValueError(
                f"select_with_exclusive_classes: exclusive_class {cls!r} "
                f"probability sum={total:.3f} > 1.0{label} — invalid categorical distribution"
            )
        weights = probs + [max(0.0, 1.0 - total)]
        idx = int(rng.choice(len(weights), p=weights))
        if idx == len(drugs):
            continue  # residual: no drug from this class
        selected.append(drugs[idx])

    # Non-exclusive drugs.
    if independent_mode == "always":
        selected.extend(independent)
    elif independent_mode == "bernoulli":
        for spec in independent:
            prob = float(spec.get("probability", 1.0))
            if prob < 1.0 and rng.random() >= prob:
                continue
            selected.append(spec)
    else:
        raise ValueError(
            f"select_with_exclusive_classes: independent_mode must be 'bernoulli' or 'always', got {independent_mode!r}"
        )

    return selected


def get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from ``obj`` whether ``obj`` is a dict or has attributes.

    Used by enrichers that consume ``ctx`` / ``ctx.config`` / record objects
    that may arrive as either dataclass instances or dicts depending on
    upstream loaders. Returns ``default`` if the attribute / key is missing
    or if ``obj`` is ``None``.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def set_attr_or_key(obj: Any, name: str, value: Any) -> None:
    """Set ``name`` on ``obj`` whether ``obj`` is a dict or a dataclass instance.

    Write-side counterpart to ``get_attr_or_key``. Replaces the
    ``if isinstance(rec, dict): rec["x"] = value else: rec.x = value``
    branching pattern scattered across enrichers (dual-access sweep, 2026-07-02
    grand design review). For a single top-level field replacement only — for
    nested containers (e.g. a record's ``extensions`` dict) or list
    append/extend, use ``get_or_create_container`` and mutate the returned
    container directly.
    """
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)


def get_or_create_container(obj: Any, name: str, factory: type) -> Any:
    """Get the mutable dict/list field ``name`` off ``obj``, creating it via
    ``factory()`` if ``obj`` is a dict and the key is missing.

    Dataclass instances always have the field already (via
    ``field(default_factory=...)``), so no creation is needed on that path —
    only ``getattr`` is used. The returned container is a plain dict/list
    either way, so callers mutate it directly (``container["k"] = v``,
    ``container.append(item)``, ``container.extend(items)``) without further
    isinstance branching. Composes for nested containers: call again on the
    dict this function just returned to reach a second level (e.g.
    ``extensions`` then a key inside it).
    """
    if isinstance(obj, dict):
        return obj.setdefault(name, factory())
    return getattr(obj, name)


def normalize_probabilities(
    probs: list[float] | np.ndarray,
    fallback: str = "uniform",
) -> np.ndarray:
    """Normalize a non-negative weight vector to sum to 1.0.

    Args:
        probs: array or list of non-negative weights.
        fallback: "uniform" (default) returns equal weight on non-positive sum;
            "raise" raises ValueError instead.

    Conventions (PR-A / Fix #100 / PR #102 2026-06-27 確立):

    - **YAML-sourced callsites MUST use ``fallback="raise"``** so a YAML edit
      accident (e.g. all weights set to 0) is caught loudly at runtime instead
      of silently defaulting to uniform sampling (= PR-90 class silent-no-op).
      All 15 YAML-sourced callsites have been migrated as of 2026-06-27
      (PR #102 added 10 callsites in hai / population / clinical_course;
      pre-PR migration covered 5 in code_status / family_history / care_level
      / observation/microbiology via PR-A Fix #100/#101).
    - **Inline literal weight callsites MAY use ``fallback="uniform"``** (the
      default), since literal weight lists cannot zero out via YAML editing.
    - Upstream validators (``_validate_microbiology``,
      ``_validate_hai_organisms``, ``_validate_demographics``,
      ``_validate_names``, ``_validate_addresses``) catch zero-sum at import
      time as an additional layer of defense (silent-no-op defense triplet:
      canonical constants + upstream validate + backward raise).

    Returns:
        np.ndarray of dtype float64 summing to 1.0.

    Byte-clean migration property: for the typical pre-A3 pattern
    ``arr = np.asarray(probs, dtype=float); arr / arr.sum()`` (numpy
    float64 sum) this helper produces a byte-identical output, because
    ``float(np.float64)`` is bit-preserving for finite values, so the
    divisor bit pattern matches and the resulting float64 array matches.

    NOTE: this is NOT pure idempotency. An input that sums to ``0.9999...``
    in float64 (e.g. ``[0.27, 0.18, 0.16, 0.13, 0.10, 0.06, 0.10]``) is
    NOT returned unchanged; it is divided by ``0.9999...`` and gets a small
    perturbation (~1e-17 per element). The byte-clean property is symmetry
    with the pre-existing code, not identity on already-normalized arrays.

    Raises:
        ValueError: if the input is empty, if any weight is negative, or if the
            input sums to zero and ``fallback="raise"``.
    """
    arr = np.asarray(probs, dtype=float)
    if len(arr) == 0:
        raise ValueError("normalize_probabilities: empty weight vector; cannot normalize")
    if (arr < 0).any():
        raise ValueError(f"normalize_probabilities: negative weight in {list(arr)}")
    total = float(arr.sum())
    if total <= 0:
        if fallback == "uniform":
            n = max(len(arr), 1)
            return np.ones(n) / n
        raise ValueError(f"normalize_probabilities: non-positive sum in {list(arr)}")
    return arr / total
