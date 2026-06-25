from sekoia_valhalla_integration_modules import (
    SekoiaValhallaIntegrationModule,
    SyncSigmaIntelligenceCenter,
    SyncSigmaRulesCatalog,
)

if __name__ == "__main__":
    module = SekoiaValhallaIntegrationModule()
    module.register(SyncSigmaIntelligenceCenter, "sync-sigma-intelligence-center")
    module.register(SyncSigmaRulesCatalog, "sync-sigma-rules-catalog")
    module.run()
