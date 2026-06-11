from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class FPGAState(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    BUILDING = "building"
    PROGRAMMING = "programming"
    RESERVED = "reserved"
    ERROR = "error"


class JobType(StrEnum):
    BUILD_AND_PROGRAM = "build_and_program"
    RUN = "run"
    RESET = "reset"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid state transitions derived from the design doc state machine.
# Key: current state. Value: set of states it may transition to.
VALID_TRANSITIONS: dict[FPGAState, set[FPGAState]] = {
    FPGAState.IDLE: {FPGAState.QUEUED},
    FPGAState.QUEUED: {FPGAState.BUILDING, FPGAState.IDLE},
    FPGAState.BUILDING: {FPGAState.PROGRAMMING, FPGAState.IDLE},
    FPGAState.PROGRAMMING: {FPGAState.RESERVED, FPGAState.ERROR},
    FPGAState.RESERVED: {FPGAState.IDLE, FPGAState.ERROR, FPGAState.RESERVED},
    FPGAState.ERROR: {FPGAState.IDLE},
}


class Session(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    fpga_id: int
    owner: str
    expires_at: datetime


class Job(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    fpga_id: int
    type: JobType
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class FPGARecord(BaseModel):
    fpga_id: int  # 0–9
    state: FPGAState = FPGAState.IDLE
    session_id: UUID | None = None
    current_job_id: UUID | None = None
