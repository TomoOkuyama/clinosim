"""Issue #455: a drug block's absent-`route` fallback must not contradict the entry's
own dose string.

`clinosim/simulator/inpatient.py` substitutes a route when a drug entry omits the
``route`` key. Two blocks have a reader that does this, each with a different default:

* ``drugs.discharge_oral``  -> ``"PO"``  (``_build_discharge_rx._append_item``)
* ``drugs.escalation``      -> ``"IV"``  (escalation order placement)

The substitution is a *grounded inference* for the majority of entries: for
``discharge_oral`` the block is named "oral" and the dose string usually says ``PO``;
for ``escalation`` the dose string usually says ``IV``. It becomes a **false assertion**
only when the dose string names a route that **excludes** the fallback — e.g.
``2000IU SC daily`` under a ``PO`` fallback.

The judgement is therefore *fallback-relative*, not "does the dose contain a non-oral
token". The latter would fire on 38 correct ``escalation`` entries whose dose says
``IV`` and whose fallback is ``IV`` — the fallback is producing the right answer there.

PR #457 fixed 4 such entries (asthma ICS/LABA ``INH`` x2, DKA insulin ``SC`` x2) but its
sweep keyed on *drug-name* words (`inhal` / `insulin` / `inject` / ...). Enoxaparin and
Denosumab carry no route hint in their names — the route lived in the **dose string**.
Three entries were therefore missed. These tests pin the dose-string axis so the class
cannot recur.

Guard design note — word boundaries are load-bearing. Substring matching
(``"PR" in dose``) false-positives on 10 real entries: 9 PRN (as-needed) doses
(``500mg PO q6h PRN``) and one ``NG`` inside ``"remaining days of 5-day course"``.
That is the same defect class as the ``_determine_route`` substring flaw
(``"IV" in "Rivaroxaban"``); the negative tests below pin it shut.
"""

import glob
import os

import pytest
import yaml

from clinosim.modules.disease.protocol import (
    DRUG_BLOCK_ROUTE_FALLBACKS,
    ROUTE_DOSE_TOKENS,
    _validate_drug_route_consistency,
    dose_contradicts_fallback,
    dose_route_tokens,
)

pytestmark = pytest.mark.unit

_YAML_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "clinosim", "modules", "disease", "reference_data")
_FILES = sorted(glob.glob(os.path.join(_YAML_DIR, "*.yaml")))


def _block_entries(block_name):
    """Yield (filename, country_key, entry) for every drug entry in `block_name`."""
    for path in _FILES:
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        block = (data.get("drugs") or {}).get(block_name)
        if not isinstance(block, dict):
            continue
        for country_key in ("japan", "us"):
            entries = block.get(country_key) or []
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if isinstance(entry, dict):
                    yield os.path.basename(path), country_key, entry


# ---------------------------------------------------------------- data invariant


def test_no_shipped_entry_contradicts_its_block_fallback():
    """No drug entry relies on a fallback its own dose string contradicts.

    Covers every block listed in DRUG_BLOCK_ROUTE_FALLBACKS, so adding a block to
    that table automatically extends this invariant.
    """
    offenders = []
    for block_name, fallback in DRUG_BLOCK_ROUTE_FALLBACKS.items():
        for fname, ck, entry in _block_entries(block_name):
            if "route" in entry:
                continue
            dose = str(entry.get("dose", ""))
            if dose_contradicts_fallback(dose, fallback):
                offenders.append(
                    f"  {fname} [{block_name}/{ck}] {entry.get('drug', '')!r} "
                    f"dose={dose!r} would be assigned route={fallback!r} "
                    f"but dose names {sorted(dose_route_tokens(dose))}"
                )
    assert offenders == [], "drug entries whose absent-route fallback contradicts their dose string:\n" + "\n".join(
        offenders
    )


def test_known_subcutaneous_discharge_entries_declare_sc():
    """The three entries missed by PR #457 now declare `route: "SC"`.

    Keyed on (drug, dose) rather than list index so YAML reordering is safe.
    """
    expected = {
        ("Enoxaparin", "2000IU SC daily"),
        ("Enoxaparin", "40mg SC daily"),
        ("Denosumab", "60mg SC q6months"),
    }
    seen = set()
    for _fname, _ck, entry in _block_entries("discharge_oral"):
        key = (str(entry.get("drug", "")), str(entry.get("dose", "")))
        if key in expected:
            seen.add(key)
            assert str(entry.get("route", "")).upper() == "SC", (
                f"{key} must declare route: 'SC' (subcutaneous-only formulation); got {entry.get('route')!r}"
            )
    assert seen == expected, f"expected discharge_oral entries not found in YAML: {expected - seen}"


# ---------------------------------------------------------------- token extraction


@pytest.mark.parametrize(
    "dose,expected",
    [
        ("2000IU SC daily", {"SC"}),
        ("40mg SC daily", {"SC"}),
        ("60mg SC q6months", {"SC"}),
        ("2.5mg NEB q1-4h", {"NEB"}),
        ("1 supp PR daily", {"PR"}),
        ("15-30g PO or PR", {"PO", "PR"}),
        ("40-80mg IV q6-8h", {"IV"}),
        ("875/125mg PO BID", {"PO"}),
        ("0.25mg IV, then 0.125-0.25mg PO daily", {"IV", "PO"}),
    ],
)
def test_dose_route_tokens_extracts_word_boundary_tokens(dose, expected):
    assert dose_route_tokens(dose) == expected


@pytest.mark.parametrize(
    "dose",
    [
        # PRN (as-needed) must NOT yield a PR token — 9 real entries depend on this.
        "500mg PO q6h PRN",
        "60mg PO TID PRN",
        "5/325mg PO q4-6h PRN",
        "650mg PO TID PRN",
        # "remaining" contains NG — one real entry depends on this.
        "40mg PO daily (remaining days of 5-day course)",
    ],
)
def test_dose_route_tokens_ignores_substring_lookalikes(dose):
    """Substring matching would yield PR / NG here; word boundaries must not."""
    assert "PR" not in dose_route_tokens(dose)
    assert "NG" not in dose_route_tokens(dose)


@pytest.mark.parametrize(
    "dose",
    [
        "Resume or initiate controller therapy",
        "Adjusted to INR 2.0-3.0 (1.5-2.5 age>70)",
        "3-4h session, 3x/week or continuous (CRRT)",
        "Percutaneous vertebroplasty under fluoroscopy",
        "",
    ],
)
def test_dose_route_tokens_empty_when_no_route_named(dose):
    assert dose_route_tokens(dose) == set()


def test_route_dose_tokens_includes_po():
    """PO must be a recognised token so a dose naming it is never a PO contradiction.

    Forward defense, not a live fix: measured impact today is 0 entries. None of the
    123 route-less entries in the checked blocks name more than one route, so dropping
    PO from the tuple would change no verdict right now. Dual-route doses do exist
    elsewhere in the corpus (`15-30g PO or PR` in `hyperkalemia_management`,
    `20-40mg IV or PO daily` in `first_line`) — neither block is checked. This test
    pins PO in place so such a dose cannot be mis-flagged if it later lands in a
    checked block, or if a dead block gains a reader and a fallback.
    """
    assert "PO" in ROUTE_DOSE_TOKENS
    assert {"SC", "IM", "IV", "INH", "NEB", "SL", "PR"} <= set(ROUTE_DOSE_TOKENS)


# ---------------------------------------------------------------- fallback relativity


@pytest.mark.parametrize(
    "dose,fallback,expected",
    [
        # PO fallback (discharge_oral)
        ("2000IU SC daily", "PO", True),
        ("60mg SC q6months", "PO", True),
        ("1 supp PR daily", "PO", True),
        ("875/125mg PO BID", "PO", False),
        ("15-30g PO or PR", "PO", False),  # PO is among the named routes
        ("500mg PO q6h PRN", "PO", False),
        ("Resume or initiate controller therapy", "PO", False),  # names nothing
        # IV fallback (escalation) — the 38-entry case the guard must not break
        ("4.5g IV q8h", "IV", False),
        ("500mg IV daily", "IV", False),
        ("15-20mg/kg IV q12h (trough 15-20)", "IV", False),
        ("3-4h session, 3x/week or continuous (CRRT)", "IV", False),  # names nothing
        ("2000IU SC daily", "IV", True),  # would contradict an IV fallback too
    ],
)
def test_dose_contradicts_fallback(dose, fallback, expected):
    assert dose_contradicts_fallback(dose, fallback) is expected


def test_escalation_iv_entries_do_not_trip_the_guard():
    """Regression guard for the supervisor-identified over-firing risk.

    38 shipped `escalation` entries omit `route` and carry an IV dose. A
    non-fallback-relative rule ("dose contains a non-oral token") would reject all
    of them. Assert a non-trivial number are present AND that none fire.
    """
    iv_dose_entries = [
        (fname, entry)
        for fname, _ck, entry in _block_entries("escalation")
        if "route" not in entry and "IV" in dose_route_tokens(str(entry.get("dose", "")))
    ]
    assert len(iv_dose_entries) >= 30, (
        f"expected the escalation IV-dose corpus to be substantial; found {len(iv_dose_entries)}"
    )
    fired = [
        f"{fname}: {entry.get('drug')!r} dose={entry.get('dose')!r}"
        for fname, entry in iv_dose_entries
        if dose_contradicts_fallback(str(entry.get("dose", "")), "IV")
    ]
    assert fired == [], "escalation entries wrongly flagged against their IV fallback:\n" + "\n".join(fired)


# ---------------------------------------------------------------- load-time validator


def test_validator_rejects_nonoral_dose_without_route():
    drugs = {"discharge_oral": {"japan": [{"drug": "Enoxaparin", "dose": "2000IU SC daily"}]}}
    with pytest.raises(ValueError, match="contradicts"):
        _validate_drug_route_consistency("test_disease", drugs)


def test_validator_accepts_nonoral_dose_with_explicit_route():
    drugs = {"discharge_oral": {"japan": [{"drug": "Enoxaparin", "dose": "2000IU SC daily", "route": "SC"}]}}
    _validate_drug_route_consistency("test_disease", drugs)  # must not raise


def test_validator_accepts_prn_dose_without_route():
    """Regression guard: PRN + `remaining` doses must not be rejected."""
    drugs = {
        "discharge_oral": {
            "us": [
                {"drug": "Acetaminophen", "dose": "500mg PO q6h PRN"},
                {"drug": "Prednisone", "dose": "40mg PO daily (remaining days of 5-day course)"},
            ]
        }
    }
    _validate_drug_route_consistency("test_disease", drugs)  # must not raise


def test_validator_accepts_escalation_iv_dose_without_route():
    """The escalation IV fallback agrees with an IV dose — must not raise."""
    drugs = {"escalation": {"japan": [{"drug": "Piperacillin/Tazobactam", "dose": "4.5g IV q8h"}]}}
    _validate_drug_route_consistency("test_disease", drugs)  # must not raise


def test_validator_rejects_escalation_dose_contradicting_iv():
    drugs = {"escalation": {"us": [{"drug": "Someting", "dose": "40mg SC daily"}]}}
    with pytest.raises(ValueError, match="contradicts"):
        _validate_drug_route_consistency("test_disease", drugs)


def test_validator_ignores_blocks_without_a_known_fallback():
    """Dead blocks have no reader and therefore no fallback to contradict.

    `post_op` / `alternative_penicillin_allergy` / `mrsa_coverage` /
    `hyperkalemia_management` / `alternative_beta_blocker_contraindicated` have zero
    Python readers (Issue #437). Validating them would fail the build for data that
    never reaches output. `first_line` has a reader but substitutes nothing (empty
    string), so there is likewise no assertion to contradict.
    """
    drugs = {
        "post_op": {"japan": [{"drug": "Enoxaparin", "dose": "2000IU SC daily"}]},
        "alternative_penicillin_allergy": {"us": [{"drug": "Clindamycin", "dose": "600mg IV q8h"}]},
        "first_line": {"japan": [{"drug": "Methylprednisolone", "dose": "40-80mg IV q6-8h"}]},
    }
    _validate_drug_route_consistency("test_disease", drugs)  # must not raise


def test_fallback_table_matches_the_readers_in_the_simulator():
    """The table must stay in sync with the two substituting readers.

    If a third block gains a route fallback, add it here and to the table together —
    otherwise the new block's entries are silently unguarded.
    """
    assert DRUG_BLOCK_ROUTE_FALLBACKS == {"discharge_oral": "PO", "escalation": "IV"}


def test_validator_error_names_the_offending_entry():
    drugs = {"discharge_oral": {"us": [{"drug": "Denosumab", "dose": "60mg SC q6months"}]}}
    with pytest.raises(ValueError) as exc:
        _validate_drug_route_consistency("vertebral_compression_fracture", drugs)
    msg = str(exc.value)
    assert "vertebral_compression_fracture" in msg
    assert "Denosumab" in msg
    assert "60mg SC q6months" in msg
    assert "discharge_oral" in msg


def test_all_shipped_disease_protocols_pass_the_validator():
    """Every disease YAML loads without tripping the guard."""
    failures = []
    for path in _FILES:
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        try:
            _validate_drug_route_consistency(data.get("disease_id", os.path.basename(path)), data.get("drugs") or {})
        except ValueError as e:
            failures.append(f"{os.path.basename(path)}: {e}")
    assert failures == [], "shipped disease YAMLs failing the route guard:\n" + "\n".join(failures)


def test_load_disease_protocol_runs_the_guard():
    """The guard is wired into the loader, not merely defined.

    A validator that exists but is never called is the silent-no-op class this
    project guards against; assert the loader path exercises it.
    """
    import clinosim.modules.disease.protocol as protocol_mod

    calls = []
    original = protocol_mod._validate_drug_route_consistency

    def _spy(disease_id, drugs):
        calls.append(disease_id)
        return original(disease_id, drugs)

    protocol_mod._validate_drug_route_consistency = _spy
    try:
        protocol_mod.load_disease_protocol.cache_clear()
        protocol_mod.load_disease_protocol("hip_fracture")
    finally:
        protocol_mod._validate_drug_route_consistency = original
        protocol_mod.load_disease_protocol.cache_clear()

    assert calls == ["hip_fracture"], f"loader did not invoke the route guard; calls={calls}"
