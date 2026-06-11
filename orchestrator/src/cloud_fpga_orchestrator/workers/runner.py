import asyncio
import logging
import os
import signal
from uuid import UUID

from redis.asyncio import Redis

from ..state import JobStatus, JobType, get_job, update_job_status
from ..state import keys
from .host_client import HostClient
from .jobs import handle_build_and_program, handle_reset, handle_run

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_BUILDS: int = int(os.environ.get("MAX_CONCURRENT_BUILDS", "2"))
_BLPOP_TIMEOUT: int = 5  # seconds between shutdown checks when queue is empty
_NUM_FPGAS: int = 10


async def run_worker(
    redis: Redis,
    host: HostClient,
    fpga_id: int,
    build_semaphore: asyncio.Semaphore,
    shutdown: asyncio.Event,
) -> None:
    """Process jobs for a single FPGA until the shutdown event is set.

    Blocks on the FPGA's Redis queue with a timeout so the shutdown event
    is checked periodically. Lets the current job finish before stopping.

    Args:
        redis: Active Redis connection.
        host: Host agent client shared across workers.
        fpga_id: Index of the FPGA this worker is responsible for (0–9).
        build_semaphore: Shared semaphore capping concurrent build jobs.
        shutdown: Event set by the signal handler to trigger graceful exit.
    """
    logger.info("Worker started for FPGA %d", fpga_id)

    while not shutdown.is_set():
        result = await redis.blpop(
            keys.fpga_queue(fpga_id), timeout=_BLPOP_TIMEOUT
        )
        if result is None:
            continue

        _, job_id_bytes = result
        job_id = UUID(job_id_bytes.decode())
        job = await get_job(redis, job_id)

        if job is None:
            logger.warning("FPGA %d: job %s not found in Redis, skipping", fpga_id, job_id)
            continue

        logger.info("FPGA %d: starting %s job %s", fpga_id, job.type, job_id)

        try:
            if job.type == JobType.BUILD_AND_PROGRAM:
                async with build_semaphore:
                    await handle_build_and_program(redis, host, job)
            elif job.type == JobType.RUN:
                await handle_run(redis, host, job)
            elif job.type == JobType.RESET:
                await handle_reset(redis, host, job)
            else:
                logger.error("FPGA %d: unknown job type %s", fpga_id, job.type)
        except Exception:
            logger.exception("FPGA %d: unhandled error in job %s", fpga_id, job_id)
            await update_job_status(redis, job_id, JobStatus.FAILED)

        logger.info("FPGA %d: finished job %s", fpga_id, job_id)

    logger.info("Worker shut down for FPGA %d", fpga_id)


async def run_all_workers(redis: Redis, host: HostClient) -> None:
    """Start all 10 FPGA workers and run until a shutdown signal is received.

    Registers SIGTERM and SIGINT handlers that set a shared shutdown event.
    All workers finish their current job before the process exits.

    Args:
        redis: Active Redis connection shared across all workers.
        host: Host agent client shared across all workers.
    """
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    build_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_BUILDS)

    tasks = [
        asyncio.create_task(
            run_worker(redis, host, fpga_id, build_semaphore, shutdown),
            name=f"worker-fpga-{fpga_id}",
        )
        for fpga_id in range(_NUM_FPGAS)
    ]

    await asyncio.gather(*tasks)
    logger.info("All workers shut down cleanly")


async def main() -> None:
    """Entry point: connect to Redis and the host agent, then run all workers."""
    logging.basicConfig(level=logging.INFO)

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis = Redis.from_url(redis_url)

    async with HostClient() as host:
        await run_all_workers(redis, host)

    await redis.aclose()
