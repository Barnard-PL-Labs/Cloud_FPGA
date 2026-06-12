"""Wishbone round-trip latency and throughput benchmark.

Measures the full network + firmware + bus path against a live FPGA node
running the Wishbone-bridge firmware: burst WRITEs followed by burst READs
of the user region, with payload verification. Successor to the prototype's
echo-based measure_tcp.py, reimplemented over the generic wire protocol
(orchestrator/.../workers/protocol.py).

Usage:
    python measure_latency.py [--host 192.168.1.101] [--port 1234] [--plot]
"""

import argparse
import socket
import statistics
import struct
import time

# Burst sizes in 32-bit words (user region holds 512).
SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
SAMPLES = 20
WARMUP = 3
TIMEOUT = 5.0

OP_WRITE = 0x01
OP_READ = 0x02
STATUS_OK = 0x00


def encode_write(address: int, words: list[int]) -> bytes:
    header = struct.pack(">B", OP_WRITE) + struct.pack(">I", len(words))[1:]
    header += struct.pack(">I", address)
    return header + struct.pack(f">{len(words)}I", *words)


def encode_read(address: int, count: int) -> bytes:
    header = struct.pack(">B", OP_READ) + struct.pack(">I", 1)[1:]
    header += struct.pack(">I", address)
    return header + struct.pack(">I", count)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("FPGA closed the connection")
        buf += chunk
    return buf


def recv_response(sock: socket.socket) -> tuple[int, list[int]]:
    header = recv_exact(sock, 4)
    status = header[0]
    length = struct.unpack(">I", b"\x00" + header[1:4])[0]
    raw = recv_exact(sock, length * 4)
    data = list(struct.unpack(f">{length}I", raw)) if length else []
    return status, data


def measure(sock: socket.socket, n_words: int) -> list[float]:
    """Round-trip times in microseconds for write-then-readback bursts."""
    payload = [(0xA5000000 | i) & 0xFFFFFFFF for i in range(n_words)]
    rtts = []

    for i in range(SAMPLES + WARMUP):
        t0 = time.perf_counter()

        sock.sendall(encode_write(0, payload))
        status, _ = recv_response(sock)
        if status != STATUS_OK:
            print(f"  write error at size={n_words} sample={i}")
            continue

        sock.sendall(encode_read(0, n_words))
        status, data = recv_response(sock)
        t1 = time.perf_counter()

        if status != STATUS_OK or data != payload:
            print(f"  readback mismatch at size={n_words} sample={i}")
            continue

        if i >= WARMUP:
            rtts.append((t1 - t0) * 1e6)

    return rtts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.101")
    ap.add_argument("--port", type=int, default=1234)
    ap.add_argument("--plot", action="store_true",
                    help="save a latency plot to latency.png (needs matplotlib)")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(TIMEOUT)
    sock.connect((args.host, args.port))

    print(f"Wishbone write+readback bursts against {args.host}:{args.port}")
    print(f"{'Words':>7} {'Bytes':>7} {'Min (us)':>10} {'Mean (us)':>10} "
          f"{'Max (us)':>10} {'Stdev':>8} {'Mbps':>8}")
    print("-" * 66)

    sizes_done, means = [], []
    for n in SIZES:
        rtts = measure(sock, n)
        if not rtts:
            print(f"{n:>7} no replies")
            continue
        mn, mx = min(rtts), max(rtts)
        avg = statistics.mean(rtts)
        sd = statistics.stdev(rtts) if len(rtts) > 1 else 0.0
        # Payload crosses the link twice (write out, read back).
        mbps = (n * 4 * 8 * 2) / (avg * 1e-6) / 1e6
        print(f"{n:>7} {n * 4:>7} {mn:>10.1f} {avg:>10.1f} "
              f"{mx:>10.1f} {sd:>8.1f} {mbps:>8.3f}")
        sizes_done.append(n * 4)
        means.append(avg)

    sock.close()

    if args.plot and sizes_done:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(sizes_done, means, "b-o", linewidth=2)
        ax.set_xlabel("Burst size (bytes)")
        ax.set_ylabel("Write + readback round trip (us)")
        ax.set_title("Cloud FPGA node -- Wishbone bridge latency")
        ax.set_xscale("log", base=2)
        ax.grid(True, alpha=0.4)
        plt.tight_layout()
        plt.savefig("latency.png", dpi=150)
        print("\nPlot saved to latency.png")


if __name__ == "__main__":
    main()
