from apscheduler.schedulers.blocking import BlockingScheduler
from sekoia_automation.storage import PersistentJSON
from sekoia_automation.trigger import Trigger

from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient
from sekoia_valhalla_integration_modules.triggers.sync_sigma_rules_catalog import (
    UUID_MAP_FILE,
)

SAMPLE_UUIDS_LOGGED = 5


class DeleteCatalogRules(Trigger):
    """One-shot cleanup trigger. Deletes every Sekoia Rules Catalog rule
    that ``sync-sigma-rules-catalog`` created (identified via the persisted
    ``valhalla_id → sekoia_uuid`` map), then idles.

    Set ``confirm=true`` in the trigger configuration for deletions to
    actually run. When ``confirm=false`` the trigger reports what it would
    delete and makes no API calls.

    After the first successful pass the id-map is empty; subsequent scheduled
    runs are cheap no-ops. This lets operators leave the trigger enabled
    without accumulating side effects.
    """

    def run(self):
        cfg = self.module.configuration
        self._sekoia = SekoiaClient(cfg.sekoia_base_url, cfg.sekoia_api_key)
        self._confirm = bool(self.configuration.get("confirm", False))
        frequency = self.configuration.get("frequency", 86400)

        self._delete_once()

        scheduler = BlockingScheduler()
        scheduler.add_job(self._delete_once, "interval", seconds=frequency)
        scheduler.start()

    def _delete_once(self):
        try:
            with PersistentJSON(UUID_MAP_FILE, self.data_path) as id_map:
                total = len(id_map)

                if total == 0:
                    self.log("Nothing to delete: state map is empty.", level="info")
                    self.send_event(
                        event_name="valhalla-sigma-catalog-delete",
                        event={
                            "dry_run": not self._confirm,
                            "total_known": 0,
                            "deleted": 0,
                            "delete_failed": 0,
                            "remaining": [],
                        },
                    )
                    return

                if not self._confirm:
                    sample = list(id_map.values())[:SAMPLE_UUIDS_LOGGED]
                    self.log(
                        f"Dry-run: would delete {total} rules. Sample uuids: "
                        f"{sample}. Set confirm=true in the trigger config to "
                        f"proceed.",
                        level="info",
                    )
                    self.send_event(
                        event_name="valhalla-sigma-catalog-delete",
                        event={
                            "dry_run": True,
                            "total_known": total,
                            "deleted": 0,
                            "delete_failed": 0,
                            "remaining": list(id_map.values()),
                        },
                    )
                    return

                deleted = 0
                failed_uuids: list[str] = []
                valhalla_ids_to_remove: list[str] = []
                for valhalla_id, sekoia_uuid in list(id_map.items()):
                    try:
                        self._sekoia.delete_rule(sekoia_uuid)
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
                self.send_event(
                    event_name="valhalla-sigma-catalog-delete",
                    event={
                        "dry_run": False,
                        "total_known": total,
                        "deleted": deleted,
                        "delete_failed": len(failed_uuids),
                        "remaining": failed_uuids,
                    },
                )
        except Exception as exc:
            self.log_exception(
                exc, message="Failed to delete Valhalla-imported Rules Catalog rules"
            )
