from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ..state.models import FPGAState, JobStatus, JobType


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Payload for POST /fpga/{id}/run."""

    op: int = Field(description="Wishbone opcode: 1 = write, 2 = read")
    address: int = Field(description="Wishbone byte address")
    data: list[int] = Field(default_factory=list, description="32-bit data words (write only)")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    """Active session information for an FPGA."""

    session_id: UUID
    fpga_id: int
    owner: str
    expires_at: datetime


class JobResponse(BaseModel):
    """Status and metadata for a single job."""

    job_id: UUID
    fpga_id: int
    type: JobType
    status: JobStatus
    created_at: datetime
    updated_at: datetime


class FPGASummary(BaseModel):
    """State snapshot for a single FPGA node."""

    fpga_id: int
    state: FPGAState
    session: SessionResponse | None
    current_job_id: UUID | None


class SubmitResponse(BaseModel):
    """Returned on a successful POST /fpga/{id}/submit (HTTP 202)."""

    job_id: UUID
    fpga_id: int
    status: JobStatus = JobStatus.QUEUED


class RunResponse(BaseModel):
    """Returned on a successful POST /fpga/{id}/run (HTTP 202)."""

    job_id: UUID
    fpga_id: int
    status: JobStatus = JobStatus.QUEUED


class RunResultResponse(BaseModel):
    """Result data available once a run job completes."""

    ok: bool
    data: list[int]


class HealthResponse(BaseModel):
    """System health snapshot."""

    status: str
    redis: bool


class ErrorResponse(BaseModel):
    """Standard error envelope returned on all non-2xx responses."""

    error: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable description")
    job_id: UUID | None = None
