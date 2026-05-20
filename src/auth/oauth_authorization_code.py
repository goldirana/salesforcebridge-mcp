from __future__ import annotations

import hashlib # For sha-256 (pkce hashing) 
import json
import logging
import secrets # generating ramdom tokens (verifiers, state)
import time
from base64 import urlsafe_b64encode # for encoding hash to url-safe-string
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx # http client (like requests, but async)

from src.config import settings
from src.auth.token_store import TokenData, TokenStore

logger = logging.getLogger(__name__)

# Salesforce OAuth endpoints (appended to instance_url)
AUTHORIZE_ENDPOINT = "/services/oauth2/authorize"
TOKEN_ENDPOINT = "/services/oauth2/token"
REVOKE_ENDPOINT = "/services/oauth2/revoke"

# File to persist pending auth state across restarts
_PENDING_FILE = Path(__file__).resolve().parent.parent.parent / ".pending_auth.json"


@dataclass
class PendingAuth:
    """Tracks state for an in-progress authorization."""

    state: str # CSRF token sent to Salesforce and returned on callback
    code_verifier: str # PKCE code verifier (secret)
    user_id: str # claude passes this 
    created_at: float # when it started


class AuthorizationCodeAuth:
    """
    Per-user OAuth 2.0 Authorization Code flow with PKCE.

    Each user authenticates individually with Salesforce.
    Tokens are stored per-user and refreshed automatically.
    """

    # Pending authorizations expire after 10 minutes
    STATE_TTL_SECONDS = 600

    def __init__(self, token_store: TokenStore) -> None:
        self._store = token_store
        self._sf = settings.salesforce
        self._pending: dict[str, PendingAuth] = {}
        self._load_pending()

    def _load_pending(self) -> None:
        """Load pending auth state from disk."""
        if not _PENDING_FILE.exists():
            return
        try:
            data = json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
            for state, item in data.items():
                self._pending[state] = PendingAuth(**item)
        except (json.JSONDecodeError, TypeError, KeyError):
            self._pending = {}

    def _save_pending(self) -> None:
        """Persist pending auth state to disk."""
        data = {state: asdict(p) for state, p in self._pending.items()}
        _PENDING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def generate_authorization_url(self, user_id: str) -> str:
        """
        Generate the Salesforce authorization URL for a user.

        Returns the URL to redirect the user to for authentication.
        """
        # Clean expired pending auths
        self._cleanup_pending()

        # Generate PKCE pair
        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)

        # Generate state token for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store pending auth
        self._pending[state] = PendingAuth(
            state=state,
            code_verifier=code_verifier,
            user_id=user_id,
            created_at=time.time(),
        )
        self._save_pending()

        params = {
            "response_type": "code",
            "client_id": self._sf.client_id,
            "redirect_uri": self._sf.callback_url,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._sf.instance_url}{AUTHORIZE_ENDPOINT}?{query_string}"

    async def handle_callback(self, code: str, state: str) -> TokenData:
        """
        Exchange the authorization code for tokens.

        Called when Salesforce redirects back to the callback URL.
        Raises AuthorizationError if state is invalid or token exchange fails.
        """
        # Validate state
        pending = self._pending.pop(state, None)
        self._save_pending()
        if pending is None:
            raise AuthorizationError("Invalid or expired state parameter")

        if time.time() - pending.created_at > self.STATE_TTL_SECONDS:
            raise AuthorizationError("Authorization request expired")

        # Exchange code for tokens
        token = await self._exchange_code(code, pending.code_verifier)
        await self._store.save_token(pending.user_id, token)

        logger.info("Successfully authenticated user %s", pending.user_id)
        return token

    async def get_access_token(self, user_id: str) -> TokenData:
        """Return a valid token for the user, refreshing if needed."""
        token = await self._store.get_token(user_id)

        if token is None:
            raise AuthorizationError(
                f"No token found for user {user_id}. User must authenticate first."
            )

        if not token.is_expired:
            return token

        # Token expired — try refresh
        if token.refresh_token:
            logger.info("Refreshing expired token for user %s", user_id)
            try:
                new_token = await self._refresh_token(token.refresh_token)
                await self._store.save_token(user_id, new_token)
                return new_token
            except AuthorizationError:
                # Refresh failed — user must re-authenticate
                await self._store.delete_token(user_id)
                raise AuthorizationError(
                    f"Token refresh failed for user {user_id}. User must re-authenticate."
                )

        # No refresh token and expired
        await self._store.delete_token(user_id)
        raise AuthorizationError(
            f"Token expired for user {user_id} with no refresh token. User must re-authenticate."
        )

    async def revoke_token(self, user_id: str) -> None:
        """Revoke and delete a user's token."""
        token = await self._store.get_token(user_id)
        if token is None:
            return

        try:
            url = f"{self._sf.instance_url}{REVOKE_ENDPOINT}"
            async with httpx.AsyncClient() as client:
                await client.post(url, data={"token": token.access_token})
        except Exception as exc:
            logger.warning("Token revocation request failed: %s", exc)
        finally:
            await self._store.delete_token(user_id)
            logger.info("Revoked token for user %s", user_id)

    async def is_authenticated(self, user_id: str) -> bool:
        """Check if a user has a valid (non-expired) token."""
        return await self._store.is_token_valid(user_id)

    # ── Private methods ──

    async def _exchange_code(self, code: str, code_verifier: str) -> TokenData:
        """Exchange authorization code + PKCE verifier for tokens."""
        url = f"{self._sf.instance_url}{TOKEN_ENDPOINT}"

        payload = {
            "grant_type": "authorization_code",
            "client_id": self._sf.client_id,
            "client_secret": self._sf.client_secret,
            "redirect_uri": self._sf.callback_url,
            "code": code,
            "code_verifier": code_verifier,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data=payload)

        if response.status_code != 200:
            logger.error(
                "Code exchange failed: %s %s",
                response.status_code,
                response.text,
            )
            raise AuthorizationError(
                f"Authorization code exchange failed ({response.status_code})"
            )

        data = response.json()

        return TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            instance_url=data.get("instance_url", self._sf.instance_url),
            expires_at=time.time() + int(data.get("expires_in", 7200)),
            token_type=data.get("token_type", "Bearer"),
        )

    async def _refresh_token(self, refresh_token: str) -> TokenData:
        """Use a refresh token to obtain a new access token."""
        url = f"{self._sf.instance_url}{TOKEN_ENDPOINT}"

        payload = {
            "grant_type": "refresh_token",
            "client_id": self._sf.client_id,
            "client_secret": self._sf.client_secret,
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data=payload)

        if response.status_code != 200:
            logger.error(
                "Token refresh failed: %s %s",
                response.status_code,
                response.text,
            )
            raise AuthorizationError(
                f"Token refresh failed ({response.status_code})"
            )

        data = response.json()

        return TokenData(
            access_token=data["access_token"],
            # Salesforce may or may not return a new refresh token
            refresh_token=data.get("refresh_token", refresh_token),
            instance_url=data.get("instance_url", self._sf.instance_url),
            expires_at=time.time() + int(data.get("expires_in", 7200)),
            token_type=data.get("token_type", "Bearer"),
        )

    def _cleanup_pending(self) -> None:
        """Remove expired pending authorization requests."""
        now = time.time()
        expired = [
            state
            for state, pending in self._pending.items()
            if now - pending.created_at > self.STATE_TTL_SECONDS
        ]
        for state in expired:
            del self._pending[state]
        if expired:
            self._save_pending()

    @staticmethod
    def _generate_code_verifier() -> str:
        """Generate a cryptographically random PKCE code_verifier (43-128 chars)."""
        return secrets.token_urlsafe(64)

    @staticmethod
    def _generate_code_challenge(code_verifier: str) -> str:
        """Derive the S256 code_challenge from a code_verifier."""
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class AuthorizationError(Exception):
    """Raised when per-user authorization fails."""
