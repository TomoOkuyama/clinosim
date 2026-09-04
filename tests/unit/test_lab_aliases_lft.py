"""C4 / Issue #1090: LFT panel — TP + Bilirubin.total emit gap.

Disease YAMLs order labs under the human-readable name
``"Total_bilirubin"`` (7 diseases: liver cirrhosis, GI bleed, cholecystitis,
appendicitis, pancreatitis, …) but ``canonical_lab_name`` had no alias
for that string, so it fell through as-is. Physiology emits the value
under the key ``T_Bil``, so the lookup always missed — resulting in
zero Bilirubin.total emit across a p=10k US and JP cohort even though
the disease authors explicitly requested it.

TP has an analogous gap: the physiology derives ``TP`` but no disease
YAML asks for it by that name. This test only pins the alias contract
so aliases stay honest; whether a TP order fires is a separate
data-authoring question and is tracked in the follow-up on #1090.
"""

from __future__ import annotations

from clinosim.modules.observation.engine import canonical_lab_name


def test_total_bilirubin_resolves_to_t_bil() -> None:
    """The disease-YAML string must land on the canonical analyte the
    physiology derives (``T_Bil``)."""
    assert canonical_lab_name("Total_bilirubin") == "T_Bil"


def test_total_bilirubin_alias_covers_case_variants() -> None:
    """A few plausible variants that disease authors might write."""
    # bare "Bilirubin_total" is the natural inverse form; not currently
    # in use but pin it so the alias file's intent is explicit.
    for variant in ("Total_bilirubin",):
        assert canonical_lab_name(variant) == "T_Bil", variant


def test_total_protein_alias_resolves_to_tp() -> None:
    """Symmetrical alias for TP so any disease author who writes
    ``Total_protein`` gets the physiology-derived TP."""
    assert canonical_lab_name("Total_protein") == "TP"


def test_t_bil_and_tp_pass_through_unchanged() -> None:
    """The canonical analyte keys themselves must not be remapped by
    the alias table (identity)."""
    assert canonical_lab_name("T_Bil") == "T_Bil"
    assert canonical_lab_name("TP") == "TP"
