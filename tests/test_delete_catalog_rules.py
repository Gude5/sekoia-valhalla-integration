from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sekoia_valhalla_integration_modules.sigma_mapper import MARKER_TAG
from sekoia_valhalla_integration_modules.triggers.delete_catalog_rules import (
    DEFAULT_MATCH_FIELD,
    DeleteCatalogRules,
)

API_KEY_UUID = "9764d1db-7211-44b0-9198-d027cafc0bd2"


@pytest.fixture
def trigger(data_storage):
    t = DeleteCatalogRules(data_path=Path(data_storage))
    t._sekoia = MagicMock()
    t._confirm = True
    t._marker_tag = MARKER_TAG
    t._match_field = DEFAULT_MATCH_FIELD
    t._match_value = ""
    t.send_event = MagicMock()
    t._send_logs_to_api = MagicMock()
    return t


def _tagged_rule(uuid: str, *tag_names: str) -> dict:
    return {
        "uuid": uuid,
        "tags": [{"uuid": f"tag-{n}", "name": n} for n in tag_names],
    }


# ---------------------------------------------------------------------------
# Tag mode (default)
# ---------------------------------------------------------------------------


def test_tag_mode_matches_rules_carrying_marker_tag(trigger):
    trigger._sekoia.iter_rules.return_value = iter(
        [
            _tagged_rule("sk-1", "attack.t1059", MARKER_TAG),
            _tagged_rule("sk-2", "attack.t1059"),  # no marker → skip
            _tagged_rule("sk-3", MARKER_TAG),
        ]
    )

    trigger._delete_once()

    # Iter unfiltered (no server-side field match in tag mode).
    trigger._sekoia.iter_rules.assert_called_once_with()
    # sk-1 and sk-3 deleted; sk-2 spared.
    assert trigger._sekoia.delete_rule.call_count == 2
    trigger._sekoia.delete_rule.assert_any_call("sk-1")
    trigger._sekoia.delete_rule.assert_any_call("sk-3")

    event = trigger.send_event.call_args.kwargs["event"]
    assert event["marker_tag"] == MARKER_TAG
    assert event["total_matched"] == 2
    assert event["deleted"] == 2


def test_tag_mode_dry_run(trigger):
    trigger._confirm = False
    trigger._sekoia.iter_rules.return_value = iter(
        [_tagged_rule("sk-1", MARKER_TAG), _tagged_rule("sk-2", MARKER_TAG)]
    )

    trigger._delete_once()

    assert trigger._sekoia.delete_rule.call_count == 0
    event = trigger.send_event.call_args.kwargs["event"]
    assert event["dry_run"] is True
    assert event["total_matched"] == 2


def test_tag_mode_zero_matches_logs_tag_histogram(trigger):
    trigger._sekoia.iter_rules.side_effect = [
        iter([]),
        iter(
            [
                _tagged_rule("a", "attack.t1059"),
                _tagged_rule("b", "attack.t1059", "attack.execution"),
            ]
        ),
    ]

    trigger._delete_once()

    assert trigger._sekoia.delete_rule.call_count == 0
    event = trigger.send_event.call_args.kwargs["event"]
    assert event["total_matched"] == 0
    assert event["observed_tags"] == {"attack.t1059": 2, "attack.execution": 1}


def test_tag_mode_accepts_plain_string_tags(trigger):
    trigger._sekoia.iter_rules.return_value = iter(
        [{"uuid": "sk-1", "tags": [MARKER_TAG, "attack.t1059"]}]
    )

    trigger._delete_once()

    assert trigger._sekoia.delete_rule.call_count == 1


# ---------------------------------------------------------------------------
# Field mode (fallback, marker_tag empty)
# ---------------------------------------------------------------------------


def test_field_mode_used_when_marker_tag_empty(trigger):
    trigger._marker_tag = ""
    trigger._match_value = API_KEY_UUID
    trigger._sekoia.iter_rules.return_value = iter(
        [{"uuid": "sk-1", "created_by": API_KEY_UUID}]
    )

    trigger._delete_once()

    trigger._sekoia.iter_rules.assert_called_once_with(
        match_field=DEFAULT_MATCH_FIELD, match_value=API_KEY_UUID
    )
    assert trigger._sekoia.delete_rule.call_count == 1
    event = trigger.send_event.call_args.kwargs["event"]
    assert event["marker_tag"] == ""
    assert event["match_field"] == DEFAULT_MATCH_FIELD
    assert event["match_value"] == API_KEY_UUID


def test_field_mode_zero_matches_logs_field_histogram(trigger):
    trigger._marker_tag = ""
    trigger._match_value = "some-uuid"
    trigger._sekoia.iter_rules.side_effect = [
        iter([]),  # filtered
        iter(
            [
                {"uuid": "a", "created_by": "other-key"},
                {"uuid": "b", "created_by": "other-key"},
            ]
        ),  # diagnostic peek
    ]

    trigger._delete_once()

    event = trigger.send_event.call_args.kwargs["event"]
    assert event["observed_created_by"] == {"other-key": 2}


# ---------------------------------------------------------------------------
# Diagnostic mode (both marker_tag and match_value empty)
# ---------------------------------------------------------------------------


def test_no_filter_runs_diagnostic_only(trigger):
    trigger._marker_tag = ""
    trigger._match_value = ""
    trigger._sekoia.iter_rules.return_value = iter(
        [
            {"uuid": "a", "created_by": API_KEY_UUID},
            {"uuid": "b", "created_by": "another-key"},
        ]
    )

    trigger._delete_once()

    assert trigger._sekoia.iter_rules.call_count == 1
    assert trigger._sekoia.delete_rule.call_count == 0
    event = trigger.send_event.call_args.kwargs["event"]
    assert event["dry_run"] is True
    assert event["marker_tag"] == ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_partial_failure_records_uuids(trigger):
    trigger._sekoia.iter_rules.return_value = iter(
        [
            _tagged_rule("sk-1", MARKER_TAG),
            _tagged_rule("sk-2", MARKER_TAG),
            _tagged_rule("sk-3", MARKER_TAG),
        ]
    )

    def _delete(sekoia_uuid):
        if sekoia_uuid == "sk-2":
            raise RuntimeError("boom on sk-2")

    trigger._sekoia.delete_rule.side_effect = _delete

    trigger._delete_once()

    event = trigger.send_event.call_args.kwargs["event"]
    assert event["deleted"] == 2
    assert event["delete_failed"] == 1
    assert event["remaining"] == ["sk-2"]


def test_client_error_during_enumeration_does_not_crash(trigger):
    trigger._sekoia.iter_rules.side_effect = RuntimeError("list API down")

    trigger._delete_once()

    trigger.send_event.assert_not_called()
    assert trigger._sekoia.delete_rule.call_count == 0
