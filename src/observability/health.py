from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    healthy: bool
    checks: dict[str, Any]
    uptime_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self.healthy else "unhealthy",
            "uptime_seconds": round(self.uptime_seconds, 1),
            "checks": self.checks,
        }


class HealthChecker:
    """
    Provides two levels of health checks:

    - liveness  (/health)  — is the process alive? Always True if this runs.
    - readiness (/ready)   — can the server handle requests? Checks SF connectivity.
    """

    def __init__(self) -> None:
        self._start_time = time.time()

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    def liveness(self) -> HealthStatus:
        """Simple liveness probe — if this returns, the process is alive."""
        return HealthStatus(
            healthy=True,
            checks={"process": "alive"},
            uptime_seconds=self.uptime,
        )

    async def readiness(self) -> HealthStatus:
        """
        Deep readiness probe — checks external dependencies.
        Used by load balancers to decide if this instance can take traffic.
        """
        checks: dict[str, Any] = {}
        all_healthy = True

        # Check Salesforce connectivity
        sf_ok = await self._check_salesforce()
        checks["salesforce"] = "reachable" if sf_ok else "unreachable"
        if not sf_ok:
            all_healthy = False

        # Check Redis (when implemented)
        # redis_ok = await self._check_redis()
        # checks["redis"] = "reachable" if redis_ok else "unreachable"
        # if not redis_ok:
        #     all_healthy = False

        return HealthStatus(
            healthy=all_healthy,
            checks=checks,
            uptime_seconds=self.uptime,
        )

    async def _check_salesforce(self) -> bool:
        """Verify Salesforce instance is reachable."""
        url = f"{settings.salesforce.instance_url}/services/data/{settings.salesforce.api_version}/limits"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
            # 401 is expected (no auth header) but means SF is reachable
            return response.status_code in (200, 401)
        except Exception as exc:
            logger.warning("Salesforce health check failed: %s", exc)
            return False


# Singleton
health_checker = HealthChecker()
