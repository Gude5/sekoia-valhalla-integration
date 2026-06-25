import requests


class SekoiaClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def create_rule(self, body: dict) -> str:
        resp = requests.post(
            f"{self._base_url}/v1/sic/conf/rules-catalog/rules",
            json=body,
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["uuid"]

    def update_rule(self, sekoia_uuid: str, body: dict) -> None:
        resp = requests.put(
            f"{self._base_url}/v1/sic/conf/rules-catalog/rules/{sekoia_uuid}",
            json=body,
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
