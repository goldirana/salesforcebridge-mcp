from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from src.config import settings
from src.observability.logging import setup_logging, ToolTimer
from src.observability.health import health_checker
from src.auth.token_store import InMemoryTokenStore
from src.auth.oauth_client_credentials import ClientCredentialsAuth
from src.integrations.salesforce import SalesforceClient
from src.tools.registry import registry
from src.tools.base import ToolResult
from src.middleware.input_validator import validate_tool_params, InputValidationError
from src.middleware.error_handler import handle_error

# ── Import tool modules so they register themselves ──
import src.tools.query       # noqa: F401
import src.tools.records     # noqa: F401
import src.tools.describe    # noqa: F401
import src.tools.cases       # noqa: F401
import src.tools.customers   # noqa: F401
import src.tools.reports     # noqa: F401

logger = logging.getLogger(__name__)

# ── Setup ──

setup_logging(
    level=settings.server.log_level,
    json_output=settings.server.is_production,
)

# Auth → SF client
token_store = InMemoryTokenStore()
auth = ClientCredentialsAuth(token_store)
sf_client = SalesforceClient(auth)

# MCP server
mcp = FastMCP(
    "Salesforce CSM Connector",
    instructions="MCP server bridging Claude to Salesforce for CSM workflows.",
)


# ── Health endpoints ──

@mcp.resource("health://liveness")
async def health() -> str:
    """Liveness probe — is the server process alive?"""
    import json
    return json.dumps(health_checker.liveness().to_dict())


@mcp.resource("health://readiness")
async def ready() -> str:
    """Readiness probe — can the server handle requests?"""
    import json
    status = await health_checker.readiness()
    return json.dumps(status.to_dict())


# ── Dynamic tool registration with MCP ──

def _register_mcp_tool(tool_name: str, tool_cls: type) -> None:
    """Register a single tool from the registry as an MCP tool."""

    # Build the MCP tool function dynamically
    async def tool_handler(**params) -> dict:
        with ToolTimer(tool_name):
            try:
                # Validate inputs
                cleaned_params = validate_tool_params(tool_name, params)

                # Execute via registry (includes role check)
                # Default role is "csm" for now — will come from auth middleware later
                result = await registry.execute_tool(
                    name=tool_name,
                    role="csm",
                    sf_client=sf_client,
                    **cleaned_params,
                )

                if result.success:
                    return {"success": True, "data": result.data, "record_count": result.record_count}
                else:
                    return {"success": False, "error": result.error}

            except InputValidationError as exc:
                error_resp = handle_error(exc)
                return error_resp.to_dict()
            except Exception as exc:
                error_resp = handle_error(exc)
                return error_resp.to_dict()

    # Set function metadata for MCP
    tool_handler.__name__ = tool_name
    tool_handler.__doc__ = tool_cls.description

    # Get the input schema from the tool class
    schema = tool_cls.input_schema
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Register with FastMCP using the decorator approach
    mcp.tool(
        name=tool_name,
        description=tool_cls.description,
    )(tool_handler)


# Register all tools from the registry with MCP
for name, tool_cls in registry._tool_classes.items():
    _register_mcp_tool(name, tool_cls)

logger.info(
    "Registered %d tools: %s",
    len(registry.get_tool_names()),
    ", ".join(registry.get_tool_names()),
)


# ── Entry point ──

def main() -> None:
    """Start the MCP server."""
    logger.info(
        "Starting Salesforce CSM Connector MCP Server on %s:%d (env=%s)",
        settings.server.host,
        settings.server.port,
        settings.server.env,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
