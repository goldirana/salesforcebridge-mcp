"""Quick diagnostic: does the auth flow persist tokens correctly?"""
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock
from src.auth.token_store import InMemoryTokenStore, TokenData
from src.auth.oauth_authorization_code import AuthorizationCodeAuth


async def test_full_flow():
    with patch("src.auth.oauth_authorization_code.settings") as mock_settings:
        mock_settings.salesforce.client_id = "test"
        mock_settings.salesforce.client_secret = "test"
        mock_settings.salesforce.instance_url = "https://test.salesforce.com"
        mock_settings.salesforce.callback_url = "http://localhost:8000/oauth/callback"

        store = InMemoryTokenStore()
        auth = AuthorizationCodeAuth(store)

        # 1. auth_start
        url = auth.generate_authorization_url("default")
        state = list(auth._pending.keys())[0]
        print(f"1. auth_start OK, pending count: {len(auth._pending)}")

        # 2. Simulate auth_complete (mock the HTTP call)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "instance_url": "https://na1.salesforce.com",
            "expires_in": "7200",
            "token_type": "Bearer",
        }

        with patch("src.auth.oauth_authorization_code.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            token = await auth.handle_callback(code="test_code", state=state)
            print(f"2. auth_complete OK, token: {token.access_token[:10]}...")

        # 3. Check is_authenticated
        user_id = "default"
        is_auth = await auth.is_authenticated(user_id)
        print(f"3. is_authenticated(user_id={user_id!r}): {is_auth}")

        # 4. Direct store check
        stored = await store.get_token(user_id)
        print(f"4. Token in store: {stored is not None}")
        if stored:
            print(f"   expired: {stored.is_expired}")
            print(f"   expires_in: {stored.expires_at - time.time():.0f}s")

        # 5. Same store, new auth instance (no restart)
        auth2 = AuthorizationCodeAuth(store)
        is_auth2 = await auth2.is_authenticated(user_id)
        print(f"5. New auth instance, same store: {is_auth2}")

        # 6. New store = simulated server restart
        store2 = InMemoryTokenStore()
        auth3 = AuthorizationCodeAuth(store2)
        is_auth3 = await auth3.is_authenticated(user_id)
        print(f"6. New store (restart simulation): {is_auth3}  <-- THIS is the problem if True should be False")


asyncio.run(test_full_flow())
