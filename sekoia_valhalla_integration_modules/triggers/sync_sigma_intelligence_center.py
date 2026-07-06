import json
import uuid

from apscheduler.schedulers.blocking import BlockingScheduler
from sekoia_automation.storage import PersistentJSON
from sekoia_automation.trigger import Trigger

from sekoia_valhalla_integration_modules.client import ValhallaClient
from sekoia_valhalla_integration_modules.stix import (
    build_bundle,
    sigma_rule_to_indicator,
)

SEEN_FILE = "valhalla-sigma-ic-seen.json"


class SyncSigmaIntelligenceCenter(Trigger):
    def run(self):
        cfg = self.module.configuration
        self._client = ValhallaClient(cfg.api_key)
        frequency = self.configuration.get("frequency", 86400)

        self._pull_once()

        scheduler = BlockingScheduler()
        scheduler.add_job(self._pull_once, "interval", seconds=frequency)
        scheduler.start()

    def _pull_once(self):
        try:
            rules = self._client.get_sigma_feed()
            with PersistentJSON(SEEN_FILE, self.data_path) as seen:
                new_rules = [r for r in rules if self._rule_key(r) not in seen]
                if new_rules:
                    self._emit_bundle(new_rules)
                    for r in new_rules:
                        seen[self._rule_key(r)] = True
                    self.log(f"Emitted {len(new_rules)} new Sigma rules", level="info")
                else:
                    self.log("No new Sigma rules since last pull", level="info")
        except Exception as exc:
            self.log_exception(exc, message="Failed to pull Valhalla Sigma feed")

    def _rule_key(self, rule: dict) -> str:
        return (
            rule.get("id") or rule.get("filename") or json.dumps(rule, sort_keys=True)
        )

    def _emit_bundle(self, rules: list[dict]):
        indicators = [sigma_rule_to_indicator(r) for r in rules]
        bundle = build_bundle(indicators)

        emit_dir = self.data_path / f"emit-{uuid.uuid4()}"
        emit_dir.mkdir(parents=True, exist_ok=True)
        (emit_dir / "bundle.json").write_text(json.dumps(bundle))

        self.send_event(
            event_name="valhalla-sigma-bundle",
            event={"bundle_path": "bundle.json"},
            directory=str(emit_dir.relative_to(self.data_path)),
            remove_directory=True,
        )
