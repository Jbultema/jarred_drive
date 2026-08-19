# Architecture

Jarred Drive has two deliberately independent runtimes.

```text
VX3 --PPM--> VESC --3 phase--> motor
               |
               | read-only UART telemetry
               v
6 NTCs ----> ESP32-S3 <---- QMI8658 IMU
enclosure -->    |  |
water probe -->  |  +---- local high-contrast status display
                 +------- microSD authoritative session folders
                              |
                    home only | Wi-Fi REST + SHA-256
                              v
                    immutable local raw copy
                              |
                              v
                 DuckDB/Parquet -> Streamlit analytics
```

The propulsion path remains complete if the ESP32 is absent, rebooting, or failed. The firmware polls VESC
telemetry but exposes no command or configuration-write API.

## Repository layers

- `firmware/`: on-water observer/logger and deterministic local safety presentation.
- `src/jarred_drive/schema.py`: versioned logger contract and import validation.
- `src/jarred_drive/sync.py`: device protocol, resumable/hash-verified transfer, raw store, and analytical
  catalog.
- `src/jarred_drive/events.py`: replaceable, transparent baseline event detector.
- `src/jarred_drive/analytics.py`: launch, crash, ride, thermal, electrical, logger-health, session, and
  progression metrics.
- `src/jarred_drive/annotations.py`: human ground-truth labels with provenance.
- `src/jarred_drive/dashboard/`: local Streamlit analytical application.
- `data/demo/`: deterministic synthetic fixture package.

Raw telemetry is immutable input. Events, rides, and summaries are derivative products and should be
regenerated whenever detection logic changes.

## Logger state model

The firmware has explicit PRE_RIDE, RECORDING, POST_RIDE, CHARGING_IDLE, and SYNC states. Radios are allowed
only in SYNC. RECORDING must stop and finalize its open files before SYNC can begin. The present bench control
uses serial `START`, `STOP`, `SYNC`, and `IDLE` commands until the final enclosure button mapping is validated.
The firmware currently starts recording at boot to preserve the existing logger behavior.

The sync transport is deliberately ordinary: the ESP advertises `jarred-drive.local`, publishes read-only
device/session endpoints, serves files with HTTP Range support, and authenticates the write-side sync
acknowledgement. The acknowledgement records transfer state only; it never deletes raw files.

## Operating modes

- **SYSTEM:** Flight Deck, Thermal Lab, and System Health answer whether the system was safe and healthy.
- **VESC / TUNING:** immutable configuration snapshots connect outcomes to settings; all views are read-only.
- **FOILING:** state timelines, launch curves/outcomes, GPS turns, ride stability, touchdown recovery, crash
  dynamics, energy, and progression.

The selected VESC and Waveshare board do not contain GNSS. Phase 2 reserves GPIO2 RX / GPIO3 TX for an
external 3.3 V UART NMEA module; the schema and dashboard already support its fields without requiring them.

The 1.47-inch device display prioritizes SYSTEM status. Rich tuning and foiling analysis belongs in the
post-session Streamlit application where screen area and interaction are safe.
