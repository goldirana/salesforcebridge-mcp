"""Unit tests for the OAuth Authorization Code + PKCE flow."""

from __future__ import annotations

import hashlib
import time
from base64 import urlsafe_b64encode
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.oauth_authorization_code import (
    AuthorizationCodeAuth,
    AuthorizationError,
    PendingAuth,
)
from src.auth.token_store import InMemoryTokenStore, TokenData


@pytest.fixture
def token_store():
    return InMemoryTokenStore()


@pytest.fixture
def auth(token_store):
    with patch("src.auth.oauth_authorization_code.settings") as mock_settings:
        mock_settings.salesforce.client_id = "test_client_id"
        mock_settings.salesforce.client_secret = "test_secret"
        mock_settings.salesforce.instance_url = "https://test.salesforce.com"
        mock_settings.salesforce.callback_url = "http://localhost:8000/oauth/callback"
        yield AuthorizationCodeAuth(token_store)


class TestGenerateAuthorizationUrl:
    def test_returns_url_with_pkce_params(self, auth):
        url = auth.generate_authorization_url("user-1")

        assert "https://test.salesforce.com/services/oauth2/authorize" in url
        assert "response_type=code" in url
        assert "client_id=test_client_id" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "state=" in url

    def test_stores_pending_auth(self, auth):
        auth.generate_authorization_url("user-1")

        assert len(auth._pending) == 1
        pending = next(iter(auth._pending.values()))
        assert pending.user_id == "user-1"
        assert pending.code_verifier  # not empty

    def test_cleans_expired_pending(self, auth):
        # Insert an expired pending auth
        auth._pending["old_state"] = PendingAuth(
            state="old_state",
            code_verifier="old_verifier",
            user_id="old_user",
            created_at=time.time() - 9999,
        )

        auth.generate_authorization_url("user-2")

        assert "old_state" not in auth._pending


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_invalid_state_raises(self, auth):
        with pytest.raises(AuthorizationError, match="Invalid or expired state"):
            await auth.handle_callback(code="some_code", state="bad_state")

    @pytest.mark.asyncio
    async def test_expired_state_raises(self, auth):
        auth._pending["expired"] = PendingAuth(
            state="expired",
            code_verifier="verifier",
            user_id="user-1",
            created_at=time.time() - 9999,
        )

        with pytest.raises(AuthorizationError, match="expired"):
            await auth.handle_callback(code="some_code", state="expired")

    @pytest.mark.asyncio
    async def test_successful_exchange(self, auth, token_store):
        # Set up pending auth
        url = auth.generate_authorization_url("user-1")
        state = next(iter(auth._pending.keys()))
        verifier = auth._pending[state].code_verifier

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "instance_url": "https://na1.salesforce.com",
            "expires_in": "7200",
            "token_type": "Bearer",
        }

        with patch("src.auth.oauth_authorization_code.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            token = await auth.handle_callback(code="auth_code_123", state=state)

        assert token.access_token == "access_123"
        assert token.refresh_token == "refresh_456"

        # Token should be stored
        stored = await token_store.get_token("user-1")
        assert stored is not None
        assert stored.access_token == "access_123"


class TestGetAccessToken:
    @pytest.mark.asyncio
    async def test_no_token_raises(self, auth):
        with pytest.raises(AuthorizationError, match="No token found"):
            await auth.get_access_token("unknown_user")

    @pytest.mark.asyncio
    async def test_returns_valid_token(self, auth, token_store):
        token = TokenData(
            access_token="valid",
            refresh_token="refresh",
            instance_url="https://na1.salesforce.com",
            expires_at=time.time() + 3600,
        )
        await token_store.save_token("user-1", token)

        result = await auth.get_access_token("user-1")
        assert result.access_token == "valid"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, auth, token_store):
        expired_token = TokenData(
            access_token="old",
            refresh_token="refresh_abc",
            instance_url="https://na1.salesforce.com",
            expires_at=time.time() - 100,
        )
        await token_store.save_token("user-1", expired_token)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "refresh_abc",
            "instance_url": "https://na1.salesforce.com",
            "expires_in": "7200",
            "token_type": "Bearer",
        }

        with patch("src.auth.oauth_authorization_code.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await auth.get_access_token("user-1")

        assert result.access_token == "new_access"


class TestPKCE:
    def test_code_verifier_length(self):
        verifier = AuthorizationCodeAuth._generate_code_verifier()
        # token_urlsafe(64) produces ~86 chars, within 43-128 range
        assert 43 <= len(verifier) <= 128

    def test_code_challenge_is_s256(self):
        verifier = "test_verifier_string"
        challenge = AuthorizationCodeAuth._generate_code_challenge(verifier)

        # Verify manually
        expected = urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        assert challenge == expected
