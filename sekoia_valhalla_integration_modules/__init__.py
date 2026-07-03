from sekoia_automation.module import Module

from sekoia_valhalla_integration_modules.models import (
    SekoiaValhallaIntegrationModuleConfiguration,
)
from sekoia_valhalla_integration_modules.triggers.delete_catalog_rules import (
    DeleteCatalogRules,
)
from sekoia_valhalla_integration_modules.triggers.sync_sigma_intelligence_center import (
    SyncSigmaIntelligenceCenter,
)
from sekoia_valhalla_integration_modules.triggers.sync_sigma_rules_catalog import (
    SyncSigmaRulesCatalog,
)


class SekoiaValhallaIntegrationModule(Module):
    configuration: SekoiaValhallaIntegrationModuleConfiguration


__all__ = [
    "DeleteCatalogRules",
    "SekoiaValhallaIntegrationModule",
    "SyncSigmaIntelligenceCenter",
    "SyncSigmaRulesCatalog",
]
