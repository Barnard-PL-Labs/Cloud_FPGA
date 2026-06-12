from cloud_fpga_orchestrator.state.keys import (
    fpga_current_job,
    fpga_queue,
    fpga_session,
    fpga_state,
    job,
    job_log,
    job_result,
)


def test_fpga_state_format():
    assert fpga_state(0) == "fpga:0:state"
    assert fpga_state(9) == "fpga:9:state"


def test_fpga_session_format():
    assert fpga_session(0) == "fpga:0:session"
    assert fpga_session(5) == "fpga:5:session"


def test_fpga_queue_format():
    assert fpga_queue(3) == "fpga:3:queue"


def test_fpga_current_job_format():
    assert fpga_current_job(2) == "fpga:2:current_job"


def test_job_format():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert job(uid) == f"job:{uid}"


def test_job_log_format():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert job_log(uid) == f"job:{uid}:log"


def test_job_result_format():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert job_result(uid) == f"job:{uid}:result"


def test_all_fpga_keys_distinct_per_id():
    keys = [fpga_state(0), fpga_session(0), fpga_queue(0), fpga_current_job(0)]
    assert len(keys) == len(set(keys))


def test_job_keys_distinct():
    uid = "abc-123"
    keys = [job(uid), job_log(uid), job_result(uid)]
    assert len(keys) == len(set(keys))
