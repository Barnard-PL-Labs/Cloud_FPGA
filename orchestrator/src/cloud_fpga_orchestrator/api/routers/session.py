from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from redis.asyncio import Redis

from ...state import Job, JobType, enqueue_job, get_session
from ...state.models import JobStatus
from ..deps import get_api_key, get_redis, get_session_id
from ..models import ErrorResponse, SessionResponse, SubmitResponse

router = APIRouter(prefix="/fpga/{fpga_id}", tags=["session"])

FPGAId = Annotated[int, Path(ge=0, le=9)]


@router.get(
    "/session",
    response_model=SessionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_session_info(
    fpga_id: FPGAId,
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
    _session_id: str | None = Depends(get_session_id),
) -> SessionResponse:
    """Return the active session for an FPGA, including remaining TTL."""
    session = await get_session(redis, fpga_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_active_session", "message": f"FPGA {fpga_id} has no active session."},
        )
    return SessionResponse(
        session_id=session.session_id,
        fpga_id=session.fpga_id,
        owner=session.owner,
        expires_at=session.expires_at,
    )


@router.post(
    "/session/release",
    response_model=SubmitResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}},
)
async def release_session(
    fpga_id: FPGAId,
    redis: Redis = Depends(get_redis),
    api_key: str | None = Depends(get_api_key),
    _session_id: str | None = Depends(get_session_id),
) -> SubmitResponse:
    """Release an FPGA session by enqueuing a reset job.

    The FPGA returns to idle once the reset job completes.
    """
    session = await get_session(redis, fpga_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_active_session", "message": f"FPGA {fpga_id} has no active session."},
        )
    job = Job(
        fpga_id=fpga_id,
        type=JobType.RESET,
        context={"owner": api_key or "anonymous"},
    )
    await enqueue_job(redis, job)
    return SubmitResponse(job_id=job.job_id, fpga_id=fpga_id, status=JobStatus.QUEUED)
