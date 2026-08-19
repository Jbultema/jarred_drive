# Jarred Drive firmware

This PlatformIO project targets the Waveshare ESP32-S3-LCD-1.47B. It is an observer and logger only:
it cannot send throttle commands or write VESC configuration.

Implemented hardware paths:

- VESC UART telemetry on GPIO44 RX / GPIO43 TX at 115200 baud.
- Seven NTC channels and one pulsed water-sensor channel through the 74HC4051.
- Latched water alarm after three consecutive wet readings.
- QMI8658 accelerometer and gyroscope sampling over the onboard I2C bus.
- Compile-time optional UART NMEA GNSS parsing on reserved GPIO2/GPIO3; disabled until an external module is
  selected because neither the VESC nor selected Waveshare board contains a receiver.
- 10 Hz schema-compatible CSV logging to the onboard microSD slot.
- Session folders containing telemetry, a read-only VESC configuration association, and SHA-256 manifest.
- PRE_RIDE / RECORDING / POST_RIDE / CHARGING_IDLE / SYNC state machine; radio use is limited to SYNC after
  the active session is finalized.
- Home-LAN REST endpoints, `jarred-drive.local` mDNS, HTTP Range downloads, and authenticated sync
  acknowledgement. Read transfers never delete SD data.
- High-contrast local SYSTEM READY / WARNING / STOP display.
- Pure C++ safety-policy tests under the native PlatformIO environment.

Before a field build, set `kConfigId` in `include/device_config.hpp` to the ID of the immutable VESC Tool
snapshot stored with that session. `FOIL_UNSET` is intentionally visible and must not be mistaken for a
captured controller configuration.

Wi-Fi credentials and the unique device token must be provided through local compile definitions
`JARRED_DRIVE_WIFI_SSID`, `JARRED_DRIVE_WIFI_PASSWORD`, and `JARRED_DRIVE_DEVICE_TOKEN`; defaults are blank and
no secrets belong in Git. The current bench workflow starts recording at boot. Send `STOP` over USB serial to
flush/hash/finalize, `SYNC` to start home-LAN service, `IDLE` to shut radios down, and `START` for a new session.
Final enclosure-button and USB-power detection remain physical validation work.

The water ADC threshold is deliberately a bench-calibration placeholder. The physical Type-B board pinout,
QMI8658 scaling, actual VESC firmware telemetry, SD card, and every warning path must pass the gates in
`docs/hardware_validation.md` before the system is trusted on water.

Commands:

```bash
make firmware-native
make firmware-hardware
```

The firmware links to `SolidGeek/VescUart` (GPL-3.0) rather than copying its implementation. Review licensing
before publishing compiled firmware or redistributing a combined work.
