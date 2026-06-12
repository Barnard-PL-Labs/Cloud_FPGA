import pytest
from datetime import datetime, timezone, timedelta
from uuid import UUID

from cloud_fpga_orchestrator.state.models import (
    FPGARecord,
    FPGAState,
    Job,
    JobStatus,
    JobType,
    Session,
    VALID_TRANSITIONS,
)


class TestValidTransitions:
    def test_all_states_have_entry(self):
        assert set(VALID_TRANSITIONS.keys()) == set(FPGAState)

    def test_all_targets_are_valid_states(self):
        all_states = set(FPGAState)
        for targets in VALID_TRANSITIONS.values():
            assert targets <= all_states

    def test_idle_only_to_queued(self):
        assert VALID_TRANSITIONS[FPGAState.IDLE] == {FPGAState.QUEUED}

    def test_queued_to_building_or_idle(self):
        assert VALID_TRANSITIONS[FPGAState.QUEUED] == {FPGAState.BUILDING, FPGAState.IDLE}

    def test_building_to_programming_or_idle(self):
        assert VALID_TRANSITIONS[FPGAState.BUILDING] == {FPGAState.PROGRAMMING, FPGAState.IDLE}

    def test_programming_to_reserved_or_error(self):
        assert VALID_TRANSITIONS[FPGAState.PROGRAMMING] == {FPGAState.RESERVED, FPGAState.ERROR}

    def test_reserved_can_self_transition(self):
        assert FPGAState.RESERVED in VALID_TRANSITIONS[FPGAState.RESERVED]

    def test_error_only_to_idle(self):
        assert VALID_TRANSITIONS[FPGAState.ERROR] == {FPGAState.IDLE}

    def test_idle_cannot_skip_to_building(self):
        assert FPGAState.BUILDING not in VALID_TRANSITIONS[FPGAState.IDLE]

    def test_error_cannot_go_to_queued(self):
        assert FPGAState.QUEUED not in VALID_TRANSITIONS[FPGAState.ERROR]


class TestFPGARecord:
    def test_defaults(self):
        r = FPGARecord(fpga_id=3)
        assert r.state == FPGAState.IDLE
        assert r.session_id is None
        assert r.current_job_id is None

    def test_fpga_id_stored(self):
        r = FPGARecord(fpga_id=7)
        assert r.fpga_id == 7


class TestJob:
    def test_defaults(self):
        job = Job(fpga_id=0, type=JobType.RUN)
        assert job.status == JobStatus.QUEUED
        assert isinstance(job.job_id, UUID)
        assert job.context == {}

    def test_created_at_is_utc(self):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        assert job.created_at.tzinfo is not None

    def test_each_job_gets_unique_id(self):
        a = Job(fpga_id=0, type=JobType.RESET)
        b = Job(fpga_id=0, type=JobType.RESET)
        assert a.job_id != b.job_id

    def test_context_stored(self):
        ctx = {"source_path": "/tmp/x.py", "owner": "alice"}
        job = Job(fpga_id=1, type=JobType.BUILD_AND_PROGRAM, context=ctx)
        assert job.context == ctx


class TestSession:
    def test_unique_session_ids(self):
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        a = Session(fpga_id=0, owner="alice", expires_at=expires)
        b = Session(fpga_id=0, owner="alice", expires_at=expires)
        assert a.session_id != b.session_id

    def test_fields_stored(self):
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        s = Session(fpga_id=5, owner="bob", expires_at=expires)
        assert s.fpga_id == 5
        assert s.owner == "bob"
        assert s.expires_at == expires
