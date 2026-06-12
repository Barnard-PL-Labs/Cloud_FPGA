# orchestrator

Full orchestration stack running on the DigitalOcean Droplet. Accepts user HDL submissions over HTTPS, manages job queues and session state in Redis, runs the build pipeline, and dispatches flash/run/reset commands to the host agent over Tailscale.

## Structure

- `src/cloud_fpga_orchestrator/api/` — FastAPI routes and request/response models
- `src/cloud_fpga_orchestrator/workers/` — per-FPGA worker processes and job logic
- `src/cloud_fpga_orchestrator/compiler/` — Amaranth → Verilog → Yosys → nextpnr-ecp5 → ecppack build pipeline
- `src/cloud_fpga_orchestrator/state/` — FPGA state machine and Redis interaction
- `tests/unit/` — state machine transitions, build stage logic, API contract tests
- `tests/integration/` — real Redis via testcontainers, mocked host agent
- `tests/e2e/` — full stack tests, skipped unless hardware is available
