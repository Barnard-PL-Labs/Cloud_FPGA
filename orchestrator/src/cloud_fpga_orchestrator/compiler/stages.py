from pathlib import Path

from .errors import (
    AmaranthConversionError,
    BitstreamPackError,
    PlaceAndRouteError,
    SoCMergeError,
    SynthesisError,
)
from .sandbox import run_sandboxed


def amaranth_to_verilog(design_path: Path, output_dir: Path) -> Path:
    """Convert a user Amaranth design to Verilog.

    Args:
        design_path: Path to the user's design.py file.
        output_dir: Directory to write user_design.v into.

    Returns:
        Path to the generated user_design.v.

    Raises:
        AmaranthConversionError: If Amaranth fails to convert the design.
    """
    # TODO: replace with real conversion command once firmware/ SoC is defined.
    # Expected command: python -m amaranth generate verilog design.py UserDesign
    result = run_sandboxed(
        [
            "python",
            "-m",
            "amaranth",
            "generate",
            "verilog",
            str(design_path),
            "UserDesign",
        ],
        cwd=output_dir,
    )
    if not result.success:
        raise AmaranthConversionError(
            stage="amaranth_to_verilog",
            message="Amaranth failed to convert user design to Verilog.",
            log=result.output,
        )
    return output_dir / "user_design.v"


def merge_soc(user_verilog: Path, output_dir: Path) -> Path:
    """Merge the user Verilog into the base LiteX SoC to produce a combined top.v.

    Args:
        user_verilog: Path to user_design.v produced by amaranth_to_verilog.
        output_dir: Directory to write top.v into.

    Returns:
        Path to the merged top.v.

    Raises:
        SoCMergeError: If the LiteX merge step fails.
    """
    # TODO: replace with real LiteX SoC build command once firmware/ is defined.
    # Expected command:
    # python firmware/src/cloud_fpga_firmware/soc.py --user-design user_design.v
    result = run_sandboxed(
        ["python", "-m", "cloud_fpga_firmware.soc", "--user-design", str(user_verilog)],
        cwd=output_dir,
    )
    if not result.success:
        raise SoCMergeError(
            stage="merge_soc",
            message="LiteX SoC merge failed.",
            log=result.output,
        )
    return output_dir / "top.v"


def synthesize(top_verilog: Path, output_dir: Path) -> Path:
    """Synthesize the merged design with Yosys to produce a gate-level netlist.

    Args:
        top_verilog: Path to top.v produced by merge_soc.
        output_dir: Directory to write netlist.json into.

    Returns:
        Path to the synthesized netlist.json.

    Raises:
        SynthesisError: If Yosys synthesis fails.
    """
    netlist = output_dir / "netlist.json"
    result = run_sandboxed(
        [
            "yosys",
            "-p",
            f"synth_ecp5 -json {netlist}",
            str(top_verilog),
        ],
        cwd=output_dir,
    )
    if not result.success:
        raise SynthesisError(
            stage="synthesize",
            message="Yosys synthesis failed.",
            log=result.output,
        )
    return netlist


def place_and_route(
    netlist: Path, constraints: Path, output_dir: Path
) -> Path:
    """Place and route the netlist with nextpnr-ecp5.

    Args:
        netlist: Path to netlist.json produced by synthesize.
        constraints: Path to the ECP5 .lpf pin constraints file.
        output_dir: Directory to write design.config into.

    Returns:
        Path to the routed design.config.

    Raises:
        PlaceAndRouteError: If nextpnr-ecp5 fails to place and route.
    """
    config = output_dir / "design.config"
    result = run_sandboxed(
        [
            "nextpnr-ecp5",
            "--85k",
            "--json", str(netlist),
            "--lpf", str(constraints),
            "--textcfg", str(config),
        ],
        cwd=output_dir,
        timeout=600,
    )
    if not result.success:
        raise PlaceAndRouteError(
            stage="place_and_route",
            message="nextpnr-ecp5 place and route failed.",
            log=result.output,
        )
    return config


def pack_bitstream(config: Path, output_dir: Path) -> Path:
    """Pack the routed config into a flashable bitstream with ecppack.

    Args:
        config: Path to design.config produced by place_and_route.
        output_dir: Directory to write bitstream.bit into.

    Returns:
        Path to the final bitstream.bit.

    Raises:
        BitstreamPackError: If ecppack fails to produce a bitstream.
    """
    bitstream = output_dir / "bitstream.bit"
    result = run_sandboxed(
        ["ecppack", str(config), str(bitstream)],
        cwd=output_dir,
    )
    if not result.success:
        raise BitstreamPackError(
            stage="pack_bitstream",
            message="ecppack failed to produce a bitstream.",
            log=result.output,
        )
    return bitstream
