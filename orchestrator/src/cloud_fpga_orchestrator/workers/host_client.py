import os
from pathlib import Path

import httpx

from .protocol import WishboneRequest, WishboneResponse

# Tailscale IP of the host agent, set in the Droplet's environment.
_HOST_AGENT_URL = os.environ.get("HOST_AGENT_URL", "http://100.x.x.x:8001")


class HostAgentError(Exception):
    """Raised when the host agent returns a non-2xx response."""

    def __init__(self, endpoint: str, status_code: int, detail: str) -> None:
        super().__init__(f"Host agent {endpoint} failed ({status_code}): {detail}")
        self.status_code = status_code


class HostClient:
    """Async HTTP client for the host hardware agent.

    Wraps the three endpoints exposed by the host agent over Tailscale:
    /flash, /run, and /reset. All network I/O is async via httpx.
    """

    def __init__(self, base_url: str = _HOST_AGENT_URL) -> None:
        self._client = httpx.AsyncClient(base_url=base_url)

    async def flash(self, fpga_id: int, bitstream_path: Path) -> None:
        """Send a bitstream to the host agent to flash over JTAG.

        Args:
            fpga_id: Index of the target FPGA (0–9).
            bitstream_path: Path to the .bit file on the Droplet.

        Raises:
            HostAgentError: If the host agent reports a flash failure.
        """
        with bitstream_path.open("rb") as f:
            response = await self._client.post(
                "/flash",
                content=f.read(),
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-FPGA-ID": str(fpga_id),
                },
                timeout=60.0,
            )
        _raise_for_error("/flash", response)

    async def run(
        self, fpga_id: int, request: WishboneRequest
    ) -> WishboneResponse:
        """Send a Wishbone transaction to the FPGA and return the response.

        The host agent opens a new TCP connection to the target FPGA,
        forwards the raw packet bytes, reads the response until EOF,
        and returns the raw bytes. Framing and parsing happen here.

        Args:
            fpga_id: Index of the target FPGA (0–9).
            request: The Wishbone transaction to execute.

        Returns:
            The parsed WishboneResponse from the FPGA.

        Raises:
            HostAgentError: If the host agent reports a transport failure.
        """
        response = await self._client.post(
            "/run",
            content=request.to_bytes(),
            headers={
                "Content-Type": "application/octet-stream",
                "X-FPGA-ID": str(fpga_id),
            },
            timeout=30.0,
        )
        _raise_for_error("/run", response)
        return WishboneResponse.from_bytes(response.content)

    async def reset(self, fpga_id: int) -> None:
        """Instruct the host agent to reflash the base LiteX SoC bitstream.

        Args:
            fpga_id: Index of the target FPGA (0–9).

        Raises:
            HostAgentError: If the host agent reports a reset failure.
        """
        response = await self._client.post(
            "/reset",
            headers={"X-FPGA-ID": str(fpga_id)},
            timeout=60.0,
        )
        _raise_for_error("/reset", response)

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    async def __aenter__(self) -> "HostClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def _raise_for_error(endpoint: str, response: httpx.Response) -> None:
    """Raise HostAgentError if the response indicates failure."""
    if response.is_error:
        detail = response.text or "no detail"
        raise HostAgentError(endpoint, response.status_code, detail)
