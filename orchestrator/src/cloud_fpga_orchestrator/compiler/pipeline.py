from dataclasses import dataclass, field
from pathlib import Path

from .errors import BuildError
from .stages import (
    amaranth_to_verilog,
    merge_soc,
    pack_bitstream,
    place_and_route,
    synthesize,
)

# Path to the ECP5 pin constraints file, relative to the repo root.
_CONSTRAINTS = Path(__file__).parents[6] / "firmware" / "constraints" / "ecp5_eval.lpf"


@dataclass
class BuildResult:
    """The outcome of a successful build pipeline run."""

    bitstream_path: Path
    logs: dict[str, str] = field(default_factory=dict)


def run_pipeline(design_path: Path, work_dir: Path) -> BuildResult:
    """Run the full Amaranth → bitstream pipeline for a user design.

    Executes all five stages in order. Stops and raises on the first failure,
    so the caller always knows exactly which stage broke.

    Args:
        design_path: Path to the user's design.py file.
        work_dir: Scratch directory for all intermediate build artifacts.

    Returns:
        A BuildResult with the path to the final bitstream and per-stage logs.

    Raises:
        BuildError: Subclass indicating which stage failed and its log output.
    """
    logs: dict[str, str] = {}

    def run_stage(name: str, fn, *args):  # type: ignore[no-untyped-def]
        try:
            result = fn(*args)
            logs[name] = ""
            return result
        except BuildError as exc:
            logs[name] = exc.log
            raise

    user_verilog = run_stage(
        "amaranth_to_verilog", amaranth_to_verilog, design_path, work_dir
    )
    top_verilog = run_stage(
        "merge_soc", merge_soc, user_verilog, work_dir
    )
    netlist = run_stage(
        "synthesize", synthesize, top_verilog, work_dir
    )
    config = run_stage(
        "place_and_route", place_and_route, netlist, _CONSTRAINTS, work_dir
    )
    bitstream = run_stage(
        "pack_bitstream", pack_bitstream, config, work_dir
    )

    return BuildResult(bitstream_path=bitstream, logs=logs)
