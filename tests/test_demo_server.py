from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarred_drive.config import load_config
from jarred_drive.demo_server import create_demo_server
from jarred_drive.sync import HttpLoggerClient, SessionStore, sync_logger
from jarred_drive.synthetic import write_demo_package


@pytest.fixture
def demo_url(tmp_path: Path) -> Iterator[str]:
    fixtures = tmp_path / "demo"
    write_demo_package(fixtures, load_config())
    server = create_demo_server(fixtures, port=0, token="test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_demo_server_uses_logger_protocol_and_syncs(demo_url: str, tmp_path: Path) -> None:
    client = HttpLoggerClient(demo_url)
    device = client.device()
    assert device.device_id == "jarred-drive-sim-01"
    assert device.mode == "SYNC"
    assert device.data_kind == "synthetic"
    assert device.capabilities and device.capabilities["config_write"] is False
    assert len(client.session_ids()) == 4

    results = sync_logger(
        client,
        SessionStore(tmp_path / "raw", tmp_path / "processed"),
        token="test-token",
    )
    assert {result.status for result in results} == {"imported"}
    assert all(result.validation and result.validation.valid for result in results)


def test_demo_server_supports_range_downloads(demo_url: str) -> None:
    session_id = "2026-08-10-001"
    manifest = json.loads(
        urllib.request.urlopen(f"{demo_url}/api/sessions/{session_id}/manifest").read()
    )
    telemetry = next(item for item in manifest["files"] if item["name"] == "telemetry.csv")
    request = urllib.request.Request(
        f"{demo_url}/api/sessions/{session_id}/files/telemetry.csv",
        headers={"Range": "bytes=100-"},
    )
    with urllib.request.urlopen(request) as response:
        assert response.status == 206
        assert response.headers["Content-Range"].startswith("bytes 100-")
        assert len(response.read()) == telemetry["size"] - 100


def test_demo_server_acknowledgement_requires_configured_token(demo_url: str) -> None:
    request = urllib.request.Request(
        f"{demo_url}/api/sync/ack",
        data=b'{"session_id":"2026-08-10-001"}',
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request)
    assert caught.value.code == 401


def test_demo_server_rejects_path_traversal(demo_url: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{demo_url}/api/sessions/%2E%2E/manifest")
    assert caught.value.code == 400
