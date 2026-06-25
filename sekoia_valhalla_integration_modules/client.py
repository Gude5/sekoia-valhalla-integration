import requests


class ValhallaClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def get_sigma_feed(self) -> list[dict]:
        resp = requests.post(
            f"{self._base_url}/api/v1/getsigma",
            data={"apikey": self._api_key, "format": "json"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") == "error":
            raise RuntimeError(f"Valhalla error: {payload.get('message')}")
        return payload.get("rules", [])
