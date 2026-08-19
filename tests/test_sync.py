from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from jarred_drive.config import load_config
from jarred_drive.sync import (
    FilesystemLoggerClient,
    ManifestFile,
    SessionStore,
    SyncError,
    sync_logger,
)
from jarred_drive.synthetic import write_demo_package


class AckFailingClient(FilesystemLoggerClient):
    def acknowledge(self, session_id: str, token: str | None = None) -> None:
        del session_id, token
        raise SyncError("bad token")


def _mock_logger(tmp_path: Path) -> Path:
    root = tmp_path / "logger"
    write_demo_package(root, load_config())
    return root


def test_sync_verifies_preserves_processes_and_deduplicates(tmp_path: Path) -> None:
    logger = _mock_logger(tmp_path)
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    client = FilesystemLoggerClient(logger)
    store = SessionStore(raw, processed)

    first = sync_logger(client, store)
    assert len(first) == 3
    assert {result.status for result in first} == {"imported"}
    assert all(result.validation and result.validation.valid for result in first)

    second = sync_logger(client, store)
    assert {result.status for result in second} == {"already_imported"}
    session_id = first[0].session_id
    assert (raw / "jarred-drive-sim-01" / session_id / "telemetry.csv").exists()
    assert (processed / "sessions" / session_id / "telemetry.parquet").exists()
    with duckdb.connect(str(processed / "jarred_drive.duckdb"), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (3,)


def test_corrupt_download_is_not_imported_or_acknowledged(tmp_path: Path) -> None:
    logger = _mock_logger(tmp_path)
    session_id = "2026-08-10-001"
    manifest_path = logger / session_id / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SyncError, match="Checksum or size"):
        sync_logger(
            FilesystemLoggerClient(logger),
            SessionStore(tmp_path / "raw", tmp_path / "processed"),
            session_ids=[session_id],
        )
    session = tmp_path / "raw" / "jarred-drive-sim-01" / session_id
    assert (session / "telemetry.csv.part").exists()
    assert not (session / "manifest.json").exists()


def test_manifest_rejects_path_traversal() -> None:
    with pytest.raises(SyncError, match="Unsafe"):
        ManifestFile.from_dict({"name": "../telemetry.csv", "size": 1, "sha256": "a" * 64})


def test_sync_requires_explicit_sync_mode(tmp_path: Path) -> None:
    logger = _mock_logger(tmp_path)
    device_path = logger / "device.json"
    device = json.loads(device_path.read_text(encoding="utf-8"))
    device["mode"] = "RECORDING"
    device_path.write_text(json.dumps(device), encoding="utf-8")
    with pytest.raises(SyncError, match="enable SYNC"):
        sync_logger(
            FilesystemLoggerClient(logger), SessionStore(tmp_path / "raw", tmp_path / "processed")
        )


def test_existing_session_id_with_changed_manifest_is_rejected(tmp_path: Path) -> None:
    logger = _mock_logger(tmp_path)
    store = SessionStore(tmp_path / "raw", tmp_path / "processed")
    client = FilesystemLoggerClient(logger)
    session_id = "2026-08-10-001"
    sync_logger(client, store, session_ids=[session_id])
    manifest_path = logger / session_id / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["firmware_version"] = "unexpected-rewrite"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SyncError, match="collision"):
        sync_logger(client, store, session_ids=[session_id])


def test_failed_ack_is_retriable_without_duplicate_import(tmp_path: Path) -> None:
    logger = _mock_logger(tmp_path)
    client = AckFailingClient(logger)
    store = SessionStore(tmp_path / "raw", tmp_path / "processed")
    session_id = "2026-08-10-001"
    first = sync_logger(client, store, session_ids=[session_id])
    second = sync_logger(client, store, session_ids=[session_id])
    assert first[0].status == "imported_ack_pending"
    assert second[0].status == "ack_pending"
