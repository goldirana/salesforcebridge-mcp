from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (no-op if file doesn't exist)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class SalesforceConfig:
    client_id: str = field(default_factory=lambda: _env("SF_CLIENT_ID"))
    client_secret: str = field(default_factory=lambda: _env("SF_CLIENT_SECRET"))
    instance_url: str = field(default_factory=lambda: _env("SF_INSTANCE_URL"))
    callback_url: str = field(default_factory=lambda: _env("SF_CALLBACK_URL", "http://localhost:8000/oauth/callback"))
    api_version: str = field(default_factory=lambda: _env("SF_API_VERSION", "v62.0"))


@dataclass(frozen=True)
class RedisConfig:
    url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379"))


@dataclass(frozen=True)
class ServerConfig:
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    env: str = field(default_factory=lambda: _env("ENV", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@dataclass(frozen=True)
class RateLimitConfig:
    requests_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_RPM", 60))
    burst_size: int = field(default_factory=lambda: _env_int("RATE_LIMIT_BURST", 10))


@dataclass(frozen=True)
class CacheConfig:
    describe_ttl_seconds: int = field(default_factory=lambda: _env_int("CACHE_DESCRIBE_TTL", 3600))
    query_ttl_seconds: int = field(default_factory=lambda: _env_int("CACHE_QUERY_TTL", 300))


@dataclass(frozen=True)
class Settings:
    salesforce: SalesforceConfig = field(default_factory=SalesforceConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)


# Singleton — import this everywhere
settings = Settings()
