# Validation report

Validated on 2026-08-19 using Python 3.12.6, Poetry 1.8.3, and the checked-in lock file.

## Software evidence

- `make check` passed: Ruff, Black, mypy across 22 source files, 33 pytest cases, four native
  firmware safety-policy tests, and `poetry check --lock`.
- `make firmware-hardware` compiled the `waveshare_esp32s3` environment successfully. The resulting
  image used 21,292 bytes of RAM (6.5%) and 415,405 bytes of flash (6.3%). This was a compile check,
  not a physical flash or sensor test.
- Streamlit AppTest exercised all nine pages against all three scenarios: Flight Deck, Launch Lab, Ride
  Dynamics, Thermal Lab, System Health, Tuning, Progress, Annotate, and Raw Data.
- A real Streamlit server returned HTTP 200 and a healthy status. Headless Chrome reached the app with
  a `CONNECTED` state; the final Flight Deck was visually inspected at 1600 x 1100. Computed heading
  and metric text colors were `rgb(230, 251, 255)` against the dark dashboard. Launch curves, crash windows,
  the meter-scaled GPS trajectory, turn dynamics, and thermal diagnostics were visually inspected at
  1720 x 1200. GPS plots were verified without network map tiles, and long diagnostics were verified in a
  GPU-disabled browser without WebGL errors.
- The committed synthetic package contains 35 artifacts across three deterministic coupled scenarios,
  including raw telemetry, launch/crash/thermal/electrical/logger derived tables, and immutable configuration
  snapshots. The safety-drill session renders a latched STOP SYSTEM state.

## Synthetic scenario results

These numbers demonstrate software behavior only. They are not on-water performance claims.

| Configuration | Scenario | Launch success | Failed rate | Launch crashes | Ride falls | Foil utilization | Energy | Peak pack | Pack spread | Longest ride |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FOIL_001 | Learning session | 75.0% | 25.0% | 1 | 6 | 56.6% | 113.2 Wh | 24.6 C | 0.6 C | 68 s |
| FOIL_002 | Pack 4 thermal anomaly | 100.0% | 0.0% | 0 | 8 | 66.5% | 172.4 Wh | 47.4 C | 22.8 C | 74 s |
| FOIL_003 | Ingress safety drill | 100.0% | 0.0% | 0 | 6 | 57.2% | 93.8 Wh | 24.1 C | 0.6 C | 70 s |

## Physical validation still required

Software completion does not establish that the unbuilt hardware is safe or field-ready. Before powered or
on-water use, complete every gate in [hardware_validation.md](hardware_validation.md), including physical
firmware flash/display checks, exact board pin confirmation, QMI8658 scaling, each NTC channel, water-sensor
calibration, microSD behavior, read-only VESC UART verification, fault injection, enclosure/EMI testing, and
classifier calibration from real sessions. GPS additionally requires and must validate a separate 3.3 V UART
NMEA GNSS receiver; neither selected board includes one.
