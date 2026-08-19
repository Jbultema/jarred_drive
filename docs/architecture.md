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
                 +------- microSD raw CSV
                              |
                              v
                    Streamlit application
                  raw -> events -> rides -> sessions
```

The propulsion path remains complete if the ESP32 is absent, rebooting, or failed. The firmware polls VESC
telemetry but exposes no command or configuration-write API.

## Repository layers

- `firmware/`: on-water observer/logger and deterministic local safety presentation.
- `src/jarred_drive/schema.py`: versioned logger contract and import validation.
- `src/jarred_drive/events.py`: replaceable, transparent baseline event detector.
- `src/jarred_drive/analytics.py`: equipment, ride, session, energy, and progression metrics.
- `src/jarred_drive/annotations.py`: human ground-truth labels with provenance.
- `src/jarred_drive/dashboard/`: local Streamlit analytical application.
- `data/demo/`: deterministic synthetic fixture package.

Raw telemetry is immutable input. Events, rides, and summaries are derivative products and should be
regenerated whenever detection logic changes.

## Operating modes

- **SYSTEM:** Flight Deck and Equipment pages answer whether the system was safe and healthy.
- **VESC / TUNING:** immutable configuration snapshots connect outcomes to settings; all views are read-only.
- **FOILING:** state timelines, routes, attempts, launches, rides, touchdowns, falls, energy, and progression.

The selected VESC and Waveshare board do not contain GNSS. Phase 2 reserves GPIO2 RX / GPIO3 TX for an
external 3.3 V UART NMEA module; the schema and dashboard already support its fields without requiring them.

The 1.47-inch device display prioritizes SYSTEM status. Rich tuning and foiling analysis belongs in the
post-session Streamlit application where screen area and interaction are safe.
