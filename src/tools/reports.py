from __future__ import annotations

import logging
from typing import Any

from src.tools.registry import registry
from src.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


@registry.register
class CaseSummaryReportTool(BaseTool):
    name = "case_summary_report"
    description = "Get a summary of cases grouped by status and priority."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Look back period in days (default 30, max 90)."},
        },
    }

    async def execute(self, **params: Any) -> ToolResult:
        days = min(params.get("days", 30), 90)

        soql = (
            f"SELECT Status, Priority, COUNT(Id) total "
            f"FROM Case WHERE CreatedDate = LAST_N_DAYS:{days} "
            f"GROUP BY Status, Priority ORDER BY Status, Priority"
        )

        try:
            result = await self.sf.query(soql)
        except Exception as exc:
            logger.error("case_summary_report failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        records = result.get("records", [])
        return ToolResult(
            success=True,
            data={"period_days": days, "summary": records},
            record_count=len(records),
        )


@registry.register
class PipelineReportTool(BaseTool):
    name = "pipeline_report"
    description = "Get the current sales pipeline summary grouped by stage."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "min_amount": {"type": "number", "description": "Minimum opportunity amount to include (default 0)."},
        },
    }

    async def execute(self, **params: Any) -> ToolResult:
        min_amount = params.get("min_amount", 0)

        soql = (
            f"SELECT StageName, COUNT(Id) total, SUM(Amount) totalAmount "
            f"FROM Opportunity WHERE IsClosed = false AND Amount >= {min_amount} "
            f"GROUP BY StageName ORDER BY StageName"
        )

        try:
            result = await self.sf.query(soql)
        except Exception as exc:
            logger.error("pipeline_report failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        records = result.get("records", [])
        return ToolResult(
            success=True,
            data={"min_amount": min_amount, "stages": records},
            record_count=len(records),
        )


@registry.register
class AccountHealthReportTool(BaseTool):
    name = "account_health_report"
    description = "Get account health metrics: open cases, recent activity, opportunity value."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Number of accounts to include (default 20, max 50)."},
        },
    }

    async def execute(self, **params: Any) -> ToolResult:
        limit = min(params.get("limit", 20), 50)

        # Accounts with most open cases
        cases_soql = (
            f"SELECT Account.Name, AccountId, COUNT(Id) openCases "
            f"FROM Case WHERE IsClosed = false "
            f"GROUP BY Account.Name, AccountId "
            f"ORDER BY COUNT(Id) DESC LIMIT {limit}"
        )

        try:
            result = await self.sf.query(cases_soql)
        except Exception as exc:
            logger.error("account_health_report failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        records = result.get("records", [])
        return ToolResult(
            success=True,
            data={"accounts": records},
            record_count=len(records),
        )
