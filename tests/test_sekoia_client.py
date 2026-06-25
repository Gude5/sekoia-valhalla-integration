import pytest
import requests_mock

from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient


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


def test_update_rule_raises_on_http_error():
    client = SekoiaClient("https://api.sekoia.io", "k")

    with requests_mock.Mocker() as m:
        m.put(
            "https://api.sekoia.io/v1/sic/conf/rules-catalog/rules/u",
            status_code=404,
        )
        with pytest.raises(Exception):
            client.update_rule("u", {})


def test_supports_path_mounted_regional_base_url():
    client = SekoiaClient("https://app.fra2.sekoia.io/api", "k")

    with requests_mock.Mocker() as m:
        m.post(
            "https://app.fra2.sekoia.io/api/v1/sic/conf/rules-catalog/rules",
            json={"uuid": "x"},
        )
        client.create_rule({})
