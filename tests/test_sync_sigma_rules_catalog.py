import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sekoia_valhalla_integration_modules.triggers.sync_sigma_rules_catalog import (
    UUID_MAP_FILE,
    SyncSigmaRulesCatalog,
)

SAMPLE_RULES = [
    {"id": "valhalla-a", "filename": "a.yml", "content": "title: A\nlevel: medium\n"},
    {"id": "valhalla-b", "filename": "b.yml", "content": "title: B\nlevel: high\n"},
]


@pytest.fixture
def trigger(data_storage):
    t = SyncSigmaRulesCatalog(data_path=Path(data_storage))
    t._valhalla = MagicMock()
    t._valhalla.get_sigma_feed.return_value = list(SAMPLE_RULES)
    t._sekoia = MagicMock()
    t._sekoia.create_rule.side_effect = lambda body: f"sekoia-{body['name']}"
    t._alert_type_uuid = "alert-type-uuid"
    t._enabled = False
    t.send_event = MagicMock()
    t._send_logs_to_api = MagicMock()
    return t


def test_first_sync_posts_all_rules_and_persists_uuids(trigger, data_storage):
    trigger._sync_once()

    assert trigger._sekoia.create_rule.call_count == 2
    assert trigger._sekoia.update_rule.call_count == 0

    trigger.send_event.assert_called_once()
    call = trigger.send_event.call_args
    assert call.kwargs["event_name"] == "valhalla-sigma-catalog-sync"
    assert call.kwargs["event"] == {"created": 2, "updated": 0}

    id_map = json.loads((Path(data_storage) / UUID_MAP_FILE).read_text())
    assert id_map == {"valhalla-a": "sekoia-A", "valhalla-b": "sekoia-B"}


def test_second_sync_puts_existing_rules(trigger):
    trigger._sync_once()
    trigger._sekoia.create_rule.reset_mock()
    trigger._sekoia.update_rule.reset_mock()
    trigger.send_event.reset_mock()

    trigger._sync_once()

    assert trigger._sekoia.create_rule.call_count == 0
    assert trigger._sekoia.update_rule.call_count == 2
    trigger._sekoia.update_rule.assert_any_call("sekoia-A", _any_dict())
    trigger.send_event.assert_called_once()
    assert trigger.send_event.call_args.kwargs["event"] == {"created": 0, "updated": 2}


def test_third_sync_only_posts_new_rule(trigger):
    trigger._sync_once()
    trigger._sekoia.create_rule.reset_mock()
    trigger._sekoia.update_rule.reset_mock()

    new_rule = {"id": "valhalla-c", "filename": "c.yml", "content": "title: C\n"}
    trigger._valhalla.get_sigma_feed.return_value = SAMPLE_RULES + [new_rule]

    trigger._sync_once()

    assert trigger._sekoia.create_rule.call_count == 1
    assert trigger._sekoia.update_rule.call_count == 2
    created_body = trigger._sekoia.create_rule.call_args.args[0]
    assert created_body["name"] == "C"


def test_skips_rules_without_valhalla_id(trigger):
    trigger._valhalla.get_sigma_feed.return_value = [
        {"filename": "no_id.yml", "content": "title: NoID\n"},
        SAMPLE_RULES[0],
    ]

    trigger._sync_once()

    assert trigger._sekoia.create_rule.call_count == 1
    created_body = trigger._sekoia.create_rule.call_args.args[0]
    assert created_body["name"] == "A"


def test_per_rule_errors_do_not_abort_sync(trigger):
    trigger._sekoia.create_rule.side_effect = [
        RuntimeError("boom on A"),
        "sekoia-B",
    ]

    trigger._sync_once()

    assert trigger._sekoia.create_rule.call_count == 2
    trigger.send_event.assert_called_once()
    assert trigger.send_event.call_args.kwargs["event"] == {"created": 1, "updated": 0}


def test_valhalla_feed_error_does_not_crash(trigger):
    trigger._valhalla.get_sigma_feed.side_effect = RuntimeError("feed down")

    trigger._sync_once()

    assert trigger._sekoia.create_rule.call_count == 0
    trigger.send_event.assert_not_called()


class _any_dict:
    """Match any dict argument in mock assertions."""

    def __eq__(self, other):
        return isinstance(other, dict)
