import pytest
import requests_mock

from sekoia_valhalla_integration_modules.client import ValhallaClient


def test_get_sigma_feed_posts_form_encoded_apikey():
    client = ValhallaClient("https://valhalla.example.com", "deadbeef")

    with requests_mock.Mocker() as m:
        m.post(
            "https://valhalla.example.com/api/v1/getsigma",
            json={"rules": [{"filename": "a.yml", "content": "title: a"}]},
        )
        rules = client.get_sigma_feed()

        assert len(m.request_history) == 1
        req = m.request_history[0]
        assert req.headers["Content-Type"].startswith("application/x-www-form-urlencoded")
        assert "apikey=deadbeef" in req.text
        assert "format=json" in req.text

    assert rules == [{"filename": "a.yml", "content": "title: a"}]


def test_get_sigma_feed_strips_trailing_slash_from_base_url():
    client = ValhallaClient("https://valhalla.example.com/", "k")

    with requests_mock.Mocker() as m:
        m.post("https://valhalla.example.com/api/v1/getsigma", json={"rules": []})
        client.get_sigma_feed()
        assert m.last_request.url == "https://valhalla.example.com/api/v1/getsigma"


def test_get_sigma_feed_raises_on_status_error_payload():
    client = ValhallaClient("https://valhalla.example.com", "bad")

    with requests_mock.Mocker() as m:
        m.post(
            "https://valhalla.example.com/api/v1/getsigma",
            json={"status": "error", "message": "invalid api key"},
        )
        with pytest.raises(RuntimeError, match="invalid api key"):
            client.get_sigma_feed()


def test_get_sigma_feed_raises_for_http_error():
    client = ValhallaClient("https://valhalla.example.com", "k")

    with requests_mock.Mocker() as m:
        m.post("https://valhalla.example.com/api/v1/getsigma", status_code=500)
        with pytest.raises(Exception):
            client.get_sigma_feed()


def test_get_sigma_feed_returns_empty_when_no_rules_key():
    client = ValhallaClient("https://valhalla.example.com", "k")

    with requests_mock.Mocker() as m:
        m.post("https://valhalla.example.com/api/v1/getsigma", json={})
        assert client.get_sigma_feed() == []
