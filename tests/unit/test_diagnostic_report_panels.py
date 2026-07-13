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
            "ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA", "Checkup",
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
            assert disp and disp != panel["loinc"], (
                f"panel={name} loinc={panel['loinc']} did not resolve to a display"
            )


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
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T15:30:39", 1),
            _order("Hct", "2026-05-12T16:00:40", 2),
            _order("Plt", "2026-05-12T17:10:41", 3),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 1
        g = groups[0]
        assert g.panel_name == "CBC"
        assert g.bucket == "2026-05-12"
        assert g.obs_refs == [
            "lab-ENC-001-0000", "lab-ENC-001-0001", "lab-ENC-001-0002", "lab-ENC-001-0003",
        ]

    def test_below_threshold_yields_no_group(self):
        """A single CBC component (below CBC's min=3 per PR2) yields no DR."""
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [_order("WBC", "2026-05-12T14:28:38", 0)]
        assert group_lab_orders(orders, "ENC-001") == []

    def test_separate_day_buckets_yield_separate_groups(self):
        """Repeat draws on a different day produce separate DRs (e.g. daily CBC
        trend). With CBC min_components=3 (PR2), each day needs at least 3
        components to register as a CBC DR."""
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
            _order("WBC", "2026-05-13T09:30:00", 3),
            _order("Hb",  "2026-05-13T09:30:01", 4),
            _order("Hct", "2026-05-13T09:30:02", 5),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 2
        assert {g.bucket for g in groups} == {"2026-05-12", "2026-05-13"}

    def test_abg_consumes_hco3_before_bmp(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("pH",   "2026-05-12T14:28:00", 0),
            _order("pCO2", "2026-05-12T14:28:01", 1),
            _order("pO2",  "2026-05-12T14:28:02", 2),
            _order("HCO3", "2026-05-12T14:28:03", 3),
            _order("Na",         "2026-05-12T14:28:10", 4),
            _order("K",          "2026-05-12T14:28:11", 5),
            _order("Cl",         "2026-05-12T14:28:12", 6),
            _order("BUN",        "2026-05-12T14:28:13", 7),
            _order("Creatinine", "2026-05-12T14:28:14", 8),
            _order("Glucose",    "2026-05-12T14:28:15", 9),
            _order("Ca",         "2026-05-12T14:28:16", 10),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        panel_names = [g.panel_name for g in groups]
        assert "ABG" in panel_names
        assert "BMP" in panel_names
        abg = next(g for g in groups if g.panel_name == "ABG")
        bmp = next(g for g in groups if g.panel_name == "BMP")
        assert "lab-ENC-001-0003" in abg.obs_refs   # HCO3
        assert "lab-ENC-001-0003" not in bmp.obs_refs

    def test_solo_lab_yields_no_group(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
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
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("Na",         "2026-05-12T14:28:00", 0),
            _order("K",          "2026-05-12T14:28:01", 1),
            _order("Cl",         "2026-05-12T14:28:02", 2),
            _order("HCO3",       "2026-05-12T14:28:03", 3),
            _order("BUN",        "2026-05-12T14:28:04", 4),
            _order("Creatinine", "2026-05-12T14:28:05", 5),
            _order("Glucose",    "2026-05-12T14:28:06", 6),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert [g.panel_name for g in groups] == ["BMP"]

    def test_bmp_six_components_below_threshold(self):
        """BMP threshold rose 5→7 (PR for Cl/Ca physiology). Six
        components on the same day must NOT group into a BMP DR."""
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("Na",         "2026-05-12T14:28:00", 0),
            _order("K",          "2026-05-12T14:28:01", 1),
            _order("HCO3",       "2026-05-12T14:28:02", 2),
            _order("BUN",        "2026-05-12T14:28:03", 3),
            _order("Creatinine", "2026-05-12T14:28:04", 4),
            _order("Glucose",    "2026-05-12T14:28:05", 5),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert all(g.panel_name != "BMP" for g in groups), (
            f"6 BMP components must be below the new threshold of 7; "
            f"got groups: {[g.panel_name for g in groups]}"
        )

    def test_ua_skip_when_no_components_present(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert all(g.panel_name != "UA" for g in groups)

    def test_components_ordered_by_yaml_definition(self):
        """obs_refs in the group must follow the YAML's components order so the
        emitted FHIR result[] is stable across runs."""
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("Plt", "2026-05-12T14:28:00", 0),
            _order("Hct", "2026-05-12T14:28:00", 1),
            _order("Hb",  "2026-05-12T14:28:00", 2),
            _order("WBC", "2026-05-12T14:28:00", 3),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 1
        g = groups[0]
        assert g.obs_refs == [
            "lab-ENC-001-0003",   # WBC (YAML order #1)
            "lab-ENC-001-0002",   # Hb
            "lab-ENC-001-0001",   # Hct
            "lab-ENC-001-0000",   # Plt
        ]


@pytest.mark.unit
class TestBuildDrResource:
    def _group(self):
        from clinosim.modules.output._fhir_diagnostic_report import _GroupedPanel
        return _GroupedPanel(
            panel_name="CBC",
            bucket="2026-05-12",
            obs_refs=[
                "lab-ENC-001-0000", "lab-ENC-001-0001",
                "lab-ENC-001-0002", "lab-ENC-001-0003",
            ],
        )

    def test_shape_us(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_dr_resource
        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002", encounter_id="ENC-001",
            country="US", performer_ref="Practitioner/TECH-LAB-001",
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
        from clinosim.modules.output._fhir_diagnostic_report import build_dr_resource
        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002", encounter_id="ENC-001",
            country="JP", performer_ref=None, issued=None, seq=0,
        )
        coding = r["code"]["coding"][0]
        assert coding["display"] == "全血球計算パネル"
        # session 48 cycle 8 cross-seed verify fix: performer_ref 未指定でも
        # hospital-main を fallback として emit(CY7-01 100% coverage 維持)。
        assert r["performer"] == [{"reference": "Organization/hospital-main"}]

    def test_seq_increments_per_call(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_dr_resource
        r0 = build_dr_resource(
            self._group(), patient_id="P", encounter_id="E",
            country="US", performer_ref=None, issued=None, seq=0,
        )
        r1 = build_dr_resource(
            self._group()._replace(bucket="2026-05-13"),
            patient_id="P", encounter_id="E",
            country="US", performer_ref=None, issued=None, seq=1,
        )
        assert r0["id"] != r1["id"]
        assert r0["id"].endswith("-0")
        assert r1["id"].endswith("-1")


@pytest.mark.unit
class TestBuildLabPanelReports:
    def _ctx(self, orders, country="US"):
        from clinosim.modules.output._fhir_common import BundleContext
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
        from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
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
        from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
        assert build_lab_panel_reports(self._ctx([])) == []

    def test_jp_locale_passes_through(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
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
        import yaml
        from pathlib import Path
        import clinosim
        path = Path(clinosim.__file__).parent / "modules/observation/reference_data/lab_panels.yaml"
        panels = yaml.safe_load(path.read_text())
        assert panels["Coag"] == ["PT", "PT_INR", "APTT"]
        assert panels["LFT"] == ["AST", "ALT", "ALP", "T_Bil", "Albumin", "TP", "GGT", "LDH"]
        assert panels["Lipid"] == ["TC", "LDL", "HDL", "TG"]
        assert "UA" in panels

    def test_lab_panel_groups_documents_coag_authoritative_scope(self):
        """I2: lab_panel_groups.yaml documents Fibrinogen exclusion + LOINC 24373-3 scope.

        YAML moved to order/reference_data/ in Task 2 (unification: panel = ordering concept).
        """
        from pathlib import Path
        import clinosim
        # Canonical YAML location: order/reference_data/ (moved from output/reference_data/)
        path = Path(clinosim.__file__).parent / "modules/order/reference_data/lab_panel_groups.yaml"
        text = path.read_text()
        assert "24373-3" in text
        assert "Fibrinogen" in text  # documents why it's NOT in Coag components

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
