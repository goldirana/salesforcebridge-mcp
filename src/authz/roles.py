"""
Role definitions for the Salesforce MCP Bridge.

Roles control which tools a user can access.
Role assignment is determined by the user's Salesforce profile.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Available roles in the system."""

    ADMIN = "admin"
    CSM = "csm"
    VIEWER = "viewer"


# Default role for all authenticated users
DEFAULT_ROLE = Role.VIEWER

# Mapping from Salesforce Profile names to local roles.
# Users whose profile doesn't match any key get DEFAULT_ROLE.
PROFILE_ROLE_MAP: dict[str, Role] = {
    "System Administrator": Role.ADMIN,
    "Custom: Sales Operations": Role.ADMIN,
    "Customer Success Manager": Role.CSM,
    "CSM": Role.CSM,
}
