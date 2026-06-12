import pytest
from uuid import uuid4

from cloud_fpga_orchestrator.state.models import FPGAState, Job, JobStatus, JobType
from cloud_fpga_orchestrator.state.store import (
    append_job_log,
    clear_current_job,
    create_session,
    delete_session,
    dequeue_job,
    enqueue_job,
    get_current_job,
    get_fpga_state,
    get_job,
    get_job_log,
    get_job_result,
    get_session,
    set_current_job,
    set_job_result,
    transition_fpga_state,
    update_job_status,
)


class TestFPGAState:
    async def test_unset_defaults_to_idle(self, redis_client):
        assert await get_fpga_state(redis_client, 0) == FPGAState.IDLE

    async def test_valid_transition_persisted(self, redis_client):
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)
        assert await get_fpga_state(redis_client, 0) == FPGAState.QUEUED

    async def test_invalid_transition_raises(self, redis_client):
        with pytest.raises(ValueError, match="Invalid transition"):
            await transition_fpga_state(redis_client, 0, FPGAState.BUILDING)

    async def test_full_happy_path_chain(self, redis_client):
        await transition_fpga_state(redis_client, 1, FPGAState.QUEUED)
        await transition_fpga_state(redis_client, 1, FPGAState.BUILDING)
        await transition_fpga_state(redis_client, 1, FPGAState.PROGRAMMING)
        await transition_fpga_state(redis_client, 1, FPGAState.RESERVED)
        assert await get_fpga_state(redis_client, 1) == FPGAState.RESERVED

    async def test_error_recovery_to_idle(self, redis_client):
        await transition_fpga_state(redis_client, 2, FPGAState.QUEUED)
        await transition_fpga_state(redis_client, 2, FPGAState.BUILDING)
        await transition_fpga_state(redis_client, 2, FPGAState.PROGRAMMING)
        await transition_fpga_state(redis_client, 2, FPGAState.ERROR)
        await transition_fpga_state(redis_client, 2, FPGAState.IDLE)
        assert await get_fpga_state(redis_client, 2) == FPGAState.IDLE

    async def test_different_fpgas_independent(self, redis_client):
        await transition_fpga_state(redis_client, 3, FPGAState.QUEUED)
        # FPGA 4 is untouched and still IDLE
        assert await get_fpga_state(redis_client, 4) == FPGAState.IDLE


class TestSessions:
    async def test_no_session_returns_none(self, redis_client):
        assert await get_session(redis_client, 0) is None

    async def test_create_and_retrieve(self, redis_client):
        session = await create_session(redis_client, 0, "alice", 3600)
        retrieved = await get_session(redis_client, 0)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id
        assert retrieved.owner == "alice"
        assert retrieved.fpga_id == 0

    async def test_delete_removes_session(self, redis_client):
        await create_session(redis_client, 0, "alice", 3600)
        await delete_session(redis_client, 0)
        assert await get_session(redis_client, 0) is None

    async def test_overwrite_session(self, redis_client):
        await create_session(redis_client, 0, "alice", 3600)
        new_session = await create_session(redis_client, 0, "bob", 3600)
        retrieved = await get_session(redis_client, 0)
        assert retrieved.owner == "bob"
        assert retrieved.session_id == new_session.session_id


class TestJobs:
    async def test_enqueue_and_dequeue_fifo(self, redis_client):
        job_a = Job(fpga_id=0, type=JobType.RUN)
        job_b = Job(fpga_id=0, type=JobType.RESET)
        await enqueue_job(redis_client, job_a)
        await enqueue_job(redis_client, job_b)

        first = await dequeue_job(redis_client, 0)
        second = await dequeue_job(redis_client, 0)
        assert first == str(job_a.job_id)
        assert second == str(job_b.job_id)

    async def test_dequeue_empty_returns_none(self, redis_client):
        assert await dequeue_job(redis_client, 9) is None

    async def test_get_job_not_found_returns_none(self, redis_client):
        assert await get_job(redis_client, uuid4()) is None

    async def test_get_job_returns_record(self, redis_client):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        retrieved = await get_job(redis_client, job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id
        assert retrieved.type == JobType.BUILD_AND_PROGRAM

    async def test_update_job_status(self, redis_client):
        job = Job(fpga_id=0, type=JobType.RESET)
        await enqueue_job(redis_client, job)
        await update_job_status(redis_client, job.job_id, JobStatus.RUNNING)
        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.RUNNING

    async def test_update_missing_job_raises(self, redis_client):
        with pytest.raises(ValueError, match="not found"):
            await update_job_status(redis_client, uuid4(), JobStatus.COMPLETE)

    async def test_update_job_bumps_updated_at(self, redis_client):
        job = Job(fpga_id=0, type=JobType.RUN)
        await enqueue_job(redis_client, job)
        original_updated_at = (await get_job(redis_client, job.job_id)).updated_at
        await update_job_status(redis_client, job.job_id, JobStatus.COMPLETE)
        new_updated_at = (await get_job(redis_client, job.job_id)).updated_at
        assert new_updated_at >= original_updated_at


class TestJobLogs:
    async def test_missing_log_returns_empty_string(self, redis_client):
        assert await get_job_log(redis_client, uuid4()) == ""

    async def test_append_and_retrieve(self, redis_client):
        job_id = uuid4()
        await append_job_log(redis_client, job_id, "line one\n")
        await append_job_log(redis_client, job_id, "line two\n")
        log = await get_job_log(redis_client, job_id)
        assert "line one\n" in log
        assert "line two\n" in log

    async def test_multiple_appends_concatenated(self, redis_client):
        job_id = uuid4()
        await append_job_log(redis_client, job_id, "a")
        await append_job_log(redis_client, job_id, "b")
        await append_job_log(redis_client, job_id, "c")
        assert await get_job_log(redis_client, job_id) == "abc"


class TestJobResults:
    async def test_missing_result_returns_none(self, redis_client):
        assert await get_job_result(redis_client, uuid4()) is None

    async def test_set_and_get(self, redis_client):
        job_id = uuid4()
        await set_job_result(redis_client, job_id, [0xDEAD, 0xBEEF])
        result = await get_job_result(redis_client, job_id)
        assert result == [0xDEAD, 0xBEEF]

    async def test_empty_result_list(self, redis_client):
        job_id = uuid4()
        await set_job_result(redis_client, job_id, [])
        assert await get_job_result(redis_client, job_id) == []


class TestCurrentJob:
    async def test_no_current_job_returns_none(self, redis_client):
        assert await get_current_job(redis_client, 0) is None

    async def test_set_and_get(self, redis_client):
        job_id = uuid4()
        await set_current_job(redis_client, 0, job_id)
        assert await get_current_job(redis_client, 0) == job_id

    async def test_clear_removes_entry(self, redis_client):
        job_id = uuid4()
        await set_current_job(redis_client, 0, job_id)
        await clear_current_job(redis_client, 0)
        assert await get_current_job(redis_client, 0) is None

    async def test_overwrite_current_job(self, redis_client):
        first = uuid4()
        second = uuid4()
        await set_current_job(redis_client, 0, first)
        await set_current_job(redis_client, 0, second)
        assert await get_current_job(redis_client, 0) == second
