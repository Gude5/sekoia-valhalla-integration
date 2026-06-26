import requests


class SekoiaAPIError(RuntimeError):
    """Raised when the Sekoia API returns a non-2xx response or an unexpected body."""


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

    @staticmethod
    def _ensure_ok(resp: requests.Response, method: str, url: str) -> None:
        if resp.ok:
            return
        body = resp.text[:500]
        raise SekoiaAPIError(
            f"{method} {url} returned HTTP {resp.status_code}: {body}"
        )

    def create_rule(self, body: dict) -> str:
        url = f"{self._base_url}/v1/sic/conf/rules-catalog/rules"
        resp = requests.post(url, json=body, headers=self._headers(), timeout=self._timeout)
        self._ensure_ok(resp, "POST", url)
        try:
            data = resp.json()
        except ValueError as exc:
            raise SekoiaAPIError(
                f"POST {url} returned non-JSON body: {resp.text[:500]}"
            ) from exc
        sekoia_uuid = data.get("uuid") or data.get("id")
        if not sekoia_uuid:
            raise SekoiaAPIError(
                f"POST {url} succeeded but response had no uuid/id field. "
                f"Body: {resp.text[:500]}"
            )
        return sekoia_uuid

    def update_rule(self, sekoia_uuid: str, body: dict) -> None:
        url = f"{self._base_url}/v1/sic/conf/rules-catalog/rules/{sekoia_uuid}"
        resp = requests.put(url, json=body, headers=self._headers(), timeout=self._timeout)
        self._ensure_ok(resp, "PUT", url)
