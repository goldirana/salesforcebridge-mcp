from __future__ import annotations

import time
import logging

import httpx

from src.config import settings
from src.auth.token_store import TokenData, TokenStore

logger = logging.getLogger(__name__)

# The user_id key used for the shared service account
SERVICE_ACCOUNT_ID = "_service_account"

# Salesforce OAuth token endpoint
TOKEN_ENDPOINT = "/services/oauth2/token"


class ClientCredentialsAuth:
    """
    Authenticates as a single service account using the
    OAuth 2.0 Client Credentials flow.

    Use this for dev / early phases. Replace with
    AuthorizationCodeAuth for per-user auth.
    """

    def __init__(self, token_store: TokenStore) -> None:
        self._store = token_store
        self._sf = settings.salesforce

    async def get_access_token(self) -> TokenData:
        """Return a valid token, refreshing if expired."""
        token = await self._store.get_token(SERVICE_ACCOUNT_ID)

        if token is not None and not token.is_expired:
            return token

        # Token missing or expired — request a new one
        logger.info("Requesting new client_credentials token from Salesforce")
        token = await self._request_token()
        await self._store.save_token(SERVICE_ACCOUNT_ID, token)
        return token

    async def _request_token(self) -> TokenData:
        """Exchange client credentials for an access token."""
        url = f"{self._sf.instance_url}{TOKEN_ENDPOINT}"

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._sf.client_id,
            "client_secret": self._sf.client_secret,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=payload)

        if response.status_code != 200:
            logger.error(
                "Token request failed: %s %s",
                response.status_code,
                response.text,
            )
            raise AuthenticationError(
                f"Salesforce token request failed ({response.status_code}): {response.text}"
            )

        data = response.json()

        return TokenData(
            access_token=data["access_token"],
            refresh_token="",  # client_credentials flow has no refresh token
            instance_url=data.get("instance_url", self._sf.instance_url),
            expires_at=time.time() + int(data.get("expires_in", 3600)),
            token_type=data.get("token_type", "Bearer"),
        )


class AuthenticationError(Exception):
    """Raised when Salesforce authentication fails."""
