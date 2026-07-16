import pytest
import requests_mock

from sekoia_valhalla_integration_modules.sekoia_client import (
    SekoiaClient,
    SekoiaRuleNotFoundError,
)


def test_create_rule_posts_with_bearer_and_returns_uuid():
    client = SekoiaClient("https://api.sekoia.io", "secret-token")

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            json={"uuid": "rule-uuid-1"},
        )
        body = {"name": "X", "type": "sigma"}
        uuid = client.create_rule(body)

        assert uuid == "rule-uuid-1"
        req = m.last_request
        assert req.headers["Authorization"] == "Bearer secret-token"
        assert req.headers["Content-Type"] == "application/json"
        assert req.json() == body


def test_create_rule_strips_trailing_slash_from_base_url():
    client = SekoiaClient("https://api.sekoia.io/", "k")

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            json={"uuid": "u"},
        )
        client.create_rule({})
        assert (
            m.last_request.url
            == "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules"
        )


def test_update_rule_puts_with_uuid_in_path():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.put(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/the-uuid",
            status_code=200,
        )
        body = {"name": "X"}
        client.update_rule("the-uuid", body)

        assert m.last_request.method == "PUT"
        assert m.last_request.json() == body
        assert m.last_request.headers["Authorization"] == "Bearer k"


def test_create_rule_raises_on_http_error():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            status_code=403,
        )
        with pytest.raises(Exception):
            client.create_rule({})


def test_update_rule_raises_rule_not_found_on_404():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.put(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=404,
        )
        with pytest.raises(SekoiaRuleNotFoundError) as excinfo:
            client.update_rule("u", {})
        assert excinfo.value.status_code == 404


def test_update_rule_raises_rule_not_found_on_403_au202():
    """Sekoia returns 403 (AU202) for PUT to a rule UUID that this API key
    doesn't own anymore (e.g. deleted rule). We treat it the same as 404."""
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.put(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=403,
            text='{"message":"Insufficient permissions","code":"AU202"}',
        )
        with pytest.raises(SekoiaRuleNotFoundError) as excinfo:
            client.update_rule("u", {})
        assert excinfo.value.status_code == 403


def test_update_rule_raises_generic_error_on_400():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.put(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=400,
        )
        with pytest.raises(Exception) as excinfo:
            client.update_rule("u", {})
        assert not isinstance(excinfo.value, SekoiaRuleNotFoundError)


def test_supports_path_mounted_regional_base_url():
    client = SekoiaClient("https://app.fra2.sekoia.io/api", "k")

    with requests_mock.Mocker() as m:
        m.post(
            "https://app.fra2.sekoia.io/api/v1/sic/conf/rules-catalog/rules",
            json={"uuid": "x"},
        )
        client.create_rule({})


def test_delete_rule_returns_normally_on_200():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.delete(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/the-uuid",
            status_code=200,
        )
        client.delete_rule("the-uuid")  # no exception
        assert m.last_request.method == "DELETE"
        assert m.last_request.headers["Authorization"] == "Bearer k"


def test_delete_rule_returns_normally_on_204():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.delete(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=204,
        )
        client.delete_rule("u")


def test_delete_rule_treats_404_as_idempotent_success():
    """Rule already gone in Sekoia is not an error."""
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.delete(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/gone",
            status_code=404,
            text='{"message":"not found"}',
        )
        client.delete_rule("gone")  # should NOT raise


def test_delete_rule_raises_on_500():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.delete(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=500,
        )
        with pytest.raises(Exception):
            client.delete_rule("u")


def test_delete_rule_raises_on_405():
    """If Sekoia disallows DELETE, we surface it."""
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.delete(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=405,
        )
        with pytest.raises(Exception):
            client.delete_rule("u")


# ---------------------------------------------------------------------------
# iter_rules — pagination + author filter
# ---------------------------------------------------------------------------


def test_iter_rules_yields_all_items_across_pages():
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        # Page 1: full page.
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            [
                {"json": {"items": [{"uuid": f"sk-{i}"} for i in range(100)]}},
                {"json": {"items": [{"uuid": "sk-100"}, {"uuid": "sk-101"}]}},
            ],
        )
        uuids = [r["uuid"] for r in client.iter_rules()]
        assert uuids == [f"sk-{i}" for i in range(102)]


def test_iter_rules_stops_when_page_is_shorter_than_page_size():
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            json={"items": [{"uuid": "sk-1"}, {"uuid": "sk-2"}]},
        )
        uuids = [r["uuid"] for r in client.iter_rules()]
        # Only one request made — short page terminates pagination.
        assert uuids == ["sk-1", "sk-2"]
        assert m.call_count == 1


def test_iter_rules_passes_generic_field_filter_as_query_param():
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            json={"items": [{"uuid": "sk-1", "created_by": "key-uuid"}]},
        )
        list(client.iter_rules(match_field="created_by", match_value="key-uuid"))
        req = m.last_request
        assert req.qs.get("match[created_by]") == ["key-uuid"]
        assert req.qs.get("limit") == ["100"]
        assert req.qs.get("offset") == ["0"]


def test_iter_rules_client_side_filter_when_server_ignores_query():
    """If the server ignores our filter query param and returns non-matching
    rules, iter_rules skips them so we never yield the wrong rule."""
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            json={
                "items": [
                    {"uuid": "sk-1", "created_by": "key-uuid"},
                    {"uuid": "sk-2", "created_by": "other-key"},
                    {"uuid": "sk-3", "created_by": "key-uuid"},
                ]
            },
        )
        uuids = [
            r["uuid"]
            for r in client.iter_rules(
                match_field="created_by", match_value="key-uuid"
            )
        ]
        assert uuids == ["sk-1", "sk-3"]


def test_iter_rules_falls_back_to_data_key_when_no_items_key():
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            json={"data": [{"uuid": "sk-1"}, {"uuid": "sk-2"}]},
        )
        uuids = [r["uuid"] for r in client.iter_rules()]
        assert uuids == ["sk-1", "sk-2"]


def test_iter_rules_raises_on_http_error():
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            status_code=500,
        )
        with pytest.raises(Exception):
            list(client.iter_rules())


def test_iter_rules_raises_on_non_json_body():
    client = SekoiaClient("https://api.sekoia.io", "k")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules",
            text="not json",
        )
        with pytest.raises(Exception):
            list(client.iter_rules())
