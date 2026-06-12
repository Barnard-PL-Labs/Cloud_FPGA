import struct

import pytest

from cloud_fpga_orchestrator.workers.protocol import (
    ResponseStatus,
    WishboneOp,
    WishboneRequest,
    WishboneResponse,
)


class TestWishboneRequestToBytes:
    def test_read_no_data_length(self):
        req = WishboneRequest(op=WishboneOp.READ, address=0x1000)
        raw = req.to_bytes()
        assert len(raw) == 8  # 1 opcode + 3 length + 4 address

    def test_read_opcode_byte(self):
        raw = WishboneRequest(op=WishboneOp.READ, address=0x0).to_bytes()
        assert raw[0] == WishboneOp.READ

    def test_read_length_zero(self):
        raw = WishboneRequest(op=WishboneOp.READ, address=0x0).to_bytes()
        assert raw[1:4] == b"\x00\x00\x00"

    def test_address_encoded_big_endian(self):
        raw = WishboneRequest(op=WishboneOp.READ, address=0xDEADBEEF).to_bytes()
        assert struct.unpack(">I", raw[4:8])[0] == 0xDEADBEEF

    def test_write_opcode_byte(self):
        raw = WishboneRequest(op=WishboneOp.WRITE, address=0x0, data=[0x1]).to_bytes()
        assert raw[0] == WishboneOp.WRITE

    def test_write_length_field(self):
        raw = WishboneRequest(
            op=WishboneOp.WRITE, address=0x0, data=[0x1, 0x2]
        ).to_bytes()
        # 3-byte length field should be 2
        assert raw[1:4] == b"\x00\x00\x02"

    def test_write_data_words(self):
        data = [0xDEADBEEF, 0xCAFEBABE]
        raw = WishboneRequest(op=WishboneOp.WRITE, address=0x4, data=data).to_bytes()
        assert struct.unpack(">I", raw[8:12])[0] == 0xDEADBEEF
        assert struct.unpack(">I", raw[12:16])[0] == 0xCAFEBABE

    def test_write_total_length_with_data(self):
        raw = WishboneRequest(
            op=WishboneOp.WRITE, address=0x0, data=[0x1, 0x2, 0x3]
        ).to_bytes()
        assert len(raw) == 8 + 3 * 4

    def test_empty_data_write(self):
        raw = WishboneRequest(op=WishboneOp.WRITE, address=0x0, data=[]).to_bytes()
        assert len(raw) == 8


class TestWishboneResponseFromBytes:
    def test_ok_status_no_data(self):
        raw = bytes([0x00, 0x00, 0x00, 0x00])
        resp = WishboneResponse.from_bytes(raw)
        assert resp.status == ResponseStatus.OK
        assert resp.data == []

    def test_error_status(self):
        raw = bytes([0x01, 0x00, 0x00, 0x00])
        resp = WishboneResponse.from_bytes(raw)
        assert resp.status == ResponseStatus.ERROR
        assert resp.ok is False

    def test_ok_property_true(self):
        raw = bytes([0x00, 0x00, 0x00, 0x00])
        assert WishboneResponse.from_bytes(raw).ok is True

    def test_data_words_decoded(self):
        raw = bytes([0x00, 0x00, 0x00, 0x02]) + struct.pack(">II", 0xAA, 0xBB)
        resp = WishboneResponse.from_bytes(raw)
        assert resp.data == [0xAA, 0xBB]

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            WishboneResponse.from_bytes(b"\x00\x00\x00")

    def test_truncated_payload_raises(self):
        # Claims 2 words but only has 4 bytes of data instead of 8
        raw = bytes([0x00, 0x00, 0x00, 0x02]) + b"\xAA\xBB\xCC\xDD"
        with pytest.raises(ValueError, match="truncated"):
            WishboneResponse.from_bytes(raw)

    def test_single_word_round_trip(self):
        original = [0xDEADBEEF]
        raw = bytes([0x00]) + struct.pack(">I", 1)[1:] + struct.pack(">I", *original)
        resp = WishboneResponse.from_bytes(raw)
        assert resp.data == original

    def test_multiple_words_round_trip(self):
        original = [0x1, 0x2, 0x3, 0x4]
        raw = bytes([0x00]) + struct.pack(">I", 4)[1:] + struct.pack(">4I", *original)
        resp = WishboneResponse.from_bytes(raw)
        assert resp.data == original
