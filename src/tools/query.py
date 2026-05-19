from __future__ import annotations

import re
import logging
from typing import Any

from src.tools.registry import registry
from src.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000

# Patterns that should never appear in a read-only SOQL query
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|UPSERT|MERGE|UNDELETE)\b", re.IGNORECASE
)


@registry.register
class SoqlQueryTool(BaseTool):
    name = "soql_query"
    description = """Execute a read-only SOQL query against Salesforce and return the results.
    Always pass the limit and let the user know about it if they exceed the max limit."""
    roles = ["admin", "csm", "viewer"]
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A valid SOQL SELECT query.",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        query: str = params.get("query", "").strip()

        # ── Validation ──
        if not query:
            return ToolResult(success=False, error="Query cannot be empty.")

        if not query.upper().startswith("SELECT"):
            return ToolResult(success=False, error="Only SELECT queries are allowed.")

        if FORBIDDEN_KEYWORDS.search(query):
            return ToolResult(
                success=False,
                error="DML statements (INSERT, UPDATE, DELETE, etc.) are not allowed. Use dedicated tools for write operations.",
            )

        # Auto-add LIMIT if missing
        if "LIMIT" not in query.upper():
            query += f" LIMIT {DEFAULT_LIMIT}"
        else:
            # Enforce max limit
            limit_match = re.search(r"LIMIT\s+(\d+)", query, re.IGNORECASE)
            if limit_match and int(limit_match.group(1)) > MAX_LIMIT:
                query = re.sub(
                    r"LIMIT\s+\d+",
                    f"LIMIT {MAX_LIMIT}",
                    query,
                    flags=re.IGNORECASE,
                )

        # ── Execute ──
        try:
            result = await self.sf.query(query)
        except Exception as exc:
            logger.error("SOQL query failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        records = result.get("records", [])
        total = result.get("totalSize", len(records))

        return ToolResult(
            success=True,
            data={
                "totalSize": total, 
                "done": result.get("done", True),
            },
            record_count=len(records),
        )
