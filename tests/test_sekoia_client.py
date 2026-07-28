import pytest
import requests_mock

from sekoia_valhalla_integration_modules import sekoia_client
from sekoia_valhalla_integration_modules.sekoia_client import (
    LIST_PAGE_SIZE,
    MAX_LIST_PAGES,
    SekoiaAPIError,
    SekoiaClient,
    SekoiaRuleNotFoundError,
)

BASE_URL = "https://api.sekoia.io"
RULES_URL = f"{BASE_URL}/v1/sic/conf/rules-catalog/rules"


def test_create_rule_posts_with_bearer_and_returns_uuid():
    client = SekoiaClient(BASE_URL, "secret-token")

    with requests_mock.Mocker() as m:
        m.post(RULES_URL, json={"uuid": "rule-uuid-1"},)
        body = {"name": "X", "type": "sigma"}
        uuid = client.create_rule(body)

        assert uuid == "rule-uuid-1"
        req = m.last_request
        assert req.headers["Authorization"] == "Bearer secret-token"
        assert req.headers["Content-Type"] == "application/json"
        assert req.json() == body


def test_create_rule_strips_trailing_slash_from_base_url():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.post(RULES_URL, json={"uuid": "u"},)
        client.create_rule({})
        assert (m.last_request.url == RULES_URL)


def test_update_rule_puts_with_uuid_in_path():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.put(f"{RULES_URL}/the-uuid", status_code=200,)
        body = {"name": "X"}
        client.update_rule("the-uuid", body)

        assert m.last_request.method == "PUT"
        assert m.last_request.json() == body
        assert m.last_request.headers["Authorization"] == "Bearer k"


def test_create_rule_raises_on_http_error():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.post(RULES_URL, status_code=403,)
        with pytest.raises(Exception):
            client.create_rule({})


def test_update_rule_raises_rule_not_found_on_404():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.put(f"{RULES_URL}/u", status_code=404,)
        with pytest.raises(SekoiaRuleNotFoundError) as excinfo:
            client.update_rule("u", {})
        assert excinfo.value.status_code == 404


def test_update_rule_raises_rule_not_found_on_403_au202():
    """Sekoia returns 403 (AU202) for PUT to a rule UUID that this API key
    doesn't own anymore (e.g. deleted rule). We treat it the same as 404."""
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.put(
            f"{RULES_URL}/u",
            status_code=403,
            text='{"message":"Insufficient permissions","code":"AU202"}',
        )
        with pytest.raises(SekoiaRuleNotFoundError) as excinfo:
            client.update_rule("u", {})
        assert excinfo.value.status_code == 403


def test_update_rule_raises_generic_error_on_400():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.put(f"{RULES_URL}/u", status_code=400,)
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
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.delete(f"{RULES_URL}/the-uuid", status_code=200,)
        client.delete_rule("the-uuid")  # no exception
        assert m.last_request.method == "DELETE"
        assert m.last_request.headers["Authorization"] == "Bearer k"


def test_delete_rule_returns_normally_on_204():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.delete(f"{RULES_URL}/u", status_code=204,)
        client.delete_rule("u")


def test_delete_rule_treats_404_as_idempotent_success():
    """Rule already gone in Sekoia is not an error."""
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.delete(
            f"{RULES_URL}/gone",
            status_code=404,
            text='{"message":"not found"}',
        )
        client.delete_rule("gone")  # should NOT raise


def test_delete_rule_raises_on_500():
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.delete(f"{RULES_URL}/u", status_code=500,)
        with pytest.raises(Exception):
            client.delete_rule("u")


def test_delete_rule_raises_on_405():
    """If Sekoia disallows DELETE, we surface it."""
    client = SekoiaClient(BASE_URL, "k")

    with requests_mock.Mocker() as m:
        m.delete(f"{RULES_URL}/u", status_code=405,)
        with pytest.raises(Exception):
            client.delete_rule("u")


# ---------------------------------------------------------------------------
# iter_rules — pagination + author filter
# ---------------------------------------------------------------------------

END_OF_LIST = {"json": {"items": []}}


def _offsets(mocker) -> list[str]:
    """The ``offset`` query param of each request made, in order."""
    return [req.qs["offset"][0] for req in mocker.request_history]


def test_iter_rules_yields_all_items_across_pages():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        # Page 1: full page.
        m.get(
            RULES_URL,
            [
                {"json": {"items": [{"uuid": f"sk-{i}"} for i in range(100)]}},
                {"json": {"items": [{"uuid": "sk-100"}, {"uuid": "sk-101"}]}},
                END_OF_LIST,
            ],
        )
        uuids = [r["uuid"] for r in client.iter_rules()]
        assert uuids == [f"sk-{i}" for i in range(102)]


def test_iter_rules_stops_on_an_empty_page_not_a_short_one():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(
            RULES_URL,
            [
                {"json": {"items": [{"uuid": "sk-1"}, {"uuid": "sk-2"}]}},
                {"json": {"items": [{"uuid": "sk-3"}]}},
                END_OF_LIST,
            ],
        )
        uuids = [r["uuid"] for r in client.iter_rules()]
        assert uuids == ["sk-1", "sk-2", "sk-3"]
        assert m.call_count == 3


def test_iter_rules_walks_every_page_when_server_caps_the_page_size():
    server_cap = 10
    all_rules = [{"uuid": f"sk-{i}"} for i in range(25)]
    pages = [
        {"json": {"items": all_rules[i : i + server_cap]}}
        for i in range(0, len(all_rules), server_cap)
    ]

    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(RULES_URL, pages + [END_OF_LIST])
        uuids = [r["uuid"] for r in client.iter_rules()]

        assert uuids == [f"sk-{i}" for i in range(25)]
        assert _offsets(m) == ["0", "10", "20", "25"]
        assert m.request_history[0].qs["limit"] == ["100"]


def test_iter_rules_returns_nothing_on_an_empty_first_page():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(RULES_URL, json={"items": []})
        assert list(client.iter_rules()) == []
        assert m.call_count == 1


def test_iter_rules_raises_rather_than_looping_when_offset_is_ignored(monkeypatch):
    monkeypatch.setattr(sekoia_client, "MAX_LIST_PAGES", 5)
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(RULES_URL, json={"items": [{"uuid": "sk-1"}]})
        with pytest.raises(SekoiaAPIError, match="did not terminate"):
            list(client.iter_rules())
        assert m.call_count == 5


def test_max_list_pages_is_generous_enough_for_a_real_tenant():
    assert MAX_LIST_PAGES * LIST_PAGE_SIZE >= 1_000_000


def test_iter_rules_passes_generic_field_filter_as_query_param():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(
            RULES_URL,
            [
                {"json": {"items": [{"uuid": "sk-1", "created_by": "key-uuid"}]}},
                END_OF_LIST,
            ],
        )
        list(client.iter_rules(match_field="created_by", match_value="key-uuid"))
        req = m.request_history[0]
        assert req.qs.get("match[created_by]") == ["key-uuid"]
        assert req.qs.get("limit") == ["100"]
        assert req.qs.get("offset") == ["0"]
        assert m.request_history[-1].qs.get("match[created_by]") == ["key-uuid"]


def test_iter_rules_client_side_filter_when_server_ignores_query():
    """If the server ignores our filter query param and returns non-matching
    rules, iter_rules skips them so we never yield the wrong rule."""
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(
            RULES_URL,
            [
                {
                    "json": {
                        "items": [
                            {"uuid": "sk-1", "created_by": "key-uuid"},
                            {"uuid": "sk-2", "created_by": "other-key"},
                            {"uuid": "sk-3", "created_by": "key-uuid"},
                        ]
                    }
                },
                END_OF_LIST,
            ],
        )
        uuids = [
            r["uuid"]
            for r in client.iter_rules(
                match_field="created_by", match_value="key-uuid"
            )
        ]
        assert uuids == ["sk-1", "sk-3"]
        assert _offsets(m) == ["0", "3"]


def test_iter_rules_falls_back_to_data_key_when_no_items_key():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(
            RULES_URL,
            [
                {"json": {"data": [{"uuid": "sk-1"}, {"uuid": "sk-2"}]}},
                {"json": {"data": []}},
            ],
        )
        uuids = [r["uuid"] for r in client.iter_rules()]
        assert uuids == ["sk-1", "sk-2"]


def test_iter_rules_raises_on_http_error():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(RULES_URL, status_code=500,)
        with pytest.raises(Exception):
            list(client.iter_rules())


def test_iter_rules_raises_on_non_json_body():
    client = SekoiaClient(BASE_URL, "k")
    with requests_mock.Mocker() as m:
        m.get(RULES_URL, text="not json",)
        with pytest.raises(Exception):
            list(client.iter_rules())
