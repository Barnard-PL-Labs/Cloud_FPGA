"""End-to-end tests for the full job lifecycle.

Each test runs against a real Redis instance (testcontainers) and a live
run_worker loop (background asyncio task). The host agent is replaced with
an AsyncMock so tests don't require physical FPGA hardware. The compiler
pipeline is patched where needed since the build toolchain (Yosys, etc.)
is not available in CI.

Flow under test:
    POST /fpga/{id}/submit|run|reset  →  Redis queue
        →  run_worker picks up job
        →  handler executes (mock host agent)
        →  Redis state updated
        →  GET /fpga/{id}/jobs/{id} reflects final status
"""

import asyncio
from unittest.mock import AsyncMock, patch

from cloud_fpga_orchestrator.compiler.errors import SynthesisError
from cloud_fpga_orchestrator.compiler.pipeline import BuildResult
from cloud_fpga_orchestrator.state.models import FPGAState
from cloud_fpga_orchestrator.state.store import create_session, transition_fpga_state
from cloud_fpga_orchestrator.workers.host_client import HostAgentError
from cloud_fpga_orchestrator.workers.protocol import ResponseStatus, WishboneResponse


async def _wait_for_job_status(
    app_client, fpga_id: int, job_id: str, target: str, timeout: float = 5.0
) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        resp = await app_client.get(f"/fpga/{fpga_id}/jobs/{job_id}")
        body = resp.json()
        if body["status"] == target:
            return body
        if loop.time() > deadline:
            raise TimeoutError(
                f"Job {job_id} did not reach '{target}' within {timeout}s "
                f"(current: {body['status']})"
            )
        await asyncio.sleep(0.05)


async def _put_fpga_in_reserved(redis_client, fpga_id: int) -> None:
    await transition_fpga_state(redis_client, fpga_id, FPGAState.QUEUED)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.BUILDING)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.PROGRAMMING)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.RESERVED)


class TestBuildAndProgramFlow:
    async def test_successful_build_job_reaches_complete(
        self, app_client, worker, tmp_path
    ):
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            resp = await app_client.post(
                "/fpga/0/submit",
                files={"file": ("design.py", b"# design", "text/plain")},
            )
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]
            await _wait_for_job_status(app_client, 0, job_id, "complete")

    async def test_successful_build_leaves_fpga_reserved(
        self, app_client, worker, tmp_path
    ):
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            resp = await app_client.post(
                "/fpga/0/submit",
                files={"file": ("design.py", b"# design", "text/plain")},
            )
            job_id = resp.json()["job_id"]
            await _wait_for_job_status(app_client, 0, job_id, "complete")

        fpga = await app_client.get("/fpga/0")
        assert fpga.json()["state"] == "reserved"

    async def test_successful_build_creates_session_for_owner(
        self, app_client, worker, tmp_path
    ):
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            resp = await app_client.post(
                "/fpga/0/submit",
                headers={"X-API-Key": "alice"},
                files={"file": ("design.py", b"# design", "text/plain")},
            )
            job_id = resp.json()["job_id"]
            await _wait_for_job_status(app_client, 0, job_id, "complete")

        session = await app_client.get("/fpga/0/session")
        assert session.status_code == 200
        assert session.json()["owner"] == "alice"

    async def test_build_failure_marks_job_failed(self, app_client, worker):
        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            side_effect=SynthesisError("synthesize", "yosys crashed", "error log"),
        ):
            resp = await app_client.post(
                "/fpga/0/submit",
                files={"file": ("design.py", b"# bad design", "text/plain")},
            )
            job_id = resp.json()["job_id"]
            await _wait_for_job_status(app_client, 0, job_id, "failed")

    async def test_build_failure_returns_fpga_to_idle(self, app_client, worker):
        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            side_effect=SynthesisError("synthesize", "yosys crashed", "error log"),
        ):
            resp = await app_client.post(
                "/fpga/0/submit",
                files={"file": ("design.py", b"# bad design", "text/plain")},
            )
            job_id = resp.json()["job_id"]
            await _wait_for_job_status(app_client, 0, job_id, "failed")

        fpga = await app_client.get("/fpga/0")
        assert fpga.json()["state"] == "idle"

    async def test_host_flash_error_marks_fpga_error(
        self, app_client, mock_host, worker, tmp_path
    ):
        fake_bit = tmp_path / "out.bit"
        fake_bit.write_bytes(b"\xff" * 4)
        mock_host.flash = AsyncMock(
            side_effect=HostAgentError("/flash", 500, "JTAG failed")
        )

        with patch(
            "cloud_fpga_orchestrator.workers.jobs.run_pipeline",
            return_value=BuildResult(bitstream_path=fake_bit, logs={}),
        ):
            resp = await app_client.post(
                "/fpga/0/submit",
                files={"file": ("design.py", b"# design", "text/plain")},
            )
            job_id = resp.json()["job_id"]
            await _wait_for_job_status(app_client, 0, job_id, "failed")

        fpga = await app_client.get("/fpga/0")
        assert fpga.json()["state"] == "error"


class TestRunFlow:
    async def test_run_job_result_retrievable_via_api(
        self, app_client, redis_client, mock_host, worker
    ):
        await _put_fpga_in_reserved(redis_client, 0)
        mock_host.run = AsyncMock(
            return_value=WishboneResponse(
                status=ResponseStatus.OK, data=[0xDEAD, 0xBEEF]
            )
        )

        resp = await app_client.post(
            "/fpga/0/run", json={"op": 2, "address": 0x1000, "data": []}
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        await _wait_for_job_status(app_client, 0, job_id, "complete")

        result = await app_client.get(f"/fpga/0/jobs/{job_id}/result")
        assert result.status_code == 200
        assert result.json()["data"] == [0xDEAD, 0xBEEF]

    async def test_run_job_marks_complete(
        self, app_client, redis_client, worker
    ):
        await _put_fpga_in_reserved(redis_client, 0)

        resp = await app_client.post(
            "/fpga/0/run", json={"op": 2, "address": 0x1000, "data": []}
        )
        job_id = resp.json()["job_id"]
        await _wait_for_job_status(app_client, 0, job_id, "complete")

    async def test_run_host_error_marks_job_failed(
        self, app_client, redis_client, mock_host, worker
    ):
        await _put_fpga_in_reserved(redis_client, 0)
        mock_host.run = AsyncMock(
            side_effect=HostAgentError("/run", 500, "TCP timeout")
        )

        resp = await app_client.post(
            "/fpga/0/run", json={"op": 2, "address": 0x1000, "data": []}
        )
        job_id = resp.json()["job_id"]
        await _wait_for_job_status(app_client, 0, job_id, "failed")


class TestResetFlow:
    async def test_reset_returns_fpga_to_idle(
        self, app_client, redis_client, worker
    ):
        await _put_fpga_in_reserved(redis_client, 0)

        resp = await app_client.post("/fpga/0/reset")
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        await _wait_for_job_status(app_client, 0, job_id, "complete")

        fpga = await app_client.get("/fpga/0")
        assert fpga.json()["state"] == "idle"

    async def test_reset_destroys_session(
        self, app_client, redis_client, worker
    ):
        await _put_fpga_in_reserved(redis_client, 0)
        await create_session(redis_client, 0, "bob", 3600)

        resp = await app_client.post("/fpga/0/reset")
        job_id = resp.json()["job_id"]
        await _wait_for_job_status(app_client, 0, job_id, "complete")

        session = await app_client.get("/fpga/0/session")
        assert session.status_code == 404

    async def test_reset_host_error_marks_fpga_error(
        self, app_client, redis_client, mock_host, worker
    ):
        await _put_fpga_in_reserved(redis_client, 0)
        mock_host.reset = AsyncMock(
            side_effect=HostAgentError("/reset", 500, "JTAG stuck")
        )

        resp = await app_client.post("/fpga/0/reset")
        job_id = resp.json()["job_id"]
        await _wait_for_job_status(app_client, 0, job_id, "failed")

        fpga = await app_client.get("/fpga/0")
        assert fpga.json()["state"] == "error"
