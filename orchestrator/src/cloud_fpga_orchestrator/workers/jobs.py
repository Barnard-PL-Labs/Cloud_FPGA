import asyncio
import os
import tempfile
from pathlib import Path

from redis.asyncio import Redis

from ..compiler import BuildError, run_pipeline
from ..state import (
    FPGAState,
    Job,
    JobStatus,
    create_session,
    delete_session,
    get_session,
    transition_fpga_state,
    update_job_status,
)
from ..state.store import append_job_log, clear_current_job, set_current_job, set_job_result
from .host_client import HostAgentError, HostClient
from .protocol import WishboneOp, WishboneRequest

_SESSION_TTL: int = int(os.environ.get("SESSION_TTL_SECONDS", "3600"))


async def handle_build_and_program(
    redis: Redis, host: HostClient, job: Job
) -> None:
    """Run the full compile and flash pipeline for a build_and_program job.

    Drives the FPGA through queued → building → programming → reserved on
    success, or back to idle on build failure, or error on JTAG failure.

    Args:
        redis: Active Redis connection.
        host: Host agent client for flash operations.
        job: The job record. Must have context["source_path"] and context["owner"].
    """
    await set_current_job(redis, job.fpga_id, job.job_id)
    await transition_fpga_state(redis, job.fpga_id, FPGAState.BUILDING)
    await update_job_status(redis, job.job_id, JobStatus.RUNNING)

    source_path = Path(job.context["source_path"])

    with tempfile.TemporaryDirectory() as work_dir:
        try:
            result = await asyncio.to_thread(
                run_pipeline, source_path, Path(work_dir)
            )
        except BuildError as exc:
            await append_job_log(redis, job.job_id, exc.log)
            await update_job_status(redis, job.job_id, JobStatus.FAILED)
            await transition_fpga_state(redis, job.fpga_id, FPGAState.IDLE)
            await clear_current_job(redis, job.fpga_id)
            return

        for stage, log in result.logs.items():
            if log:
                await append_job_log(redis, job.job_id, f"[{stage}]\n{log}\n")

        await transition_fpga_state(redis, job.fpga_id, FPGAState.PROGRAMMING)

        try:
            await host.flash(job.fpga_id, result.bitstream_path)
        except HostAgentError as exc:
            await append_job_log(redis, job.job_id, str(exc))
            await update_job_status(redis, job.job_id, JobStatus.FAILED)
            await transition_fpga_state(redis, job.fpga_id, FPGAState.ERROR)
            await clear_current_job(redis, job.fpga_id)
            return

    await transition_fpga_state(redis, job.fpga_id, FPGAState.RESERVED)
    await create_session(redis, job.fpga_id, job.context["owner"], _SESSION_TTL)
    await update_job_status(redis, job.job_id, JobStatus.COMPLETE)
    await clear_current_job(redis, job.fpga_id)


async def handle_run(redis: Redis, host: HostClient, job: Job) -> None:
    """Send a Wishbone transaction to the FPGA and store the result.

    The FPGA state does not change on a run job regardless of outcome.
    On success the session TTL is renewed. The response data is written
    to Redis for the API to retrieve.

    Args:
        redis: Active Redis connection.
        host: Host agent client for run operations.
        job: The job record. Must have context["op"], context["address"],
             and optionally context["data"].
    """
    await set_current_job(redis, job.fpga_id, job.job_id)
    await update_job_status(redis, job.job_id, JobStatus.RUNNING)

    request = WishboneRequest(
        op=WishboneOp(job.context["op"]),
        address=job.context["address"],
        data=job.context.get("data", []),
    )

    try:
        response = await host.run(job.fpga_id, request)
    except HostAgentError as exc:
        await append_job_log(redis, job.job_id, str(exc))
        await update_job_status(redis, job.job_id, JobStatus.FAILED)
        await clear_current_job(redis, job.fpga_id)
        return

    await set_job_result(redis, job.job_id, response.data)
    await update_job_status(redis, job.job_id, JobStatus.COMPLETE)
    await clear_current_job(redis, job.fpga_id)

    session = await get_session(redis, job.fpga_id)
    if session:
        await create_session(redis, job.fpga_id, session.owner, _SESSION_TTL)


async def handle_reset(redis: Redis, host: HostClient, job: Job) -> None:
    """Reflash the base LiteX SoC and return the FPGA to idle.

    Drives the FPGA to idle on success, or error if the JTAG reset fails.
    Always destroys the active session regardless of outcome.

    Args:
        redis: Active Redis connection.
        host: Host agent client for reset operations.
        job: The job record. No additional context required.
    """
    await set_current_job(redis, job.fpga_id, job.job_id)
    await update_job_status(redis, job.job_id, JobStatus.RUNNING)

    try:
        await host.reset(job.fpga_id)
    except HostAgentError as exc:
        await append_job_log(redis, job.job_id, str(exc))
        await update_job_status(redis, job.job_id, JobStatus.FAILED)
        await transition_fpga_state(redis, job.fpga_id, FPGAState.ERROR)
        await clear_current_job(redis, job.fpga_id)
        return

    await delete_session(redis, job.fpga_id)
    await transition_fpga_state(redis, job.fpga_id, FPGAState.IDLE)
    await update_job_status(redis, job.job_id, JobStatus.COMPLETE)
    await clear_current_job(redis, job.fpga_id)
