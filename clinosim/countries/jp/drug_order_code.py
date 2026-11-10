"""JP order code of a disease-YAML drug entry (``drug_order_code``
"jp_route_product", Issue #3194; Issue #2351).

The drug catalog's YJ product for the drug and its route (the entry's
``route``, else the route in its dose string, else the name heuristic) — the
same code the FHIR builders emit; ``""`` when the catalog lists no product for
that route.
"""

from __future__ import annotations

from typing import Any

from clinosim.country_profile import register_implementation


@register_implementation("drug_order_code", "jp_route_product")
def jp_route_product(spec: dict[str, Any], country: str) -> str:
    """The YJ product code for the entry's drug and route."""
    from clinosim.codes.drugs import jp_drug_code_for_name, protocol_drug_name
    from clinosim.modules.order.engine import parse_dose_string
    from clinosim.simulator.helpers import _determine_route

    drug = protocol_drug_name(spec)
    route = str(spec.get("route") or parse_dose_string(str(spec.get("dose") or "")).get("route") or "")
    return jp_drug_code_for_name(drug, route or _determine_route(drug, "")) or ""
