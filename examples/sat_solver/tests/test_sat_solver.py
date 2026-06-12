"""Simulation tests for the SAT solver Wishbone slave.

Drives the same Wishbone transaction sequence the runtime performs (clear
literals, load formula, pulse start, poll done, read model) against the
simulated SATSlave. No hardware required.
"""

import importlib.util
from pathlib import Path

from amaranth.sim import Simulator

# Load this example's design.py under a unique module name so multiple
# examples can be collected in one pytest run without colliding.
_spec = importlib.util.spec_from_file_location(
    "sat_solver_design", Path(__file__).resolve().parents[1] / "design.py"
)
_design = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_design)

CLAUSE_LEN = _design.CLAUSE_LEN
LIT_BASE = _design.LIT_BASE
MAX_CLAUSES = _design.MAX_CLAUSES
MAX_VARS = _design.MAX_VARS
SATSlave = _design.SATSlave


def check_model(model: int, clauses: list[list[int]]) -> bool:
    """Verify in Python that a model satisfies every clause."""
    for clause in clauses:
        ok = False
        for lit in clause:
            val = bool((model >> (abs(lit) - 1)) & 1)
            if (lit > 0 and val) or (lit < 0 and not val):
                ok = True
                break
        if not ok:
            return False
    return True


def run_solver(n_vars: int, clauses: list[list[int]]) -> tuple[int, int, int]:
    """Simulate one full solve. Returns (is_sat, model, cycles)."""
    dut = SATSlave()
    result = {}

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

        # Clear all literal registers, then load the formula -- the same
        # sequence the runtime performs over the Wishbone bridge.
        for i in range(MAX_CLAUSES * CLAUSE_LEN):
            await wb_write(LIT_BASE + i, 0)
        for c, clause in enumerate(clauses):
            for slot, lit in enumerate(clause):
                word = (1 << 5) | ((1 if lit < 0 else 0) << 4) | (abs(lit) - 1)
                await wb_write(LIT_BASE + c * CLAUSE_LEN + slot, word)
        await wb_write(1, n_vars)
        await wb_write(2, len(clauses))
        await wb_write(0, 1)

        for _ in range(2**MAX_VARS + 64):
            ctrl = await wb_read(0)
            if ctrl & 1:
                break
        else:
            raise AssertionError("solver never asserted done")

        result["sat"] = (ctrl >> 1) & 1
        result["model"] = await wb_read(3)
        result["cycles"] = await wb_read(4)

        # done must be stable across repeated reads (start must auto-clear)
        again = await wb_read(0)
        assert again & 1, "done bit not stable after solve (start stuck?)"

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)
    sim.add_testbench(drive)
    sim.run()
    return result["sat"], result["model"], result["cycles"]


def test_sat_4var():
    clauses = [[1, 2], [-1, 3], [-2, -3], [1, -2, 4]]
    is_sat, model, _ = run_solver(4, clauses)
    assert is_sat == 1
    assert check_model(model, clauses)


def test_unsat_trivial():
    is_sat, _, cycles = run_solver(1, [[1], [-1]])
    assert is_sat == 0
    assert cycles == 2  # UNSAT exhausts exactly 2**n_vars assignments


def test_unsat_pigeonhole():
    clauses = [
        [1, 2], [3, 4], [5, 6],
        [-1, -3], [-1, -5], [-3, -5],
        [-2, -4], [-2, -6], [-4, -6],
        [-1, -2], [-3, -4], [-5, -6],
    ]
    is_sat, _, cycles = run_solver(6, clauses)
    assert is_sat == 0
    assert cycles == 64  # 2**6


def test_sat_6var():
    clauses = [[1, 2, 3], [-1, 4], [-2, 5], [-3, 6], [-4, -5], [-5, -6]]
    is_sat, model, _ = run_solver(6, clauses)
    assert is_sat == 1
    assert check_model(model, clauses)


def test_resolve_after_unsat():
    """done/sat flags and literal registers must reset between solves."""
    is_sat, _, _ = run_solver(1, [[1], [-1]])
    assert is_sat == 0
    clauses = [[1, 2], [-1, 3], [-2, -3], [1, -2, 4]]
    is_sat, model, _ = run_solver(4, clauses)
    assert is_sat == 1
    assert check_model(model, clauses)
