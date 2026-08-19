# Analytics reference

Jarred Drive derives analysis from immutable raw telemetry. Detector output is a reviewable baseline, not
ground truth: correct event timing on the Annotate page before using field results for tuning decisions.

## Launch analysis

An attempt begins at the transition into `ACCELERATING` and ends at the first applicable event before the
next attempt:

- `SUCCESS`: a `TAKEOFF` occurs.
- `LAUNCH_CRASH`: a `FALL` occurs before takeoff.
- `FAILED`: power stops or another attempt begins without takeoff or a detected fall.

For each attempt the application reports time to takeoff, power 10–90% rise time, peak and mean battery
power, launch energy, battery and motor current, duty, ERPM, speed, voltage sag, sag per kW, acceleration and
angular-rate transients, pack spread, and pack/VESC temperature rise. Aligned curves make the power ramp and
failed-attempt shape directly comparable. GPS speed is optional; ERPM and electrical metrics remain available
without it.

## Ride and crash dynamics

A ride runs from takeoff through the next fall or session end and can contain recovered touchdowns. Ride
metrics include flight time, energy per foil minute, mean/peak load, voltage floor, speed, duty, vibration,
angular-rate RMS/peak, touchdown recovery, and thermal rise.

Each `FALL` receives a three-second lead-in and 1.5-second impact window. A crash is classified as a launch
crash when the most recent attempt has no takeoff; otherwise it is a ride fall. The report preserves pre-fall
speed/power/duty, acceleration transient, axis-specific and total angular rate, voltage floor, time since
takeoff, and observed motor-power cut latency. No composite “severity” score is asserted because rider impact
is not measured by the enclosure-mounted IMU.

## Thermal and electrical analysis

All six pack sensors, VESC MOSFET, safety/motor NTC, and enclosure sensor retain full-session traces. The
Thermal Lab calculates start/end/rise, mean, p95, peak, rolling ten-second heating/cooling rate, pack spread,
launch-aligned temperatures, and phase-specific behavior for idle, acceleration, foiling, touchdown, and
fall. Threshold lines come from `configs/system.yaml`.

Electrical phase summaries report duration, energy, mean/p95/peak power, battery and motor current, minimum
voltage, maximum sag, duty, and ERPM. Jarred Drive does not report mechanical efficiency because shaft torque
is not measured.

## Logger and sensor monitoring

System Health reports effective sample rate, timestamp gaps and jitter, numeric completeness, GNSS fix
coverage, remote-status availability, SD-health coverage, VESC fault samples/codes, water-alarm samples,
water ADC floor, voltage envelope, current, and duty. A health flag is an observation, not proof that an
unobservable system—especially the VX3 radio link—is healthy.

## Synthetic simulator

The deterministic demo is designed for application development, not hardware prediction. It couples:

- attempt-specific successful, aborted, and launch-crash power curves;
- first-order speed response through acceleration, flight, touchdown, fall, and drift;
- alternating turns with integrated heading, latitude/longitude, GPS noise, and a controlled fix dropout;
- yaw rate and centripetal/longitudinal acceleration with localized fall-impact transients;
- current-dependent voltage sag and state-of-charge decline;
- thermal accumulation/cooling for every sensor, including a high-resistance Pack 4 anomaly;
- SD-health degradation, water ingress, and VESC-fault episodes.

Synthetic truth fields are prefixed `sim_` and never belong to the field logger contract. Replace simulator
assumptions with measured distributions once bench and on-water recordings exist.
