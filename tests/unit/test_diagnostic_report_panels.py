"""Unit tests for DiagnosticReport panel grouping (post-hoc, AD-56 builder)."""

import pytest


@pytest.mark.unit
class TestLoadPanelGroups:
    def test_yaml_loads_with_all_expected_panels(self):
        # Canonical loader now lives in order.panel_grouping (Task 2 unification).
        # session 48 cycle 8 CY8-01: Checkup panel 追加 for JP-eCheckup 5 項目。
        from clinosim.modules.order.panel_grouping import load_panel_definitions

        panels = load_panel_definitions()
        assert set(panels.keys()) == {
            "ABG",
            "CBC",
            "BMP",
            "LFT",
            "Lipid",
            "Coag",
            "UA",
            "Checkup",
        }

    def test_each_panel_has_loinc_components_threshold(self):
        from clinosim.modules.order.panel_grouping import load_panel_definitions

        for name, panel in load_panel_definitions().items():
            assert "loinc" in panel and panel["loinc"]
            assert "display" in panel and panel["display"]
            assert isinstance(panel["components"], list) and panel["components"]
            assert isinstance(panel["min_components"], int) and panel["min_components"] >= 1

    def test_each_loinc_resolves_via_codes_lookup(self):
        from clinosim.codes import lookup
        from clinosim.modules.order.panel_grouping import load_panel_definitions

        for name, panel in load_panel_definitions().items():
            disp = lookup("loinc", panel["loinc"], "en")
            assert disp and disp != panel["loinc"], f"panel={name} loinc={panel['loinc']} did not resolve to a display"


def _order(lab_name: str, when: str, idx: int) -> dict:
    """Build a minimal CIF-shaped lab order with one result, for grouping tests."""
    return {
        "order_type": "lab",
        "order_code": lab_name,
        "display_name": lab_name,
        "result": {"lab_name": lab_name, "value": 1.0, "result_datetime": when},
    }


@pytest.mark.unit
class TestGroupLabOrders:
    def test_cbc_full_panel_emits_one_group(self):
        """Day-bucket: components can be hours apart but still group as one DR per day."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb", "2026-05-12T15:30:39", 1),
            _order("Hct", "2026-05-12T16:00:40", 2),
            _order("Plt", "2026-05-12T17:10:41", 3),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 1
        g = groups[0]
        assert g.panel_name == "CBC"
        assert g.bucket == "2026-05-12"
        assert g.obs_refs == [
            "lab-ENC-001-0000",
            "lab-ENC-001-0001",
            "lab-ENC-001-0002",
            "lab-ENC-001-0003",
        ]

    def test_below_threshold_yields_no_group(self):
        """A single CBC component (below CBC's min=3 per PR2) yields no DR."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [_order("WBC", "2026-05-12T14:28:38", 0)]
        assert group_lab_orders(orders, "ENC-001") == []

    def test_separate_day_buckets_yield_separate_groups(self):
        """Repeat draws on a different day produce separate DRs (e.g. daily CBC
        trend). With CBC min_components=3 (PR2), each day needs at least 3
        components to register as a CBC DR."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb", "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
            _order("WBC", "2026-05-13T09:30:00", 3),
            _order("Hb", "2026-05-13T09:30:01", 4),
            _order("Hct", "2026-05-13T09:30:02", 5),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 2
        assert {g.bucket for g in groups} == {"2026-05-12", "2026-05-13"}

    def test_abg_consumes_hco3_before_bmp(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("pH", "2026-05-12T14:28:00", 0),
            _order("pCO2", "2026-05-12T14:28:01", 1),
            _order("pO2", "2026-05-12T14:28:02", 2),
            _order("HCO3", "2026-05-12T14:28:03", 3),
            _order("Na", "2026-05-12T14:28:10", 4),
            _order("K", "2026-05-12T14:28:11", 5),
            _order("Cl", "2026-05-12T14:28:12", 6),
            _order("BUN", "2026-05-12T14:28:13", 7),
            _order("Creatinine", "2026-05-12T14:28:14", 8),
            _order("Glucose", "2026-05-12T14:28:15", 9),
            _order("Ca", "2026-05-12T14:28:16", 10),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        panel_names = [g.panel_name for g in groups]
        assert "ABG" in panel_names
        assert "BMP" in panel_names
        abg = next(g for g in groups if g.panel_name == "ABG")
        bmp = next(g for g in groups if g.panel_name == "BMP")
        assert "lab-ENC-001-0003" in abg.obs_refs  # HCO3
        assert "lab-ENC-001-0003" not in bmp.obs_refs

    def test_solo_lab_yields_no_group(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("CRP", "2026-05-12T14:28:38", 0),
            _order("BNP", "2026-05-12T14:28:39", 1),
            _order("Troponin_I", "2026-05-12T14:28:40", 2),
            _order("HbA1c", "2026-05-12T14:28:41", 3),
        ]
        assert group_lab_orders(orders, "ENC-001") == []

    def test_bmp_seven_components_form_group(self):
        """BMP min_components = 7 after Cl/Ca added to derive_lab_values
        (canonical N − 1 = 8 − 1). Seven components (any 7 of canonical 8)
        on the same day must group into a BMP DR."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("Na", "2026-05-12T14:28:00", 0),
            _order("K", "2026-05-12T14:28:01", 1),
            _order("Cl", "2026-05-12T14:28:02", 2),
            _order("HCO3", "2026-05-12T14:28:03", 3),
            _order("BUN", "2026-05-12T14:28:04", 4),
            _order("Creatinine", "2026-05-12T14:28:05", 5),
            _order("Glucose", "2026-05-12T14:28:06", 6),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert [g.panel_name for g in groups] == ["BMP"]

    def test_bmp_six_components_below_threshold(self):
        """BMP threshold rose 5→7 (PR for Cl/Ca physiology). Six
        components on the same day must NOT group into a BMP DR."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("Na", "2026-05-12T14:28:00", 0),
            _order("K", "2026-05-12T14:28:01", 1),
            _order("HCO3", "2026-05-12T14:28:02", 2),
            _order("BUN", "2026-05-12T14:28:03", 3),
            _order("Creatinine", "2026-05-12T14:28:04", 4),
            _order("Glucose", "2026-05-12T14:28:05", 5),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert all(g.panel_name != "BMP" for g in groups), (
            f"6 BMP components must be below the new threshold of 7; got groups: {[g.panel_name for g in groups]}"
        )

    def test_ua_skip_when_no_components_present(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb", "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert all(g.panel_name != "UA" for g in groups)

    def test_components_ordered_by_yaml_definition(self):
        """obs_refs in the group must follow the YAML's components order so the
        emitted FHIR result[] is stable across runs."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import group_lab_orders

        orders = [
            _order("Plt", "2026-05-12T14:28:00", 0),
            _order("Hct", "2026-05-12T14:28:00", 1),
            _order("Hb", "2026-05-12T14:28:00", 2),
            _order("WBC", "2026-05-12T14:28:00", 3),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 1
        g = groups[0]
        assert g.obs_refs == [
            "lab-ENC-001-0003",  # WBC (YAML order #1)
            "lab-ENC-001-0002",  # Hb
            "lab-ENC-001-0001",  # Hct
            "lab-ENC-001-0000",  # Plt
        ]


@pytest.mark.unit
class TestBuildDrResource:
    def _group(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel

        return _GroupedPanel(
            panel_name="CBC",
            bucket="2026-05-12",
            obs_refs=[
                "lab-ENC-001-0000",
                "lab-ENC-001-0001",
                "lab-ENC-001-0002",
                "lab-ENC-001-0003",
            ],
        )

    def test_shape_us(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_dr_resource

        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002",
            encounter_id="ENC-001",
            country="US",
            performer_ref="Practitioner/TECH-LAB-001",
            issued="2026-05-12T14:28:39",
            seq=0,
        )
        assert r["resourceType"] == "DiagnosticReport"
        assert r["id"] == "dr-cbc-ENC-001-0"
        assert r["status"] == "final"
        cat = r["category"][0]["coding"][0]
        assert cat["code"] == "LAB"
        coding = r["code"]["coding"][0]
        assert coding["system"] == "http://loinc.org"
        assert coding["code"] == "58410-2"
        assert "Complete blood count" in coding["display"]
        assert r["subject"] == {"reference": "Patient/POP-000002"}
        assert r["encounter"] == {"reference": "Encounter/ENC-001"}
        assert r["effectiveDateTime"] == "2026-05-12"
        # session 48 feedback FB-F1: instant 型に JST TZ 付与
        assert r["issued"] == "2026-05-12T14:28:39+09:00"
        assert r["performer"] == [{"reference": "Practitioner/TECH-LAB-001"}]
        assert r["result"] == [
            {"reference": "Observation/lab-ENC-001-0000"},
            {"reference": "Observation/lab-ENC-001-0001"},
            {"reference": "Observation/lab-ENC-001-0002"},
            {"reference": "Observation/lab-ENC-001-0003"},
        ]

    def test_shape_jp_uses_japanese_display(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_dr_resource

        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002",
            encounter_id="ENC-001",
            country="JP",
            performer_ref=None,
            issued=None,
            seq=0,
        )
        coding = r["code"]["coding"][0]
        assert coding["display"] == "全血球計算パネル"
        # session 48 cycle 8 cross-seed verify fix: performer_ref 未指定でも
        # hospital-main を fallback として emit(CY7-01 100% coverage 維持)。
        assert r["performer"] == [{"reference": "Organization/hospital-main"}]

    def test_seq_increments_per_call(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_dr_resource

        r0 = build_dr_resource(
            self._group(),
            patient_id="P",
            encounter_id="E",
            country="US",
            performer_ref=None,
            issued=None,
            seq=0,
        )
        r1 = build_dr_resource(
            self._group()._replace(bucket="2026-05-13"),
            patient_id="P",
            encounter_id="E",
            country="US",
            performer_ref=None,
            issued=None,
            seq=1,
        )
        assert r0["id"] != r1["id"]
        assert r0["id"].endswith("-0")
        assert r1["id"].endswith("-1")


@pytest.mark.unit
class TestBuildLabPanelReports:
    def _ctx(self, orders, country="US"):
        from clinosim.modules.output.fhir_r4.lib.common import BundleContext

        record = {
            "patient": {"patient_id": "POP-000002"},
            "orders": orders,
        }
        return BundleContext(
            record=record,
            country=country,
            roster_map={},
            hospital_config={},
            patient_data={"patient_id": "POP-000002"},
            patient_id="POP-000002",
            is_readmission=False,
            prior_encounter_id=None,
            primary_dx_code="",
            admit_dx_code="",
            admit_dx_system="",
            primary_enc_id="ENC-001",
            patient_sex="F",
        )

    def test_cbc_panel_emits_one_dr(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports

        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb", "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
            _order("Plt", "2026-05-12T14:28:41", 3),
        ]
        out = build_lab_panel_reports(self._ctx(orders))
        assert len(out) == 1
        r = out[0]
        assert r["resourceType"] == "DiagnosticReport"
        assert r["id"] == "dr-cbc-ENC-001-0"
        assert len(r["result"]) == 4

    def test_no_lab_orders_yields_empty_list(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports

        assert build_lab_panel_reports(self._ctx([])) == []

    def test_jp_locale_passes_through(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports

        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb", "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
        ]
        out = build_lab_panel_reports(self._ctx(orders, country="JP"))
        assert len(out) == 1
        assert out[0]["code"]["coding"][0]["display"] == "全血球計算パネル"


@pytest.mark.unit
class TestPanelYAMLs:
    """Improvements I1 / I2 / I3: panel YAMLs are aligned across input
    (lab_panels.yaml = panel order expansion) and output
    (lab_panel_groups.yaml = DR grouping)."""

    def test_lab_panels_yaml_has_coag_lft_lipid_ua(self):
        """I1: lab_panels.yaml (expansion source) gains Coag/LFT/Lipid/UA
        to match lab_panel_groups.yaml (DR grouping source)."""
        from pathlib import Path

        import yaml

        import clinosim

        path = Path(clinosim.__file__).parent / "modules/observation/reference_data/lab_panels.yaml"
        panels = yaml.safe_load(path.read_text())
        assert panels["Coag"] == ["PT", "PT_INR", "APTT"]
        assert panels["LFT"] == ["AST", "ALT", "ALP", "T_Bil", "Albumin", "TP", "GGT", "LDH"]
        assert panels["Lipid"] == ["TC", "LDL", "HDL", "TG"]
        assert "UA" in panels

    def test_lab_panel_groups_documents_coag_authoritative_scope(self):
        """I2: lab_panel_groups.yaml documents Fibrinogen exclusion + LOINC scope.

        session 59 #276:LOINC 24373-3 は "Ferritin" semantic-mismatch のため
        14979-9 (aPTT) に substitute。yaml も 14979-9 参照 + 24373-3 の drop
        経緯(session 59 substitution)を documentation として保持。
        """
        from pathlib import Path

        import clinosim

        # Canonical YAML location: order/reference_data/ (moved from output/reference_data/)
        path = Path(clinosim.__file__).parent / "modules/order/reference_data/lab_panel_groups.yaml"
        text = path.read_text()
        # #276 (session 59):24373-3 は semantic-mismatch のため drop、
        # 現行 loinc = 14979-9。両 code が yaml text 内に document 経緯として残る。
        assert "14979-9" in text  # canonical Coag panel loinc after #276
        assert "24373-3" in text  # kept in comment documenting the substitution
        assert "Fibrinogen" in text  # documents why it's NOT in Coag components

    def test_dr_code_text_populated_with_jp_label_on_jp(self):
        """Issue #783 (part of #774): `DiagnosticReport.code.text` = the
        panel's JA primary label on JP output. Pre-fix this field was unset
        on 95.8% of DRs — consumers saw only the LOINC code string and could
        not distinguish CBC vs Coag vs LFT reports at a glance."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        group = _GroupedPanel(
            panel_name="CBC",
            bucket="2026-05-12",
            obs_refs=["lab-ENC-001-0000"],
        )
        r = build_dr_resource(
            group,
            patient_id="P",
            encounter_id="ENC-001",
            country="JP",
            performer_ref=None,
            issued=None,
            seq=0,
        )
        assert r["code"]["text"] == "血算 (CBC)"

    def test_dr_code_text_uses_english_display_on_us(self):
        """Issue #783: US output uses the panel's English `display` for `.text`
        (JP `display_ja` is JP-only)."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        group = _GroupedPanel(panel_name="LFT", bucket="2026-05-12", obs_refs=["lab-ENC-001-0000"])
        r = build_dr_resource(
            group,
            patient_id="P",
            encounter_id="ENC-001",
            country="US",
            performer_ref=None,
            issued=None,
            seq=0,
        )
        # US uses English display from panel definition
        assert r["code"]["text"] == "Hepatic function 2000 panel - Serum or Plasma"

    def test_dr_code_text_populated_for_all_panels(self):
        """Issue #783: every panel must have `code.text` populated (no more
        95.8% null rate). Exercise all panel names to lock this in."""
        from clinosim.modules.order.panel_grouping import load_panel_definitions
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        for panel_name, panel in load_panel_definitions().items():
            group = _GroupedPanel(
                panel_name=panel_name,
                bucket="2026-05-12",
                obs_refs=["lab-ENC-001-0000"],
            )
            r = build_dr_resource(
                group,
                patient_id="P",
                encounter_id="ENC-001",
                country="JP",
                performer_ref=None,
                issued=None,
                seq=0,
            )
            assert r["code"].get("text"), f"panel={panel_name} produced empty code.text"
            # Every JP-shipped panel now carries a display_ja
            assert panel.get("display_ja"), f"panel={panel_name} missing display_ja"

    def test_lab_panels_yaml_header_does_not_cite_clca_silent_drop(self):
        """I3: stale 'e.g. Cl/Ca in BMP today' comment is removed (PR #78
        added Cl/Ca derives; the example is now misleading)."""
        from pathlib import Path

        import clinosim

        path = Path(clinosim.__file__).parent / "modules/observation/reference_data/lab_panels.yaml"
        text = path.read_text()
        # The stale phrasing referenced "Cl/Ca in BMP today" as a silent-drop
        # example. After PR #78 (Cl/Ca added) that example is no longer
        # accurate; UA's urine analytes are the only remaining silent-drops.
        assert "Cl/Ca in BMP today" not in text


def _order_with_result(lab_name, when, idx, *, value, unit="", flag=""):
    """Richer order helper for P1-10 conclusion tests (value/unit/flag)."""
    result = {"lab_name": lab_name, "value": value, "result_datetime": when}
    if unit:
        result["unit"] = unit
    if flag:
        result["flag"] = flag
    return {
        "order_type": "lab",
        "order_code": lab_name,
        "display_name": lab_name,
        "result": result,
    }


@pytest.mark.unit
class TestPanelConclusion:
    """P1-10 session-88j META #774 follow-up.

    ``build_dr_resource`` populates ``conclusion`` from the contributing
    Observations' values + flags — fact-only aggregation, no clinical
    interpretation. Legacy callers that omit ``orders`` fall through to
    the PR #791 baseline (no conclusion emitted) so pre-P1-10 tests keep
    passing untouched.
    """

    def _group(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel

        return _GroupedPanel(
            panel_name="LFT",
            bucket="2026-05-12",
            obs_refs=[
                "lab-ENC-001-0000",
                "lab-ENC-001-0001",
                "lab-ENC-001-0002",
                "lab-ENC-001-0003",
            ],
        )

    def _orders_lft(self):
        return [
            _order_with_result("AST", "2026-05-12T14:28:38", 0, value=84.0, unit="U/L", flag="H"),
            _order_with_result("ALT", "2026-05-12T14:28:38", 1, value=52.0, unit="U/L"),
            _order_with_result("ALP", "2026-05-12T14:28:38", 2, value=92, unit="U/L"),
            _order_with_result("T-Bil", "2026-05-12T14:28:38", 3, value=0.9, unit="mg/dL"),
        ]

    def test_conclusion_ja_lists_values_and_flags(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_dr_resource

        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002",
            encounter_id="ENC-001",
            country="JP",
            performer_ref=None,
            issued=None,
            seq=0,
            orders=self._orders_lft(),
        )
        assert "conclusion" in r
        c = r["conclusion"]
        assert "AST 84 U/L [H]" in c
        assert "ALT 52 U/L" in c
        assert "ALP 92 U/L" in c
        assert "T-Bil 0.9 mg/dL" in c
        assert "、" in c
        assert "参照範囲外: AST" in c
        for forbidden in ("経過観察", "薬剤性", "疑い", "考慮"):
            assert forbidden not in c, f"unattributed clinical claim leaked: {forbidden!r}"

    def test_conclusion_en_uses_comma_joiner_and_out_of_range(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_dr_resource

        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002",
            encounter_id="ENC-001",
            country="US",
            performer_ref=None,
            issued=None,
            seq=0,
            orders=self._orders_lft(),
        )
        c = r["conclusion"]
        assert "AST 84 U/L [H]" in c
        assert ", " in c and "、" not in c
        assert "Out of reference range: AST" in c

    def test_conclusion_no_flagged_analytes_omits_range_sentence(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(
            panel_name="CBC",
            bucket="2026-05-12",
            obs_refs=["lab-ENC-001-0000", "lab-ENC-001-0001"],
        )
        orders = [
            _order_with_result("WBC", "2026-05-12T14:28:38", 0, value=6.5, unit="10*3/uL"),
            _order_with_result("Hb", "2026-05-12T14:28:38", 1, value=13.2, unit="g/dL"),
        ]
        r = build_dr_resource(g, "P", "ENC-001", "JP", None, None, 0, orders=orders)
        c = r["conclusion"]
        assert "WBC 6.5 10*3/uL" in c and "Hb 13.2 g/dL" in c
        assert "参照範囲外" not in c
        assert "Out of reference range" not in c

    def test_conclusion_abg_mixed_flags_lists_each_flagged_name(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(
            panel_name="ABG",
            bucket="2026-05-12",
            obs_refs=["lab-ENC-001-0000", "lab-ENC-001-0001", "lab-ENC-001-0002"],
        )
        orders = [
            _order_with_result("pH", "2026-05-12T14:28:38", 0, value=7.32, flag="L"),
            _order_with_result("PaCO2", "2026-05-12T14:28:38", 1, value=48, unit="mmHg", flag="H"),
            _order_with_result("HCO3", "2026-05-12T14:28:38", 2, value=22, unit="mmol/L"),
        ]
        r = build_dr_resource(g, "P", "ENC-001", "US", None, None, 0, orders=orders)
        c = r["conclusion"]
        assert "pH 7.32 [L]" in c
        assert "PaCO2 48 mmHg [H]" in c
        assert "HCO3 22 mmol/L" in c
        assert "Out of reference range: pH, PaCO2" in c

    def test_missing_orders_arg_omits_conclusion_backwards_compat(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(panel_name="CBC", bucket="2026-05-12", obs_refs=["lab-ENC-001-0000"])
        r = build_dr_resource(g, "P", "ENC-001", "JP", None, None, 0)
        assert "conclusion" not in r

    def test_empty_orders_or_missing_result_omits_conclusion(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(panel_name="CBC", bucket="2026-05-12", obs_refs=["lab-ENC-001-0000"])
        orders = [{"order_type": "lab", "display_name": "WBC", "result": None}]
        r = build_dr_resource(g, "P", "ENC-001", "JP", None, None, 0, orders=orders)
        assert "conclusion" not in r

    # prompt-v11 source-side counterpart: EN lab NAMES (Albumin,
    # Creatinine, …) MUST render in canonical JA katakana on JP output.
    # Verified against the p=10000 s500 iris4h-ai deployment where 2,178
    # DR.conclusion EN lab hits leaked from this exact aggregation path.
    def test_conclusion_ja_localizes_full_english_lab_names(self):
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(
            panel_name="BMP",
            bucket="2026-05-12",
            obs_refs=["lab-ENC-001-0000", "lab-ENC-001-0001", "lab-ENC-001-0002"],
        )
        orders = [
            _order_with_result("Albumin", "2026-05-12T14:28:38", 0, value=4.0, unit="g/dL", flag="L"),
            _order_with_result("Creatinine", "2026-05-12T14:28:38", 1, value=1.2, unit="mg/dL", flag="H"),
            _order_with_result("Glucose", "2026-05-12T14:28:38", 2, value=180, unit="mg/dL"),
        ]
        r = build_dr_resource(g, "P", "ENC-001", "JP", None, None, 0, orders=orders)
        c = r["conclusion"]
        assert "アルブミン 4 g/dL [L]" in c
        assert "クレアチニン 1.2 mg/dL [H]" in c
        assert "血糖 180 mg/dL" in c
        # EN forms must NOT appear
        for en_name in ("Albumin", "Creatinine", "Glucose"):
            assert en_name not in c, f"EN lab name leaked: {en_name!r}"
        # Flagged list also uses the JA form
        assert "参照範囲外: アルブミン、クレアチニン" in c

    def test_conclusion_us_keeps_english_lab_names(self):
        """Sanity: US output MUST keep EN names — no accidental localization."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(panel_name="BMP", bucket="2026-05-12", obs_refs=["lab-ENC-001-0000"])
        orders = [_order_with_result("Albumin", "2026-05-12T14:28:38", 0, value=4.0, unit="g/dL")]
        r = build_dr_resource(g, "P", "ENC-001", "US", None, None, 0, orders=orders)
        assert "Albumin 4 g/dL" in r["conclusion"]

    def test_conclusion_ja_preserves_medical_abbreviations(self):
        """BUN / CRP / BNP / HbA1c / Na / K etc. are JA medical standard —
        NOT touched by the localization even on JP output. Regression
        guard for the widened v11 coverage list."""
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _GroupedPanel, build_dr_resource

        g = _GroupedPanel(
            panel_name="BMP",
            bucket="2026-05-12",
            obs_refs=[f"lab-ENC-001-{i:04d}" for i in range(5)],
        )
        orders = [
            _order_with_result("BUN", "2026-05-12T14:28:38", 0, value=15, unit="mg/dL"),
            _order_with_result("CRP", "2026-05-12T14:28:38", 1, value=0.4, unit="mg/dL"),
            _order_with_result("BNP", "2026-05-12T14:28:38", 2, value=25, unit="pg/mL"),
            _order_with_result("HbA1c", "2026-05-12T14:28:38", 3, value=5.6, unit="%"),
            _order_with_result("Na", "2026-05-12T14:28:38", 4, value=140, unit="mmol/L"),
        ]
        r = build_dr_resource(g, "P", "ENC-001", "JP", None, None, 0, orders=orders)
        c = r["conclusion"]
        for abbrev in ("BUN 15", "CRP 0.4", "BNP 25", "HbA1c 5.6", "Na 140"):
            assert abbrev in c, f"expected abbreviation {abbrev!r} preserved"
