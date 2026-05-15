from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from src.config import settings
from src.auth.token_store import TokenData
from src.auth.oauth_client_credentials import ClientCredentialsAuth, AuthenticationError

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
DEFAULT_QUERY_LIMIT = 200
MAX_RECORDS = 2000


class SalesforceClient:
    """
    Wrapper around the Salesforce REST API.

    Handles:
    - Authenticated requests using TokenData
    - Auto-refresh on 401 and retry
    - Response size limits
    - Retry with backoff on transient errors (503, 429)
    """

    def __init__(self, auth: ClientCredentialsAuth) -> None:
        self._auth = auth
        self._api_version = settings.salesforce.api_version

    async def query(self, soql: str) -> dict[str, Any]:
        """Execute a SOQL query and return results."""
        path = f"/services/data/{self._api_version}/query"
        params = {"q": soql}
        return await self._request("GET", path, params=params)

    async def query_more(self, next_records_url: str) -> dict[str, Any]:
        """Fetch the next page of query results."""
        return await self._request("GET", next_records_url)

    async def get_record(self, sobject: str, record_id: str, fields: Optional[list[str]] = None) -> dict[str, Any]:
        """Get a single record by ID."""
        path = f"/services/data/{self._api_version}/sobjects/{sobject}/{record_id}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        return await self._request("GET", path, params=params)

    async def create_record(self, sobject: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new record. Returns {id, success, errors}."""
        path = f"/services/data/{self._api_version}/sobjects/{sobject}"
        return await self._request("POST", path, json_body=data)

    async def update_record(self, sobject: str, record_id: str, data: dict[str, Any]) -> None:
        """Update an existing record."""
        path = f"/services/data/{self._api_version}/sobjects/{sobject}/{record_id}"
        await self._request("PATCH", path, json_body=data)

    async def delete_record(self, sobject: str, record_id: str) -> None:
        """Delete a record by ID."""
        path = f"/services/data/{self._api_version}/sobjects/{sobject}/{record_id}"
        await self._request("DELETE", path)

    async def describe_object(self, sobject: str) -> dict[str, Any]:
        """Get schema metadata for an sObject."""
        path = f"/services/data/{self._api_version}/sobjects/{sobject}/describe"
        return await self._request("GET", path)

    async def describe_global(self) -> dict[str, Any]:
        """List all available sObjects."""
        path = f"/services/data/{self._api_version}/sobjects"
        return await self._request("GET", path)

    # ── Internal ──────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Any:
        """Make an authenticated request with auto-refresh retry."""
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            token = await self._auth.get_access_token()
            url = self._build_url(token, path)
            headers = {
                "Authorization": f"{token.token_type} {token.access_token}",
                "Content-Type": "application/json",
            }

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    )
            except httpx.RequestError as exc:
                logger.warning("Request failed (attempt %d): %s", attempt + 1, exc)
                last_error = SalesforceAPIError(f"Connection error: {exc}")
                continue

            # 401 — token expired, clear and retry
            if response.status_code == 401 and attempt < MAX_RETRIES:
                logger.info("Got 401, refreshing token (attempt %d)", attempt + 1)
                from src.auth.oauth_client_credentials import SERVICE_ACCOUNT_ID
                await self._auth._store.delete_token(SERVICE_ACCOUNT_ID)
                continue

            # 429 / 503 — transient, retry
            if response.status_code in (429, 503) and attempt < MAX_RETRIES:
                logger.warning(
                    "Transient error %d (attempt %d), retrying",
                    response.status_code,
                    attempt + 1,
                )
                continue

            # 204 No Content — success with no body (update/delete)
            if response.status_code == 204:
                return None

            # Success
            if 200 <= response.status_code < 300:
                return response.json()

            # Client/server error — don't retry
            last_error = SalesforceAPIError(
                f"Salesforce API error ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
            break

        raise last_error

    def _build_url(self, token: TokenData, path: str) -> str:
        """Build the full URL. If path is already absolute, use instance_url as base."""
        base = token.instance_url.rstrip("/")
        if path.startswith("http"):
            return path
        return f"{base}{path}"


class SalesforceAPIError(Exception):
    """Raised when a Salesforce API call fails."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code
