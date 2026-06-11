# host

Minimal hardware agent that runs on the local host machine. Exposes a small HTTP API bound exclusively to the Tailscale IP — no public surface, no persistent state. Receives job commands from the Droplet orchestrator and acts on physical hardware.

## Structure

- `src/cloud_fpga_host/` — FastAPI application with three endpoints: `POST /flash`, `POST /run`, `POST /reset`
- `tests/unit/` — endpoint contract tests, request/response parsing
- `tests/integration/` — full app tests with mocked `openFPGALoader` subprocess and UDP/TCP sockets
