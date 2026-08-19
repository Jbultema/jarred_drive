# Validation report

Validated on 2026-08-19 using Python 3.12.6, Poetry 1.8.3, and the checked-in lock file.

## Software evidence

- `make check` passed: Ruff, Black, mypy across 19 source files, 23 pytest cases, four native
  firmware safety-policy tests, and `poetry check --lock`.
- `make firmware-hardware` compiled the `waveshare_esp32s3` environment successfully. The resulting
  image used 21,292 bytes of RAM (6.5%) and 415,405 bytes of flash (6.3%). This was a compile check,
  not a physical flash or sensor test.
- Streamlit AppTest exercised Flight Deck, Rides, Equipment, Tuning, Progress, Annotate, and Raw Data.
- A real Streamlit server returned HTTP 200 and a healthy status. Headless Chrome reached the app with
  a `CONNECTED` state; the final Flight Deck was visually inspected at 1600 x 1100. Computed heading
  and metric text colors were `rgb(230, 251, 255)` against the dark dashboard after correcting the
  initial contrast defect.
- The committed synthetic package contains three deterministic sessions and immutable configuration
  snapshots. The safety-drill session renders a latched STOP SYSTEM state.

## Synthetic scenario results

These numbers demonstrate software behavior only. They are not on-water performance claims.

| Configuration | Scenario | Launch success | Foil utilization | Energy | Peak pack | Longest ride |
|---|---|---:|---:|---:|---:|---:|
| FOIL_001 | Learning session | 85.7% | 55.5% | 86.2 Wh | 23.6 C | 68 s |
| FOIL_002 | Pack 4 thermal anomaly | 100.0% | 66.5% | 142.7 Wh | 41.3 C | 74 s |
| FOIL_003 | Ingress safety drill | 100.0% | 57.2% | 79.0 Wh | 23.6 C | 70 s |

## Physical validation still required

Software completion does not establish that the unbuilt hardware is safe or field-ready. Before powered or
on-water use, complete every gate in [hardware_validation.md](hardware_validation.md), including physical
firmware flash/display checks, exact board pin confirmation, QMI8658 scaling, each NTC channel, water-sensor
calibration, microSD behavior, read-only VESC UART verification, fault injection, enclosure/EMI testing, and
classifier calibration from real sessions. GPS additionally requires and must validate a separate 3.3 V UART
NMEA GNSS receiver; neither selected board includes one.
