# Logger synchronization

## Normal workflow

1. Finish the ride while the logger remains independently powered.
2. Stop recording; firmware flushes and closes all files, writes the configuration association, calculates
   SHA-256 hashes, and finalizes `manifest.json`.
3. At home, connect USB-C and explicitly enter SYNC. Only this mode enables Wi-Fi.
4. Open **Devices / Sync**. The app tries `http://jarred-drive.local`; a direct LAN IP can be entered when mDNS
   is unavailable.
5. The app compares remote session IDs to its DuckDB catalog, downloads only missing sessions, resumes a
   `.part` file with HTTP Range, verifies every size/hash, runs QA, writes Parquet, and then acknowledges import.
6. The logger retains its authoritative SD copy. Deletion is never automatic and is not exposed in this app.

The `poetry run jarred-drive sync --url demo` command exercises exactly this pipeline against synthetic files.

## iPhone and desktop coexistence

The ESP microSD remains the shared source of truth. The iPhone and Streamlit computer each independently pull
the same finalized manifest and raw files, verify the same SHA-256 hashes, and retain their own local copy.
They therefore agree by content identity without requiring the computer to relay data to the phone or a cloud
database. During development, `jarred-drive serve-demo` makes the computer impersonate that read-only ESP API,
so synthetic sessions exercise the actual iPhone transport.

The first native prototype does not upload phone-only data back to the computer. That is not needed for ESP
sessions because acknowledgement never deletes the authoritative microSD copy. A later peer-reconciliation
feature can exchange manifests if field experience reveals a real gap; it should not create a second mutable
raw-data authority.

## REST contract

- `GET /api/device`
- `GET /api/status`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}/manifest`
- `GET /api/sessions/{session_id}/files/{filename}` with optional `Range: bytes=N-`
- `POST /api/sync/ack` with `Authorization: Bearer <device-token>`

Read endpoints exist only while the logger is in SYNC mode. Write-side acknowledgement is authenticated. There
is deliberately no VESC control/configuration endpoint, no cloud dependency, and no automatic raw-data delete.

The native app currently uses the read endpoints only. Its configuration view is an immutable snapshot; VESC
changes remain a separate, deliberate VESC Tool operation performed ashore.

## Local storage

```text
data/
  raw/<device_id>/<session_id>/
    manifest.json
    telemetry.*
    imu.*                 # when full-rate logger output is enabled
    config.json
    import_qa.json
  processed/
    jarred_drive.duckdb
    sessions/<session_id>/telemetry.parquet
```

Raw files are immutable evidence. DuckDB, Parquet, events, rides, and features are replaceable products. CSV is
supported as the initial wire/log format and manual-debug fallback, but it is not the analytical store.

## Current limits

- The app uses the logger's known mDNS hostname rather than scanning the LAN for every `_http._tcp` device.
- The firmware manifest has empty UTC start/end values until GNSS time capture is completed.
- Full-rate `imu.bin`, BLE provisioning, USB-power auto-SYNC, a physical mode button, persistent on-device ack
  markers, and authenticated configuration/firmware update endpoints are intentionally deferred.
- A successful build and synthetic sync do not validate Wi-Fi range through the sealed enclosure, SD endurance,
  power behavior, or interrupted transfers on the actual board; those remain hardware gates.
