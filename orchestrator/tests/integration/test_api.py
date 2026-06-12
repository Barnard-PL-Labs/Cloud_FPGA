from uuid import uuid4

from cloud_fpga_orchestrator.state.models import FPGAState, Job, JobStatus, JobType
from cloud_fpga_orchestrator.state.store import (
    create_session,
    enqueue_job,
    set_job_result,
    transition_fpga_state,
    update_job_status,
)


async def _put_fpga_in_reserved(redis_client, fpga_id: int) -> None:
    await transition_fpga_state(redis_client, fpga_id, FPGAState.QUEUED)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.BUILDING)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.PROGRAMMING)
    await transition_fpga_state(redis_client, fpga_id, FPGAState.RESERVED)


class TestHealth:
    async def test_health_ok(self, app_client):
        resp = await app_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["redis"] is True


class TestFPGAListing:
    async def test_list_fpgas_returns_ten(self, app_client):
        resp = await app_client.get("/fpga")
        assert resp.status_code == 200
        assert len(resp.json()) == 10

    async def test_list_fpgas_all_idle_on_clean_state(self, app_client):
        resp = await app_client.get("/fpga")
        for summary in resp.json():
            assert summary["state"] == "idle"

    async def test_get_single_fpga(self, app_client):
        resp = await app_client.get("/fpga/0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["fpga_id"] == 0
        assert body["state"] == "idle"

    async def test_get_fpga_reflects_state_change(self, app_client, redis_client):
        await transition_fpga_state(redis_client, 3, FPGAState.QUEUED)
        resp = await app_client.get("/fpga/3")
        assert resp.json()["state"] == "queued"


class TestSubmit:
    async def test_submit_idle_fpga_returns_202(self, app_client):
        resp = await app_client.post(
            "/fpga/0/submit",
            files={"file": ("design.py", b"# design", "text/plain")},
        )
        assert resp.status_code == 202

    async def test_submit_returns_job_id(self, app_client):
        resp = await app_client.post(
            "/fpga/0/submit",
            files={"file": ("design.py", b"# design", "text/plain")},
        )
        body = resp.json()
        assert "job_id" in body
        assert body["fpga_id"] == 0
        assert body["status"] == "queued"

    async def test_submit_transitions_fpga_to_queued(self, app_client, redis_client):
        await app_client.post(
            "/fpga/0/submit",
            files={"file": ("design.py", b"# design", "text/plain")},
        )
        from cloud_fpga_orchestrator.state.store import get_fpga_state
        state = await get_fpga_state(redis_client, 0)
        assert state == FPGAState.QUEUED

    async def test_submit_non_idle_fpga_returns_409(self, app_client, redis_client):
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)
        resp = await app_client.post(
            "/fpga/0/submit",
            files={"file": ("design.py", b"# design", "text/plain")},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "fpga_not_idle"


class TestJobStatus:
    async def test_get_job_returns_200(self, app_client, redis_client):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        resp = await app_client.get(f"/fpga/0/jobs/{job.job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == str(job.job_id)
        assert body["status"] == "queued"

    async def test_get_job_wrong_fpga_returns_404(self, app_client, redis_client):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        resp = await app_client.get(f"/fpga/1/jobs/{job.job_id}")
        assert resp.status_code == 404

    async def test_get_missing_job_returns_404(self, app_client):
        resp = await app_client.get(f"/fpga/0/jobs/{uuid4()}")
        assert resp.status_code == 404

    async def test_get_job_logs(self, app_client, redis_client):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        from cloud_fpga_orchestrator.state.store import append_job_log
        await append_job_log(redis_client, job.job_id, "build output\n")
        resp = await app_client.get(f"/fpga/0/jobs/{job.job_id}/logs")
        assert resp.status_code == 200
        assert "build output" in resp.text

    async def test_get_result_complete_job(self, app_client, redis_client):
        job = Job(fpga_id=0, type=JobType.RUN, status=JobStatus.COMPLETE)
        await enqueue_job(redis_client, job)
        await update_job_status(redis_client, job.job_id, JobStatus.COMPLETE)
        await set_job_result(redis_client, job.job_id, [0x1, 0x2])
        resp = await app_client.get(f"/fpga/0/jobs/{job.job_id}/result")
        assert resp.status_code == 200
        assert resp.json()["data"] == [0x1, 0x2]

    async def test_get_result_incomplete_job_returns_409(
        self, app_client, redis_client
    ):
        job = Job(fpga_id=0, type=JobType.RUN)
        await enqueue_job(redis_client, job)
        resp = await app_client.get(f"/fpga/0/jobs/{job.job_id}/result")
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "job_not_complete"


class TestCancelJob:
    async def test_cancel_queued_job_returns_204(self, app_client, redis_client):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        resp = await app_client.delete(f"/fpga/0/jobs/{job.job_id}")
        assert resp.status_code == 204

    async def test_cancelled_job_status_is_cancelled(self, app_client, redis_client):
        from cloud_fpga_orchestrator.state.store import get_job
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        await app_client.delete(f"/fpga/0/jobs/{job.job_id}")
        retrieved = await get_job(redis_client, job.job_id)
        assert retrieved.status == JobStatus.CANCELLED

    async def test_cancel_running_job_returns_409(self, app_client, redis_client):
        job = Job(fpga_id=0, type=JobType.BUILD_AND_PROGRAM)
        await enqueue_job(redis_client, job)
        await update_job_status(redis_client, job.job_id, JobStatus.RUNNING)
        resp = await app_client.delete(f"/fpga/0/jobs/{job.job_id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "job_not_cancellable"

    async def test_cancel_missing_job_returns_404(self, app_client):
        resp = await app_client.delete(f"/fpga/0/jobs/{uuid4()}")
        assert resp.status_code == 404


class TestRunEndpoint:
    async def test_run_on_reserved_fpga_returns_202(self, app_client, redis_client):
        await _put_fpga_in_reserved(redis_client, 0)
        resp = await app_client.post(
            "/fpga/0/run",
            json={"op": 2, "address": 0x1000, "data": []},
        )
        assert resp.status_code == 202

    async def test_run_on_non_reserved_returns_409(self, app_client):
        resp = await app_client.post(
            "/fpga/0/run",
            json={"op": 2, "address": 0x1000, "data": []},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "fpga_not_reserved"


class TestResetEndpoint:
    async def test_reset_reserved_fpga_returns_202(self, app_client, redis_client):
        await _put_fpga_in_reserved(redis_client, 0)
        resp = await app_client.post("/fpga/0/reset")
        assert resp.status_code == 202

    async def test_reset_error_fpga_returns_202(self, app_client, redis_client):
        await transition_fpga_state(redis_client, 0, FPGAState.QUEUED)
        await transition_fpga_state(redis_client, 0, FPGAState.BUILDING)
        await transition_fpga_state(redis_client, 0, FPGAState.PROGRAMMING)
        await transition_fpga_state(redis_client, 0, FPGAState.ERROR)
        resp = await app_client.post("/fpga/0/reset")
        assert resp.status_code == 202

    async def test_reset_idle_fpga_returns_409(self, app_client):
        resp = await app_client.post("/fpga/0/reset")
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "fpga_not_resettable"


class TestSessionEndpoints:
    async def test_get_session_no_session_returns_404(self, app_client):
        resp = await app_client.get("/fpga/0/session")
        assert resp.status_code == 404

    async def test_get_session_returns_session_data(self, app_client, redis_client):
        await create_session(redis_client, 0, "alice", 3600)
        resp = await app_client.get("/fpga/0/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["owner"] == "alice"
        assert body["fpga_id"] == 0

    async def test_release_session_no_session_returns_404(self, app_client):
        resp = await app_client.post("/fpga/0/session/release")
        assert resp.status_code == 404

    async def test_release_session_enqueues_reset_job(self, app_client, redis_client):
        await create_session(redis_client, 0, "alice", 3600)
        resp = await app_client.post("/fpga/0/session/release")
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["fpga_id"] == 0
