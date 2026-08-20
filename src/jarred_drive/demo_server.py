"""HTTP development logger backed by deterministic synthetic session bundles.

The server intentionally implements the same read-only endpoints as the ESP
logger so native clients do not need a special synthetic-data transport.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

_SESSION_RESOURCE = re.compile(r"^/api/sessions/([^/]+)/(manifest|files/([^/]+))$")


@dataclass(frozen=True)
class DemoServerConfig:
    root: Path
    token: str | None = None


def _safe_component(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and path.name == value and value not in {".", ".."}


def make_demo_handler(config: DemoServerConfig) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one immutable synthetic fixture root."""

    class DemoLoggerHandler(BaseHTTPRequestHandler):
        server_version = "JarredDriveDemo/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _device_payload(self) -> dict[str, object]:
            payload = json.loads((config.root / "device.json").read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("device.json must contain an object")
            return payload

        def _session_ids(self) -> list[str]:
            return sorted(
                path.parent.name
                for path in config.root.glob("*/manifest.json")
                if _safe_component(path.parent.name)
            )

        def _send_file(self, path: Path) -> None:
            if not path.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            size = path.stat().st_size
            start = 0
            range_header = self.headers.get("Range", "")
            if range_header:
                match = re.fullmatch(r"bytes=(\d+)-", range_header)
                if match is None:
                    self._send_json(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, {"error": "range"})
                    return
                start = int(match.group(1))
                if start >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
            status = HTTPStatus.PARTIAL_CONTENT if start else HTTPStatus.OK
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size - start))
            if start:
                self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                while chunk := handle.read(64 * 1024):
                    self.wfile.write(chunk)

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                device = self._device_payload()
                if path == "/api/device":
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            key: device[key]
                            for key in (
                                "device_id",
                                "name",
                                "hardware_revision",
                                "firmware_version",
                                "data_kind",
                                "capabilities",
                            )
                            if key in device
                        },
                    )
                    return
                if path == "/api/status":
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            key: device[key]
                            for key in ("mode", "battery_percent", "sd_free_percent")
                        },
                    )
                    return
                if path == "/api/sessions":
                    self._send_json(
                        HTTPStatus.OK,
                        [{"session_id": session_id} for session_id in self._session_ids()],
                    )
                    return
                match = _SESSION_RESOURCE.fullmatch(path)
                if match is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                session_id = unquote(match.group(1))
                filename = (
                    "manifest.json" if match.group(2) == "manifest" else unquote(match.group(3))
                )
                if not _safe_component(session_id) or not _safe_component(filename):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unsafe_path"})
                    return
                self._send_file(config.root / session_id / filename)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != "/api/sync/ack":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if (
                config.token is not None
                and self.headers.get("Authorization") != f"Bearer {config.token}"
            ):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            self._send_json(
                HTTPStatus.OK,
                {"status": "acknowledged", "deleted": False, "synthetic": True},
            )

    return DemoLoggerHandler


def create_demo_server(
    root: Path | str,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    server_factory: Callable[..., ThreadingHTTPServer] = ThreadingHTTPServer,
) -> ThreadingHTTPServer:
    fixture_root = Path(root).resolve()
    if not (fixture_root / "device.json").is_file():
        raise FileNotFoundError(f"Synthetic device fixture not found under {fixture_root}")
    return server_factory((host, port), make_demo_handler(DemoServerConfig(fixture_root, token)))
