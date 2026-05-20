from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from src.config import settings
from src.observability.logging import setup_logging, ToolTimer
from src.observability.health import health_checker
from src.auth.token_store import InMemoryTokenStore, FileTokenStore
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

# Auth (per-user OAuth Authorization Code + PKCE)
from src.auth.oauth_authorization_code import AuthorizationCodeAuth, AuthorizationError
from src.auth.callback_server import OAuthCallbackServer

token_store = FileTokenStore()  # Persists tokens to .tokens.json across restarts
# =========================
## For testing use the client credentials
# from src.auth.oauth_client_credentials import ClientCredentialsAuth
# user_auth = ClientCredentialsAuth(token_store)
# =========================
user_auth = AuthorizationCodeAuth(token_store)
callback_server = OAuthCallbackServer()

# Default user ID for single-user MCP sessions
DEFAULT_USER_ID = "default"


class _BoundUserAuth:
    """Adapter that binds AuthorizationCodeAuth to a specific user_id for SalesforceClient."""

    def __init__(self, auth: AuthorizationCodeAuth, user_id: str) -> None:
        self._auth = auth
        self._user_id = user_id

    async def get_access_token(self):
        return await self._auth.get_access_token(self._user_id)


# MCP server
mcp = FastMCP(
    name="Salesforce CSM Connector",
    instructions=(
        "You are connected to Salesforce org. "
        "Use 'describe_object' first if you're unsure what fields exist. "
        "Then use 'soql_query' to search, or the record tools to create/update/delete."
    ),
)


# ── Auth tools (per-user OAuth) ──

@mcp.tool(name="auth_start", description="Start the OAuth login flow. Returns the Salesforce authorization URL. After the user logs in, they should copy the full redirect URL from the browser and pass it to 'auth_complete'. Do NOT call auth_wait.")
async def auth_start(user_id: str = "") -> dict:
    """Generate an authorization URL and start the callback listener."""
    callback_server.start()
    # Always use DEFAULT_USER_ID for single-user MCP sessions
    url = user_auth.generate_authorization_url(DEFAULT_USER_ID)
    return {"authorization_url": url, "user_id": DEFAULT_USER_ID, "next_step": "After the user logs in at Salesforce, they will be redirected to a localhost URL. Ask them to copy that full URL and then call 'auth_complete' with it."}


@mcp.tool(name="auth_complete", description="Complete the OAuth login. Pass the full redirect URL from the browser address bar (e.g. http://localhost:8000/oauth/callback?code=...&state=...). Use this after logging in at Salesforce.")
async def auth_complete(redirect_url: str) -> dict:
    """Parse code/state from the redirect URL and exchange for tokens."""
    from urllib.parse import urlparse, parse_qs
    import httpx
    try:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if not code or not state:
            return {"success": False, "error": "Could not find 'code' and 'state' parameters in the URL. Make sure you copied the full URL from the browser."}

        token = await user_auth.handle_callback(code, state)
        callback_server.stop()
        return {"success": True, "instance_url": token.instance_url}
    except httpx.TimeoutException:
        return {"success": False, "error": "Request to Salesforce timed out. Check your network connection and try again."}
    except AuthorizationError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool(name="auth_wait", description="[Internal] Wait for OAuth callback on localhost. Do NOT use this — use 'auth_complete' with the redirect URL instead.")
async def auth_wait(user_id: str) -> dict:
    """Wait for OAuth callback and complete token exchange."""
    try:
        code, state = await callback_server.wait_for_callback(timeout=30)
        token = await user_auth.handle_callback(code, state)
        callback_server.stop()
        return {"success": True, "instance_url": token.instance_url, "user_id": user_id}
    except TimeoutError:
        callback_server.stop()
        return {"success": False, "error": "Callback server did not receive the redirect. Use 'auth_complete' with the redirect URL from your browser instead."}
    except AuthorizationError as exc:
        callback_server.stop()
        return {"success": False, "error": str(exc)}


@mcp.tool(name="auth_callback", description="Manually complete OAuth by providing code and state separately. Prefer 'auth_complete' with the full URL instead.")
async def auth_callback(code: str, state: str) -> dict:
    """Exchange the authorization code for tokens (manual fallback)."""
    try:
        token = await user_auth.handle_callback(code, state)
        return {"success": True, "instance_url": token.instance_url}
    except AuthorizationError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool(name="auth_status", description="Check if the user is currently authenticated with Salesforce.")
async def auth_status(user_id: str = "") -> dict:
    """Check authentication status."""
    authenticated = await user_auth.is_authenticated(DEFAULT_USER_ID)
    return {"user_id": DEFAULT_USER_ID, "authenticated": authenticated}


@mcp.tool(name="auth_revoke", description="Revoke Salesforce authentication and delete stored tokens.")
async def auth_revoke(user_id: str = "") -> dict:
    """Revoke and delete the user's token."""
    await user_auth.revoke_token(DEFAULT_USER_ID)
    return {"user_id": DEFAULT_USER_ID, "revoked": True}


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
                # Require per-user auth before any data access
                if not await user_auth.is_authenticated(DEFAULT_USER_ID):
                    return {
                        "success": False,
                        "error": "Not authenticated. Please use 'auth_start' to log in to Salesforce first.",
                    }

                sf_client = SalesforceClient(_BoundUserAuth(user_auth, DEFAULT_USER_ID))

                # Resolve user's role (defaults to viewer)
                from src.authz.middleware import resolve_role
                role = await resolve_role(DEFAULT_USER_ID)

                cleaned_params = validate_tool_params(_name, kwargs)
                result = await registry.execute_tool(
                    name=_name,
                    role=role.value,
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
