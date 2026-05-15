from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TokenData:
    access_token: str
    refresh_token: str
    instance_url: str
    expires_at: float  # Unix timestamp
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        # Consider expired 60s early to avoid edge-case failures
        return time.time() >= (self.expires_at - 60)


class TokenStore(ABC):
    """Interface for token storage backends."""

    @abstractmethod
    async def save_token(self, user_id: str, token: TokenData) -> None:
        ...

    @abstractmethod
    async def get_token(self, user_id: str) -> Optional[TokenData]:
        ...

    @abstractmethod
    async def delete_token(self, user_id: str) -> None:
        ...

    async def is_token_valid(self, user_id: str) -> bool:
        token = await self.get_token(user_id)
        return token is not None and not token.is_expired


class InMemoryTokenStore(TokenStore):
    """Dev/single-instance token store. Swap to RedisTokenStore for production."""

    def __init__(self) -> None:
        self._tokens: dict[str, TokenData] = {}

    async def save_token(self, user_id: str, token: TokenData) -> None:
        self._tokens[user_id] = token

    async def get_token(self, user_id: str) -> Optional[TokenData]:
        token = self._tokens.get(user_id)
        if token is None:
            return None
        if token.is_expired:
            # Don't delete — caller may want to use refresh_token
            return token
        return token

    async def delete_token(self, user_id: str) -> None:
        self._tokens.pop(user_id, None)
