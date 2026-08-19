# Reference projects and design influence

These projects were used as inspiration and protocol/interaction references, not copied as a product template.

- [SolidGeek/VescUart](https://github.com/SolidGeek/VescUart): VESC UART packet handling and telemetry fields.
  It is GPL-3.0; the firmware consumes it as a dependency and redistribution implications must be reviewed.
- [kevingraehl/vesc-hud](https://github.com/kevingraehl/vesc-hud): high-contrast ESP32 VESC display and the
  important rule that reconnect/boot must never silently apply a profile.
- [Luddi96/BREmote](https://github.com/Luddi96/BREmote): e-foil context, water-ingress alarm, and fall-detection
  direction.
- [wavrx/iRemote](https://github.com/wavrx/iRemote): ESP32 display, IMU, telemetry alerts, and trip summaries.
- [VESC firmware logging](https://github.com/vedderb/bldc): GNSS/map field conventions, fault rendering, and
  local SD logging concepts.
- [Waveshare ESP32-S3-LCD-1.47B](https://www.waveshare.com/wiki/ESP32-S3-LCD-1.47B): official LCD, IMU,
  microSD, GPIO, schematic, and demo references for the exact board family.
- [roypeter/esp32-obd2-logger](https://github.com/roypeter/esp32-obd2-logger): session files, status surfaces,
  storage fallback, and downloadable raw records.

Jarred Drive retains its own domain contracts: independent propulsion, six modular pack sensors, pulsed water
probe, configuration-linked sessions, ride/flight distinction, manual annotations, and optional GNSS.
