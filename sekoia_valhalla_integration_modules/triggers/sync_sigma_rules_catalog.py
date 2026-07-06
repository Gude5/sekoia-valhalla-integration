from collections import Counter

from apscheduler.schedulers.blocking import BlockingScheduler
from sekoia_automation.storage import PersistentJSON
from sekoia_automation.trigger import Trigger

from sekoia_valhalla_integration_modules.client import ValhallaClient
from sekoia_valhalla_integration_modules.sekoia_client import (
    SekoiaClient,
    SekoiaRuleNotFoundError,
)
from sekoia_valhalla_integration_modules.sigma_mapper import (
    convert_payload_to_ecs,
    sigma_rule_to_catalog_payload,
)

UUID_MAP_FILE = "valhalla-sigma-catalog-uuid-map.json"
TOP_UNMAPPED_REPORT = 20


class SyncSigmaRulesCatalog(Trigger):
    def run(self):
        cfg = self.module.configuration
        self._valhalla = ValhallaClient(cfg.base_url, cfg.api_key)
        self._sekoia = SekoiaClient(cfg.sekoia_base_url, cfg.sekoia_api_key)
        self._alert_type_uuid = self.configuration["alert_type_uuid"]
        self._enabled = self.configuration.get("enabled", False)
        frequency = self.configuration.get("frequency", 86400)

        self._sync_once()

        scheduler = BlockingScheduler()
        scheduler.add_job(self._sync_once, "interval", seconds=frequency)
        scheduler.start()

    def _sync_once(self):
        try:
            rules = self._valhalla.get_sigma_feed()
            created = 0
            updated = 0
            failed = 0
            skipped_unmapped = 0
            unmapped_field_counter: Counter[str] = Counter()
            first_failure_logged = False
            with PersistentJSON(UUID_MAP_FILE, self.data_path) as id_map:
                for rule in rules:
                    valhalla_id = rule.get("id")
                    if not valhalla_id:
                        continue

                    parsed, unmapped = convert_payload_to_ecs(
                        rule.get("content", "")
                    )
                    if parsed is None:
                        skipped_unmapped += 1
                        for f in unmapped:
                            unmapped_field_counter[f] += 1
                        continue

                    body = sigma_rule_to_catalog_payload(
                        rule,
                        parsed,
                        self._alert_type_uuid,
                        self._enabled,
                    )
                    try:
                        if valhalla_id in id_map:
                            try:
                                self._sekoia.update_rule(
                                    id_map[valhalla_id], body
                                )
                                updated += 1
                            except SekoiaRuleNotFoundError:
                                # Stale id-map entry: the tenant-side rule
                                # was deleted (or attributed to a different
                                # key). Drop the entry and POST as new.
                                del id_map[valhalla_id]
                                sekoia_uuid = self._sekoia.create_rule(body)
                                id_map[valhalla_id] = sekoia_uuid
                                created += 1
                        else:
                            sekoia_uuid = self._sekoia.create_rule(body)
                            id_map[valhalla_id] = sekoia_uuid
                            created += 1
                    except Exception as exc:
                        failed += 1
                        # Log the first failure loudly with the full POST body
                        # so the user can see exactly what shape the API rejected.
                        if not first_failure_logged:
                            self.log(
                                f"First rule sync failure (subsequent failures "
                                f"counted but not individually logged). "
                                f"Rule id={valhalla_id}, name={body.get('name')!r}. "
                                f"Sent body: {body}. Error: {exc}",
                                level="error",
                            )
                            first_failure_logged = True

            top_unmapped = dict(unmapped_field_counter.most_common(TOP_UNMAPPED_REPORT))
            self.log(
                f"Catalog sync: created={created} updated={updated} "
                f"failed={failed} skipped_unmapped={skipped_unmapped} "
                f"total_rules={len(rules)} top_unmapped={top_unmapped}",
                level="info",
            )
            self.send_event(
                event_name="valhalla-sigma-catalog-sync",
                event={
                    "created": created,
                    "updated": updated,
                    "failed": failed,
                    "skipped_unmapped": skipped_unmapped,
                    "total_rules": len(rules),
                    "top_unmapped": top_unmapped,
                },
            )
        except Exception as exc:
            self.log_exception(
                exc, message="Failed to sync Valhalla Sigma to Rules Catalog"
            )
