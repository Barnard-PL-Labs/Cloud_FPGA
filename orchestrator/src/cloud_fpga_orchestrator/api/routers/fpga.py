import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as FPath, UploadFile
from redis.asyncio import Redis

from ...state import (
    FPGAState,
    Job,
    JobType,
    enqueue_job,
    get_fpga_state,
    get_session,
    transition_fpga_state,
)
from ...state.store import get_current_job
from ...state.models import JobStatus
from ..deps import get_api_key, get_redis, get_session_id
from ..models import (
    ErrorResponse,
    FPGASummary,
    RunRequest,
    RunResponse,
    SessionResponse,
    SubmitResponse,
)

router = APIRouter(tags=["fpga"])

FPGAId = Annotated[int, FPath(ge=0, le=9)]

_NUM_FPGAS = 10
_UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", tempfile.gettempdir())) / "cloud_fpga_uploads"


@router.get("/fpga", response_model=list[FPGASummary])
async def list_fpgas(
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
) -> list[FPGASummary]:
    """Return the current state and session info for all FPGA nodes."""
    summaries = []
    for fpga_id in range(_NUM_FPGAS):
        state = await get_fpga_state(redis, fpga_id)
        session = await get_session(redis, fpga_id)
        summaries.append(
            FPGASummary(
                fpga_id=fpga_id,
                state=state,
                session=SessionResponse(
                    session_id=session.session_id,
                    fpga_id=session.fpga_id,
                    owner=session.owner,
                    expires_at=session.expires_at,
                ) if session else None,
                current_job_id=await get_current_job(redis, fpga_id),
            )
        )
    return summaries


@router.get(
    "/fpga/{fpga_id}",
    response_model=FPGASummary,
    responses={404: {"model": ErrorResponse}},
)
async def get_fpga(
    fpga_id: FPGAId,
    redis: Redis = Depends(get_redis),
    _api_key: str | None = Depends(get_api_key),
) -> FPGASummary:
    """Return the current state and session info for a single FPGA."""
    state = await get_fpga_state(redis, fpga_id)
    session = await get_session(redis, fpga_id)
    return FPGASummary(
        fpga_id=fpga_id,
        state=state,
        session=SessionResponse(
            session_id=session.session_id,
            fpga_id=session.fpga_id,
            owner=session.owner,
            expires_at=session.expires_at,
        ) if session else None,
        current_job_id=await get_current_job(redis, fpga_id),
    )


@router.post(
    "/fpga/{fpga_id}/submit",
    response_model=SubmitResponse,
    status_code=202,
    responses={409: {"model": ErrorResponse}},
)
async def submit(
    fpga_id: FPGAId,
    file: UploadFile,
    redis: Redis = Depends(get_redis),
    api_key: str | None = Depends(get_api_key),
) -> SubmitResponse:
    """Accept an HDL source file, enqueue a build_and_program job, and return a job ID.

    The FPGA must be idle. The uploaded file is saved to the uploads
    directory; its path is passed to the worker via the job context.
    """
    state = await get_fpga_state(redis, fpga_id)
    if state != FPGAState.IDLE:
        raise HTTPException(
            status_code=409,
            detail={"error": "fpga_not_idle", "message": f"FPGA {fpga_id} is {state}, not idle."},
        )

    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    job = Job(fpga_id=fpga_id, type=JobType.BUILD_AND_PROGRAM)
    dest = _UPLOADS_DIR / f"{job.job_id}.py"
    dest.write_bytes(await file.read())

    job.context = {"source_path": str(dest), "owner": api_key or "anonymous"}

    await enqueue_job(redis, job)
    await transition_fpga_state(redis, fpga_id, FPGAState.QUEUED)

    return SubmitResponse(job_id=job.job_id, fpga_id=fpga_id, status=JobStatus.QUEUED)


@router.post(
    "/fpga/{fpga_id}/run",
    response_model=RunResponse,
    status_code=202,
    responses={409: {"model": ErrorResponse}},
)
async def run(
    fpga_id: FPGAId,
    body: RunRequest,
    redis: Redis = Depends(get_redis),
    api_key: str | None = Depends(get_api_key),
    session_id: str | None = Depends(get_session_id),
) -> RunResponse:
    """Enqueue a Wishbone run transaction for a reserved FPGA.

    The FPGA must be reserved and the caller must hold the active session.
    """
    state = await get_fpga_state(redis, fpga_id)
    if state != FPGAState.RESERVED:
        raise HTTPException(
            status_code=409,
            detail={"error": "fpga_not_reserved", "message": f"FPGA {fpga_id} is {state}, not reserved."},
        )

    job = Job(
        fpga_id=fpga_id,
        type=JobType.RUN,
        context={
            "op": body.op,
            "address": body.address,
            "data": body.data,
            "owner": api_key or "anonymous",
        },
    )
    await enqueue_job(redis, job)
    return RunResponse(job_id=job.job_id, fpga_id=fpga_id, status=JobStatus.QUEUED)


@router.post(
    "/fpga/{fpga_id}/reset",
    response_model=SubmitResponse,
    status_code=202,
    responses={409: {"model": ErrorResponse}},
)
async def reset(
    fpga_id: FPGAId,
    redis: Redis = Depends(get_redis),
    api_key: str | None = Depends(get_api_key),
    _session_id: str | None = Depends(get_session_id),
) -> SubmitResponse:
    """Enqueue a reset job to reflash the base LiteX SoC and return the FPGA to idle."""
    state = await get_fpga_state(redis, fpga_id)
    if state not in {FPGAState.RESERVED, FPGAState.ERROR}:
        raise HTTPException(
            status_code=409,
            detail={"error": "fpga_not_resettable", "message": f"FPGA {fpga_id} is {state} and cannot be reset."},
        )

    job = Job(
        fpga_id=fpga_id,
        type=JobType.RESET,
        context={"owner": api_key or "anonymous"},
    )
    await enqueue_job(redis, job)
    return SubmitResponse(job_id=job.job_id, fpga_id=fpga_id, status=JobStatus.QUEUED)
