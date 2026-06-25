import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sekoia_valhalla_integration_modules.triggers.sync_sigma_intelligence_center import (
    SEEN_FILE,
    SyncSigmaIntelligenceCenter,
)

SAMPLE_RULES = [
    {"id": "id-a", "filename": "rule_a.yml", "content": "title: A"},
    {"id": "id-b", "filename": "rule_b.yml", "content": "title: B"},
]


@pytest.fixture
def trigger(data_storage):
    t = SyncSigmaIntelligenceCenter(data_path=Path(data_storage))
    t._client = MagicMock()
    t._client.get_sigma_feed.return_value = list(SAMPLE_RULES)
    t.send_event = MagicMock()
    t._send_logs_to_api = MagicMock()
    return t


def test_pull_once_emits_bundle_on_first_pass(trigger, data_storage):
    trigger._pull_once()

    assert trigger.send_event.call_count == 1
    call = trigger.send_event.call_args
    assert call.kwargs["event_name"] == "valhalla-sigma-bundle"
    assert call.kwargs["event"] == {"bundle_path": "bundle.json"}
    assert call.kwargs["remove_directory"] is True

    emit_dir = Path(data_storage) / call.kwargs["directory"]
    bundle_path = emit_dir / "bundle.json"
    assert bundle_path.is_file()
    bundle = json.loads(bundle_path.read_text())
    assert bundle["type"] == "bundle"
    assert len(bundle["objects"]) == len(SAMPLE_RULES)
    assert {obj["name"] for obj in bundle["objects"]} == {"rule_a.yml", "rule_b.yml"}


def test_pull_once_dedupes_on_second_pass(trigger, data_storage):
    trigger._pull_once()
    trigger.send_event.reset_mock()

    trigger._pull_once()
    assert trigger.send_event.call_count == 0

    seen_path = Path(data_storage) / SEEN_FILE
    assert seen_path.is_file()
    seen = json.loads(seen_path.read_text())
    assert set(seen) == {"id-a", "id-b"}


def test_pull_once_only_emits_new_rules(trigger, data_storage):
    trigger._pull_once()

    new_rule = {"id": "id-c", "filename": "rule_c.yml", "content": "title: C"}
    trigger._client.get_sigma_feed.return_value = SAMPLE_RULES + [new_rule]
    trigger.send_event.reset_mock()

    trigger._pull_once()

    assert trigger.send_event.call_count == 1
    call = trigger.send_event.call_args
    emit_dir = Path(data_storage) / call.kwargs["directory"]
    bundle = json.loads((emit_dir / "bundle.json").read_text())
    assert len(bundle["objects"]) == 1
    assert bundle["objects"][0]["name"] == "rule_c.yml"


def test_pull_once_swallows_client_errors(trigger):
    trigger._client.get_sigma_feed.side_effect = RuntimeError("boom")

    trigger._pull_once()

    assert trigger.send_event.call_count == 0
