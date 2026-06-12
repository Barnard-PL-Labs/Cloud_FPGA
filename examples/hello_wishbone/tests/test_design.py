"""Simulation tests for the hello_wishbone echo memory.

Verifies the Wishbone interface contract every user design must honor:
registered single-cycle ack that clears when stb drops, plus write/read
data integrity with no aliasing between addresses.
"""

from amaranth.sim import Simulator
from design import DEPTH, EchoSlave


def run_transactions(script):
    """Run a list of ("w", adr, dat) / ("r", adr, expected) transactions."""
    dut = EchoSlave()

    async def drive(ctx):
        async def wb_write(adr, dat):
            ctx.set(dut.wb_cyc, 1)
            ctx.set(dut.wb_stb, 1)
            ctx.set(dut.wb_we, 1)
            ctx.set(dut.wb_adr, adr)
            ctx.set(dut.wb_dat_w, dat)
            for _ in range(8):
                await ctx.tick()
                if ctx.get(dut.wb_ack):
                    break
            else:
                raise AssertionError(f"ack never fired on write to adr={adr}")
            ctx.set(dut.wb_stb, 0)
            ctx.set(dut.wb_we, 0)
            await ctx.tick()
            assert ctx.get(dut.wb_ack) == 0, "ack did not clear after stb dropped"

        async def wb_read(adr):
            ctx.set(dut.wb_cyc, 1)
            ctx.set(dut.wb_stb, 1)
            ctx.set(dut.wb_we, 0)
            ctx.set(dut.wb_adr, adr)
            for _ in range(8):
                await ctx.tick()
                if ctx.get(dut.wb_ack):
                    break
            else:
                raise AssertionError(f"ack never fired on read from adr={adr}")
            val = ctx.get(dut.wb_dat_r)
            ctx.set(dut.wb_stb, 0)
            await ctx.tick()
            assert ctx.get(dut.wb_ack) == 0, "ack did not clear after stb dropped"
            return val

        ctx.set(dut.wb_cyc, 0)
        ctx.set(dut.wb_stb, 0)
        await ctx.tick()

        for op, adr, dat in script:
            if op == "w":
                await wb_write(adr, dat)
            else:
                got = await wb_read(adr)
                assert got == dat, (
                    f"read adr={adr}: expected {dat:#010x}, got {got:#010x}"
                )

        ctx.set(dut.wb_cyc, 0)
        await ctx.tick()

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)
    sim.add_testbench(drive)
    sim.run()


def test_write_read_roundtrip():
    run_transactions([
        ("w", 0, 0xDEAD_BEEF),
        ("r", 0, 0xDEAD_BEEF),
    ])


def test_no_aliasing_between_addresses():
    run_transactions([
        ("w", 0, 0xDEAD_BEEF),
        ("w", 1, 0xCAFE_BABE),
        ("r", 0, 0xDEAD_BEEF),  # unchanged by the write to adr=1
        ("r", 1, 0xCAFE_BABE),
        ("w", 0, 0x1234_5678),  # overwrite
        ("r", 1, 0xCAFE_BABE),  # still unchanged
        ("r", 0, 0x1234_5678),
    ])


def test_full_depth_boundaries():
    last = DEPTH - 1
    run_transactions([
        ("w", 0, 0x0000_0001),
        ("w", last, 0xFFFF_FFFE),
        ("r", 0, 0x0000_0001),
        ("r", last, 0xFFFF_FFFE),
    ])
