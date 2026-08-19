#pragma once

namespace jarred_drive {

// Set this to the immutable VESC Tool snapshot ID used for the session. The
// firmware records the ID; it never writes these settings to the controller.
constexpr const char* kConfigId = "FOIL_UNSET";

// Phase 2: set true only after selecting and bench-validating a 3.3 V UART
// NMEA GNSS module. No receiver exists on the selected VESC or ESP32 board.
constexpr bool kGnssEnabled = false;

}  // namespace jarred_drive
