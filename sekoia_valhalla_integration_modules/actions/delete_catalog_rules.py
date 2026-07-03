from sekoia_automation.action import Action
from sekoia_automation.storage import PersistentJSON

from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient
from sekoia_valhalla_integration_modules.triggers.sync_sigma_rules_catalog import (
    UUID_MAP_FILE,
)

SAMPLE_UUIDS_LOGGED = 5


class DeleteCatalogRules(Action):
    def run(self, arguments: dict) -> dict:
        cfg = self.module.configuration
        sekoia = SekoiaClient(cfg.sekoia_base_url, cfg.sekoia_api_key)
        confirm = bool(arguments.get("confirm", False))

        with PersistentJSON(UUID_MAP_FILE, self.data_path) as id_map:
            total = len(id_map)

            if total == 0:
                self.log("Nothing to delete: state map is empty.", level="info")
                return {
                    "dry_run": not confirm,
                    "total_known": 0,
                    "deleted": 0,
                    "delete_failed": 0,
                    "remaining": [],
                }

            if not confirm:
                sample = list(id_map.values())[:SAMPLE_UUIDS_LOGGED]
                self.log(
                    f"Dry-run: would delete {total} rules. "
                    f"Sample uuids: {sample}. Re-run with confirm=true to proceed.",
                    level="info",
                )
                return {
                    "dry_run": True,
                    "total_known": total,
                    "deleted": 0,
                    "delete_failed": 0,
                    "remaining": list(id_map.values()),
                }

            deleted = 0
            failed_uuids: list[str] = []
            valhalla_ids_to_remove: list[str] = []
            for valhalla_id, sekoia_uuid in list(id_map.items()):
                try:
                    sekoia.delete_rule(sekoia_uuid)
                    deleted += 1
                    valhalla_ids_to_remove.append(valhalla_id)
                except Exception as exc:
                    failed_uuids.append(sekoia_uuid)
                    self.log(
                        f"Failed to delete rule {sekoia_uuid}: {exc}",
                        level="warning",
                    )

            for vid in valhalla_ids_to_remove:
                del id_map[vid]

            self.log(
                f"Delete summary: deleted={deleted} failed={len(failed_uuids)} "
                f"total_known={total}",
                level="info",
            )
            return {
                "dry_run": False,
                "total_known": total,
                "deleted": deleted,
                "delete_failed": len(failed_uuids),
                "remaining": failed_uuids,
            }
