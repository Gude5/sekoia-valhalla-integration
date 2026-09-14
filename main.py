from nextron_valhalla_sigma_rules_modules import (
    DeleteCatalogRules,
    NextronValhallaSigmaRulesModule,
    SyncSigmaRulesCatalog,
)

if __name__ == "__main__":
    module = NextronValhallaSigmaRulesModule()
    module.register(SyncSigmaRulesCatalog, "sync-sigma-rules-catalog")
    module.register(DeleteCatalogRules, "delete-catalog-rules")
    module.run()
