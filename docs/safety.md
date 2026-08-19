# Safety case and software boundary

Jarred Drive is instrumentation, not a propulsion safety controller. It cannot make the DIY electrical or
mechanical system safe by itself.

## Enforced boundaries

- VX3 uses PPM directly to the VESC; the ESP never relays throttle.
- VESC COMM UART is used only for telemetry requests in version 1.
- Wi-Fi is forced off when a recording begins and can only run in explicit SYNC mode after the session is
  closed and finalized. A native state-machine test enforces this transition boundary.
- Logger REST endpoints expose no throttle, braking, or VESC configuration write operation. Sync
  acknowledgement is token-authenticated and never deletes raw data.
- No method in the Python package or firmware sends duty, RPM, current, brake, or configuration commands.
- Pack sensors connected to the ESP are diagnostic. The dedicated VESC NTC remains independent.
- Water detection is pulsed, requires consecutive wet samples, and latches for the session.
- A display or SD failure raises a warning but cannot interrupt motor control.
- Passive UART cannot observe VX3 link state; UNKNOWN is displayed as a warning and is never mislabeled OK.
- Synthetic limits and alerts are development examples until calibrated and validated on physical hardware.
- The lumbar-to-board coiled umbilical, rear connector, contained mast wiring, motor mount, and exposed
  propeller are physical safety items outside the logger's control. Their strain relief, separation behavior,
  guarding, waterproofing, and retention require dedicated validation before powered riding.

## UI behavior

The local display and desktop app use three levels: READY, WARNING, and STOP. Water ingress, active VESC
fault, a critical pack temperature, or lost remote status produces STOP. A pack anomaly, noncritical thermal
warning, or SD problem produces WARNING. Alerts visually dominate normal metrics.

## Not yet proven

- The chosen temperature thresholds are not validated against the actual cells, enclosure, adhesives, VESC,
  or cooling conditions.
- The water ADC threshold is intentionally a placeholder until bench calibration with the physical electrodes.
- Foiling-state detection is not validated on rider data. Synthetic truth only exercises the software path.
- Firmware compilation does not prove correct pinout, sensor scaling, waterproofing, RF behavior, or on-water
  reliability.

The build/commissioning guide supplied with the project remains the authoritative sequence for physical work.
If a physical label, connector, schematic, or measured signal conflicts with repository assumptions, stop and
update the mapping before applying power.
