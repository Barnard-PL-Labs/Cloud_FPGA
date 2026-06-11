def fpga_state(fpga_id: int) -> str:
    """Return the Redis key for an FPGA's current state."""
    return f"fpga:{fpga_id}:state"


def fpga_session(fpga_id: int) -> str:
    """Return the Redis key for an FPGA's active session."""
    return f"fpga:{fpga_id}:session"


def fpga_queue(fpga_id: int) -> str:
    """Return the Redis key for an FPGA's job queue (a Redis list)."""
    return f"fpga:{fpga_id}:queue"


def job(job_id: str) -> str:
    """Return the Redis key for a job record."""
    return f"job:{job_id}"


def job_log(job_id: str) -> str:
    """Return the Redis key for a job's build log."""
    return f"job:{job_id}:log"


def job_result(job_id: str) -> str:
    """Return the Redis key for a run job's response data."""
    return f"job:{job_id}:result"
