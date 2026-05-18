from __future__ import annotations

import logging
from typing import Any

from src.tools.registry import registry
from src.tools.base import BaseTool, ToolResult
from src.tools.records import _validate_record_id

logger = logging.getLogger(__name__)


@registry.register
class GetOpenCasesTool(BaseTool):
    name = "get_open_cases"
    description = "Get all open support cases, optionally filtered by account or priority."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "account_id": {"type": "string", "description": "Filter by Account ID (optional)."},
            "priority": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
                "description": "Filter by priority (optional).",
            },
            "limit": {"type": "integer", "description": "Max records to return (default 50, max 200)."},
        },
    }

    async def execute(self, **params: Any) -> ToolResult:
        account_id = params.get("account_id")
        priority = params.get("priority")
        limit = min(params.get("limit", 50), 200)

        conditions = ["IsClosed = false"]

        if account_id:
            if err := _validate_record_id(account_id):
                return ToolResult(success=False, error=err)
            conditions.append(f"AccountId = '{account_id}'")

        if priority:
            if priority not in ("High", "Medium", "Low"):
                return ToolResult(success=False, error=f"Invalid priority: '{priority}'")
            conditions.append(f"Priority = '{priority}'")

        where = " AND ".join(conditions)
        soql = (
            f"SELECT Id, CaseNumber, Subject, Status, Priority, AccountId, "
            f"Account.Name, CreatedDate, LastModifiedDate "
            f"FROM Case WHERE {where} ORDER BY CreatedDate DESC LIMIT {limit}"
        )

        try:
            result = await self.sf.query(soql)
        except Exception as exc:
            logger.error("get_open_cases failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        records = result.get("records", [])
        return ToolResult(
            success=True,
            data={"totalSize": result.get("totalSize", 0), "cases": records},
            record_count=len(records),
        )


@registry.register
class GetCaseDetailTool(BaseTool):
    name = "get_case_detail"
    description = "Get full details of a specific case including comments and history."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "case_id": {"type": "string", "description": "The Case record ID."},
        },
        "required": ["case_id"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        case_id = params.get("case_id", "")

        if err := _validate_record_id(case_id):
            return ToolResult(success=False, error=err)

        try:
            case = await self.sf.get_record("Case", case_id)
        except Exception as exc:
            logger.error("get_case_detail failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        # Fetch recent case comments
        comments_soql = (
            f"SELECT Id, CommentBody, CreatedDate, CreatedBy.Name "
            f"FROM CaseComment WHERE ParentId = '{case_id}' "
            f"ORDER BY CreatedDate DESC LIMIT 20"
        )

        try:
            comments_result = await self.sf.query(comments_soql)
            comments = comments_result.get("records", [])
        except Exception:
            comments = []

        return ToolResult(
            success=True,
            data={"case": case, "recentComments": comments},
            record_count=1,
        )
