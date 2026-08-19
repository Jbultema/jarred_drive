#pragma once

namespace jarred_drive {

constexpr const char* kDeviceId = "jarred-drive-01";
constexpr const char* kDeviceName = "Jarred Drive Logger";
constexpr const char* kFirmwareVersion = "0.3.1";
constexpr const char* kHardwareRevision = "logger-v1";

// Supply these as local PlatformIO build flags or an ignored local environment;
// never commit real home-network credentials or device tokens.
#ifdef JARRED_DRIVE_WIFI_SSID
constexpr const char* kWifiSsid = JARRED_DRIVE_WIFI_SSID;
#else
constexpr const char* kWifiSsid = "";
#endif
#ifdef JARRED_DRIVE_WIFI_PASSWORD
constexpr const char* kWifiPassword = JARRED_DRIVE_WIFI_PASSWORD;
#else
constexpr const char* kWifiPassword = "";
#endif
#ifdef JARRED_DRIVE_DEVICE_TOKEN
constexpr const char* kDeviceToken = JARRED_DRIVE_DEVICE_TOKEN;
#else
constexpr const char* kDeviceToken = "";
#endif

// Set this to the immutable VESC Tool snapshot ID used for the session. The
// firmware records the ID; it never writes these settings to the controller.
constexpr const char* kConfigId = "FOIL_UNSET";

// Phase 2: set true only after selecting and bench-validating a 3.3 V UART
// NMEA GNSS module. No receiver exists on the selected VESC or ESP32 board.
constexpr bool kGnssEnabled = false;

}  // namespace jarred_drive
