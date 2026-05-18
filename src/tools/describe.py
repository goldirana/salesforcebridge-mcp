from __future__ import annotations

import logging
from typing import Any

from src.tools.registry import registry
from src.tools.base import BaseTool, ToolResult
from src.tools.records import _validate_sobject

logger = logging.getLogger(__name__)


@registry.register
class DescribeObjectTool(BaseTool):
    name = "describe_object"
    description = "Get the schema (fields, types, relationships) for a Salesforce object."
    roles = ["admin", "csm", "viewer"]
    input_schema = {
        "type": "object",
        "properties": {
            "sobject": {"type": "string", "description": "Salesforce object API name (e.g. Account, Case)."},
        },
        "required": ["sobject"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        sobject = params.get("sobject", "")

        if err := _validate_sobject(sobject):
            return ToolResult(success=False, error=err)

        try:
            schema = await self.sf.describe_object(sobject)
        except Exception as exc:
            logger.error("describe_object failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        # Return a trimmed summary — full describe is huge and eats Claude's context
        fields = [
            {
                "name": f["name"],
                "label": f["label"],
                "type": f["type"],
                "nillable": f["nillable"],
                "updateable": f["updateable"],
                "referenceTo": f.get("referenceTo", []),
            }
            for f in schema.get("fields", [])
        ]

        return ToolResult(
            success=True,
            data={
                "name": schema.get("name"),
                "label": schema.get("label"),
                "keyPrefix": schema.get("keyPrefix"),
                "queryable": schema.get("queryable"),
                "createable": schema.get("createable"),
                "updateable": schema.get("updateable"),
                "deletable": schema.get("deletable"),
                "fieldCount": len(fields),
                "fields": fields,
            },
        )


@registry.register
class ListObjectsTool(BaseTool):
    name = "list_objects"
    description = "List all available Salesforce objects in the org."
    roles = ["admin", "csm", "viewer"]
    input_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **params: Any) -> ToolResult:
        try:
            result = await self.sf.describe_global()
        except Exception as exc:
            logger.error("describe_global failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        objects = [
            {
                "name": obj["name"],
                "label": obj["label"],
                "queryable": obj["queryable"],
                "custom": obj.get("custom", False),
            }
            for obj in result.get("sobjects", [])
        ]

        return ToolResult(
            success=True,
            data={"objectCount": len(objects), "objects": objects},
            record_count=len(objects),
        )
