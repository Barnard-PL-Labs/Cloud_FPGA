import httpx
import pytest
import pytest_asyncio
from redis.asyncio import ConnectionPool, Redis
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer() as container:
        yield container


@pytest_asyncio.fixture
async def redis_client(redis_container):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    url = f"redis://{host}:{port}"
    pool = ConnectionPool.from_url(url)
    client = Redis(connection_pool=pool)
    await client.flushdb()
    yield client
    await client.aclose()
    await pool.aclose()


@pytest_asyncio.fixture
async def app_client(redis_client):
    from cloud_fpga_orchestrator.api.app import create_app
    from cloud_fpga_orchestrator.api.deps import get_redis

    app = create_app()

    async def _override_get_redis():
        yield redis_client

    app.dependency_overrides[get_redis] = _override_get_redis

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
