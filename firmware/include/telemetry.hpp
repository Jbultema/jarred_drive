#pragma once

#include <array>
#include <cstdint>

namespace jarred_drive {

constexpr const char* kSchemaVersion = "1.0.0";
constexpr std::size_t kPackCount = 6;

struct TelemetrySample {
  std::uint32_t timestamp_ms{0};
  float vesc_vin_v{0.0F};
  float vesc_battery_a{0.0F};
  float vesc_motor_a{0.0F};
  float vesc_duty{0.0F};
  float vesc_erpm{0.0F};
  float vesc_mosfet_c{0.0F};
  float vesc_safety_ntc_c{0.0F};
  std::array<float, kPackCount> pack_c{};
  float enclosure_c{0.0F};
  std::uint16_t water_adc{4095};
  bool water_alarm{false};
  float accel_x_g{0.0F};
  float accel_y_g{0.0F};
  float accel_z_g{1.0F};
  float gyro_x_dps{0.0F};
  float gyro_y_dps{0.0F};
  float gyro_z_dps{0.0F};
  float amp_hours{0.0F};
  float watt_hours{0.0F};
  std::uint8_t fault_code{0};
  // -1 unknown (normal for passive UART), 0 explicit fault, 1 explicitly OK.
  std::int8_t remote_ok{-1};
  bool sd_ok{false};
  bool gnss_valid{false};
  double gps_lat{0.0};
  double gps_lon{0.0};
  float gps_speed_mps{0.0F};
  float gps_course_deg{0.0F};
  std::uint8_t gps_fix_quality{0};
};

}  // namespace jarred_drive
