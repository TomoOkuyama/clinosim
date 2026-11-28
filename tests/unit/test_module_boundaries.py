"""Rename-aware ratchet on module boundaries (Issue #3978).

implementation-rules "Module boundaries": the counter in
``tests/unit/module_boundaries.py`` reads every import statement under
``clinosim/`` with the AST (function-local and ``TYPE_CHECKING`` imports
included) and every path built into a ``reference_data`` directory, and counts
six rules:

1. ``foundation_imports`` — a foundation package (``datafiles``, ``determinism``,
   ``seeding``, ``age_bands``, ``timeutil``, ``reference_data``,
   ``countries/__init__``, ``country_profile``, ``codes``, ``locale``, ``types``,
   ``modules/_shared``) imports ``clinosim.modules`` (other than ``_shared``),
   ``clinosim.simulator``, ``clinosim.eval`` or ``clinosim.audit``;
2. ``module_to_simulator`` — ``clinosim/modules/<m>/`` (``m`` other than
   ``output``) imports ``clinosim.simulator``;
3. ``private_cross_package`` — a package imports a ``_``-prefixed module or name
   of another package; written exceptions: ``_<topic>_thresholds`` /
   ``_<topic>_defaults`` constant modules, ``_bb_*`` bundle builders imported by
   ``output/fhir_r4/builder.py`` or an ``audit.py``, and ``modules/_shared``;
4. ``output_to_simulator`` — ``clinosim/modules/output/`` imports
   ``clinosim.simulator``;
5. ``qa_to_simulator`` — ``clinosim/eval/`` or ``clinosim/audit/`` imports
   ``clinosim.simulator``;
6. ``foreign_reference_data`` — a path is built into the ``reference_data``
   directory of another package (or into one the counter cannot attribute).

Each rule's total may not rise; a decrease passes without editing the baseline,
and moving or renaming a file is not a raise. The stored totals are lowered by
``python -m tests.unit.module_boundaries --write``, never inside a feature change.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from tests.unit import code_data_separation as cds
from tests.unit import module_boundaries as mb
from tests.unit.ratchet_baseline import Ratchet

pytestmark = pytest.mark.unit


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Write ``files`` (paths relative to a ``clinosim`` package) under ``root`` and return the package dir."""
    pkg = root / "clinosim"
    for rel, text in {"__init__.py": "", **files}.items():
        (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
        (pkg / rel).write_text(text, encoding="utf-8")
    return pkg


def _keys(pkg: Path, kind: str) -> dict[str, int]:
    return dict(mb.scan(pkg)[kind])


def _totals(pkg: Path) -> dict[str, int]:
    return mb.totals(mb.scan(pkg))


# Packages a synthetic tree needs so that ``from pkg import name`` can tell a submodule from a name.
SKELETON = {
    "simulator/__init__.py": "",
    "simulator/device_removal.py": "",
    "simulator/_dispatch.py": "",
    "modules/__init__.py": "",
    "modules/_shared.py": "",
    "modules/disease/__init__.py": "",
    "modules/disease/localization.py": "",
    "modules/disease/_internal.py": "",
    "modules/order/__init__.py": "",
    "modules/order/_order_thresholds.py": "",
    "modules/order/_dose_defaults.py": "",
    "modules/output/__init__.py": "",
    "modules/output/fhir_r4/__init__.py": "",
    "modules/output/fhir_r4/labs.py": "",
    "eval/__init__.py": "",
    "audit/__init__.py": "",
    "codes/__init__.py": "",
}


# --- rule 1: foundation packages --------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "datafiles.py",
        "determinism.py",
        "seeding.py",
        "age_bands.py",
        "timeutil.py",
        "reference_data.py",
        "countries/__init__.py",
        "country_profile.py",
        "codes/loader.py",
        "locale/loaders/narrative.py",
        "types/patient.py",
        "modules/_shared.py",
    ],
)
def test_every_foundation_package_is_held_to_rule_1(tmp_path: Path, rel: str) -> None:
    assert mb.is_foundation(rel)
    pkg = _tree(tmp_path, {**SKELETON, rel: "import clinosim.simulator.device_removal\n"})
    assert _totals(pkg)["foundation_imports"] == 1


def test_not_foundation() -> None:
    for rel in ("countries/jp/insurance.py", "simulator/engine.py", "modules/disease/protocol.py", "api.py"):
        assert not mb.is_foundation(rel), rel


def test_rule_1_forbids_modules_simulator_output_eval_and_audit_only(tmp_path: Path) -> None:
    src = (
        "from clinosim.simulator import device_removal\n"
        "from clinosim.modules.disease.localization import x\n"
        "from clinosim.modules.output.fhir_r4 import labs\n"
        "import clinosim.eval\n"
        "from clinosim.audit import y\n"
        "from clinosim.modules._shared import get_attr_or_key\n"  # modules/_shared is foundation
        "from clinosim.modules import _shared\n"
        "from clinosim.codes import display\n"
        "from clinosim.datafiles import load_data_yaml\n"
        "import numpy\n"
    )
    pkg = _tree(tmp_path, {**SKELETON, "types/a.py": src})
    assert _keys(pkg, "foundation_imports") == {
        "foundation_imports::<module>::from clinosim.simulator import device_removal": 1,
        "foundation_imports::<module>::from clinosim.modules.disease.localization import x": 1,
        "foundation_imports::<module>::from clinosim.modules.output.fhir_r4 import labs": 1,
        "foundation_imports::<module>::import clinosim.eval": 1,
        "foundation_imports::<module>::from clinosim.audit import y": 1,
    }


def test_function_local_and_type_checking_imports_are_counted(tmp_path: Path) -> None:
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from clinosim.simulator.device_removal import Plan\n"
        "class Loader:\n"
        "    def load(self):\n"
        "        from clinosim.simulator import device_removal\n"
        "        return device_removal\n"
    )
    pkg = _tree(tmp_path, {**SKELETON, "seeding.py": src})
    assert _keys(pkg, "foundation_imports") == {
        "foundation_imports::<module>::from clinosim.simulator.device_removal import Plan": 1,
        "foundation_imports::Loader.load::from clinosim.simulator import device_removal": 1,
    }


# --- rule 2: domain module -> simulator -------------------------------------------------------


def test_rule_2_counts_each_imported_name_of_a_domain_module(tmp_path: Path) -> None:
    files = {
        **SKELETON,
        "modules/device/__init__.py": "",
        "modules/device/engine.py": (
            "from clinosim.simulator.device_removal import plan, schedule as sch\n"
            "from ...simulator import device_removal\n"  # relative import, resolved
            "import clinosim.simulator\n"
        ),
        "modules/device/sub/__init__.py": "",
        "modules/device/sub/deep.py": "from ....simulator.device_removal import plan\n",
        # not rule 2: simulator importing modules, output importing simulator, the modules package itself
        "simulator/engine.py": "from clinosim.modules.disease.localization import x\n",
        "modules/output/fhir_r4/x.py": "from clinosim.simulator import device_removal\n",
        "modules/__init__.py": "from clinosim.simulator import device_removal\n",
    }
    pkg = _tree(tmp_path, files)
    assert _keys(pkg, "module_to_simulator") == {
        "module_to_simulator::<module>::from clinosim.simulator.device_removal import plan": 2,
        "module_to_simulator::<module>::from clinosim.simulator.device_removal import schedule": 1,
        "module_to_simulator::<module>::from clinosim.simulator import device_removal": 1,
        "module_to_simulator::<module>::import clinosim.simulator": 1,
    }


# --- rule 3: private names across packages ----------------------------------------------------


def test_rule_3_counts_private_names_and_private_modules_of_another_package(tmp_path: Path) -> None:
    files = {
        **SKELETON,
        "simulator/inpatient.py": (
            "from clinosim.modules.disease.localization import _localize, localize\n"
            "from clinosim.modules.disease import _internal\n"
            "from clinosim.modules.disease._internal import helper\n"
            "import clinosim.modules.disease._internal as di\n"
            "from clinosim.modules.disease import __version__\n"  # dunder is not private
            "from clinosim.simulator._dispatch import _route\n"  # same package
            "from ._dispatch import _route as r\n"  # same package, relative
        ),
    }
    pkg = _tree(tmp_path, files)
    assert _keys(pkg, "private_cross_package") == {
        "private_cross_package::<module>::from clinosim.modules.disease.localization import _localize": 1,
        "private_cross_package::<module>::from clinosim.modules.disease import _internal": 1,
        "private_cross_package::<module>::from clinosim.modules.disease._internal import helper": 1,
        "private_cross_package::<module>::import clinosim.modules.disease._internal": 1,
    }


def test_rule_3_packages_are_modules_countries_and_top_level_packages() -> None:
    assert mb.package_of(("modules", "document", "narrative", "_x")) == "modules/document"
    assert mb.package_of(("modules", "output", "fhir_r4", "builder")) == "modules/output"
    assert mb.package_of(("modules", "_shared")) == "modules/_shared"
    assert mb.package_of(("modules",)) == "modules"
    assert mb.package_of(("countries", "jp", "insurance")) == "countries/jp"
    assert mb.package_of(("countries",)) == "countries"
    assert mb.package_of(("simulator", "phases", "_forward_loop")) == "simulator"
    assert mb.package_of(("seeding",)) == "seeding"


def test_rule_3_exception_thresholds_and_defaults_modules(tmp_path: Path) -> None:
    src = (
        "from clinosim.modules.order._order_thresholds import MAX_DOSE\n"
        "from clinosim.modules.order import _dose_defaults\n"
        "from clinosim.modules.order._order_thresholds import _SALT\n"  # a private name is still private
    )
    pkg = _tree(tmp_path, {**SKELETON, "simulator/x.py": src})
    assert _keys(pkg, "private_cross_package") == {
        "private_cross_package::<module>::from clinosim.modules.order._order_thresholds import _SALT": 1,
    }


def test_rule_3_exception_bundle_builders_in_builder_and_audit_only(tmp_path: Path) -> None:
    imp = "from clinosim.modules.disease.localization import _bb_conditions\n"
    files = {
        **SKELETON,
        "modules/output/fhir_r4/builder.py": imp,
        "modules/order/audit.py": "from clinosim.modules.output.fhir_r4.labs import _bb_service_requests\n",
        "modules/order/engine.py": "from clinosim.modules.output.fhir_r4.labs import _bb_service_requests\n",
        "modules/output/fhir_r4/other.py": imp,
    }
    pkg = _tree(tmp_path, files)
    assert _keys(pkg, "private_cross_package") == {
        "private_cross_package::<module>::from clinosim.modules.output.fhir_r4.labs import _bb_service_requests": 1,
        "private_cross_package::<module>::from clinosim.modules.disease.localization import _bb_conditions": 1,
    }


def test_rule_3_exception_modules_shared(tmp_path: Path) -> None:
    src = (
        "from clinosim.modules._shared import get_attr_or_key as _get\n"
        "from clinosim.modules import _shared\n"
        "from clinosim.modules._shared import _private\n"  # a private name of _shared is still private
    )
    pkg = _tree(tmp_path, {**SKELETON, "simulator/x.py": src})
    assert _keys(pkg, "private_cross_package") == {
        "private_cross_package::<module>::from clinosim.modules._shared import _private": 1,
    }


# --- rules 4 and 5: output and QA -> simulator ------------------------------------------------


def test_rule_4_output_to_simulator(tmp_path: Path) -> None:
    files = {**SKELETON, "modules/output/fhir_r4/x.py": "def f():\n    from clinosim.simulator import device_removal\n"}
    pkg = _tree(tmp_path, files)
    assert _keys(pkg, "output_to_simulator") == {
        "output_to_simulator::f::from clinosim.simulator import device_removal": 1
    }
    assert _totals(pkg)["module_to_simulator"] == 0


def test_rule_5_eval_and_audit_to_simulator(tmp_path: Path) -> None:
    files = {
        **SKELETON,
        "eval/axes/clinical.py": "from clinosim.simulator.device_removal import plan\n",
        "audit/engine.py": "import clinosim.simulator._dispatch\n",
        "eval/engine.py": "from clinosim.modules.disease.localization import x\n",
    }
    pkg = _tree(tmp_path, files)
    assert _keys(pkg, "qa_to_simulator") == {
        "qa_to_simulator::<module>::from clinosim.simulator.device_removal import plan": 1,
        "qa_to_simulator::<module>::import clinosim.simulator._dispatch": 1,
    }


# --- rule 6: foreign reference_data paths -----------------------------------------------------


def test_rule_6_counts_a_path_into_another_packages_reference_data(tmp_path: Path) -> None:
    src = (
        "from pathlib import Path\n"
        "_HERE = Path(__file__).resolve().parent\n"
        "_MODULES = _HERE.parent\n"
        "_OWN = _HERE / 'reference_data' / 'own.yaml'\n"  # own: not counted
        "_OWN2 = Path(__file__).parent / 'reference_data'\n"
        "_PANELS = _HERE.parent / 'observation' / 'reference_data' / 'lab_panels.yaml'\n"
        "def load():\n"
        "    return Path(__file__).resolve().parents[1] / 'imaging' / 'reference_data' / 'x.yaml'\n"
        "def all_ids():\n"
        "    return [p for d in ('disease', 'encounter') for p in (_MODULES / d / 'reference_data').glob('*')]\n"
        "_DOC = 'see reference_data/own.yaml'\n"  # a string, not a path
    )
    pkg = _tree(tmp_path, {**SKELETON, "modules/order/panels.py": src})
    assert _keys(pkg, "foreign_reference_data") == {
        "foreign_reference_data::<module>::_HERE.parent / 'observation' / 'reference_data' / 'lab_panels.yaml'": 1,
        (
            "foreign_reference_data::load::"
            "Path(__file__).resolve().parents[1] / 'imaging' / 'reference_data' / 'x.yaml'"
        ): 1,
        "foreign_reference_data::all_ids::_MODULES / d / 'reference_data'": 1,  # cannot be attributed
    }


def test_rule_6_attributes_nested_paths_to_the_owning_package(tmp_path: Path) -> None:
    files = {
        **SKELETON,
        # parents[4] of modules/document/narrative/renderers/sb/x.py is modules/: document's own data
        "modules/document/narrative/renderers/sb/x.py": (
            "from pathlib import Path\n"
            "P = Path(__file__).resolve().parents[4] / 'document' / 'reference_data' / 'a.yaml'\n"
            "Q = Path(__file__).resolve().parents[2] / 'reference_data' / 'b.yaml'\n"  # narrative/reference_data
        ),
        "modules/output/fhir_r4/labs/r.py": (
            "from pathlib import Path\nR = Path(__file__).resolve().parents[1] / 'reference_data' / 'c.yaml'\n"
        ),
        "simulator/enumerate.py": (
            "from pathlib import Path\n"
            "_REPO_ROOT = Path(__file__).resolve().parents[2]\n"
            "D = _REPO_ROOT / 'clinosim' / 'modules' / 'disease' / 'reference_data'\n"
            "S = _REPO_ROOT / 'clinosim' / 'simulator' / 'reference_data'\n"
        ),
        "locale/loaders/narrative.py": (
            "from pathlib import Path\n"
            "_LOCALE_DIR = Path(__file__).resolve().parents[1]\n"
            "def f():\n"
            "    return _LOCALE_DIR.parent / 'modules' / 'imaging' / 'reference_data' / 'body_sites.yaml'\n"
        ),
        "simulator/joins.py": (
            "import os\n"
            "from pathlib import Path\n"
            "J = Path(__file__).resolve().parent.joinpath('reference_data', 'x.yaml')\n"  # own
            "K = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference_data')\n"  # own
            "L = os.path.join(os.path.dirname(__file__), '..', 'modules', 'disease', 'reference_data')\n"
        ),
    }
    pkg = _tree(tmp_path, files)
    assert _keys(pkg, "foreign_reference_data") == {
        "foreign_reference_data::<module>::_REPO_ROOT / 'clinosim' / 'modules' / 'disease' / 'reference_data'": 1,
        (
            "foreign_reference_data::f::"
            "_LOCALE_DIR.parent / 'modules' / 'imaging' / 'reference_data' / 'body_sites.yaml'"
        ): 1,
        (
            "foreign_reference_data::<module>::"
            "os.path.join(os.path.dirname(__file__), '..', 'modules', 'disease', 'reference_data')"
        ): 1,
    }


# --- the ratchet ------------------------------------------------------------------------------

VIOLATING = {
    **SKELETON,
    "modules/device/__init__.py": "",
    "modules/device/engine.py": (
        "from pathlib import Path\n"
        "from clinosim.simulator.device_removal import plan\n"
        "from clinosim.modules.disease.localization import _localize\n"
        "class Remover:\n"
        "    def run(self):\n"
        "        from clinosim.simulator import _dispatch\n"
        "        return Path(__file__).resolve().parent.parent / 'disease' / 'reference_data'\n"
    ),
}


def test_moving_a_file_passes(tmp_path: Path) -> None:
    pkg = _tree(tmp_path, VIOLATING)
    baseline = mb.baseline_from(mb.scan(pkg))
    _tree(tmp_path, {"modules/nursing/__init__.py": ""})
    shutil.move(str(pkg / "modules/device/engine.py"), str(pkg / "modules/nursing/device_engine.py"))
    found = mb.scan(pkg)
    verdict = mb.compare(baseline, found)
    assert verdict.raised == {} and verdict.new_keys == []
    assert mb.totals(found) == baseline["totals"]


def test_a_new_simulator_import_in_a_module_fails(tmp_path: Path) -> None:
    pkg = _tree(tmp_path, VIOLATING)
    baseline = mb.baseline_from(mb.scan(pkg))
    _tree(tmp_path, {"modules/device/extra.py": "from clinosim.simulator import device_removal\n"})
    verdict = mb.compare(baseline, mb.scan(pkg))
    assert verdict.raised == {"module_to_simulator": (3, 2)}
    assert verdict.new_keys == ["module_to_simulator::<module>::from clinosim.simulator import device_removal"]


def test_removing_a_violation_passes_without_a_baseline_edit(tmp_path: Path) -> None:
    pkg = _tree(tmp_path, VIOLATING)
    baseline = mb.baseline_from(mb.scan(pkg))
    src = (pkg / "modules/device/engine.py").read_text()
    (pkg / "modules/device/engine.py").write_text(
        src.replace("from clinosim.simulator.device_removal import plan\n", "")
    )
    verdict = mb.compare(baseline, mb.scan(pkg))
    assert verdict.raised == {}
    assert verdict.lowered == {"module_to_simulator": (1, 2)}


def test_writing_lowers_the_totals_and_never_raises_them(tmp_path: Path) -> None:
    pkg = _tree(tmp_path, VIOLATING)
    baseline = mb.baseline_from(mb.scan(pkg))
    assert baseline["totals"] == {
        "foundation_imports": 0,
        "module_to_simulator": 2,
        "private_cross_package": 2,
        "output_to_simulator": 0,
        "qa_to_simulator": 0,
        "foreign_reference_data": 1,
    }
    (pkg / "modules/device/engine.py").write_text("")
    assert mb.lowered_baseline(baseline, mb.scan(pkg))["totals"]["module_to_simulator"] == 0
    _tree(tmp_path, {"eval/x.py": "import clinosim.simulator\n"})
    with pytest.raises(ValueError, match="qa_to_simulator"):
        mb.lowered_baseline(baseline, mb.scan(pkg))


def test_clusters_group_findings_by_importing_package_and_target(tmp_path: Path) -> None:
    pkg = _tree(tmp_path, VIOLATING)
    found = mb.clusters(pkg)
    assert dict(found["module_to_simulator"]) == {
        "modules/device -> clinosim.simulator.device_removal": 1,
        "modules/device -> clinosim.simulator._dispatch": 1,
    }
    assert dict(found["foreign_reference_data"]) == {"modules/device -> modules/disease/reference_data": 1}
    assert mb.totals(found) == mb.totals(mb.scan(pkg))


def test_both_ratchets_share_one_baseline_machinery() -> None:
    assert isinstance(mb.RATCHET, Ratchet) and isinstance(cds.RATCHET, Ratchet)
    assert mb.RATCHET.baseline != cds.RATCHET.baseline


@pytest.mark.parametrize("kind", mb.KINDS)
def test_no_rule_total_exceeds_its_stored_total(kind: str) -> None:
    verdict = mb.compare(mb.load_baseline(), mb.current_scan())
    assert kind not in verdict.raised, (
        f"{mb.RULES[kind]} — total {kind} rose (found, stored): {verdict.raised[kind]}. "
        f"New content keys: {verdict.new_keys}. "
        "Import the owner's public API (non-underscore names of its non-underscore submodules), "
        "move the logic to the owning module, or read another module's data through its accessor "
        "(implementation-rules, Module boundaries). A move is not a raise."
    )


def test_new_content_keys_are_reported() -> None:
    verdict = mb.compare(mb.load_baseline(), mb.current_scan())
    if verdict.new_keys:
        warnings.warn(
            f"module-boundary ratchet: new content keys (net-zero swaps are visible here): {verdict.new_keys}",
            stacklevel=1,
        )
    if verdict.lowered:
        warnings.warn(
            f"module-boundary ratchet: totals can be lowered with: {mb.REGENERATE} ({verdict.lowered})", stacklevel=1
        )


def test_the_printing_command_reports_the_current_totals() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "tests.unit.module_boundaries"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    ).stdout
    assert out.splitlines()[0] == json.dumps(mb.totals(mb.current_scan()))
