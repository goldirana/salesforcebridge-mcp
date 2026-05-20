"""
Authorization middleware — resolves the user's role and enforces tool access.

Sits between authentication (who are you?) and tool execution (what can you do?).
"""

from __future__ import annotations

import logging
from typing import Optional

from src.authz.roles import Role, DEFAULT_ROLE, PROFILE_ROLE_MAP
from src.auth.token_store import TokenStore

logger = logging.getLogger(__name__)

# In-memory cache: user_id → resolved Role
_role_cache: dict[str, Role] = {}


async def resolve_role(user_id: str, sf_client=None) -> Role:
    """
    Determine the user's role.

    Strategy:
    1. Check cache
    2. If sf_client is available, query Salesforce for the user's Profile
    3. Map Profile name → Role via PROFILE_ROLE_MAP
    4. Fall back to DEFAULT_ROLE (viewer)
    """
    # Check cache first
    if user_id in _role_cache:
        return _role_cache[user_id]

    role = DEFAULT_ROLE

    if sf_client is not None:
        try:
            # Query the current user's profile from Salesforce
            userinfo = await sf_client.query(
                "SELECT Profile.Name FROM User WHERE Id = UserInfo.getUserId() LIMIT 1"
            )
            records = userinfo.get("records", [])
            if records:
                profile_name = records[0].get("Profile", {}).get("Name", "")
                role = PROFILE_ROLE_MAP.get(profile_name, DEFAULT_ROLE)
                logger.info(
                    "Resolved role for user %s: profile=%s → role=%s",
                    user_id, profile_name, role.value,
                )
        except Exception as exc:
            logger.warning(
                "Could not resolve role from Salesforce for user %s: %s. Using default=%s",
                user_id, exc, DEFAULT_ROLE.value,
            )

    _role_cache[user_id] = role
    return role


def set_role(user_id: str, role: Role) -> None:
    """Manually set a user's role (for testing or admin override)."""
    _role_cache[user_id] = role
    logger.info("Manually set role for user %s: %s", user_id, role.value)


def clear_role(user_id: str) -> None:
    """Clear cached role for a user (e.g., on logout)."""
    _role_cache.pop(user_id, None)


def get_cached_role(user_id: str) -> Optional[Role]:
    """Return the cached role if available, None otherwise."""
    return _role_cache.get(user_id)
