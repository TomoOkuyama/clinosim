"""JP-eCheckup 事業者健診 opt-in module(P2-13 PR3 sub-PR-A、session 47).

opt-in 制御は SimulatorConfig.modules["health_checkup"]=True + country=JP。
default OFF で急性期病院想定を維持する。

このモジュールは POST_RECORDS enricher として動作し、選定サブセットの
患者に対して以下を追加する:

- CHECKUP encounter(1 日完結の年次法定健診)
- 法定健診項目 ObservationRecord 5 種
  (BMI / 収縮期 BP / 拡張期 BP / HbA1c / LDL コレステロール)
- HEALTH_CHECKUP_REPORT の ClinicalDocument stub(narrative=None)

narrative content は TemplateNarrativePass(Stage 2)が事後に populate する。
FHIR emit path は _fhir_composition.py の JP-eCheckup builder が担う。
"""

from clinosim.modules.health_checkup.engine import (
    HEALTH_CHECKUP_SUBSET_RATE,
    enrich_health_checkup,
)

__all__ = ["enrich_health_checkup", "HEALTH_CHECKUP_SUBSET_RATE"]
