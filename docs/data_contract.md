# Raw telemetry contract

Schema version `1.0.0` is a row-oriented CSV designed for append-only microSD logging. One file contains one
session and timestamps increase monotonically. The ESP firmware emits the required fields documented by
`jarred_drive.schema.REQUIRED_COLUMNS`.

Optional GNSS is all-or-nothing:

- `gps_lat`, `gps_lon`
- `gps_speed_mps`, `gps_course_deg`
- `gps_fix_quality`

A log without GNSS remains valid and supports all non-spatial analytics. The desktop application treats
unknown additional columns as forward-compatible observations.

`remote_ok` is nullable because the passive VESC UART path cannot prove VX3 link status. Blank means UNKNOWN,
not OK. The dashboard warns on UNKNOWN and stops only when a future independent input explicitly reports
false. It never infers remote health from ordinary VESC telemetry.

Synthetic files add `sim_state` and `scenario`. These are explicitly synthetic-only and will never be expected
from field hardware.

## Derived tables

Events contain `session_id`, `timestamp_ms`, `event_type`, `confidence`, `source`, and `notes`. Supported
events include motor start/stop, start attempt, takeoff, touchdown, recovery, fall, water detected, temperature
warning, VESC fault, and session boundaries.

Ride records describe a successful takeoff through fall/session end and may include multiple flight segments
separated by recovered touchdowns. Session summaries aggregate attempts, launch success, foil utilization,
energy, distance, speed, thermal behavior, alarms, and ride-duration metrics.

## Evolution rules

1. Never silently reinterpret an existing field or unit.
2. Add optional fields without changing the version only when old readers can ignore them safely.
3. Increment the schema version for renamed fields, new required fields, or semantic/unit changes.
4. Preserve the original raw file and regenerate derived tables after migrations.
5. Store the VESC configuration ID with every row and keep the immutable snapshot beside the session.

Use `configs/vesc_snapshot_template.json` to record a VESC Tool snapshot, then register it locally with
`jarred-drive register-config`. Set the same ID in `firmware/include/device_config.hpp` before compiling the
field firmware. This is an association and audit mechanism only; it never applies settings to the VESC.
