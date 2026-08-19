# Jarred Drive

Jarred Drive is a local-first foil-assist flight recorder and analytics system. It combines a read-only
ESP32 instrument/logger with a Streamlit post-session application for equipment health, VESC configuration
tracking, foiling analytics, GPS routes, and manual event annotation.

> **Safety boundary:** VESC controls propulsion. VX3 controls the VESC. Jarred Drive observes and records.
> The ESP32 is never required for throttle or failsafe behavior, and this version contains no VESC write path.

## What is working

- Versioned 10 Hz raw telemetry contract covering VESC, six pack temperatures, enclosure temperature,
  pulsed water sensor, QMI8658 IMU, health flags, and optional GNSS.
- Deterministic coupled simulation for a learning session, a Pack 4 thermal anomaly, and a latched
  water-ingress/VESC-fault drill, including launches, aborts, crashes, turns, GPS motion, IMU dynamics,
  voltage sag, thermal response, GNSS dropout, and logger-health degradation.
- Raw → detected events → rides → session summaries, with confidence and provenance retained.
- Streamlit Devices / Sync, Flight Deck, Launch Lab, Ride Dynamics, Thermal Lab, System Health, Tuning,
  Progress, Annotation, and Raw Data views.
- A responsive cockpit-inspired visual system with compact navigation, session provenance chips, health-state
  banners, consistent metric cards, and GPU-independent SVG analytical charts.
- Home-LAN logger protocol with mDNS naming, REST manifests, resumable file downloads, SHA-256 verification,
  duplicate-safe imports, immutable raw storage, QA reports, and DuckDB/Parquet processed storage.
- A filesystem-backed synthetic logger that exercises the complete synchronization workflow before hardware
  exists. It uses the same manifests and verification code as a physical logger.
- Aligned launch power curves, failed-launch classification, crash windows, GPS turn dynamics, phase-specific
  thermal/electrical analysis, logger integrity, and configuration comparisons.
- Manual annotations stored separately and merged without destroying detector output.
- PlatformIO firmware targeting Waveshare ESP32-S3-LCD-1.47B, plus host-native safety-policy tests.

Synthetic content is labeled as such throughout. It demonstrates the workflows; it is not evidence of actual
hardware behavior, classification accuracy, thermal limits, or performance.

Metric definitions and inference boundaries are documented in [docs/analytics.md](docs/analytics.md).

GPS support is optional and ready in software, but the current Flipsky VESC and Waveshare board do not contain
a receiver. Field GPS requires a separate Phase 2 UART NMEA GNSS module on the reserved ESP GPIO2/GPIO3 pair.

## Quick start

Prerequisites: pyenv, Python 3.12.6, Poetry 1.8+, and a VS Code or shell terminal.

```bash
pyenv install -s 3.12.6
pyenv local 3.12.6
poetry env use "$(pyenv which python)"
poetry install
make demo
make check
make dashboard
```

The launcher checks local ports beginning at `8501`, selects the first available one, and prints the exact
URL to open. The newest demo session is selected by default. To begin the search elsewhere:

```bash
JARRED_DRIVE_PORT_START=8600 make dashboard
```

## Common workflows

```bash
# Validate a logger export
poetry run jarred-drive validate-log path/to/telemetry.csv

# Recompute a summary with the transparent baseline detector
poetry run jarred-drive summarize path/to/telemetry.csv --output analysis.json
# Also writes events, rides, launches, crashes, thermal/electrical phases, and monitoring files.

# Register the matching read-only VESC Tool snapshot
poetry run jarred-drive register-config path/to/FOIL_012.json

# Exercise a complete sync against the synthetic development logger
poetry run jarred-drive sync --url demo

# Sync a physical logger after explicitly placing it in SYNC mode
poetry run jarred-drive sync --url http://jarred-drive.local --token YOUR_LOCAL_DEVICE_TOKEN

# Build the actual board firmware (does not flash hardware)
make firmware-hardware
```

The demo logger lives in `data/demo/`. Verified raw copies go under ignored `data/raw/<device>/<session>/`;
replaceable DuckDB/Parquet outputs go under ignored `data/processed/`; manual labels remain under ignored
`data/annotations/`. No cloud service is used and the app never deletes logger data.

## Documentation

- [Architecture](docs/architecture.md)
- [Data contract](docs/data_contract.md)
- [Synchronization](docs/synchronization.md)
- [Safety case](docs/safety.md)
- [Hardware validation gates](docs/hardware_validation.md)
- [Reference projects](docs/references.md)
- [Development and validation](docs/development.md)
