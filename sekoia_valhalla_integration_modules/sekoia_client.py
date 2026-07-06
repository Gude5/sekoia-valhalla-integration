from typing import Iterator, Optional

import requests


class SekoiaAPIError(RuntimeError):
    """Raised when the Sekoia API returns a non-2xx response or an unexpected body."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class SekoiaRuleNotFoundError(SekoiaAPIError):
    """Raised on PUT to a rule UUID that Sekoia doesn't own for this API
    key. Sekoia returns HTTP 403 (code AU202) for UUIDs that were
    previously created by this key but have since been deleted, so we
    treat 403 and 404 on ``update_rule`` interchangeably as "stale
    identifier — POST it as new instead"."""


LIST_PAGE_SIZE = 100


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
            f"{method} {url} returned HTTP {resp.status_code}: {body}",
            status_code=resp.status_code,
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
        if resp.status_code in (403, 404):
            raise SekoiaRuleNotFoundError(
                f"PUT {url} returned HTTP {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )
        self._ensure_ok(resp, "PUT", url)

    def delete_rule(self, sekoia_uuid: str) -> None:
        """DELETE a rule by uuid. 404 is treated as idempotent success (the
        rule was already gone in Sekoia)."""
        url = f"{self._base_url}/v1/sic/conf/rules-catalog/rules/{sekoia_uuid}"
        resp = requests.delete(url, headers=self._headers(), timeout=self._timeout)
        if resp.status_code == 404:
            return
        self._ensure_ok(resp, "DELETE", url)

    def iter_rules(
        self,
        match_field: Optional[str] = None,
        match_value: Optional[str] = None,
        page_size: int = LIST_PAGE_SIZE,
    ) -> Iterator[dict]:
        """Paginate ``GET /v1/sic/conf/rules-catalog/rules`` and yield
        each rule dict. When ``match_field`` and ``match_value`` are set,
        only rules whose top-level ``match_field`` equals ``match_value``
        are yielded. Server-side filtering is attempted via
        ``match[<field>]=<value>``; a client-side filter is applied as a
        safety net so we never yield a rule that doesn't match.
        """
        url = f"{self._base_url}/v1/sic/conf/rules-catalog/rules"
        offset = 0
        while True:
            params: dict[str, object] = {"limit": page_size, "offset": offset}
            if match_field and match_value:
                params[f"match[{match_field}]"] = match_value
            resp = requests.get(
                url, params=params, headers=self._headers(), timeout=self._timeout
            )
            self._ensure_ok(resp, "GET", url)
            try:
                data = resp.json()
            except ValueError as exc:
                raise SekoiaAPIError(
                    f"GET {url} returned non-JSON body: {resp.text[:500]}"
                ) from exc

            items = data.get("items") or data.get("data") or []
            if not isinstance(items, list):
                raise SekoiaAPIError(
                    f"GET {url} returned unexpected list shape: {resp.text[:500]}"
                )

            for item in items:
                if match_field and match_value and item.get(match_field) != match_value:
                    # Server-side filter didn't apply (unknown query param);
                    # fall back to client-side filtering.
                    continue
                yield item

            if len(items) < page_size:
                return
            offset += page_size
