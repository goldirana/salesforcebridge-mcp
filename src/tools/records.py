from __future__ import annotations

import re
import logging
from typing import Any

from src.tools.registry import registry
from src.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Only allow valid Salesforce object API names (alphanumeric + underscores, with __c for custom)
SOBJECT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(__c)?$")
SF_ID_PATTERN = re.compile(r"^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$")


def _validate_sobject(name: str) -> str | None:
    if not name or not SOBJECT_PATTERN.match(name):
        return f"Invalid sObject name: '{name}'"
    return None


def _validate_record_id(record_id: str) -> str | None:
    if not record_id or not SF_ID_PATTERN.match(record_id):
        return f"Invalid Salesforce record ID: '{record_id}'"
    return None


@registry.register
class GetRecordTool(BaseTool):
    name = "get_record"
    description = "Retrieve a single Salesforce record by its object type and record ID."
    roles = ["admin", "csm", "viewer"]
    input_schema = {
        "type": "object",
        "properties": {
            "sobject": {"type": "string", "description": "Salesforce object API name (e.g. Account, Case, Contact)."},
            "record_id": {"type": "string", "description": "The 15 or 18 character Salesforce record ID."},
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of field names to return. Returns all fields if omitted.",
            },
        },
        "required": ["sobject", "record_id"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        sobject = params.get("sobject", "")
        record_id = params.get("record_id", "")
        fields = params.get("fields")

        if err := _validate_sobject(sobject):
            return ToolResult(success=False, error=err)
        if err := _validate_record_id(record_id):
            return ToolResult(success=False, error=err)

        try:
            record = await self.sf.get_record(sobject, record_id, fields)
        except Exception as exc:
            logger.error("get_record failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        return ToolResult(success=True, data=record, record_count=1)


@registry.register
class CreateRecordTool(BaseTool):
    name = "create_record"
    description = "Create a new Salesforce record."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "sobject": {"type": "string", "description": "Salesforce object API name."},
            "data": {"type": "object", "description": "Field-value pairs for the new record."},
        },
        "required": ["sobject", "data"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        sobject = params.get("sobject", "")
        data = params.get("data", {})

        if err := _validate_sobject(sobject):
            return ToolResult(success=False, error=err)
        if not data:
            return ToolResult(success=False, error="Record data cannot be empty.")

        try:
            result = await self.sf.create_record(sobject, data)
        except Exception as exc:
            logger.error("create_record failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            data={"id": result.get("id"), "success": result.get("success")},
            record_count=1,
        )


@registry.register
class UpdateRecordTool(BaseTool):
    name = "update_record"
    description = "Update fields on an existing Salesforce record."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "sobject": {"type": "string", "description": "Salesforce object API name."},
            "record_id": {"type": "string", "description": "The 15 or 18 character Salesforce record ID."},
            "data": {"type": "object", "description": "Field-value pairs to update."},
        },
        "required": ["sobject", "record_id", "data"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        sobject = params.get("sobject", "")
        record_id = params.get("record_id", "")
        data = params.get("data", {})

        if err := _validate_sobject(sobject):
            return ToolResult(success=False, error=err)
        if err := _validate_record_id(record_id):
            return ToolResult(success=False, error=err)
        if not data:
            return ToolResult(success=False, error="Update data cannot be empty.")

        try:
            await self.sf.update_record(sobject, record_id, data)
        except Exception as exc:
            logger.error("update_record failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        return ToolResult(success=True, data={"id": record_id, "updated": True})


@registry.register
class DeleteRecordTool(BaseTool):
    name = "delete_record"
    description = "Delete a Salesforce record by its object type and record ID."
    roles = ["admin"]
    input_schema = {
        "type": "object",
        "properties": {
            "sobject": {"type": "string", "description": "Salesforce object API name."},
            "record_id": {"type": "string", "description": "The 15 or 18 character Salesforce record ID."},
        },
        "required": ["sobject", "record_id"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        sobject = params.get("sobject", "")
        record_id = params.get("record_id", "")

        if err := _validate_sobject(sobject):
            return ToolResult(success=False, error=err)
        if err := _validate_record_id(record_id):
            return ToolResult(success=False, error=err)

        try:
            await self.sf.delete_record(sobject, record_id)
        except Exception as exc:
            logger.error("delete_record failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        return ToolResult(success=True, data={"id": record_id, "deleted": True})
