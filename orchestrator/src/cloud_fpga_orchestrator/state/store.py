from datetime import datetime, timedelta, timezone
from uuid import UUID

from redis.asyncio import Redis

from . import keys
from .models import VALID_TRANSITIONS, FPGAState, Job, JobStatus, Session


async def get_fpga_state(redis: Redis, fpga_id: int) -> FPGAState:
    """Return the current state of the given FPGA.

    Defaults to IDLE if no state has been written yet.
    """
    value = await redis.get(keys.fpga_state(fpga_id))
    return FPGAState(value.decode()) if value else FPGAState.IDLE


async def transition_fpga_state(
    redis: Redis, fpga_id: int, to: FPGAState
) -> None:
    """Transition an FPGA to a new state.

    Raises:
        ValueError: If the transition from the current state to `to` is invalid.
    """
    current = await get_fpga_state(redis, fpga_id)
    if to not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Invalid transition for FPGA {fpga_id}: {current} -> {to}"
        )
    await redis.set(keys.fpga_state(fpga_id), to.value)


async def get_session(redis: Redis, fpga_id: int) -> Session | None:
    """Return the active session for an FPGA, or None if no session exists."""
    value = await redis.get(keys.fpga_session(fpga_id))
    return Session.model_validate_json(value) if value else None


async def create_session(
    redis: Redis, fpga_id: int, owner: str, ttl_seconds: int
) -> Session:
    """Create and persist a session for an FPGA, expiring after `ttl_seconds`.

    Returns:
        The newly created Session.
    """
    session = Session(
        fpga_id=fpga_id,
        owner=owner,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    )
    await redis.set(
        keys.fpga_session(fpga_id),
        session.model_dump_json(),
        ex=ttl_seconds,
    )
    return session


async def delete_session(redis: Redis, fpga_id: int) -> None:
    """Delete the active session for an FPGA."""
    await redis.delete(keys.fpga_session(fpga_id))


async def enqueue_job(redis: Redis, job: Job) -> None:
    """Persist a job record and push its ID onto the FPGA's job queue."""
    await redis.set(keys.job(str(job.job_id)), job.model_dump_json())
    await redis.rpush(keys.fpga_queue(job.fpga_id), str(job.job_id))


async def dequeue_job(redis: Redis, fpga_id: int) -> str | None:
    """Pop and return the next job ID from an FPGA's queue, or None if empty."""
    value = await redis.lpop(keys.fpga_queue(fpga_id))
    return value.decode() if value else None


async def get_job(redis: Redis, job_id: UUID) -> Job | None:
    """Return a job record by ID, or None if not found."""
    value = await redis.get(keys.job(str(job_id)))
    return Job.model_validate_json(value) if value else None


async def update_job_status(
    redis: Redis, job_id: UUID, status: JobStatus
) -> None:
    """Update the status field of an existing job record.

    Raises:
        ValueError: If the job does not exist.
    """
    job = await get_job(redis, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job.status = status
    job.updated_at = datetime.now(timezone.utc)
    await redis.set(keys.job(str(job_id)), job.model_dump_json())


async def append_job_log(redis: Redis, job_id: UUID, text: str) -> None:
    """Append a line of text to a job's build log."""
    await redis.append(keys.job_log(str(job_id)), text)


async def get_job_log(redis: Redis, job_id: UUID) -> str:
    """Return the full build log for a job as a string."""
    value = await redis.get(keys.job_log(str(job_id)))
    return value.decode() if value else ""


async def set_job_result(redis: Redis, job_id: UUID, data: list[int]) -> None:
    """Persist the response data words from a completed run job."""
    import json
    await redis.set(keys.job_result(str(job_id)), json.dumps(data))


async def get_job_result(redis: Redis, job_id: UUID) -> list[int] | None:
    """Return the response data words from a completed run job, or None if not found."""
    import json
    value = await redis.get(keys.job_result(str(job_id)))
    return json.loads(value) if value else None
