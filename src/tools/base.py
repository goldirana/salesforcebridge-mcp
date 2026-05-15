from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.integrations.salesforce import SalesforceClient


@dataclass
class ToolResult:
    """Standardised response returned by every tool."""
    success: bool
    data: Any = None
    error: str | None = None
    record_count: int = 0


class BaseTool(ABC):
    """
    All MCP tools inherit from this.

    Subclasses must define:
    - name: unique tool identifier
    - description: shown to Claude (keep it concise — it eats context tokens)
    - roles: which roles can use this tool
    - input_schema: JSON Schema describing the tool's parameters
    - execute(): the actual logic
    """

    name: str = ""
    description: str = ""
    roles: list[str] = field(default_factory=lambda: ["admin"])
    input_schema: dict[str, Any] = field(default_factory=dict)

    def __init__(self, sf_client: SalesforceClient) -> None:
        self.sf = sf_client

    @abstractmethod
    async def execute(self, **params: Any) -> ToolResult:
        """Run the tool with the given parameters."""
        ...

    def to_mcp_schema(self) -> dict[str, Any]:
        """Return the MCP-compatible tool definition for Claude."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
