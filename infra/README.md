# infra

Deployment configuration for the Droplet and host machine. No application code lives here — only the configs needed to run and connect the services.

## Structure

- `nginx/` — reverse proxy config for the DigitalOcean Droplet; terminates HTTPS and forwards to the orchestrator
- `systemd/` — unit files to run the orchestrator (Droplet) and host agent (host machine) as services that start on boot and restart on failure
- `netplan/` — static IP configuration for the host's FPGA-facing ethernet interface (`192.168.1.10/24`)
- `udev/` — rules that map each FPGA's FTDI USB serial number to a stable device name (`/dev/fpga00`–`/dev/fpga09`)
