"""
Authorization policies — which role can use which tools.

This module provides a check function used by the authz middleware
before any tool is executed.
"""

from __future__ import annotations

from src.authz.roles import Role
from src.tools.registry import registry


def can_execute(role: Role, tool_name: str) -> bool:
    """Return True if the role is allowed to execute the given tool."""
    tool_cls = registry._tool_classes.get(tool_name)
    if tool_cls is None:
        return False
    return role.value in tool_cls.roles


def get_allowed_tools(role: Role) -> list[str]:
    """Return tool names the role is allowed to use."""
    return [
        name
        for name, cls in registry._tool_classes.items()
        if role.value in cls.roles
    ]


def get_denied_tools(role: Role) -> list[str]:
    """Return tool names the role is NOT allowed to use."""
    return [
        name
        for name, cls in registry._tool_classes.items()
        if role.value not in cls.roles
    ]
