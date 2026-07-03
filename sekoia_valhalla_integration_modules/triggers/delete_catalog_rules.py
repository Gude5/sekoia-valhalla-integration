import json
from collections import Counter

from apscheduler.schedulers.blocking import BlockingScheduler
from sekoia_automation.trigger import Trigger

from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient

SAMPLE_UUIDS_LOGGED = 5
DIAGNOSTIC_SAMPLE_SIZE = 200
DIAGNOSTIC_RULE_DUMP_CHARS = 2000
DEFAULT_AUTHOR = "valhalla-integration"


class DeleteCatalogRules(Trigger):
    """Cleanup trigger. Enumerates the Sekoia Rules Catalog and deletes
    every rule whose top-level ``author`` field equals a configurable
    marker (default ``valhalla-integration`` — Sekoia sets this field to
    the integration slug for every rule the sync trigger's API key
    creates).

    Set ``confirm=true`` in the trigger configuration for deletions to
    actually run. When ``confirm=false`` the trigger reports what it
    would delete and makes no DELETE calls.

    Runs once on start, then re-runs on the configured ``frequency``
    (default 24h). Subsequent runs are cheap no-ops once the tenant
    is clean.
    """

    def run(self):
        cfg = self.module.configuration
        self._sekoia = SekoiaClient(cfg.sekoia_base_url, cfg.sekoia_api_key)
        self._confirm = bool(self.configuration.get("confirm", False))
        self._author = self.configuration.get("author", DEFAULT_AUTHOR)
        frequency = self.configuration.get("frequency", 86400)

        self._delete_once()

        scheduler = BlockingScheduler()
        scheduler.add_job(self._delete_once, "interval", seconds=frequency)
        scheduler.start()

    def _delete_once(self):
        try:
            matches = [
                r for r in self._sekoia.iter_rules(match_author=self._author)
                if r.get("uuid")
            ]
            total = len(matches)

            if total == 0:
                author_histogram = self._peek_authors()
                self.log(
                    f"Nothing to delete: no rules match author={self._author!r}. "
                    f"Sampled {sum(author_histogram.values())} tenant rules; "
                    f"top authors observed: {dict(author_histogram.most_common(10))}. "
                    f"If your Valhalla-imported rules use a different author "
                    f"value, override it via the trigger's `author` config.",
                    level="info",
                )
                self.send_event(
                    event_name="valhalla-sigma-catalog-delete",
                    event={
                        "dry_run": not self._confirm,
                        "author": self._author,
                        "total_matched": 0,
                        "deleted": 0,
                        "delete_failed": 0,
                        "remaining": [],
                        "observed_authors": dict(author_histogram.most_common(10)),
                    },
                )
                return

            if not self._confirm:
                sample = [r.get("uuid") for r in matches[:SAMPLE_UUIDS_LOGGED]]
                self.log(
                    f"Dry-run: would delete {total} rules with author="
                    f"{self._author!r}. Sample uuids: {sample}. Set "
                    f"confirm=true in the trigger config to proceed.",
                    level="info",
                )
                self.send_event(
                    event_name="valhalla-sigma-catalog-delete",
                    event={
                        "dry_run": True,
                        "author": self._author,
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
                f"total_matched={total} author={self._author!r}",
                level="info",
            )
            self.send_event(
                event_name="valhalla-sigma-catalog-delete",
                event={
                    "dry_run": False,
                    "author": self._author,
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

    def _peek_authors(self) -> Counter:
        """Sample the first N rules unfiltered and return a histogram of
        their ``author`` values. Also logs the key set of a sample rule
        and a JSON-dumped preview, so operators can spot other fields
        usable as delete-time markers when ``author`` is unset."""
        histogram: Counter = Counter()
        first_rule: dict | None = None
        try:
            for i, rule in enumerate(self._sekoia.iter_rules()):
                if i >= DIAGNOSTIC_SAMPLE_SIZE:
                    break
                if first_rule is None:
                    first_rule = rule
                histogram[rule.get("author") or "<null>"] += 1
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
