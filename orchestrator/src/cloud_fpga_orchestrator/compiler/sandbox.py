import resource
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxResult:
    """The outcome of a sandboxed subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        """Combined stdout and stderr, stripped of leading/trailing whitespace."""
        return (self.stdout + self.stderr).strip()

    @property
    def success(self) -> bool:
        """True if the process exited with code 0."""
        return self.returncode == 0


def run_sandboxed(
    cmd: list[str],
    cwd: Path,
    timeout: int = 300,
    max_memory_mb: int = 4096,
) -> SandboxResult:
    """Run a command in a resource-limited subprocess.

    Args:
        cmd: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        timeout: Wall-clock time limit in seconds before the process is killed.
        max_memory_mb: Virtual memory ceiling in megabytes.

    Returns:
        A SandboxResult containing the exit code and captured output.

    Raises:
        subprocess.TimeoutExpired: If the process exceeds `timeout` seconds.
    """

    def _set_limits() -> None:
        limit = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        preexec_fn=_set_limits,
    )
    return SandboxResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
