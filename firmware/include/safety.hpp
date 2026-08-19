#pragma once

#include <array>
#include <cstdint>

#include "telemetry.hpp"

namespace jarred_drive {

enum class SafetyLevel : std::uint8_t { kReady = 0, kWarning = 1, kStop = 2 };

struct SafetyThresholds {
  float pack_warning_c{45.0F};
  float pack_critical_c{50.0F};
  float pack_delta_warning_c{7.0F};
  float mosfet_warning_c{75.0F};
};

struct SafetyResult {
  SafetyLevel level{SafetyLevel::kReady};
  bool pack_hot{false};
  bool pack_delta{false};
  bool vesc_hot{false};
  bool water{false};
  bool vesc_fault{false};
};

SafetyResult evaluate_safety(const TelemetrySample& sample,
                             const SafetyThresholds& thresholds = SafetyThresholds{});

}  // namespace jarred_drive
