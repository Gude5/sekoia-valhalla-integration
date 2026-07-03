import json
from collections import Counter

from apscheduler.schedulers.blocking import BlockingScheduler
from sekoia_automation.trigger import Trigger

from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient

SAMPLE_UUIDS_LOGGED = 5
DIAGNOSTIC_SAMPLE_SIZE = 200
DIAGNOSTIC_RULE_DUMP_CHARS = 2000
DEFAULT_MATCH_FIELD = "created_by"


class DeleteCatalogRules(Trigger):
    """Cleanup trigger. Enumerates the Sekoia Rules Catalog and deletes
    every rule whose configured top-level field equals a configured
    value. The intended use is
    ``match_field=created_by`` +
    ``match_value=<api-key-uuid>`` — every rule the sync trigger's API
    key creates carries that key's UUID in ``created_by``, so filtering
    on it uniquely identifies our imports without touching anything the
    tenant's other users or Sekoia's own catalog created.

    You can find the API key UUID either in Sekoia's Settings → API Keys
    UI or, first-time, by running this trigger in dry-run with
    ``match_value`` empty — the zero-match diagnostic logs the top
    ``created_by`` UUIDs observed in the tenant.

    Set ``confirm=true`` in the trigger configuration for deletions to
    actually run. When ``confirm=false`` the trigger reports what it
    would delete and makes no DELETE calls.
    """

    def run(self):
        cfg = self.module.configuration
        self._sekoia = SekoiaClient(cfg.sekoia_base_url, cfg.sekoia_api_key)
        self._confirm = bool(self.configuration.get("confirm", False))
        self._match_field = self.configuration.get("match_field", DEFAULT_MATCH_FIELD)
        self._match_value = self.configuration.get("match_value", "")
        frequency = self.configuration.get("frequency", 86400)

        self._delete_once()

        scheduler = BlockingScheduler()
        scheduler.add_job(self._delete_once, "interval", seconds=frequency)
        scheduler.start()

    def _delete_once(self):
        try:
            if not self._match_value:
                self._log_diagnostic_no_value()
                return

            matches = [
                r
                for r in self._sekoia.iter_rules(
                    match_field=self._match_field,
                    match_value=self._match_value,
                )
                if r.get("uuid")
            ]
            total = len(matches)

            if total == 0:
                histogram = self._peek_field_values(self._match_field)
                self.log(
                    f"Nothing to delete: no rules where "
                    f"{self._match_field}={self._match_value!r}. Sampled "
                    f"{sum(histogram.values())} tenant rules; top "
                    f"{self._match_field} values observed: "
                    f"{dict(histogram.most_common(10))}. If your "
                    f"Valhalla-imported rules use a different value, override "
                    f"via the trigger's `match_value` config.",
                    level="info",
                )
                self.send_event(
                    event_name="valhalla-sigma-catalog-delete",
                    event={
                        "dry_run": not self._confirm,
                        "match_field": self._match_field,
                        "match_value": self._match_value,
                        "total_matched": 0,
                        "deleted": 0,
                        "delete_failed": 0,
                        "remaining": [],
                        f"observed_{self._match_field}": dict(
                            histogram.most_common(10)
                        ),
                    },
                )
                return

            if not self._confirm:
                sample = [r.get("uuid") for r in matches[:SAMPLE_UUIDS_LOGGED]]
                self.log(
                    f"Dry-run: would delete {total} rules where "
                    f"{self._match_field}={self._match_value!r}. Sample uuids: "
                    f"{sample}. Set confirm=true in the trigger config to "
                    f"proceed.",
                    level="info",
                )
                self.send_event(
                    event_name="valhalla-sigma-catalog-delete",
                    event={
                        "dry_run": True,
                        "match_field": self._match_field,
                        "match_value": self._match_value,
                        "total_matched": total,
                        "deleted": 0,
                        "delete_failed": 0,
                        "remaining": [r["uuid"] for r in matches],
                    },
                )
                return

            deleted = 0
            failed_uuids: list[str] = []
            for rule in matches:
                sekoia_uuid = rule["uuid"]
                try:
                    self._sekoia.delete_rule(sekoia_uuid)
                    deleted += 1
                except Exception as exc:
                    failed_uuids.append(sekoia_uuid)
                    self.log(
                        f"Failed to delete rule {sekoia_uuid}: {exc}",
                        level="warning",
                    )

            self.log(
                f"Delete summary: deleted={deleted} failed={len(failed_uuids)} "
                f"total_matched={total} filter={self._match_field}="
                f"{self._match_value!r}",
                level="info",
            )
            self.send_event(
                event_name="valhalla-sigma-catalog-delete",
                event={
                    "dry_run": False,
                    "match_field": self._match_field,
                    "match_value": self._match_value,
                    "total_matched": total,
                    "deleted": deleted,
                    "delete_failed": len(failed_uuids),
                    "remaining": failed_uuids,
                },
            )
        except Exception as exc:
            self.log_exception(
                exc, message="Failed to delete Valhalla-imported Rules Catalog rules"
            )

    def _log_diagnostic_no_value(self) -> None:
        """Emitted when the trigger has no ``match_value`` configured.
        Samples the tenant and shows the distinct values of the configured
        match field so the operator can spot their API key's UUID (for
        ``match_field=created_by``) or whichever discriminator they want."""
        histogram = self._peek_field_values(self._match_field)
        self.log(
            f"No match_value configured. Sampled {sum(histogram.values())} "
            f"tenant rules; top {self._match_field} values observed: "
            f"{dict(histogram.most_common(10))}. Copy your API key's UUID "
            f"from Sekoia (Settings → API Keys) or from this list and set it "
            f"as the trigger's `match_value` config, then re-run.",
            level="info",
        )
        self.send_event(
            event_name="valhalla-sigma-catalog-delete",
            event={
                "dry_run": True,
                "match_field": self._match_field,
                "match_value": "",
                "total_matched": 0,
                "deleted": 0,
                "delete_failed": 0,
                "remaining": [],
                f"observed_{self._match_field}": dict(histogram.most_common(10)),
            },
        )

    def _peek_field_values(self, field: str) -> Counter:
        """Sample the first N rules unfiltered, return a histogram of
        ``field`` values seen. Also logs the sample rule's key set and a
        JSON dump of the first rule for further introspection."""
        histogram: Counter = Counter()
        first_rule: dict | None = None
        try:
            for i, rule in enumerate(self._sekoia.iter_rules()):
                if i >= DIAGNOSTIC_SAMPLE_SIZE:
                    break
                if first_rule is None:
                    first_rule = rule
                histogram[rule.get(field) or "<null>"] += 1
        except Exception as exc:
            self.log(f"Diagnostic peek failed: {exc}", level="warning")

        if first_rule is not None:
            preview = json.dumps(first_rule, default=str)[
                :DIAGNOSTIC_RULE_DUMP_CHARS
            ]
            self.log(
                f"Diagnostic — sample rule keys: {sorted(first_rule.keys())}. "
                f"First rule (truncated to {DIAGNOSTIC_RULE_DUMP_CHARS} chars): "
                f"{preview}",
                level="info",
            )
        return histogram
