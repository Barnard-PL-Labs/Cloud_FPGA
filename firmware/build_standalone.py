#!/usr/bin/env python3
"""Standalone build: full bitstream for one FPGA node, no orchestrator.

Interim manual path until the Droplet build pipeline is deployed; also
useful for bringing up new boards. Mirrors what the orchestrator's
compiler stages will do:

  1. Export the user design (Amaranth) to Verilog, top renamed to
     `user_design` (yosys).
  2. Generate CSR headers and build the LiteX software libraries.
  3. Cross-compile the Wishbone-bridge firmware (make -C sw).
  4. Build the gateware with the firmware baked into ROM.

Usage:
    conda activate litex-ecp5      # or any env with LiteX-from-git
    python build_standalone.py [--design ../examples/sat_solver/design.py:SATSlave]

Output:
    /tmp/cloud-fpga-build/gateware/cloud_fpga_soc.bit

Program with:
    openFPGALoader -b ecpix5 /tmp/cloud-fpga-build/gateware/cloud_fpga_soc.bit
"""

import argparse
import importlib.util
import os
import subprocess
import sys

FIRMWARE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(FIRMWARE_DIR, "src"))

DEFAULT_DESIGN = os.path.join(
    FIRMWARE_DIR, "..", "examples", "sat_solver", "design.py"
) + ":SATSlave"


def export_user_design(design_spec, out_dir):
    """Export an Amaranth design to Verilog with top renamed to user_design.

    Args:
        design_spec: "path/to/design.py:ClassName"
        out_dir: directory for the generated .il/.ys/.v files.

    Returns:
        Path to user_design.v.
    """
    from amaranth.back.rtlil import convert

    design_path, class_name = design_spec.rsplit(":", 1)
    design_dir = os.path.dirname(os.path.abspath(design_path))
    sys.path.insert(0, design_dir)
    spec = importlib.util.spec_from_file_location("user_design_mod", design_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dut = getattr(mod, class_name)()

    os.makedirs(out_dir, exist_ok=True)
    il_path = os.path.join(out_dir, "user_design.il")
    v_path = os.path.join(out_dir, "user_design.v")

    with open(il_path, "w") as f:
        f.write(convert(dut, ports=dut.ports()))

    # Script file rather than -p so paths with spaces survive.
    ys_path = os.path.join(out_dir, "user_design.ys")
    with open(ys_path, "w") as f:
        f.write(f'read_rtlil "{il_path}"\n')
        f.write("hierarchy -check -top top\n")
        f.write("proc; opt\n")
        f.write("rename top user_design\n")
        f.write(f'write_verilog "{v_path}"\n')

    subprocess.run(["yosys", "-q", "-s", ys_path], check=True)
    print(f"[export] {v_path}")
    return v_path


def main():
    from cloud_fpga_firmware.soc import DEFAULT_BUILD_DIR, build_soc

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--design",
        default=DEFAULT_DESIGN,
        help="user design as path/to/design.py:ClassName "
        "(default: the SAT solver example)",
    )
    parser.add_argument("--build-dir", default=DEFAULT_BUILD_DIR)
    args = parser.parse_args()

    build_dir = args.build_dir
    sw_dir = os.path.join(FIRMWARE_DIR, "sw")
    rom_bin = os.path.join(sw_dir, "firmware_rom.bin")

    # 1. User design -> user_design.v
    v_path = export_user_design(args.design, os.path.join(build_dir, "gateware"))

    # 2. CSR headers + LiteX libraries (no gateware yet).
    print("[headers] generating CSR headers and LiteX libraries ...")
    build_soc(v_path, build_dir=build_dir, compile_gateware=False)

    # 3. Firmware.
    print("[firmware] compiling firmware_rom.bin ...")
    subprocess.run(
        ["make", "-C", sw_dir, "firmware_rom.bin", f"BUILD_DIR={build_dir}"],
        check=True,
    )

    # 4. Gateware with firmware in ROM.
    build_soc(v_path, build_dir=build_dir, rom_init_bin=rom_bin)
    print(f"[done] {build_dir}/gateware/cloud_fpga_soc.bit")


if __name__ == "__main__":
    main()
