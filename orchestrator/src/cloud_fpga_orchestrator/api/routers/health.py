from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from ..deps import get_redis
from ..models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(redis: Redis = Depends(get_redis)) -> HealthResponse:
    """Return the health status of the service and its Redis connection."""
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return HealthResponse(
        status="ok" if redis_ok else "degraded",
        redis=redis_ok,
    )
