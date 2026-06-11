from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from redis.asyncio import Redis

from ...state import get_job, get_job_log, update_job_status
from ...state import keys
from ...state.models import JobStatus
from ...state.store import get_job_result
from ..deps import get_api_key, get_redis, get_session_id
from ..models import ErrorResponse, JobResponse, RunResultResponse

router = APIRouter(prefix="/fpga/{fpga_id}/jobs", tags=["jobs"])

FPGAId = Annotated[int, Path(ge=0, le=9)]


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_job_status(
    fpga_id: FPGAId,
    job_id: UUID,
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
) -> JobResponse:
    """Return the current status and metadata for a job."""
    job = await get_job(redis, job_id)
    if job is None or job.fpga_id != fpga_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "job_not_found", "message": f"Job {job_id} not found for FPGA {fpga_id}."},
        )
    return JobResponse(
        job_id=job.job_id,
        fpga_id=job.fpga_id,
        type=job.type,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get(
    "/{job_id}/logs",
    response_model=str,
    responses={404: {"model": ErrorResponse}},
)
async def get_logs(
    fpga_id: FPGAId,
    job_id: UUID,
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
) -> str:
    """Return the full build log for a job."""
    job = await get_job(redis, job_id)
    if job is None or job.fpga_id != fpga_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "job_not_found", "message": f"Job {job_id} not found for FPGA {fpga_id}."},
        )
    return await get_job_log(redis, job_id)


@router.get(
    "/{job_id}/result",
    response_model=RunResultResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_run_result(
    fpga_id: FPGAId,
    job_id: UUID,
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
) -> RunResultResponse:
    """Return the Wishbone response data from a completed run job."""
    job = await get_job(redis, job_id)
    if job is None or job.fpga_id != fpga_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "job_not_found", "message": f"Job {job_id} not found for FPGA {fpga_id}."},
        )
    if job.status != JobStatus.COMPLETE:
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_complete", "message": f"Job {job_id} is not yet complete."},
        )
    data = await get_job_result(redis, job_id)
    return RunResultResponse(ok=data is not None, data=data or [])


@router.delete(
    "/{job_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def cancel_job(
    fpga_id: FPGAId,
    job_id: UUID,
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
) -> None:
    """Cancel a queued job before the worker picks it up.

    Only jobs in QUEUED status can be cancelled. Returns 409 if the job
    has already started.
    """
    job = await get_job(redis, job_id)
    if job is None or job.fpga_id != fpga_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "job_not_found", "message": f"Job {job_id} not found for FPGA {fpga_id}."},
        )
    if job.status != JobStatus.QUEUED:
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_cancellable", "message": f"Job {job_id} is {job.status} and cannot be cancelled."},
        )
    await redis.lrem(keys.fpga_queue(fpga_id), 0, str(job_id))
    await update_job_status(redis, job_id, JobStatus.CANCELLED)
