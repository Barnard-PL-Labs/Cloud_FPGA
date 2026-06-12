import struct
from dataclasses import dataclass, field
from enum import IntEnum


class WishboneOp(IntEnum):
    WRITE = 0x01
    READ = 0x02


class ResponseStatus(IntEnum):
    OK = 0x00
    ERROR = 0x01


@dataclass
class WishboneRequest:
    """A single Wishbone bus transaction to be sent to the FPGA.

    Wire format (big-endian):
        Byte 0:     opcode  (1 = write, 2 = read)
        Bytes 1-3:  length  (number of 32-bit words that follow)
        Bytes 4-7:  address (Wishbone byte offset)
        Bytes 8+:   data    (one 32-bit word per entry, write only)
    """

    op: WishboneOp
    address: int
    data: list[int] = field(default_factory=list)

    def to_bytes(self) -> bytes:
        """Serialize the request to its wire representation."""
        length = len(self.data)
        header = (
            struct.pack(">B", self.op)
            + struct.pack(">I", length)[1:]
            + struct.pack(">I", self.address)
        )
        words = struct.pack(f">{length}I", *self.data) if self.data else b""
        return header + words


@dataclass
class WishboneResponse:
    """The reply packet returned by the FPGA firmware.

    Wire format (big-endian):
        Byte 0:     status  (0x00 = ok, 0x01 = error)
        Bytes 1-3:  length  (number of 32-bit words that follow)
        Bytes 4+:   data    (one 32-bit word per entry)
    """

    status: ResponseStatus
    data: list[int]

    @property
    def ok(self) -> bool:
        """True if the firmware reported a successful transaction."""
        return self.status == ResponseStatus.OK

    @classmethod
    def from_bytes(cls, raw: bytes) -> "WishboneResponse":
        """Parse a response from its wire representation.

        Args:
            raw: Raw bytes received from the FPGA over TCP.

        Returns:
            A WishboneResponse with status and data words.

        Raises:
            ValueError: If the payload is too short to be a valid response.
        """
        if len(raw) < 4:
            raise ValueError(f"Response too short: {len(raw)} bytes")
        status = ResponseStatus(raw[0])
        length = struct.unpack(">I", b"\x00" + raw[1:4])[0]
        expected = 4 + length * 4
        if len(raw) < expected:
            raise ValueError(
                f"Response truncated: expected {expected} bytes, got {len(raw)}"
            )
        data = list(struct.unpack(f">{length}I", raw[4:expected]))
        return cls(status=status, data=data)
