from __future__ import annotations

import logging
from typing import Any, Type

from src.tools.base import BaseTool, ToolResult
from src.integrations.salesforce import SalesforceClient

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for all MCP tools.

    Tools register themselves here at import time.
    The server queries the registry to build the tool list for Claude.
    """

    def __init__(self) -> None:
        self._tool_classes: dict[str, Type[BaseTool]] = {}

    def register(self, tool_cls: Type[BaseTool]) -> Type[BaseTool]:
        """
        Decorator to register a tool class.

        Usage:
            @registry.register
            class SoqlQueryTool(BaseTool):
                name = "soql_query"
                ...
        """
        name = tool_cls.name
        if not name:
            raise ValueError(f"{tool_cls.__name__} must define a 'name' attribute")
        if name in self._tool_classes:
            raise ValueError(f"Tool '{name}' is already registered")

        self._tool_classes[name] = tool_cls
        logger.info("Registered tool: %s", name)
        return tool_cls

    def get_tool_names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tool_classes.keys())

    def get_tools_for_role(self, role: str, sf_client: SalesforceClient) -> dict[str, BaseTool]:
        """Return instantiated tools that the given role can access."""
        return {
            name: cls(sf_client)
            for name, cls in self._tool_classes.items()
            if role in cls.roles
        }

    def get_all_tools(self, sf_client: SalesforceClient) -> dict[str, BaseTool]:
        """Return all registered tools, instantiated with the SF client."""
        return {
            name: cls(sf_client)
            for name, cls in self._tool_classes.items()
        }

    def get_mcp_schemas(self, role: str, sf_client: SalesforceClient) -> list[dict[str, Any]]:
        """Return MCP-compatible tool definitions filtered by role."""
        tools = self.get_tools_for_role(role, sf_client)
        return [tool.to_mcp_schema() for tool in tools.values()]

    async def execute_tool(
        self, name: str, role: str, sf_client: SalesforceClient, **params: Any
    ) -> ToolResult:
        """Look up a tool by name, check role access, and execute it."""
        if name not in self._tool_classes:
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        tool_cls = self._tool_classes[name]

        if role not in tool_cls.roles:
            return ToolResult(success=False, error=f"Role '{role}' cannot use tool '{name}'")

        tool = tool_cls(sf_client)
        return await tool.execute(**params)


# Singleton — import this in tool files to register
registry = ToolRegistry()
