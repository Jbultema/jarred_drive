#include "safety.hpp"

#include <algorithm>

namespace jarred_drive {

SafetyResult evaluate_safety(const TelemetrySample& sample, const SafetyThresholds& thresholds) {
  SafetyResult result{};
  const auto limits = std::minmax_element(sample.pack_c.begin(), sample.pack_c.end());
  const auto minimum = limits.first;
  const auto maximum = limits.second;
  result.pack_hot = *maximum >= thresholds.pack_warning_c;
  result.pack_delta = (*maximum - *minimum) >= thresholds.pack_delta_warning_c;
  result.vesc_hot = sample.vesc_mosfet_c >= thresholds.mosfet_warning_c;
  result.water = sample.water_alarm;
  result.vesc_fault = sample.fault_code != 0;
  if (result.water || result.vesc_fault || *maximum >= thresholds.pack_critical_c ||
      sample.remote_ok == 0) {
    result.level = SafetyLevel::kStop;
  } else if (result.pack_hot || result.pack_delta || result.vesc_hot || !sample.sd_ok ||
             sample.remote_ok < 0) {
    result.level = SafetyLevel::kWarning;
  }
  return result;
}

}  // namespace jarred_drive
