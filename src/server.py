from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP

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
    name="Salesforce CSM Connector",
    instructions=(
        "You are connected to Salesforce org. "
        "Use 'describe_object' first if you're unsure what fields exist. "
        "Then use 'soql_query' to search, or the record tools to create/update/delete."
    ),
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

# JSON Schema type → Python type annotation mapping
_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _register_mcp_tool(tool_name: str, tool_cls: type) -> None:
    """Register a tool from the registry as an MCP tool with a proper signature."""

    schema = tool_cls.input_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    # Build inspect.Parameters from the JSON Schema
    params = []
    annotations = {}
    for prop_name, prop_def in properties.items():
        prop_type = _TYPE_MAP.get(prop_def.get("type", "string"), str)
        annotations[prop_name] = prop_type

        if prop_name in required:
            param = inspect.Parameter(
                prop_name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=prop_type,
            )
        else:
            param = inspect.Parameter(
                prop_name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=prop_type,
            )
        params.append(param)

    sig = inspect.Signature(params)

    # Capture tool_name and tool_cls in closure
    _name = tool_name
    _cls = tool_cls

    async def tool_handler(**kwargs) -> dict:
        with ToolTimer(_name):
            try:
                cleaned_params = validate_tool_params(_name, kwargs)
                result = await registry.execute_tool(
                    name=_name,
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

    # Set metadata so FastMCP introspects correctly
    tool_handler.__name__ = _name
    tool_handler.__doc__ = _cls.description
    tool_handler.__signature__ = sig
    tool_handler.__annotations__ = annotations

    mcp.tool(name=_name, description=_cls.description)(tool_handler)


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
