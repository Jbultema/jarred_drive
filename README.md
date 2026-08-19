# Jarred Drive

Jarred Drive is a local-first foil-assist flight recorder and analytics system. It combines a read-only
ESP32 instrument/logger with a Streamlit post-session application for equipment health, VESC configuration
tracking, foiling analytics, GPS routes, and manual event annotation.

> **Safety boundary:** VESC controls propulsion. VX3 controls the VESC. Jarred Drive observes and records.
> The ESP32 is never required for throttle or failsafe behavior, and this version contains no VESC write path.

## What is working

- Versioned 10 Hz raw telemetry contract covering VESC, six pack temperatures, enclosure temperature,
  pulsed water sensor, QMI8658 IMU, health flags, and optional GNSS.
- Deterministic synthetic sessions for a normal learning session, a Pack 4 thermal anomaly, and a latched
  water-ingress/VESC-fault drill.
- Raw → detected events → rides → session summaries, with confidence and provenance retained.
- Streamlit Flight Deck, Rides, Equipment, Tuning, Progress, Annotation, and Raw Data views.
- GPS route coloring, launch/ride/energy metrics, thermal spread diagnostics, and configuration comparisons.
- Manual annotations stored separately and merged without destroying detector output.
- PlatformIO firmware targeting Waveshare ESP32-S3-LCD-1.47B, plus host-native safety-policy tests.

Synthetic content is labeled as such throughout. It demonstrates the workflows; it is not evidence of actual
hardware behavior, classification accuracy, thermal limits, or performance.

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

Open the local URL printed by Streamlit. The newest demo session is selected by default.

## Common workflows

```bash
# Validate a logger export
poetry run jarred-drive validate-log path/to/telemetry.csv

# Recompute a summary with the transparent baseline detector
poetry run jarred-drive summarize path/to/telemetry.csv

# Register the matching read-only VESC Tool snapshot
poetry run jarred-drive register-config path/to/FOIL_012.json

# Build the actual board firmware (does not flash hardware)
make firmware-hardware
```

The demo data lives in `data/demo/`. Real imports go under ignored `data/imports/`; manual labels go under
ignored `data/annotations/`. No session data is uploaded anywhere by the application.

## Documentation

- [Architecture](docs/architecture.md)
- [Data contract](docs/data_contract.md)
- [Safety case](docs/safety.md)
- [Hardware validation gates](docs/hardware_validation.md)
- [Reference projects](docs/references.md)
- [Development and validation](docs/development.md)
