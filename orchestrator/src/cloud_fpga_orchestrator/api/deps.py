import os
from collections.abc import AsyncGenerator

from fastapi import Header
from redis.asyncio import ConnectionPool, Redis

_pool: ConnectionPool | None = None


def init_pool() -> None:
    """Initialize the shared Redis connection pool.

    Called once at application startup.
    """
    global _pool
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    _pool = ConnectionPool.from_url(redis_url)


async def close_pool() -> None:
    """Close the shared Redis connection pool.

    Called once at application shutdown.
    """
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Yield a Redis client using the shared connection pool.

    Used as a FastAPI dependency via Depends(get_redis).
    """
    if _pool is None:
        raise RuntimeError("Redis pool not initialized — call init_pool() at startup")
    async with Redis(connection_pool=_pool) as redis:
        yield redis


async def get_api_key(
    x_api_key: str | None = Header(default=None),
) -> str | None:
    """Read the API key from the X-API-Key header.

    Authentication is not enforced in the initial prototype.
    This stub exists so auth can be layered in without changing route signatures.
    """
    return x_api_key


async def get_session_id(
    x_session_id: str | None = Header(default=None),
) -> str | None:
    """Read the session ID from the X-Session-ID header."""
    return x_session_id
