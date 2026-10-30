"""clinosim.modules.prophylaxis — standard-of-care prophylaxis for inpatients.

Currently ships DVT (VTE) chemoprophylaxis (Enoxaparin 40 mg SC daily) for
inpatient encounters ≥ 48 h that do not already have a therapeutic
anticoagulant on board and do not hit a skip rule in
``reference_data/prophylaxis_rules.yaml`` (pediatric age gate, active
GI/CNS bleed, delivery admission, active DVT/PE treatment) or a
major / contraindicated ``drug_safety`` pair with an active medication.

Registered as POST_ENCOUNTER order 75 — after ``device`` (70) so device
placement is visible, before ``hai`` (80) so HAI empirical antibiotics
do not perturb the prophylaxis decision.

See ``clinosim/modules/prophylaxis/README.md`` (canonical 11-section)
for design + spec.
"""

from clinosim.modules.prophylaxis.engine import (
    build_dvt_prophylaxis_orders,
    should_skip_dvt_prophylaxis,
)

__all__ = [
    "build_dvt_prophylaxis_orders",
    "should_skip_dvt_prophylaxis",
]
