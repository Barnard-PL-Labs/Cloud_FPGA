# Cloud_FPGA
We propose a cloud infrastructure containing FPGAs built on solely open-source and lightweight toolchains, specifically targeting agentic evaluation in physical engineering tasks rather than industry-grade FPGA prototyping.

## Problem Statement

With artificial intelligence becoming increasingly better with the advent of LLM-based systems, automated scientific discovery has become a real and tangible goal. For example, Liu et al. illustrates AutoResearchClaw, an autonomous research system that is capable of discovering literature, evaluating its own ideas, performing iterative experimentation, writing reports, and verifying its results. However, there remains a gap in LLM-based automated research in physical environments such as Electronic Design Automation (EDA) tasks pertaining to FPGA-based development. Traditional SWE-based agents do not perform as well in hardware environments.

Cloud FPGA infrastructure provides a safe and accessible environment for agents to learn how to reason about physical engineering decisions. Amazon EC2 F2 Instances provide industry-grade cloud FPGA resources, however their use of robust proprietary software often leads to long delays in FPGA usage, posing a significant barrier to agentic systems that often require quick feedback for iterative refinement.

We propose a cloud infrastructure containing FPGAs built on solely open-source and lightweight toolchains, specifically targeting agentic evaluation in physical engineering tasks rather than industry-grade FPGA prototyping. Our initial design will focus on agents' ability to design automated reasoning tools, specifically boolean satisfiability solvers, a complex task motivated by the success of stand-alone hardware solvers such as SAT-Accel and SAT-Hard.

## System Overview

The proposed infrastructure contains 10 [Lattice ECP5 Evaluation Boards](https://www.latticesemi.com/en/Products/DevelopmentBoardsAndKits/ECP5EvaluationBoard), each with an ECP5-5G FPGA (LFE5UM5G-85F-8BG381). Each board serves as a node in our local network of FPGAs. Each FPGA individually connects to a shared host machine via USB/JTAG for programming and ethernet for runtime interfacing. A [DigitalOcean](https://www.digitalocean.com/products#core-cloud) Droplet runs the full orchestration stack and accepts HTTPS requests from users. A [Tailscale](https://tailscale.com) tunnel connects the Droplet to the host machine, carrying job commands (flash, run, reset) to a minimal hardware agent on the host.

The system is divided into four layers:

```
┌──────────────────────────────────────────────────────────────────┐
│                 User — Amaranth HDL submission                   │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTPS :443
┌─────────────────────────────▼────────────────────────────────────┐
│  Droplet — nginx · FastAPI · Redis · Workers (×10) · Build      │
└─────────────────────────────┬────────────────────────────────────┘
                              │ Job commands over Tailscale
┌─────────────────────────────▼────────────────────────────────────┐
│            Host — Hardware agent (JTAG relay + runtime bridge)   │
└─────────────────────────────┬────────────────────────────────────┘
                              │ JTAG / UDP-TCP
┌─────────────────────────────▼────────────────────────────────────┐
│    Hardware Firmware — LiteX SoC (VexRiscv + LiteEth +          │
│                        Wishbone) per FPGA                        │
└─────────────────────────────┬────────────────────────────────────┘
                              │ Wishbone bus
┌─────────────────────────────▼────────────────────────────────────┐
│              Physical — 10× Lattice ECP5-5G boards               │
└──────────────────────────────────────────────────────────────────┘
```

**Physical Layer** — Ten Lattice ECP5-5G evaluation boards each serve as an independent FPGA node. Each board draws power from a shared PDU and connects to the host machine over two interfaces: a mini USB port (via an FTDI chip for JTAG programming) and an ethernet port (via a LAN8720 PHY board for runtime data transfer). All boards share an unmanaged ethernet switch and a powered USB hub that fan out to the host over single cables.

**Hardware Firmware Layer** — Each FPGA runs a LiteX SoC consisting of a VexRiscv soft-core CPU, a LiteEth MAC and DMA for ethernet, a Wishbone bus for memory-mapped I/O, and on-chip ROM and SRAM. Bare-metal firmware on the CPU handles ethernet initialization and routes incoming packets to user-defined memory regions via the Wishbone bus. The full toolchain — Yosys, nextpnr-ecp5, and ecppack — synthesizes, places and routes, and packs bitstreams from LiteX-generated Verilog. The SoC currently consumes roughly 6% of logic and 11% of block RAM, leaving the vast majority of the chip free for user designs.

**Host Layer** — The host is a minimal hardware agent with no public surface and no persistent state. It exposes a small HTTP API bound exclusively to its Tailscale IP, with three endpoints (`/flash`, `/run`, `/reset`) that Droplet workers call over the tunnel. The JTAG agent executes `openFPGALoader` against the USB hub to program FPGAs; the runtime bridge forwards UDP/TCP payloads to the target FPGA on the local LAN and returns results.

**Droplet / Orchestration Layer** — A [DigitalOcean](https://www.digitalocean.com/products#core-cloud) General Purpose Droplet (minimum 2 vCPUs, 8 GB RAM) runs the full orchestration stack: an nginx reverse proxy terminating HTTPS, a FastAPI server for the user-facing REST API, Redis for job queues and session state, ten per-FPGA worker processes, and the build server that runs the Amaranth → Verilog → Yosys → nextpnr-ecp5 → ecppack pipeline. Workers issue flash, run, and reset commands to the host agent over Tailscale.

**User Interface Layer** — Users submit a single Amaranth `.py` file whose top-level module conforms to a defined Wishbone B4 slave interface contract. The API returns a session ID on successful programming; subsequent run requests reference that session to send data to and receive results from the live FPGA.

## Repository Structure

```
Cloud_FPGA/
├── docs/design/          # design documents and architecture diagrams
├── firmware/             # LiteX SoC definition and bare-metal VexRiscv firmware
├── host/                 # hardware agent running on the local host machine
├── orchestrator/         # full orchestration stack running on the DigitalOcean Droplet
├── infra/                # deployment configs (nginx, systemd, netplan, udev)
├── examples/             # reference Amaranth HDL designs
└── scripts/              # one-off cluster setup and maintenance scripts
```

Each directory contains its own `README.md` with a description and breakdown of its contents.
