import json
from collections import Counter
from typing import Iterable

from apscheduler.schedulers.blocking import BlockingScheduler
from sekoia_automation.trigger import Trigger

from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient
from sekoia_valhalla_integration_modules.sigma_mapper import MARKER_TAG

SAMPLE_UUIDS_LOGGED = 5
DIAGNOSTIC_SAMPLE_SIZE = 200
DIAGNOSTIC_RULE_DUMP_CHARS = 2000
DEFAULT_MATCH_FIELD = "created_by"


def _rule_has_tag(rule: dict, tag_name: str) -> bool:
    """Return True if any of ``rule['tags']`` has ``name == tag_name``.

    Sekoia serialises tags as either a list of dicts (``{"uuid", "name"}``)
    or, defensively, plain strings — accept both shapes."""
    for tag in rule.get("tags") or []:
        if isinstance(tag, dict) and tag.get("name") == tag_name:
            return True
        if isinstance(tag, str) and tag == tag_name:
            return True
    return False


def _tag_names(rule: dict) -> Iterable[str]:
    for tag in rule.get("tags") or []:
        if isinstance(tag, dict) and tag.get("name"):
            yield tag["name"]
        elif isinstance(tag, str):
            yield tag


class DeleteCatalogRules(Trigger):
    """Cleanup trigger. Deletes every Rules Catalog rule the sync trigger
    created.

    Default mode (**tag mode**): filters by the marker tag the sync
    trigger attaches to every rule it POSTs (``valhalla-integration``).
    This is stable across Sekoia API-key rotations — unlike ``created_by``.

    Advanced mode (**field mode**): set ``marker_tag`` to empty and
    provide ``match_field`` + ``match_value`` to filter by any top-level
    rule field. Useful for cleaning up rules that predate the marker tag
    (e.g. imported by an older version of the integration).

    Set ``confirm=true`` in the trigger configuration for deletions to
    actually run. When ``confirm=false`` the trigger reports what it
    would delete and makes no DELETE calls.
    """

    def run(self):
        cfg = self.module.configuration
        self._sekoia = SekoiaClient(cfg.sekoia_base_url, cfg.sekoia_api_key)
        self._confirm = bool(self.configuration.get("confirm", False))
        self._marker_tag = self.configuration.get("marker_tag", MARKER_TAG)
        self._match_field = self.configuration.get("match_field", DEFAULT_MATCH_FIELD)
        self._match_value = self.configuration.get("match_value", "")
        frequency = self.configuration.get("frequency", 86400)

        self._delete_once()

        scheduler = BlockingScheduler()
        scheduler.add_job(self._delete_once, "interval", seconds=frequency)
        scheduler.start()

    def _delete_once(self):
        try:
            if self._marker_tag:
                matches, filter_desc = self._collect_by_tag(self._marker_tag)
            elif self._match_value:
                matches, filter_desc = self._collect_by_field(
                    self._match_field, self._match_value
                )
            else:
                self._log_diagnostic_no_filter()
                return

            self._process_matches(matches, filter_desc)
        except Exception as exc:
            self.log_exception(
                exc, message="Failed to delete Valhalla-imported Rules Catalog rules"
            )

    def _collect_by_tag(self, tag: str) -> tuple[list[dict], str]:
        matches = [
            r
            for r in self._sekoia.iter_rules()
            if r.get("uuid") and _rule_has_tag(r, tag)
        ]
        return matches, f"tag={tag!r}"

    def _collect_by_field(self, field: str, value: str) -> tuple[list[dict], str]:
        matches = [
            r
            for r in self._sekoia.iter_rules(match_field=field, match_value=value)
            if r.get("uuid")
        ]
        return matches, f"{field}={value!r}"

    def _process_matches(self, matches: list[dict], filter_desc: str) -> None:
        total = len(matches)

        if total == 0:
            self._log_zero_matches(filter_desc)
            return

        if not self._confirm:
            sample = [r.get("uuid") for r in matches[:SAMPLE_UUIDS_LOGGED]]
            self.log(
                f"Dry-run: would delete {total} rules where {filter_desc}. "
                f"Sample uuids: {sample}. Set confirm=true in the trigger "
                f"config to proceed.",
                level="info",
            )
            self.send_event(
                event_name="valhalla-sigma-catalog-delete",
                event=self._summary_event(
                    dry_run=True,
                    total_matched=total,
                    deleted=0,
                    delete_failed=0,
                    remaining=[r["uuid"] for r in matches],
                ),
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
            f"total_matched={total} filter={filter_desc}",
            level="info",
        )
        self.send_event(
            event_name="valhalla-sigma-catalog-delete",
            event=self._summary_event(
                dry_run=False,
                total_matched=total,
                deleted=deleted,
                delete_failed=len(failed_uuids),
                remaining=failed_uuids,
            ),
        )

    def _summary_event(
        self,
        *,
        dry_run: bool,
        total_matched: int,
        deleted: int,
        delete_failed: int,
        remaining: list[str],
    ) -> dict:
        return {
            "dry_run": dry_run,
            "marker_tag": self._marker_tag,
            "match_field": self._match_field if not self._marker_tag else "",
            "match_value": self._match_value if not self._marker_tag else "",
            "total_matched": total_matched,
            "deleted": deleted,
            "delete_failed": delete_failed,
            "remaining": remaining,
        }

    def _log_zero_matches(self, filter_desc: str) -> None:
        """Log a histogram of the field or tag values seen so the operator
        can figure out what to configure."""
        event: dict = {
            "dry_run": not self._confirm,
            "marker_tag": self._marker_tag,
            "match_field": self._match_field if not self._marker_tag else "",
            "match_value": self._match_value if not self._marker_tag else "",
            "total_matched": 0,
            "deleted": 0,
            "delete_failed": 0,
            "remaining": [],
        }
        if self._marker_tag:
            tag_histogram = self._peek_tag_names()
            self.log(
                f"Nothing to delete: no rules carry tag={self._marker_tag!r}. "
                f"Sampled {sum(tag_histogram.values())} tag mentions across "
                f"tenant rules; top tags observed: "
                f"{dict(tag_histogram.most_common(10))}. If your Valhalla "
                f"imports predate the marker tag, disable tag mode "
                f"(`marker_tag=` empty) and configure "
                f"`match_field`/`match_value` instead.",
                level="info",
            )
            event["observed_tags"] = dict(tag_histogram.most_common(10))
        else:
            field_histogram = self._peek_field_values(self._match_field)
            self.log(
                f"Nothing to delete: no rules where "
                f"{self._match_field}={self._match_value!r}. Sampled "
                f"{sum(field_histogram.values())} tenant rules; top "
                f"{self._match_field} values observed: "
                f"{dict(field_histogram.most_common(10))}. If your "
                f"Valhalla-imported rules use a different value, override "
                f"via the trigger's `match_value` config.",
                level="info",
            )
            event[f"observed_{self._match_field}"] = dict(
                field_histogram.most_common(10)
            )
        self.send_event(
            event_name="valhalla-sigma-catalog-delete", event=event
        )

    def _log_diagnostic_no_filter(self) -> None:
        """Emitted when both ``marker_tag`` and ``match_value`` are empty."""
        histogram = self._peek_field_values(self._match_field)
        self.log(
            f"No marker_tag and no match_value configured. Sampled "
            f"{sum(histogram.values())} tenant rules; top "
            f"{self._match_field} values observed: "
            f"{dict(histogram.most_common(10))}. Set either `marker_tag` "
            f"(default) or `match_value` and re-run.",
            level="info",
        )
        self.send_event(
            event_name="valhalla-sigma-catalog-delete",
            event={
                "dry_run": True,
                "marker_tag": "",
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

    def _peek_tag_names(self) -> Counter:
        """Sample the first N rules unfiltered, return a histogram of the
        distinct tag names seen. Each rule contributes each of its tags
        once, so a tag on N rules counts N times."""
        histogram: Counter = Counter()
        try:
            for i, rule in enumerate(self._sekoia.iter_rules()):
                if i >= DIAGNOSTIC_SAMPLE_SIZE:
                    break
                for name in _tag_names(rule):
                    histogram[name] += 1
        except Exception as exc:
            self.log(f"Diagnostic peek failed: {exc}", level="warning")
        return histogram
