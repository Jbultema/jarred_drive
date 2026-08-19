"""Offline logger discovery and checksum-verified session synchronization.

microSD remains authoritative.  This module only copies raw files, verifies them,
and creates replaceable analytical artifacts after the immutable copy is sound.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

import duckdb

from jarred_drive.io import read_telemetry
from jarred_drive.schema import ValidationReport, validate_telemetry

MANIFEST_SCHEMA_VERSION = "1.0"
DEFAULT_DEVICE_URL = "http://jarred-drive.local"


class SyncError(RuntimeError):
    """A transfer or remote-protocol failure."""


@dataclass(frozen=True)
class ManifestFile:
    name: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ManifestFile:
        name = str(payload.get("name", ""))
        path = PurePosixPath(name)
        if not name or path.name != name or name in {".", ".."}:
            raise SyncError(f"Unsafe manifest filename: {name!r}")
        raw_size = payload.get("size", -1)
        if not isinstance(raw_size, (int, float, str)):
            raise SyncError(f"Invalid size for {name}")
        size = int(raw_size)
        digest = str(payload.get("sha256", "")).lower()
        if size < 0 or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise SyncError(f"Invalid file metadata for {name}")
        return cls(name=name, size=size, sha256=digest)


@dataclass(frozen=True)
class SessionManifest:
    schema_version: str
    telemetry_schema_version: str
    device_id: str
    session_id: str
    start_time_utc: str
    end_time_utc: str
    duration_s: float
    firmware_version: str
    hardware_revision: str
    vesc_config_id: str
    vesc_config_hash: str
    files: tuple[ManifestFile, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> SessionManifest:
        raw_files = payload.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise SyncError("Session manifest must contain at least one file")
        files = tuple(ManifestFile.from_dict(item) for item in raw_files if isinstance(item, dict))
        if len(files) != len(raw_files):
            raise SyncError("Every manifest file entry must be an object")
        if len({item.name for item in files}) != len(files):
            raise SyncError("Manifest contains duplicate filenames")
        raw_duration = payload.get("duration_s", 0.0)
        if not isinstance(raw_duration, (int, float, str)):
            raise SyncError("Manifest duration must be numeric")
        manifest = cls(
            schema_version=str(payload.get("schema_version", "")),
            telemetry_schema_version=str(payload.get("telemetry_schema_version", "")),
            device_id=str(payload.get("device_id", "")),
            session_id=str(payload.get("session_id", "")),
            start_time_utc=str(payload.get("start_time_utc", "")),
            end_time_utc=str(payload.get("end_time_utc", "")),
            duration_s=float(raw_duration),
            firmware_version=str(payload.get("firmware_version", "")),
            hardware_revision=str(payload.get("hardware_revision", "")),
            vesc_config_id=str(payload.get("vesc_config_id", "")),
            vesc_config_hash=str(payload.get("vesc_config_hash", "")),
            files=files,
        )
        if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
            raise SyncError(f"Unsupported manifest schema {manifest.schema_version!r}")
        for label, value in (
            ("device_id", manifest.device_id),
            ("session_id", manifest.session_id),
        ):
            if not value or PurePosixPath(value).name != value:
                raise SyncError(f"Invalid {label}: {value!r}")
        if not any(item.name.startswith("telemetry.") for item in files):
            raise SyncError("Manifest does not include telemetry")
        return manifest

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "telemetry_schema_version": self.telemetry_schema_version,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "duration_s": self.duration_s,
            "firmware_version": self.firmware_version,
            "hardware_revision": self.hardware_revision,
            "vesc_config_id": self.vesc_config_id,
            "vesc_config_hash": self.vesc_config_hash,
            "files": [item.__dict__ for item in self.files],
        }


@dataclass(frozen=True)
class DeviceInfo:
    device_id: str
    name: str
    hardware_revision: str
    firmware_version: str
    mode: str
    battery_percent: float
    sd_free_percent: float


@dataclass(frozen=True)
class SyncResult:
    session_id: str
    status: str
    downloaded_bytes: int
    verified_files: int
    validation: ValidationReport | None
    message: str


ProgressCallback = Callable[[str, str, int, int], None]


class LoggerClient(Protocol):
    def device(self) -> DeviceInfo: ...

    def session_ids(self) -> list[str]: ...

    def manifest(self, session_id: str) -> SessionManifest: ...

    def download(self, session_id: str, filename: str, destination: Path, offset: int) -> int: ...

    def acknowledge(self, session_id: str, token: str | None = None) -> None: ...


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class FilesystemLoggerClient:
    """A deterministic development logger backed by generated demo folders."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def device(self) -> DeviceInfo:
        path = self.root / "device.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DeviceInfo(**payload)

    def session_ids(self) -> list[str]:
        return sorted(
            path.parent.name
            for path in self.root.glob("*/manifest.json")
            if path.parent != self.root
        )

    def manifest(self, session_id: str) -> SessionManifest:
        path = self.root / session_id / "manifest.json"
        return SessionManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def download(self, session_id: str, filename: str, destination: Path, offset: int) -> int:
        source = self.root / session_id / filename
        if not source.is_file():
            raise SyncError(f"Mock logger file not found: {filename}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        copied = 0
        with source.open("rb") as reader, destination.open("ab" if offset else "wb") as writer:
            reader.seek(offset)
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
                copied += len(chunk)
        return copied

    def acknowledge(self, session_id: str, token: str | None = None) -> None:
        del session_id, token  # The tracked synthetic fixture is intentionally immutable.


class HttpLoggerClient:
    """Small REST client for the ESP home-LAN API; no cloud service is involved."""

    def __init__(self, base_url: str = DEFAULT_DEVICE_URL, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _json(self, path: str) -> dict[str, object] | list[object]:
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise SyncError(f"Logger request failed for {path}: {error}") from error

    def device(self) -> DeviceInfo:
        payload = self._json("/api/device")
        if not isinstance(payload, dict):
            raise SyncError("Device endpoint did not return an object")
        status = self._json("/api/status")
        if not isinstance(status, dict):
            raise SyncError("Status endpoint did not return an object")
        raw_battery = status.get("battery_percent", 0.0)
        raw_sd_free = status.get("sd_free_percent", 0.0)
        if not isinstance(raw_battery, (int, float, str)) or not isinstance(
            raw_sd_free, (int, float, str)
        ):
            raise SyncError("Device battery and storage status must be numeric")
        return DeviceInfo(
            device_id=str(payload.get("device_id", "")),
            name=str(payload.get("name", payload.get("device_id", "Jarred Drive Logger"))),
            hardware_revision=str(payload.get("hardware_revision", "unknown")),
            firmware_version=str(payload.get("firmware_version", "unknown")),
            mode=str(status.get("mode", "UNKNOWN")),
            battery_percent=float(raw_battery),
            sd_free_percent=float(raw_sd_free),
        )

    def session_ids(self) -> list[str]:
        payload = self._json("/api/sessions")
        if not isinstance(payload, list):
            raise SyncError("Sessions endpoint did not return a list")
        return [str(item["session_id"] if isinstance(item, dict) else item) for item in payload]

    def manifest(self, session_id: str) -> SessionManifest:
        safe_id = urllib.parse.quote(session_id, safe="")
        payload = self._json(f"/api/sessions/{safe_id}/manifest")
        if not isinstance(payload, dict):
            raise SyncError("Manifest endpoint did not return an object")
        return SessionManifest.from_dict(payload)

    def download(self, session_id: str, filename: str, destination: Path, offset: int) -> int:
        safe_id = urllib.parse.quote(session_id, safe="")
        safe_name = urllib.parse.quote(filename, safe="")
        request = urllib.request.Request(
            f"{self.base_url}/api/sessions/{safe_id}/files/{safe_name}",
            headers={"Range": f"bytes={offset}-"} if offset else {},
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout_s)
        except (OSError, urllib.error.URLError) as error:
            raise SyncError(f"Download failed for {filename}: {error}") from error
        accepted_resume = offset > 0 and getattr(response, "status", 200) == 206
        mode = "ab" if accepted_resume else "wb"
        copied = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        with response, destination.open(mode) as writer:
            while chunk := response.read(1024 * 1024):
                writer.write(chunk)
                copied += len(chunk)
        return copied

    def acknowledge(self, session_id: str, token: str | None = None) -> None:
        payload = json.dumps({"session_id": session_id}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base_url + "/api/sync/ack", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                if response.status >= 300:
                    raise SyncError(f"Logger rejected acknowledgement: HTTP {response.status}")
        except (OSError, urllib.error.URLError) as error:
            raise SyncError(f"Session imported but acknowledgement failed: {error}") from error


class SessionStore:
    """Immutable raw hierarchy plus replaceable DuckDB/Parquet derivatives."""

    def __init__(self, raw_root: Path | str, processed_root: Path | str) -> None:
        self.raw_root = Path(raw_root)
        self.processed_root = Path(processed_root)
        self.database_path = self.processed_root / "jarred_drive.duckdb"

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self.processed_root.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.database_path))
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
              device_id VARCHAR PRIMARY KEY, name VARCHAR, hardware_revision VARCHAR,
              firmware_version VARCHAR, last_sync_time TIMESTAMP, logger_battery_percent DOUBLE
            );
            CREATE TABLE IF NOT EXISTS sessions (
              session_id VARCHAR PRIMARY KEY, device_id VARCHAR, start_time_utc VARCHAR,
              end_time_utc VARCHAR, duration_s DOUBLE, vesc_config_id VARCHAR,
              firmware_version VARCHAR, hardware_revision VARCHAR, schema_version VARCHAR,
              imported_at TIMESTAMP, qa_valid BOOLEAN, raw_path VARCHAR, parquet_path VARCHAR
            );
            """
        )
        return connection

    def known_sessions(self, device_id: str) -> set[str]:
        if not self.database_path.exists():
            return set()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id FROM sessions WHERE device_id = ?", [device_id]
            ).fetchall()
        return {str(row[0]) for row in rows}

    def record_device(self, device: DeviceInfo) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM devices WHERE device_id = ?", [device.device_id])
            connection.execute(
                "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?)",
                [
                    device.device_id,
                    device.name,
                    device.hardware_revision,
                    device.firmware_version,
                    datetime.now(UTC).replace(tzinfo=None),
                    device.battery_percent,
                ],
            )

    def import_verified(
        self, manifest: SessionManifest, session_dir: Path
    ) -> tuple[ValidationReport, Path]:
        telemetry_candidates = [
            item.name for item in manifest.files if item.name == "telemetry.csv"
        ]
        if not telemetry_candidates:
            raise SyncError(
                "This app version can preserve but cannot yet process non-CSV telemetry"
            )
        telemetry_path = session_dir / telemetry_candidates[0]
        frame = read_telemetry(telemetry_path)
        report = validate_telemetry(frame)
        telemetry_versions = set(frame["schema_version"].dropna().astype(str))
        if telemetry_versions != {manifest.telemetry_schema_version}:
            raise SyncError(
                "Telemetry schema does not match the version declared by the session manifest"
            )
        qa_path = session_dir / "import_qa.json"
        qa_path.write_text(
            json.dumps({"valid": report.valid, "issues": report.as_dicts()}, indent=2) + "\n",
            encoding="utf-8",
        )
        if not report.valid:
            raise SyncError("Raw files verified, but telemetry failed data-quality validation")
        parquet_dir = self.processed_root / "sessions" / manifest.session_id
        parquet_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = parquet_dir / "telemetry.parquet"
        with self._connect() as connection:
            connection.register("telemetry_frame", frame)
            connection.execute("COPY telemetry_frame TO ? (FORMAT PARQUET)", [str(parquet_path)])
            connection.unregister("telemetry_frame")
            connection.execute("DELETE FROM sessions WHERE session_id = ?", [manifest.session_id])
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    manifest.session_id,
                    manifest.device_id,
                    manifest.start_time_utc,
                    manifest.end_time_utc,
                    manifest.duration_s,
                    manifest.vesc_config_id,
                    manifest.firmware_version,
                    manifest.hardware_revision,
                    manifest.telemetry_schema_version,
                    datetime.now(UTC).replace(tzinfo=None),
                    report.valid,
                    str(session_dir),
                    str(parquet_path),
                ],
            )
        return report, parquet_path


def sync_logger(
    client: LoggerClient,
    store: SessionStore,
    token: str | None = None,
    progress: ProgressCallback | None = None,
    session_ids: Iterable[str] | None = None,
) -> list[SyncResult]:
    """Copy, resume, hash-check, validate, process, and acknowledge logger sessions."""
    device = client.device()
    if device.mode.upper() != "SYNC":
        raise SyncError(f"Logger is in {device.mode} mode; enable SYNC before transfer")
    store.record_device(device)
    selected = list(session_ids) if session_ids is not None else client.session_ids()
    known = store.known_sessions(device.device_id)
    results: list[SyncResult] = []
    for session_id in selected:
        manifest = client.manifest(session_id)
        if manifest.device_id != device.device_id or manifest.session_id != session_id:
            raise SyncError(f"Manifest identity mismatch for {session_id}")
        session_dir = store.raw_root / device.device_id / session_id
        manifest_path = session_dir / "manifest.json"
        if session_id in known and manifest_path.exists():
            local_manifest = SessionManifest.from_dict(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            if local_manifest != manifest:
                raise SyncError(
                    f"Session ID collision: {session_id} has different remote and local manifests"
                )
            try:
                client.acknowledge(session_id, token)
                status = "already_imported"
                message = "No duplicate created; logger acknowledgement confirmed"
            except SyncError as error:
                status = "ack_pending"
                message = str(error)
            results.append(SyncResult(session_id, status, 0, 0, None, message))
            continue
        session_dir.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        verified = 0
        for item in manifest.files:
            destination = session_dir / item.name
            if destination.exists() and destination.stat().st_size == item.size:
                if sha256_file(destination) == item.sha256:
                    verified += 1
                    if progress:
                        progress(session_id, item.name, item.size, item.size)
                    continue
                destination.rename(destination.with_suffix(destination.suffix + ".invalid"))
            partial = destination.with_suffix(destination.suffix + ".part")
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > item.size:
                partial.unlink()
                offset = 0
            elif offset == item.size and offset > 0:
                if sha256_file(partial) == item.sha256:
                    partial.replace(destination)
                    verified += 1
                    if progress:
                        progress(session_id, item.name, item.size, item.size)
                    continue
                partial.rename(partial.with_suffix(partial.suffix + ".invalid"))
                offset = 0
            if progress:
                progress(session_id, item.name, offset, item.size)
            downloaded += client.download(session_id, item.name, partial, offset)
            if partial.stat().st_size != item.size or sha256_file(partial) != item.sha256:
                raise SyncError(
                    f"Checksum or size verification failed for {session_id}/{item.name}"
                )
            partial.replace(destination)
            verified += 1
            if progress:
                progress(session_id, item.name, item.size, item.size)
        manifest_path.write_text(json.dumps(manifest.as_dict(), indent=2) + "\n", encoding="utf-8")
        try:
            report, _ = store.import_verified(manifest, session_dir)
        except Exception:
            # Raw verified data is deliberately retained for repair/reprocessing.
            raise
        try:
            client.acknowledge(session_id, token)
            results.append(
                SyncResult(
                    session_id, "imported", downloaded, verified, report, "Verified and imported"
                )
            )
        except SyncError as error:
            results.append(
                SyncResult(
                    session_id,
                    "imported_ack_pending",
                    downloaded,
                    verified,
                    report,
                    str(error),
                )
            )
    return results


def copy_manual_session(source: Path, raw_root: Path, device_id: str = "manual-import") -> Path:
    """Preserve a manually supplied raw file in the same device/session hierarchy."""
    frame = read_telemetry(source)
    report = validate_telemetry(frame)
    if not report.valid:
        raise SyncError("Telemetry failed validation")
    session_ids = frame["session_id"].dropna().astype(str).unique()
    if len(session_ids) != 1:
        raise SyncError("One file must contain exactly one session")
    destination = Path(raw_root) / device_id / session_ids[0] / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
