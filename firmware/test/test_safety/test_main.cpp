#include <unity.h>

#include "safety.hpp"
#include "operating_mode.hpp"

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

void test_radios_are_only_allowed_in_sync_mode() {
  using jarred_drive::LoggerMode;
  TEST_ASSERT_FALSE(jarred_drive::radio_allowed(LoggerMode::kPreRide));
  TEST_ASSERT_FALSE(jarred_drive::radio_allowed(LoggerMode::kRecording));
  TEST_ASSERT_FALSE(jarred_drive::radio_allowed(LoggerMode::kPostRide));
  TEST_ASSERT_TRUE(jarred_drive::radio_allowed(LoggerMode::kSync));
}

void test_recording_must_finalize_before_sync() {
  jarred_drive::ModeController controller;
  TEST_ASSERT_TRUE(controller.start_recording());
  TEST_ASSERT_FALSE(controller.enter_sync());
  TEST_ASSERT_TRUE(controller.stop_recording());
  TEST_ASSERT_FALSE(controller.enter_sync());
  TEST_ASSERT_TRUE(controller.finalize_session());
  TEST_ASSERT_TRUE(controller.enter_sync());
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_nominal_sample_is_ready);
  RUN_TEST(test_water_alarm_is_stop);
  RUN_TEST(test_pack_delta_is_warning);
  RUN_TEST(test_unknown_remote_status_is_warning_not_ready);
  RUN_TEST(test_radios_are_only_allowed_in_sync_mode);
  RUN_TEST(test_recording_must_finalize_before_sync);
  return UNITY_END();
}
