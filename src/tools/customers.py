from __future__ import annotations

import logging
from typing import Any

from src.tools.registry import registry
from src.tools.base import BaseTool, ToolResult
from src.tools.records import _validate_record_id

logger = logging.getLogger(__name__)


@registry.register
class GetCustomerOverviewTool(BaseTool):
    name = "get_customer_overview"
    description = "Get a CSM overview of an account: basic info, open cases, recent opportunities, and contacts."
    roles = ["admin", "csm"]
    input_schema = {
        "type": "object",
        "properties": {
            "account_id": {"type": "string", "description": "The Account record ID."},
        },
        "required": ["account_id"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        account_id = params.get("account_id", "")

        if err := _validate_record_id(account_id):
            return ToolResult(success=False, error=err)

        try:
            account = await self.sf.get_record("Account", account_id)
        except Exception as exc:
            logger.error("get_customer_overview account fetch failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        # Open cases count and recent ones
        cases_soql = (
            f"SELECT Id, CaseNumber, Subject, Status, Priority, CreatedDate "
            f"FROM Case WHERE AccountId = '{account_id}' AND IsClosed = false "
            f"ORDER BY CreatedDate DESC LIMIT 10"
        )

        # Recent opportunities
        opps_soql = (
            f"SELECT Id, Name, StageName, Amount, CloseDate "
            f"FROM Opportunity WHERE AccountId = '{account_id}' "
            f"ORDER BY CloseDate DESC LIMIT 10"
        )

        # Key contacts
        contacts_soql = (
            f"SELECT Id, Name, Title, Email, Phone "
            f"FROM Contact WHERE AccountId = '{account_id}' "
            f"ORDER BY CreatedDate DESC LIMIT 10"
        )

        cases, opps, contacts = [], [], []

        try:
            cases = (await self.sf.query(cases_soql)).get("records", [])
        except Exception:
            logger.warning("Failed to fetch cases for account %s", account_id)

        try:
            opps = (await self.sf.query(opps_soql)).get("records", [])
        except Exception:
            logger.warning("Failed to fetch opportunities for account %s", account_id)

        try:
            contacts = (await self.sf.query(contacts_soql)).get("records", [])
        except Exception:
            logger.warning("Failed to fetch contacts for account %s", account_id)

        return ToolResult(
            success=True,
            data={
                "account": account,
                "openCases": cases,
                "recentOpportunities": opps,
                "keyContacts": contacts,
            },
            record_count=1,
        )


@registry.register
class SearchCustomersTool(BaseTool):
    name = "search_customers"
    description = "Search for customer accounts by name."
    roles = ["admin", "csm", "viewer"]
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Account name or partial name to search for."},
            "limit": {"type": "integer", "description": "Max results (default 20, max 100)."},
        },
        "required": ["name"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        name = params.get("name", "").strip()
        limit = min(params.get("limit", 20), 100)

        if not name:
            return ToolResult(success=False, error="Search name cannot be empty.")

        if len(name) < 2:
            return ToolResult(success=False, error="Search name must be at least 2 characters.")

        # Escape single quotes in name to prevent SOQL injection
        safe_name = name.replace("'", "\\'")

        soql = (
            f"SELECT Id, Name, Industry, Type, Phone, Website "
            f"FROM Account WHERE Name LIKE '%{safe_name}%' "
            f"ORDER BY Name ASC LIMIT {limit}"
        )

        try:
            result = await self.sf.query(soql)
        except Exception as exc:
            logger.error("search_customers failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

        records = result.get("records", [])
        return ToolResult(
            success=True,
            data={"totalSize": result.get("totalSize", 0), "accounts": records},
            record_count=len(records),
        )
