#include <unity.h>

#include "safety.hpp"

using jarred_drive::SafetyLevel;
using jarred_drive::TelemetrySample;

void test_nominal_sample_is_ready() {
  TelemetrySample sample{};
  sample.pack_c = {30.0F, 30.5F, 31.0F, 30.2F, 30.7F, 30.4F};
  sample.vesc_mosfet_c = 48.0F;
  sample.remote_ok = 1;
  sample.sd_ok = true;
  TEST_ASSERT_EQUAL_INT(static_cast<int>(SafetyLevel::kReady),
                        static_cast<int>(jarred_drive::evaluate_safety(sample).level));
}

void test_water_alarm_is_stop() {
  TelemetrySample sample{};
  sample.pack_c = {30.0F, 30.0F, 30.0F, 30.0F, 30.0F, 30.0F};
  sample.remote_ok = 1;
  sample.sd_ok = true;
  sample.water_alarm = true;
  const auto result = jarred_drive::evaluate_safety(sample);
  TEST_ASSERT_TRUE(result.water);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(SafetyLevel::kStop), static_cast<int>(result.level));
}

void test_pack_delta_is_warning() {
  TelemetrySample sample{};
  sample.pack_c = {30.0F, 30.0F, 30.0F, 38.0F, 30.0F, 30.0F};
  sample.remote_ok = 1;
  sample.sd_ok = true;
  const auto result = jarred_drive::evaluate_safety(sample);
  TEST_ASSERT_TRUE(result.pack_delta);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(SafetyLevel::kWarning), static_cast<int>(result.level));
}

void test_unknown_remote_status_is_warning_not_ready() {
  TelemetrySample sample{};
  sample.pack_c = {30.0F, 30.0F, 30.0F, 30.0F, 30.0F, 30.0F};
  sample.remote_ok = -1;
  sample.sd_ok = true;
  TEST_ASSERT_EQUAL_INT(static_cast<int>(SafetyLevel::kWarning),
                        static_cast<int>(jarred_drive::evaluate_safety(sample).level));
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_nominal_sample_is_ready);
  RUN_TEST(test_water_alarm_is_stop);
  RUN_TEST(test_pack_delta_is_warning);
  RUN_TEST(test_unknown_remote_status_is_warning_not_ready);
  return UNITY_END();
}
