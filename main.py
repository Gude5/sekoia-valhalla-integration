from sekoia_valhalla_integration_modules import (
    DeleteCatalogRules,
    SekoiaValhallaIntegrationModule,
    SyncSigmaRulesCatalog,
)

if __name__ == "__main__":
    module = SekoiaValhallaIntegrationModule()
    module.register(SyncSigmaRulesCatalog, "sync-sigma-rules-catalog")
    module.register(DeleteCatalogRules, "delete-catalog-rules")
    module.run()
