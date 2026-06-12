import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import ConnectionPool, Redis
from testcontainers.redis import RedisContainer

from cloud_fpga_orchestrator.workers.protocol import ResponseStatus, WishboneResponse
from cloud_fpga_orchestrator.workers.runner import run_worker


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer() as container:
        yield container


@pytest_asyncio.fixture
async def redis_client(redis_container):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    pool = ConnectionPool.from_url(f"redis://{host}:{port}")
    client = Redis(connection_pool=pool)
    await client.flushdb()
    yield client
    await client.aclose()
    await pool.aclose()


@pytest.fixture
def mock_host():
    host = AsyncMock()
    host.flash = AsyncMock(return_value=None)
    host.run = AsyncMock(
        return_value=WishboneResponse(status=ResponseStatus.OK, data=[0x42])
    )
    host.reset = AsyncMock(return_value=None)
    return host


@pytest_asyncio.fixture
async def worker(redis_client, mock_host):
    """Run a single FPGA-0 worker as a background task for the duration of the test."""
    shutdown = asyncio.Event()
    semaphore = asyncio.Semaphore(2)
    task = asyncio.create_task(
        run_worker(
            redis_client, mock_host,
            fpga_id=0, build_semaphore=semaphore, shutdown=shutdown,
        )
    )
    yield shutdown
    shutdown.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest_asyncio.fixture
async def app_client(redis_client):
    from cloud_fpga_orchestrator.api.app import create_app
    from cloud_fpga_orchestrator.api.deps import get_redis

    app = create_app()

    async def _override():
        yield redis_client

    app.dependency_overrides[get_redis] = _override

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
