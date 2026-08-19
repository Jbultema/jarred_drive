"""Launch Streamlit on the first available local port."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_START_PORT = 8501
PORT_ATTEMPTS = 100


def is_port_available(host: str, port: int) -> bool:
    """Return whether an IPv4 TCP port can be bound on the requested host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind((host, port))
        except OSError:
            return False
    return True


def find_available_port(
    host: str = DEFAULT_HOST,
    start_port: int = DEFAULT_START_PORT,
    attempts: int = PORT_ATTEMPTS,
) -> int:
    """Find the first available TCP port at or above ``start_port``."""
    if not 1 <= start_port <= 65535:
        raise ValueError("start_port must be between 1 and 65535")
    if attempts < 1:
        raise ValueError("attempts must be positive")

    end_port = min(65535, start_port + attempts - 1)
    for port in range(start_port, end_port + 1):
        if is_port_available(host, port):
            return port
    raise RuntimeError(f"No available port found from {start_port} through {end_port}")


def main() -> None:
    """Select a free port and replace this process with Streamlit."""
    start_port = int(os.environ.get("JARRED_DRIVE_PORT_START", DEFAULT_START_PORT))
    port = find_available_port(start_port=start_port)
    app_path = Path(__file__).with_name("app.py")
    url = f"http://{DEFAULT_HOST}:{port}"
    print(f"Jarred Drive selected available dashboard URL: {url}", flush=True)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.address",
            DEFAULT_HOST,
            "--server.port",
            str(port),
        ],
    )


if __name__ == "__main__":
    main()
