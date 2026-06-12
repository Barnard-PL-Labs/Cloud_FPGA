from unittest.mock import AsyncMock, patch

import pytest

from cloud_fpga_orchestrator.compiler.errors import SynthesisError
from cloud_fpga_orchestrator.compiler.pipeline import BuildResult
from cloud_fpga_orchestrator.state.models import FPGAState, Job, JobStatus, JobType
from cloud_fpga_orchestrator.state.store import (
    create_session,
    enqueue_job,
    get_current_job,
    get_fpga_state,
    get_job,
    get_job_result,
    get_session,
    transition_fpga_state,
)
from cloud_fpga_orchestrator.workers.host_client import HostAgentError
from cloud_fpga_orchestrator.workers.jobs import (
    handle_build_and_program,
    handle_reset,
    handle_run,
)
from cloud_fpga_orchestrator.workers.protocol import ResponseStatus, WishboneResponse


@pytest.fixture
def mock_host():
    host = AsyncMock()
    host.flash = AsyncMock(return_value=None)
    host.run = AsyncMock(
        return_value=WishboneResponse(status=ResponseStatus.OK, data=[])
    )
    host.reset = AsyncMock(return_value=None)
    return host


async def _put_fpga_in_reserved(redis_client, fpga_id: int) -> None:
    await transition_fpga_state(redis_client, fpga_id, FPGAState.QUEUED)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.BUILDING)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.PROGRAMMING)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.RESERVED)


class TestHandleBuildAndProgram:
    async def test_success_reaches_reserved(self, redis_client, mock_host, tmp_path):
        source = tmp_path / "design.py"
        source.write_text("# design")
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        assert await get_fpga_state(redis_client, 0) == FPGAState.RESERVED

    async def test_success_creates_session(self, redis_client, mock_host, tmp_path):
        source = tmp_path / "design.py"
        source.write_text("# design")
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        session = await get_session(redis_client, 0)
        assert session is not None
        assert session.owner == "alice"

    async def test_success_marks_job_complete(self, redis_client, mock_host, tmp_path):
        source = tmp_path / "design.py"
        source.write_text("# design")
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.COMPLETE

    async def test_success_clears_current_job(self, redis_client, mock_host, tmp_path):
        source = tmp_path / "design.py"
        source.write_text("# design")
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        assert await get_current_job(redis_client, 0) is None

    async def test_build_error_returns_to_idle(self, redis_client, mock_host, tmp_path):
        source = tmp_path / "bad.py"
        source.write_text("# bad")

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            side_effect=SynthesisError("synthesize", "yosys crashed", "error output"),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        assert await get_fpga_state(redis_client, 0) == FPGAState.IDLE

    async def test_build_error_marks_job_failed(
        self, redis_client, mock_host, tmp_path
    ):
        source = tmp_path / "bad.py"
        source.write_text("# bad")

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            side_effect=SynthesisError("synthesize", "yosys crashed", "error output"),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.FAILED

    async def test_flash_error_marks_state_error(
        self, redis_client, mock_host, tmp_path
    ):
        source = tmp_path / "design.py"
        source.write_text("# design")
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        mock_host.flash = AsyncMock(
            side_effect=HostAgentError("/flash", 500, "JTAG failed")
        )

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        assert await get_fpga_state(redis_client, 0) == FPGAState.ERROR

    async def test_flash_error_marks_job_failed(
        self, redis_client, mock_host, tmp_path
    ):
        source = tmp_path / "design.py"
        source.write_text("# design")
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        mock_host.flash = AsyncMock(
            side_effect=HostAgentError("/flash", 500, "JTAG failed")
        )

        job = Job(
            fpga_id=0,
            type=JobType.BUILD_AND_PROGRAM,
            context={"source_path": str(source), "owner": "alice"},
        )
        await enqueue_job(redis_client, job)
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            await handle_build_and_program(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.FAILED


class TestHandleRun:
    async def test_success_stores_result(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 1)
        mock_host.run = AsyncMock(
            return_value=WishboneResponse(status=ResponseStatus.OK, data=[0x42, 0xFF])
        )

        job = Job(
            fpga_id=1,
            type=JobType.RUN,
            context={"op": 2, "address": 0x1000, "data": []},
        )
        await enqueue_job(redis_client, job)
        await handle_run(redis_client, mock_host, job)

        result = await get_job_result(redis_client, job.job_id)
        assert result == [0x42, 0xFF]

    async def test_success_marks_job_complete(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 1)

        job = Job(
            fpga_id=1,
            type=JobType.RUN,
            context={"op": 2, "address": 0x1000, "data": []},
        )
        await enqueue_job(redis_client, job)
        await handle_run(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.COMPLETE

    async def test_success_clears_current_job(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 1)

        job = Job(
            fpga_id=1,
            type=JobType.RUN,
            context={"op": 2, "address": 0x1000, "data": []},
        )
        await enqueue_job(redis_client, job)
        await handle_run(redis_client, mock_host, job)

        assert await get_current_job(redis_client, 1) is None

    async def test_host_error_marks_job_failed(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 1)
        mock_host.run = AsyncMock(
            side_effect=HostAgentError("/run", 500, "TCP timeout")
        )

        job = Job(
            fpga_id=1,
            type=JobType.RUN,
            context={"op": 2, "address": 0x1000, "data": []},
        )
        await enqueue_job(redis_client, job)
        await handle_run(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.FAILED

    async def test_success_renews_session(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 1)
        await create_session(redis_client, 1, "alice", 3600)

        job = Job(
            fpga_id=1,
            type=JobType.RUN,
            context={"op": 2, "address": 0x1000, "data": []},
        )
        await enqueue_job(redis_client, job)
        await handle_run(redis_client, mock_host, job)

        renewed_session = await get_session(redis_client, 1)
        assert renewed_session is not None
        assert renewed_session.owner == "alice"


class TestHandleReset:
    async def test_success_returns_fpga_to_idle(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 2)

        job = Job(fpga_id=2, type=JobType.RESET, context={})
        await enqueue_job(redis_client, job)
        await handle_reset(redis_client, mock_host, job)

        assert await get_fpga_state(redis_client, 2) == FPGAState.IDLE

    async def test_success_destroys_session(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 2)
        await create_session(redis_client, 2, "bob", 3600)

        job = Job(fpga_id=2, type=JobType.RESET, context={})
        await enqueue_job(redis_client, job)
        await handle_reset(redis_client, mock_host, job)

        assert await get_session(redis_client, 2) is None

    async def test_success_marks_job_complete(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 2)

        job = Job(fpga_id=2, type=JobType.RESET, context={})
        await enqueue_job(redis_client, job)
        await handle_reset(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.COMPLETE

    async def test_host_error_marks_state_error(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 2)
        mock_host.reset = AsyncMock(
            side_effect=HostAgentError("/reset", 500, "JTAG stuck")
        )

        job = Job(fpga_id=2, type=JobType.RESET, context={})
        await enqueue_job(redis_client, job)
        await handle_reset(redis_client, mock_host, job)

        assert await get_fpga_state(redis_client, 2) == FPGAState.ERROR

    async def test_host_error_marks_job_failed(self, redis_client, mock_host):
        await _put_fpga_in_reserved(redis_client, 2)
        mock_host.reset = AsyncMock(
            side_effect=HostAgentError("/reset", 500, "JTAG stuck")
        )

        job = Job(fpga_id=2, type=JobType.RESET, context={})
        await enqueue_job(redis_client, job)
        await handle_reset(redis_client, mock_host, job)

        updated = await get_job(redis_client, job.job_id)
        assert updated.status == JobStatus.FAILED
